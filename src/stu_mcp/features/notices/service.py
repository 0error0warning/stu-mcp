"""On-demand notice collection, independent of page layouts and HTTP clients."""
from __future__ import annotations

from ...collection import Article, Collection
from ...network import CampusHTTP
from ...runtime import AppError
from ...webvpn import protected_access
from .adapter import NoticeAdapter
from .schema import PUBLIC_LISTINGS


def public(limit: int, *, http_factory=CampusHTTP) -> Collection:
    result = Collection(limited=True, coverage={"scope": "recent_listing_pages", "per_listing": limit})
    adapter = NoticeAdapter(http_factory)
    with adapter.public_session() as http:
        for category, url in PUBLIC_LISTINGS:
            try:
                result.items.extend(adapter.public_listing(http, url, category, limit))
            except AppError as exc:
                result.fail(category, exc)
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
