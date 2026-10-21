from types import SimpleNamespace

import pytest

from stu_mcp import collectors
from stu_mcp.features.notices import service
from stu_mcp.features.notices.schema import (
    OA_DIRECT,
    OA_LIST_PATH,
    OA_SECURE_PROXY,
    PUBLIC_LISTINGS,
    QUICK_LINKS,
)
from stu_mcp.runtime import AppError

OA_LISTING = ('<form><input type="password"></form><table><tr><td>'
              '<a href="/newstemplateprotal.jsp?docid=DEMO">合成通知</a></td>'
              '<td>合成学院</td><td>2026-10-20</td></tr></table>')


class FakeHTTP:
    def __init__(self, source, pages, calls):
        self.source, self.pages, self.calls, self.client = source, pages, calls, self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.calls.append((self.source, "close"))

    def text(self, url):
        self.calls.append((self.source, url))
        value = self.pages[url]
        if isinstance(value, AppError):
            raise value
        return value


def factory(pages, calls):
    return lambda source: FakeHTTP(source, pages, calls)


def public_pages():
    return {**{url: f'<li><a href="/info/1001/{index}.htm">合成通知{index}</a>2026-10-20</li>'
               for index, (_, url) in enumerate(PUBLIC_LISTINGS)},
            QUICK_LINKS: '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}


def test_public_partial_collection_keeps_other_columns_when_one_page_changes():
    pages, calls = public_pages(), []
    pages[PUBLIC_LISTINGS[1][1]] = "<h1>新版未知页面</h1>"
    pages[QUICK_LINKS] = "<main>新版未知目录</main>"
    result = service.public(5, http_factory=factory(pages, calls))
    assert result.status == "partial" and len(result.items) == 3
    assert [error["part"] for error in result.errors] == [PUBLIC_LISTINGS[1][0], "校园服务入口"]
    assert all(error["status"] == "schema_changed" for error in result.errors)
    assert result.coverage == {"scope": "recent_listing_pages", "per_listing": 5}
    assert all(source == "public" for source, _ in calls)
    assert len(calls) == 6


def test_public_all_pages_failed_is_not_a_successful_empty_collection():
    pages, calls = {url: "<h1>未知页面</h1>" for url in public_pages()}, []
    with pytest.raises(AppError) as error:
        service.public(5, http_factory=factory(pages, calls))
    assert error.value.code == "source_unavailable"


def test_anonymous_oa_does_not_inspect_a_vault_or_protected_reader():
    calls = []

    def forbidden(*_):
        pytest.fail("anonymous OA must not use authentication")

    result = service.oa(object(), 5, http_factory=factory({OA_DIRECT + OA_LIST_PATH: OA_LISTING}, calls),
                        protected_reader=forbidden)
    assert result.private is False and result.session_version is None
    assert result.items[0]["department"] == "合成学院"
    assert result.coverage["access"] == "anonymous_http"
    assert calls == [("oa", OA_DIRECT + OA_LIST_PATH), ("oa", "close")]


def test_oa_transport_or_schema_failure_uses_only_the_existing_https_protected_path():
    calls, protected_calls = [], []

    def protected(vault, url, read):
        protected_calls.append((vault, url))
        return SimpleNamespace(value=read(SimpleNamespace(text=OA_LISTING)), session_version=b"synthetic")

    vault = object()
    result = service.oa(vault, 5, http_factory=factory({OA_DIRECT + OA_LIST_PATH: "<h1>未知页面</h1>"}, calls),
                        protected_reader=protected)
    assert protected_calls == [(vault, OA_SECURE_PROXY + OA_LIST_PATH)]
    assert result.private is True and result.session_version == b"synthetic"
    assert result.items[0]["url"].startswith(OA_SECURE_PROXY + "/")
    assert result.coverage["access"] == "authenticated_https"
    assert calls[-1] == ("oa", "close")


def test_recognized_empty_oa_board_does_not_trigger_login():
    def forbidden(*_):
        pytest.fail("a verified empty anonymous board must not trigger login")

    result = service.oa(object(), 5, http_factory=factory(
        {OA_DIRECT + OA_LIST_PATH: '<form id="searchForm"></form><p>暂无通知</p>'}, []), protected_reader=forbidden)
    assert result.items == [] and result.private is False


@pytest.mark.parametrize("source,base", [("public", "https://www.stu.edu.cn/info/1/2.htm"),
                                       ("oa", OA_DIRECT + "/newstemplateprotal.jsp?docid=DEMO")])
def test_anonymous_article_transport_reads_only_the_requested_source(source, base):
    calls = []
    result = service.article({"source": source, "url": base}, object(),
                             http_factory=factory({base: '<div id="docContent">合成正文</div>'}, calls))
    assert result.item == {"body": "合成正文", "attachments": []} and result.session_version is None
    assert calls == [(source, base), (source, "close")]


def test_protected_article_carries_session_version_without_exporting_it_into_the_item():
    calls, vault = [], object()
    url = OA_SECURE_PROXY + "/newstemplateprotal.jsp?docid=DEMO"

    def protected(given_vault, given_url, read):
        calls.append((given_vault, given_url))
        return SimpleNamespace(value=read(SimpleNamespace(text='<div id="docContent">合成正文</div>')),
                               session_version=b"synthetic")

    result = service.article({"source": "oa", "url": url}, vault, protected_reader=protected)
    assert calls == [(vault, url)] and result.session_version == b"synthetic"
    assert result.item == {"body": "合成正文", "attachments": []}


def test_changed_article_does_not_replace_previously_cached_body(app, monkeypatch):
    url = "https://www.stu.edu.cn/info/1/2.htm"
    record = {"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知", "url": url,
              "body": "已核实的合成正文", "attachments": [{"name": "合成附件", "url": "/synthetic.pdf"}]}
    app.store.save_batch("public", [record])
    before = app.store.get(record["id"])
    monkeypatch.setattr(collectors, "article", lambda item, vault: service.article(
        item, vault, http_factory=factory({url: "<h1>服务器内部错误</h1>"}, [])))
    with pytest.raises(AppError) as error:
        app.notice(record["id"], refresh=True)
    assert error.value.code == "source_unavailable"
    after = app.store.get(record["id"])
    assert after["body"] == before["body"] and after["attachments"] == before["attachments"]
    assert after["detail_collected_at"] == before["detail_collected_at"]


def test_partial_listing_update_preserves_an_existing_article_detail(app, monkeypatch):
    pages, calls = public_pages(), []
    monkeypatch.setattr(collectors, "public", lambda limit: service.public(limit, http_factory=factory(pages, calls)))
    app.refresh("public")
    record = next(item for item in app.query("notice", source="public")["items"] if item["category"] == PUBLIC_LISTINGS[0][0])
    app.store.save_batch("public", [{**record, "body": "合成正文保留", "attachments": []}])
    before = app.store.get(record["id"])
    pages[PUBLIC_LISTINGS[1][1]] = "<h1>未知新版页面</h1>"
    result = app.refresh("public")
    assert result["status"] == "partial" and result["errors"][0]["status"] == "schema_changed"
    after = app.store.get(record["id"])
    assert after["body"] == "合成正文保留" and after["detail_collected_at"] == before["detail_collected_at"]
