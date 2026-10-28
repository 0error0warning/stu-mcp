"""Explicit optional rendering, with a fresh anonymous context per request."""
from __future__ import annotations

from contextlib import suppress
from urllib.parse import urlsplit

from ...runtime import AppError
from .adapter import MAX_HTML_BYTES, MAX_REDIRECTS, USER_AGENT, article_url, check_status

# Serialize only article evidence, not megabytes of runtime scripts or comments.
# Snapshot expressions are fixed, never assembled from source-provided text.
_SNAPSHOT = r"""() => {
    const out = document.createElement('main');
    const selector = '#activity-name, #js_name, #js_author_name, #publish_time, #meta_content, '
        + '#js_content, .weui-msg__text-area, #js_verify, .weui_msg, '
        + 'meta[property="og:title"], meta[name="author"], meta[property="article:published_time"]';
    for (const node of document.querySelectorAll(selector)) {
        if (!node.parentElement?.closest(selector)) out.append(node.cloneNode(true));
    }
    if (!out.childNodes.length) out.textContent = document.body?.innerText.slice(0, 10000) || '';
    for (const node of out.querySelectorAll('script, style, noscript, iframe, svg, link')) node.remove();
    for (const image of out.querySelectorAll('img')) image.replaceWith(document.createElement('img'));
    const values = {
        msg_title: typeof msg_title === 'string' ? msg_title : '',
        nickname: typeof nickname === 'string' ? nickname : '',
        ct: typeof ct !== 'undefined' ? String(ct) : '',
        content_noencode: typeof content_noencode === 'string' ? content_noencode : ''
    };
    const script = document.createElement('script');
    script.textContent = Object.entries(values).map(([key, value]) =>
        'var ' + key + ' = ' + JSON.stringify(value).replace(/</g, '\\u003c') + ';').join('\n');
    out.append(script);
    return out.outerHTML;
}"""


def fetch_browser(url: str) -> tuple[str, str]:
    url = article_url(url)
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ImportError:
        raise AppError("browser_unavailable", "可选浏览器未安装；请在 MCP 宿主安装 stu-mcp[browser] 及 Chromium，或使用 HTTP。", "wechat") from None

    failure, navigations = None, 0

    def route(request_route):
        nonlocal failure, navigations
        request = request_route.request
        parts = urlsplit(request.url)
        allowed = (request.method == "GET" and parts.scheme == "https" and parts.netloc in {
            "mp.weixin.qq.com", "res.wx.qq.com", "res2.wx.qq.com"}
            and request.resource_type in {"document", "script", "xhr", "fetch"})
        if request.is_navigation_request() and request.frame.parent_frame is not None:
            allowed = False
        elif request.is_navigation_request():
            navigations += 1
            try:
                article_url(request.url, redirect=True)
                if navigations > MAX_REDIRECTS + 1:
                    raise AppError("unsafe_redirect", "文章跳转次数超过上限。", "wechat")
            except AppError as exc:
                failure, allowed = exc, False
        request_route.continue_() if allowed else request_route.abort()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=10000)
            try:
                with browser.new_context(user_agent=USER_AGENT, accept_downloads=False,
                                         service_workers="block") as context:
                    context.route("**/*", route)
                    page = context.new_page()
                    try:
                        response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    except TimeoutError:
                        raise
                    except Error:
                        raise failure or AppError("network_error", "可选浏览器无法连接文章来源。", "wechat") from None
                    if failure:
                        raise failure
                    if response is not None:
                        check_status(response.status)
                    with suppress(TimeoutError):
                        page.wait_for_function("(document.querySelector('#js_content')?.textContent?.trim().length || 0) >= 20",
                                               timeout=3000)
                    if failure:
                        raise failure
                    final = article_url(page.url, redirect=True)
                    html = page.evaluate(_SNAPSHOT)
                    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
                        raise AppError("response_too_large", "渲染后的文章内容超过 4 MiB 上限。", "wechat")
                    return html, final
            finally:
                browser.close()
    except TimeoutError:
        raise failure or AppError("request_timeout", "可选浏览器读取超时。", "wechat") from None
    except Error:
        raise failure or AppError("browser_unavailable", "可选浏览器未能运行；请检查宿主 Chromium 安装，或使用 HTTP。", "wechat") from None
