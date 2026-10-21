"""Bounded HTTP access, explicit destination policy, scoped session cookies."""
from __future__ import annotations

import json
import math
import socket
import ssl
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.cookiejar import Cookie
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .access_policy import policy_for_url
from .http_privacy import private_http_logging
from .parsing import is_login
from .runtime import AppError
from .sources import SOURCES

MAX_BYTES = 8 * 1024 * 1024
CONNECT_SECONDS = 3
AUTH_CONNECT_SECONDS = 8
HOST_COOLDOWN_SECONDS = 15
PASSWORD_KEYS = {"password", "passwd", "pwd", "userpassword", "j_password"}
AUTH_QUERY_KEYS = {"token", "access_token", "refresh_token", "ticket", "sessionid", "authorization"} | PASSWORD_KEYS


class TransportEvidence:
    """Keep stage names only, never trace info (URLs, TLS objects or headers)."""
    def __init__(self):
        self.phase = "unknown"

    def trace(self, event: str, _info: dict) -> None:
        if event == "connection.connect_tcp.started":
            # The backend may resolve DNS inside connect_tcp. This does not
            # establish which DNS server, route, target IP or TCP hop was used.
            self.phase = "connect_before_tls"
        elif event == "connection.start_tls.started":
            self.phase = "tls"
        elif ".receive_response_headers.started" in event:
            self.phase = "http_response"
        elif ".receive_response_headers.complete" in event or ".receive_response_body.started" in event:
            self.phase = "body_read"
        elif ".send_request_" in event and event.endswith(".started"):
            self.phase = "request_write"


