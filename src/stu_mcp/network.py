"""Bounded HTTP access, explicit destination policy, scoped session cookies."""
from __future__ import annotations

import json
import time
from http.cookiejar import Cookie
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx

from .runtime import AppError
from .sources import SOURCES

MAX_BYTES = 8 * 1024 * 1024
PASSWORD_KEYS = {"password", "passwd", "pwd", "userpassword", "j_password"}
AUTH_QUERY_KEYS = {"token", "access_token", "refresh_token", "ticket", "sessionid", "authorization"} | PASSWORD_KEYS


def checked_url(source: str, url: str, *, authenticated: bool = False, allow_legacy_http: bool = False) -> str:
    parsed = urlparse(url)
    spec = SOURCES[source]
    if parsed.username or parsed.password or parsed.hostname not in spec.hosts or parsed.fragment:
        raise AppError("unsafe_url", "请求地址不在此来源的允许范围内。", source)
    legacy_jw = source == "jw" and allow_legacy_http and parsed.hostname == "jw.stu.edu.cn"
    if parsed.port not in (None, 443) and not (parsed.port == 80 and (legacy_jw or source == "oa" and not authenticated)):
        raise AppError("unsafe_url", "该来源端口不受支持。", source)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and (legacy_jw or source == "oa"
                                        and parsed.hostname == "oa.stu.edu.cn" and not authenticated)):
        raise AppError("insecure_transport", "已阻止通过非 HTTPS 连接发送登录态。", source)
    if any(k.lower() in AUTH_QUERY_KEYS for k, _ in parse_qsl(parsed.query)):
        raise AppError("unsafe_url", "请求地址包含认证字段，已停止操作。", source)
    return url


def scoped_state(state: dict, source: str) -> dict:
    hosts = SOURCES[source].hosts
    cookies = []
    for c in state.get("cookies", []):
        if not isinstance(c, dict):
            continue
        domain = str(c.get("domain", "")).lstrip(".").lower()
        if domain and any(h == domain or h.endswith("." + domain) for h in hosts):
            cookies.append(c)
    origins = [o for o in state.get("origins", []) if isinstance(o, dict)
               and urlparse(str(o.get("origin", ""))).hostname in hosts
               and urlparse(str(o.get("origin", ""))).scheme == "https"]
    return {"cookies": cookies, "origins": origins}


