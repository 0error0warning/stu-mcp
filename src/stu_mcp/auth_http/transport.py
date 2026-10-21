"""Bounded direct authentication HTTP; redirects and success belong to adapters."""
from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from ..http_privacy import private_http_logging
from ..runtime import AppError


class HTTPFlow:
    def __init__(self, source: str, hosts: tuple[str, ...], *, transport=None, timeout: float = 60,
                 max_requests: int = 32, headers: dict | None = None,
                 allow_http: Callable[[str], bool] | None = None):
        self.source, self.hosts = source, hosts
        self.allow_http = allow_http
        self.deadline, self.max_requests, self.requests = time.monotonic() + timeout, max_requests, 0
        self.client = httpx.Client(verify=True, trust_env=False, follow_redirects=False,
                                  transport=transport or httpx.HTTPTransport(retries=0, trust_env=False),
                                  headers={"User-Agent": "STU-MCP/HTTP", **(headers or {})})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def check(self):
        if time.monotonic() >= self.deadline or self.requests >= self.max_requests:
            raise AppError("authentication_budget", "认证已达到时间或请求上限；没有自动重试。", self.source)

    def checked_url(self, url: str) -> str:
        try:
            if not isinstance(url, str):
                raise ValueError
            parsed = urlsplit(url)
            if (any(ord(c) < 32 for c in url) or parsed.username
                    or parsed.password or parsed.fragment or parsed.hostname not in self.hosts):
                raise ValueError
            if parsed.scheme == "https" and parsed.port in {None, 443}:
                return url
            if (parsed.scheme == "http" and parsed.port in {None, 80} and self.allow_http
                    and self.allow_http(url)):
                return url
        except (TypeError, ValueError):
            pass
        raise AppError("insecure_authentication_route", "认证跳转超出此来源已核验的地址或传输范围。", self.source)

    def request(self, method: str, url: str, *, data=None, json=None, content=None, headers=None,
                timeout: float | None = None, credential: bool = False) -> httpx.Response:
        self.check()
        self.checked_url(url)
        method = method.upper()
        if method not in {"GET", "POST"} or credential and urlsplit(url).scheme != "https":
            raise AppError("unsafe_authentication_request", "认证请求方式不受支持；密码只发送到 HTTPS。", self.source)
        self.requests += 1
        remaining = min(timeout or 12, self.deadline - time.monotonic())
        try:
            with private_http_logging(), self.client.stream(
                method, url, data=data, json=json, content=content, headers=headers,
                timeout=httpx.Timeout(max(.01, remaining), connect=min(4, max(.01, remaining))),
            ) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000 or time.monotonic() >= self.deadline:
                        raise AppError("authentication_response_limit", "认证响应超过大小或时间上限；未重发请求。", self.source)
                decoded_headers = response.headers.copy()
                decoded_headers.pop("content-encoding", None)
                decoded_headers["content-length"] = str(len(body))
                return httpx.Response(response.status_code, headers=decoded_headers, content=bytes(body),
                                      request=response.request)
        except httpx.HTTPError:
            raise AppError("authentication_outcome_unknown" if credential else "authentication_network_error",
                           "认证请求结果无法确认；没有重发，请先核对登录状态。" if credential else
                           "此来源认证网络不可达；未改变代理、DNS 或证书校验。", self.source) from None

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def state(self, hosts: tuple[str, ...] | None = None) -> dict:
        hosts = hosts or self.hosts
        result = []
        for cookie in self.client.cookies.jar:
            domain = cookie.domain.lstrip(".").lower()
            if not domain or not any(host == domain or host.endswith("." + domain) for host in hosts):
                continue
            result.append({"name": cookie.name, "value": cookie.value, "domain": cookie.domain,
                           "path": cookie.path or "/", "expires": cookie.expires if cookie.expires is not None else -1,
                           "httpOnly": cookie.has_nonstandard_attr("HttpOnly"), "secure": cookie.secure,
                           "sameSite": "Lax"})
        return {"cookies": result, "origins": []}
