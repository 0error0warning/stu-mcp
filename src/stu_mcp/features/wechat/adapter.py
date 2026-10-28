"""Bounded credential-free HTTP reads and exact public article URL policy."""
from __future__ import annotations

import re
import time
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx

from ...runtime import AppError

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5
DEADLINE_SECONDS = 30
_PUBLIC_KEYS = frozenset({"__biz", "mid", "idx", "sn", "chksm"})
_PRIVATE_KEYS = frozenset({"key", "uin", "pass_ticket", "wxtoken", "token", "access_token", "auth",
                           "authorization", "ticket", "code", "openid", "exportkey", "cookie"})


def article_url(value: str, *, redirect: bool = False) -> str:
    code = "unsafe_redirect" if redirect else "invalid_article_url"
    message = "只接受 HTTPS mp.weixin.qq.com 的公开文章链接，不接收含登录凭据的链接。"
    try:
        if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\s\\\x00-\x1f]", value):
            raise ValueError
        parts = urlsplit(unescape(value))
        if (parts.scheme != "https" or parts.netloc.lower() != "mp.weixin.qq.com"
                or parts.username or parts.password):
            raise ValueError
        pairs = parse_qsl(parts.query, keep_blank_values=True, max_num_fields=40)
        if any(key.lower() in _PRIVATE_KEYS for key, _ in pairs):
            raise ValueError
        if redirect and parts.path == "/mp/wappoc_appmsgcaptcha":
            raise AppError("captcha_required", "来源跳转到人工验证页；未读取到正文。", "wechat")
        public = [(key, val) for key, val in pairs if key in _PUBLIC_KEYS]
        if len({key for key, _ in public}) != len(public):
            raise ValueError
        if re.fullmatch(r"/s/[\w~=-]{6,128}", parts.path, flags=re.ASCII):
            query = ""
        elif parts.path == "/s" and {"__biz", "mid", "idx", "sn"} <= {key for key, val in public if val}:
            query = urlencode(public)
        else:
            raise ValueError
        return urlunsplit(("https", "mp.weixin.qq.com", parts.path, query, ""))
    except (ValueError, TypeError):
        raise AppError(code, message, "wechat") from None


def check_status(status: int) -> None:
    if status == 429:
        raise AppError("rate_limited", "来源限制访问频率，请稍后重试。", "wechat", http_status=status)
    if status in {404, 410}:
        raise AppError("article_unavailable", "文章已失效或不可查看。", "wechat", http_status=status)
    if status in {401, 403}:
        raise AppError("access_denied", "来源拒绝匿名读取，请在原文页面检查。", "wechat", http_status=status)
    if status != 200:
        raise AppError("source_unavailable", "来源未返回正常文章页面。", "wechat", http_status=status)


def fetch_http(url: str, *, client_factory=httpx.Client) -> tuple[str, str]:
    url = article_url(url)
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        with client_factory(trust_env=False, follow_redirects=False,
                            headers={"User-Agent": USER_AGENT, "Accept": "text/html",
                                     "Accept-Language": "zh-CN,zh;q=0.9"}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AppError("request_timeout", "文章读取超时。", "wechat")
                client.cookies.clear()
                with client.stream("GET", url, timeout=min(10, remaining)) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = article_url(urljoin(url, response.headers.get("location", "")), redirect=True)
                        continue
                    check_status(response.status_code)
                    if "html" not in response.headers.get("content-type", "").lower():
                        raise AppError("schema_changed", "来源返回的内容不是 HTML 文章。", "wechat")
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        if time.monotonic() > deadline:
                            raise AppError("request_timeout", "文章读取超时。", "wechat")
                        if len(data) + len(chunk) > MAX_HTML_BYTES:
                            raise AppError("response_too_large", "文章页面超过 4 MiB 上限，未返回截断正文。", "wechat")
                        data.extend(chunk)
                    return data.decode("utf-8", errors="replace"), url
        raise AppError("unsafe_redirect", "文章跳转次数超过上限。", "wechat")
    except httpx.TimeoutException:
        raise AppError("request_timeout", "文章读取超时。", "wechat") from None
    except httpx.HTTPError:
        raise AppError("network_error", "无法连接公众号文章来源，请检查 MCP 宿主网络。", "wechat") from None
