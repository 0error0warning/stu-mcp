"""Anonymous fixed-origin HTTP, signing and request budgets; no account session."""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx

from ...runtime import AppError
from .parser import param_string, response_data
from .schema import (
    API_BASE,
    API_PATHS,
    APP_VERSION,
    DEADLINE_SECONDS,
    PUBLIC_SIGNING_CONSTANT,
    REQUEST_LIMIT,
    RESPONSE_BYTES,
    WEB_BASE,
)


def sign_params(params: dict, timestamp_ms: int | None = None) -> dict[str, str]:
    values = {k: param_string(v) for k, v in params.items() if v is not None and k != "sig"}
    values.update(appid="330012", app_key_vs=APP_VERSION,
              flyer=str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)))
    basis = "".join(sorted(f"{k}={v}" for k, v in values.items())) + PUBLIC_SIGNING_CONSTANT
    values["sig"] = hashlib.md5(basis.encode()).hexdigest()
    return values


class HuyouHTTP:
    def __init__(self, *, transport=None):
        self.client = httpx.Client(verify=True, trust_env=False, follow_redirects=False, transport=transport,
                                   timeout=httpx.Timeout(15, connect=8), headers={
                                       "User-Agent": "STU-MCP (+https://github.com/0error0warning/stu-mcp)",
                                       "Referer": WEB_BASE, "Origin": WEB_BASE.rstrip("/"),
                                       "S-VS": APP_VERSION, "P-APPID": "110503"})
        self.requests, self.retries, self._sign_ms = 0, 0, 0
        self.deadline, self.last_request = time.monotonic() + DEADLINE_SECONDS, 0.0
        self.stopped: AppError | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def get(self, path: str, params: dict) -> dict:
        if path not in API_PATHS:
            raise AppError("unsafe_url", "狐友只允许指定的公开读取接口。", "huyou")
        for attempt in range(2):
            if self.stopped:
                raise self.stopped
            if self.requests >= REQUEST_LIMIT or time.monotonic() >= self.deadline:
                code = "request_limit" if self.requests >= REQUEST_LIMIT else "request_deadline"
                self.stopped = AppError(code, "此轮狐友读取已达 40 次请求或 45 秒上限，保留已获取结果。", "huyou")
                raise self.stopped
            delay = max(0, 0.25 - (time.monotonic() - self.last_request))
            if delay:
                time.sleep(delay)
            if time.monotonic() >= self.deadline:
                self.stopped = AppError("request_deadline", "此轮狐友读取已达时间上限，保留已获取结果。", "huyou")
                raise self.stopped
            self.last_request, self.requests = time.monotonic(), self.requests + 1
            self._sign_ms = max(int(time.time() * 1000), self._sign_ms + 1)
            self.client.cookies.clear()  # Never adopt Set-Cookie as an account session.
            url = API_BASE + path + "?" + urlencode(sign_params(params, self._sign_ms))
            try:
                with self.client.stream("GET", url, timeout=min(15, max(0.1, self.deadline - time.monotonic()))) as r:
                    if r.status_code in (401, 403):
                        self.stopped = AppError("huyou_login_required", "狐友要求登录或拒绝访问；本版仅支持公开读取。", "huyou")
                        raise self.stopped
                    if r.is_redirect:
                        raise AppError("unsafe_redirect", "狐友返回跳转，未转发请求或认证数据。", "huyou")
                    if r.status_code in (429, 500, 502, 503, 504):
                        retry_after = r.headers.get("Retry-After", "0.5")
                        try:
                            retry_delay = float(retry_after)
                        except ValueError:
                            try:
                                retry_delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                            except (TypeError, ValueError, OverflowError):
                                retry_delay = 0.5
                        if (r.status_code == 429 and attempt or not math.isfinite(retry_delay) or retry_delay > 2
                                or time.monotonic() + max(0, retry_delay) >= self.deadline):
                            self.stopped = AppError("rate_limited", "狐友要求稍后重试，已停止本轮读取。", "huyou")
                            raise self.stopped
                        if attempt == 0:
                            self.retries += 1
                            time.sleep(max(0, retry_delay))
                            continue
                    r.raise_for_status()
                    parts, size = [], 0
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > RESPONSE_BYTES:
                            raise AppError("response_too_large", "狐友响应超过 2 MiB 上限。", "huyou")
                        if time.monotonic() > self.deadline:
                            self.stopped = AppError("request_deadline", "此轮狐友读取已达时间上限。", "huyou")
                            raise self.stopped
                        parts.append(chunk)
                payload = json.loads(b"".join(parts))
                break
            except httpx.TransportError:
                if attempt == 0:
                    self.retries += 1
                    continue
                raise AppError("network_error", "狐友暂时无法连接，请稍后重试。", "huyou") from None
            except httpx.HTTPError:
                raise AppError("network_error", "狐友 HTTP 读取失败，未当作空结果。", "huyou") from None
            except (ValueError, UnicodeError):
                raise AppError("schema_changed", "狐友未返回有效 JSON，未当作空结果。", "huyou") from None
        try:
            return response_data(payload)
        except AppError as exc:
            if exc.code == "huyou_login_required":
                self.stopped = exc
            raise