def failure_layer(exc: Exception, evidence: TransportEvidence | None = None) -> str:
    """Use exception types, never provider prose/URLs that may carry secrets."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return "tls_verification" if isinstance(current, ssl.SSLCertVerificationError) else "tls"
        if isinstance(current, socket.gaierror):
            return "dns"
        current = current.__cause__ or current.__context__
    if evidence and evidence.phase != "unknown":
        return evidence.phase
    return ("connect_or_tls" if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
            else "read" if isinstance(exc, (httpx.ReadError, httpx.ReadTimeout)) else "transport")


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


def checked_url(source: str, url: str, *, authenticated: bool = False, allow_legacy_http: bool = False,
                allow_oa_http: bool = False) -> str:
    parsed = urlparse(url)
    spec = SOURCES[source]
    if parsed.username or parsed.password or parsed.hostname not in spec.hosts or parsed.fragment:
        raise AppError("unsafe_url", "请求地址不在此来源的允许范围内。", source)
    legacy_jw = source == "jw" and allow_legacy_http and parsed.hostname == "jw.stu.edu.cn"
    legacy_oa = (source == "oa" and allow_oa_http and parsed.scheme == "http"
                 and parsed.hostname == "oa-stu-edu-cn.webvpn.stu.edu.cn" and parsed.port == 8118)
    if parsed.port not in (None, 443) and not legacy_oa and not (
            parsed.port == 80 and (legacy_jw or source == "oa" and not authenticated)):
        raise AppError("unsafe_url", "该来源端口不受支持。", source)
    if parsed.scheme != "https" and not legacy_oa and not (parsed.scheme == "http" and (legacy_jw or source == "oa"
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
    result = {"cookies": cookies, "origins": origins}
    if source == "yuketang" and "yuketang_authorization" in state:
        authorization = state["yuketang_authorization"]
        if (not isinstance(authorization, str) or not authorization.startswith("Bearer ")
                or not 8 <= len(authorization) <= 8192
                or any(not 33 <= ord(char) <= 126 for char in authorization[7:])):
            raise AppError("session_invalid", "雨课堂认证字段无效，请重新登录。", source)
        result["yuketang_authorization"] = authorization
    if source == "oa" and "webvpn_oa_route" in state:
        route = state["webvpn_oa_route"]
        if not isinstance(route, dict) or set(route) != {"scheme", "host", "port"} or route not in (
            {"scheme": "http", "host": "oa-stu-edu-cn.webvpn.stu.edu.cn", "port": 8118},
            {"scheme": "https", "host": "oa-stu-edu-cn.webvpn.stu.edu.cn", "port": 443},
        ):
            raise AppError("session_invalid", "WebVPN 资源路由无效，请重新登录。", source)
        result["webvpn_oa_route"] = dict(route)
    if source == "oa" and state.get("webvpn_catalog_verified") is True:
        result["webvpn_catalog_verified"] = True
    return result


class CampusHTTP:
    def __init__(self, source: str, state: dict | None = None, *, transport=None, allow_legacy_http: bool = False,
                 allow_oa_http: bool = False):
        self.source = source
        self.authenticated = state is not None
        if allow_legacy_http and source != "jw":
            raise AppError("unsafe_policy", "HTTP 兼容只允许用于学校教务来源。", source)
        self.allow_legacy_http = allow_legacy_http
        if allow_oa_http and source != "oa":
            raise AppError("unsafe_policy", "OA HTTP 兼容不能用于其他来源。", source)
        self.allow_oa_http = allow_oa_http
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
            if allow_oa_http and domain.lstrip(".").lower() not in {
                "webvpn.stu.edu.cn", "oa-stu-edu-cn.webvpn.stu.edu.cn"}:
                continue  # Never expose a central SSO/parent-domain cookie through OA HTTP.
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
            if authorization := scoped_state(state or {}, source).get("yuketang_authorization"):
                headers["Authorization"] = authorization
        self.client = httpx.Client(cookies=cookies, headers=headers, verify=True, trust_env=False,
                                   timeout=httpx.Timeout(18, connect=AUTH_CONNECT_SECONDS),
                                   follow_redirects=False, transport=transport)
        self.requests = 0
        self.deadline = time.monotonic() + 45
        # One extra connect attempt for the entire anonymous read, not per page.
        self._connect_retry = 1
        self._failed_hosts: dict[tuple, tuple[float, AppError]] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def request(self, url: str, *, data: dict | None = None, max_bytes: int = MAX_BYTES) -> httpx.Response:
        current, method = url, "POST" if data is not None else "GET"
        for _ in range(5):
            checked_url(self.source, current, authenticated=self.authenticated, allow_legacy_http=self.allow_legacy_http,
                        allow_oa_http=self.allow_oa_http)
            if self.allow_oa_http and urlparse(current).scheme == "http" and method != "GET":
                raise AppError("insecure_transport", "OA HTTP 兼容仅允许读取，不发送表单或认证输入。", self.source)
            target = urlparse(current)
            host_key = (target.scheme, target.hostname, target.port or (443 if target.scheme == "https" else 80))
            anonymous_get = method == "GET" and not self.authenticated and data is None
            failed = self._failed_hosts.get(host_key) if anonymous_get else None
            if failed and failed[0] > time.monotonic():
                previous = failed[1]
                raise AppError(previous.code, previous.message, self.source,
                               retry_after_seconds=math.ceil(failed[0] - time.monotonic()),
                               network={**(previous.network or {}), "cached_failure": True})
            if urlparse(current).scheme == "http" and data and any(str(k).lower() in PASSWORD_KEYS for k in data):
                raise AppError("insecure_password_form", "账号密码只能提交到学校 HTTPS 登录页。", self.source)
            if self.requests >= 100:
                raise AppError("request_limit", "此轮请求已达到上限；请缩小范围后再刷新。", self.source)
            self.requests += 1
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise AppError("request_deadline", "此轮读取已达到 45 秒上限，已有结果会注明范围。", self.source)
            self.used_legacy_http |= urlparse(current).scheme == "http"
            evidence = TransportEvidence()
            connect_seconds = CONNECT_SECONDS if anonymous_get else AUTH_CONNECT_SECONDS
            try:
                with private_http_logging(self.authenticated), self.client.stream(
                    method, current, data=data if method == "POST" else None,
                    extensions={"trace": evidence.trace},
                    timeout=httpx.Timeout(min(18, remaining), connect=min(connect_seconds, remaining)),
                ) as response:
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
            except httpx.HTTPError as exc:
                layer = failure_layer(exc, evidence)
                if (anonymous_get and self._connect_retry and isinstance(exc, httpx.ConnectTimeout)
                        and layer == "connect_before_tls"
                        and self.deadline - time.monotonic() > CONNECT_SECONDS + .2):
                    self._connect_retry -= 1
                    time.sleep(.15)
                    continue
                policy = policy_for_url(current)
                context = {"transport": "direct", "failure_layer": layer,
                           "cached_failure": False, "automatic_proxy_fallback": False}
                if policy:
                    context.update(endpoint_id=policy.endpoint_id, preferred_access=policy.preferred_access)
                code = "request_timeout" if isinstance(exc, httpx.TimeoutException) else "network_error"
                hint = policy.hint if policy else "请检查该来源的 DNS、网络路由或校园接入条件；其他来源仍可使用。"
                error = AppError(code, "此端点未能完成直连。" + hint, self.source, network=context)
                # A failed connect/DNS/TLS applies to this origin, not all STU
                # hosts. Never cache resource HTTP errors or replay auth/POST.
                if anonymous_get and isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
                    self._failed_hosts[host_key] = (time.monotonic() + HOST_COOLDOWN_SECONDS, error)
                raise error from None
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