class CampusHTTP:
    def __init__(self, source: str, state: dict | None = None, *, transport=None, allow_legacy_http: bool = False):
        self.source = source
        self.authenticated = state is not None
        if allow_legacy_http and source != "jw":
            raise AppError("unsafe_policy", "HTTP 兼容只允许用于学校教务来源。", source)
        self.allow_legacy_http = allow_legacy_http
        cookies = httpx.Cookies()
        for c in scoped_state(state or {}, source)["cookies"]:
            try:
                expiry = float(c.get("expires", -1))
                if 0 < expiry < time.time():
                    continue
            except (TypeError, ValueError):
                continue
            domain = str(c["domain"])
            if allow_legacy_http and domain.lstrip(".").lower() != "jw.stu.edu.cn":
                continue  # Do not reuse central SSO cookies on the legacy JW endpoint.
            cookies.jar.set_cookie(Cookie(0, str(c["name"]), str(c["value"]), None, False,
                                         domain, bool(domain), domain.startswith("."), str(c.get("path", "/")),
                                         True, bool(c.get("secure", False)), None if expiry <= 0 else int(expiry),
                                         expiry <= 0, None, None, {}, False))
        headers = {"User-Agent": "STU-MCP/0.1 (+https://github.com/0error0warning/stu-mcp)",
                   "Accept": "text/html,application/json"}
        if source == "mystu":
            headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Referer"] = "https://my.stu.edu.cn/discussion/my-courses"
        if source == "yuketang":
            headers["xtbz"] = "ykt"
        self.client = httpx.Client(cookies=cookies, headers=headers, verify=True, trust_env=False,
                                   timeout=httpx.Timeout(18, connect=8), follow_redirects=False, transport=transport)
        self.requests = 0
        self.deadline = time.monotonic() + 45

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def request(self, url: str, *, data: dict | None = None, max_bytes: int = MAX_BYTES) -> httpx.Response:
        current, method = url, "POST" if data is not None else "GET"
        for _ in range(5):
            checked_url(self.source, current, authenticated=self.authenticated, allow_legacy_http=self.allow_legacy_http)
            if urlparse(current).scheme == "http" and data and any(str(k).lower() in PASSWORD_KEYS for k in data):
                raise AppError("insecure_password_form", "账号密码只能提交到学校 HTTPS 登录页。", self.source)
            if self.requests >= 100:
                raise AppError("request_limit", "此轮请求已达到上限；请缩小范围后再刷新。", self.source)
            self.requests += 1
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise AppError("request_deadline", "此轮读取已达到 45 秒上限，已有结果会注明范围。", self.source)
            try:
                with self.client.stream(method, current, data=data if method == "POST" else None,
                                        timeout=httpx.Timeout(min(18, remaining), connect=min(8, remaining))) as response:
                    if response.status_code in (401, 403):
                        raise AppError("login_expired" if self.authenticated else "needs_login",
                                       "此来源需要登录或重新登录；其他来源仍可使用。", self.source)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise AppError("network_error", "来源返回了无效跳转。", self.source)
                        target = urljoin(current, location)
                        destination = urlparse(target)
                        webvpn_login = (self.source == "oa" and self.authenticated
                                        and destination.hostname == "webvpn.stu.edu.cn"
                                        and destination.path.startswith("/portal"))
                        if "sso.stu.edu.cn" in target or "/login" in destination.path.lower() or webvpn_login:
                            raise AppError("login_expired" if self.authenticated else "needs_login",
                                           "此来源需要在本地浏览器登录。", self.source)
                        if response.status_code not in (301, 302, 303) and urlparse(target).netloc != urlparse(current).netloc:
                            raise AppError("unsafe_redirect", "已阻止跨站转发请求内容。", self.source)
                        current = target
                        if response.status_code in (301, 302, 303):
                            method = "GET"
                        continue
                    response.raise_for_status()
                    parts, length = [], 0
                    for chunk in response.iter_bytes():
                        if time.monotonic() > self.deadline:
                            raise AppError("request_deadline", "来源读取超时，已停止此轮请求。", self.source)
                        length += len(chunk)
                        if length > max_bytes:
                            raise AppError("response_too_large", "响应超过大小上限，已停止读取。", self.source)
                        parts.append(chunk)
                    # iter_bytes has already decoded HTTP compression. Do not decode it twice.
                    content = b"".join(parts)
                    headers = response.headers.copy()
                    headers.pop("content-encoding", None)
                    headers["content-length"] = str(len(content))
                    return httpx.Response(response.status_code, headers=headers,
                                          content=content, request=response.request)
            except AppError:
                raise
            except httpx.HTTPError:
                raise AppError("network_error", "校园来源暂时无法连接；请检查校园网络、VPN 或稍后重试。",
                               self.source) from None
        raise AppError("redirect_limit", "来源跳转次数超过上限。", self.source)

    def text(self, url: str, *, data: dict | None = None) -> str:
        return self.request(url, data=data).text

    def json(self, url: str) -> dict:
        try:
            payload = self.request(url).json()
        except (json.JSONDecodeError, UnicodeError):
            raise AppError("schema_changed", "来源未返回预期的 JSON 数据。", self.source) from None
        if not isinstance(payload, dict):
            raise AppError("schema_changed", "来源数据结构发生变化。", self.source)
        if payload.get("errcode", 0) not in (0, None):
            raise AppError("source_rejected", "来源拒绝了请求；请在设置页检查登录状态。", self.source)
        return payload
