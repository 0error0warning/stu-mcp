"""One article per bounded read, with the same validation for both backends."""
from __future__ import annotations

from datetime import UTC, datetime

from ...runtime import AppError
from .adapter import article_url, fetch_http
from .parser import parse_article


def read_article(url: str, backend: str = "http", offset: int = 0, max_chars: int = 8000) -> dict:
    result = {"source": "wechat", "backend": backend if isinstance(backend, str) and backend in {"http", "browser"} else None,
              "cached": False, "content_ready": False, "content_trust": "untrusted_source_data",
              "execution_scope": "mcp_host"}
    try:
        canonical = article_url(url)
        result["source_url"] = canonical
        if not isinstance(backend, str) or backend not in {"http", "browser"}:
            raise AppError("invalid_backend", "backend 只能为 http 或 browser；不会自动切换。", "wechat")
        if type(offset) is not int or not 0 <= offset <= 4 * 1024 * 1024:
            raise AppError("invalid_offset", "offset 必须是 0–4194304 的整数。", "wechat")
        if type(max_chars) is not int or not 1 <= max_chars <= 20000:
            raise AppError("invalid_limit", "max_chars 必须是 1–20000 的整数。", "wechat")
        if backend == "browser":
            from .browser import fetch_browser
            html, final_url = fetch_browser(canonical)
        else:
            html, final_url = fetch_http(canonical)
        result["source_url"] = final_url
        article = parse_article(html)
        body = article.pop("text")
        end = min(len(body), offset + max_chars)
        result.update(ok=True, status="ok", content_ready=True, **article,
                      text=body[offset:end], offset=offset, total_chars=len(body),
                      has_more=end < len(body), next_offset=end if end < len(body) else None,
                      coverage="article_text_only")
    except AppError as exc:
        result.update(exc.result())
        result["next_action"] = {
            "captcha_required": "open_source_page", "article_unavailable": "check_source_url",
            "insufficient_content": "open_source_page", "browser_unavailable": "install_optional_browser",
        }.get(exc.code, result["next_action"])
    result["checked_at"] = datetime.now(UTC).isoformat()
    return result
