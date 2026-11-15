"""On-demand notice collection, independent of page layouts and HTTP clients."""
from __future__ import annotations

from urllib.parse import urlparse

from ...collection import Article, Collection
from ...network import CampusHTTP
from ...runtime import AppError
from ...webvpn import protected_access
from .adapter import NoticeAdapter
from .schema import PUBLIC_LISTINGS, XTW_HOST, XTW_MAX_PAGES


def _public_listing(adapter, http, category: str, url: str, limit: int) -> Collection:
    max_pages = XTW_MAX_PAGES if urlparse(url).hostname == XTW_HOST else 1
    scope = {"category": category, "url": url, "pages_read": 0, "items": 0,
             "max_pages": max_pages, "has_more": None, "status": "ok"}
    result = Collection(coverage=scope)
    current, visited, seen = url, set(), {}
    for _ in range(max_pages):
        visited.add(current)
        try:
            page = adapter.public_page(http, current, category, limit + 1, root=url)
            scope["pages_read"] += 1
            for item in page.items:
                previous = seen.get(item["id"])
                if previous and any(previous.get(key) != item.get(key) for key in ("title", "published_at")):
                    raise AppError("schema_changed", "通知在翻页时出现冲突标题或日期。", "public")
                if previous:
                    continue
                if len(result.items) == limit:
                    break
                result.items.append(item)
                seen[item["id"]] = item
            next_url = page.coverage["next_url"]
            extra = any(item["id"] not in seen for item in page.items)
            scope["has_more"] = bool(next_url) if max_pages > 1 else None
            if extra:
                scope["has_more"] = True
            result.errors.extend(page.errors)
            if page.errors:
                scope["has_more"] = None
            if page.errors or not next_url or len(result.items) >= limit:
                break
            if next_url in visited:
                raise AppError("schema_changed", "通知栏目重复返回已读页面，已停止翻页。", "public")
            current = next_url
        except AppError as exc:
            result.fail(category, exc, stage="listing")
            scope["has_more"] = None
            break
    scope["items"] = len(result.items)
    scope["status"] = "partial" if result.errors else "limited" if scope["has_more"] else "ok"
    return result


def public(limit: int, *, http_factory=CampusHTTP) -> Collection:
    result = Collection(limited=True, coverage={"scope": "recent_listing_pages", "per_listing": limit, "listings": []})
    adapter = NoticeAdapter(http_factory)
    with adapter.public_session() as http:
        for category, url in PUBLIC_LISTINGS:
            listing = _public_listing(adapter, http, category, url, limit)
            result.items.extend(listing.items)
            result.errors.extend(listing.errors)
            result.coverage["listings"].append(listing.coverage)
        try:
            result.items.extend(adapter.service_links(http))
        except AppError as exc:
            result.fail("校园服务入口", exc)
    if not result.items:
        raise AppError("source_unavailable", "公开来源暂时无法读取；这不表示没有通知。", "public")
    return result


def oa(vault, limit: int, *, http_factory=CampusHTTP, protected_reader=protected_access) -> Collection:
    adapter = NoticeAdapter(http_factory, protected_reader)
    private, version = False, None
    try:
        records = adapter.anonymous_oa(limit)
    except AppError:
        accessed = adapter.protected_oa(vault, limit)
        records, version, private = accessed.value, accessed.session_version, True
    return Collection(records, private=private, limited=True, session_version=version,
                      coverage={"scope": "first_listing_page", "limit": limit,
                                "access": "authenticated_https" if private else "anonymous_http"})


def article(record: dict, vault, *, http_factory=CampusHTTP, protected_reader=protected_access) -> Article:
    source, url = record["source"], record.get("url")
    if source not in {"public", "oa"} or not url:
        raise AppError("unsupported_article", "请通过对应课程工具读取此来源。", source)
    return NoticeAdapter(http_factory, protected_reader).article(record, vault)
