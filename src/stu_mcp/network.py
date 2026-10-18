"""Bounded HTTP access, explicit destination policy, scoped session cookies."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .parsers import is_login
from .runtime import AppError
from .sources import SOURCES

MAX_BYTES = 8 * 1024 * 1024
PASSWORD_KEYS = {"password", "passwd", "pwd", "userpassword", "j_password"}
AUTH_QUERY_KEYS = {"token", "access_token", "refresh_token", "ticket", "sessionid", "authorization"} | PASSWORD_KEYS


def retry_after(value: str | None) -> int | None:
    """Expose a bounded delay, never arbitrary response-header text."""
    if not value:
        return None
    try:
        seconds = int(value) if value.isdigit() else int(
            (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        return max(0, min(seconds, 86400))
    except (TypeError, ValueError, OverflowError):
        return None


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
        self.used_legacy_http = False
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
            self.used_legacy_http |= urlparse(current).scheme == "http"
            try:
                with self.client.stream(method, current, data=data if method == "POST" else None,
                                        timeout=httpx.Timeout(min(18, remaining), connect=min(8, remaining))) as response:
                    status = response.status_code
                    if status == 401:
                        raise AppError("login_expired" if self.authenticated else "needs_login",
                                       "此来源需要登录或重新登录；其他来源仍可使用。", self.source,
                                       http_status=status)
                    if status == 403:
                        raise AppError("access_denied", "来源拒绝访问此资源；请在原页面核对权限或访问限制。",
                                       self.source, http_status=status)
                    if status == 429:
                        raise AppError("rate_limited", "来源限制了请求频率，请等待后重试。", self.source,
                                       http_status=status, retry_after_seconds=retry_after(response.headers.get("retry-after")))
                    if status == 404:
                        raise AppError("not_found", "来源未找到此资源；请刷新列表后核对原页面。",
                                       self.source, http_status=status)
                    if status >= 500:
                        raise AppError("source_unavailable", "来源服务暂时异常，请稍后重试。",
                                       self.source, http_status=status,
                                       retry_after_seconds=retry_after(response.headers.get("retry-after")))
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise AppError("network_error", "来源返回了无效跳转。", self.source)
                        target = urljoin(current, location)
                        destination = urlparse(target)
                        webvpn_login = (self.source == "oa" and self.authenticated
                                        and destination.hostname == "webvpn.stu.edu.cn"
                                        and destination.path.startswith("/portal"))
                        if destination.hostname == "sso.stu.edu.cn" or "/login" in destination.path.lower() or webvpn_login:
                            raise AppError("login_expired" if self.authenticated else "needs_login",
                                           "此来源需要在本地浏览器登录。", self.source)
                        if response.status_code not in (301, 302, 303) and urlparse(target).netloc != urlparse(current).netloc:
                            raise AppError("unsafe_redirect", "已阻止跨站转发请求内容。", self.source)
                        current = target
                        if response.status_code in (301, 302, 303):
                            method = "GET"
                        continue
                    if status >= 400:
                        raise AppError("source_rejected", "来源未接受此请求；请核对资源与读取条件。",
                                       self.source, http_status=status)
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
                    result = httpx.Response(response.status_code, headers=headers,
                                            content=content, request=response.request)
                    if content.lstrip().startswith(b"<"):
                        if (self.source == "mystu" and "/mod/quiz/" in urlparse(current).path
                                and BeautifulSoup(result.text, "html.parser").select_one('input[name="quizpassword"]')):
                            raise AppError("activity_password_required", "此测验要求活动密码，请在学校页面处理。",
                                           self.source, http_status=status)
                        # The anonymous OA bulletin lives on a page that may also
                        # contain a login form. A form alone must not hide that board.
                        if (self.authenticated or self.source in {"jw", "mystu", "yuketang"}) and is_login(result.text):
                            raise AppError("login_expired" if self.authenticated else "needs_login",
                                           "此来源需要在本地浏览器登录。", self.source, http_status=status)
                    return result
            except AppError:
                raise
            except httpx.TimeoutException:
                raise AppError("request_timeout", "来源未在时限内响应，请稍后重试。", self.source) from None
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
        if self.source == "yuketang":
            codes = [payload.get(k) for k in ("errcode", "code")]
            if any(code in (401000, "401000") for code in codes):
                raise AppError("login_expired" if self.authenticated else "needs_login",
                               "雨课堂已拒绝登录会话，请在本地设置页重新登录。", self.source)
            # v2 uses errcode, classroom v3 uses code, and LMS uses success.
            # Error messages can contain credentials or personal data; keep them
            # out of the MCP result and do not guess authentication from prose.
            if any(code not in (0, "0", None) for code in codes) or payload.get("success") is False:
                raise AppError("source_rejected", "雨课堂未接受此读取；请在原页面核对资源状态。", self.source)
            if "success" in payload and not isinstance(payload["success"], bool):
                raise AppError("schema_changed", "雨课堂的业务状态字段无法识别。", self.source)
        elif payload.get("errcode", 0) not in (0, "0", None):
            raise AppError("source_rejected", "来源未接受此请求；请在原页面核对读取条件。", self.source)
        return payload
