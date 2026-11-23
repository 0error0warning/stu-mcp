"""Transport boundary; no settings changes or alternative authentication paths."""
from __future__ import annotations

from urllib.parse import urlparse

from ...collection import Article, Collection
from ...network import CampusHTTP, checked_url
from ...runtime import AppError
from ...webvpn import protected_access
from .parser import (
    parse_links,
    parse_oa,
    parse_oa_article,
    parse_public,
    parse_public_article,
    public_next_page,
)
from .schema import OA_DIRECT, OA_LIST_PATH, OA_SECURE_PROXY, QUICK_LINKS, is_oa_webvpn_url, oa_content_url


class NoticeAdapter:
    def __init__(self, http_factory=CampusHTTP, protected_reader=protected_access):
        self.http_factory = http_factory
        self.protected_reader = protected_reader

    def public_session(self):
        return self.http_factory("public")

    def public_listing(self, http, url: str, category: str, limit: int) -> list[dict]:
        return self.public_page(http, url, category, limit).items

    def public_page(self, http, url: str, category: str, limit: int, *, root: str | None = None) -> Collection:
        html = http.text(url)
        records = parse_public(html, url, category, limit)
        for record in records:
            checked_url("public", record["url"])
        page = Collection(records, coverage={"next_url": None})
        if root:
            try:
                page.coverage["next_url"] = public_next_page(html, url, root)
            except AppError as exc:
                page.fail(category, exc, stage="pagination")
        return page

    def service_links(self, http) -> list[dict]:
        return parse_links(http.text(QUICK_LINKS), QUICK_LINKS)

    def anonymous_oa(self, limit: int) -> list[dict]:
        # Keep anonymous HTTP entirely separate from any saved WebVPN session.
        http = self.http_factory("oa")
        try:
            return parse_oa(http.text(OA_DIRECT + OA_LIST_PATH), OA_DIRECT, limit)
        finally:
            http.client.close()

    def protected_oa(self, vault, limit: int):
        return self.protected_reader(vault, OA_SECURE_PROXY + OA_LIST_PATH,
                                     lambda response: parse_oa(response.text, OA_SECURE_PROXY, limit))

    def article(self, record: dict, vault) -> Article:
        source, url = record["source"], record["url"]
        version = None
        if source == "oa":
            url = oa_content_url(url)
        if source == "oa" and is_oa_webvpn_url(url):
            accessed = self.protected_reader(vault, url, lambda response: response.text)
            html, version = accessed.value, accessed.session_version
        else:
            with self.http_factory(source) as http:
                html = http.text(url)
        parsed = urlparse(url)
        item = (parse_oa_article(html, f"{parsed.scheme}://{parsed.netloc}") if source == "oa"
                else parse_public_article(html, url))
        return Article(item, version)
