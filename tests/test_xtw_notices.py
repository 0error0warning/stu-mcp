"""Synthetic regressions for the public Youth League templates observed 2026-11-15."""
from urllib.parse import urljoin

import httpx
import pytest

from stu_mcp.features.notices import service
from stu_mcp.features.notices.parser import parse_public, parse_public_article
from stu_mcp.features.notices.schema import QUICK_LINKS
from stu_mcp.network import checked_url
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError
from stu_mcp.sources import PUBLIC_LISTINGS

BASE = "https://xtw.stu.edu.cn"
LISTING = BASE + "/index/tzgg.htm"
ARTICLE = BASE + "/info/1048/12345.htm"
DOWNLOAD = ("/system/_content/download.jsp?urltype=news.DownloadAttachUrl"
            "&owner=123456&wbfileid=0123456789ABCDEF0123456789ABCDEF")


def listing_row(identity=12345, *, year="2026", month_day="11/12", title="合成校团委通知"):
    return (f'<li><a href="/info/1048/{identity}.htm" title="{title}">'
            f'<div class="text-ldata"><div><p>{month_day}</p><span>{year}</span></div></div>'
            f'<div class="text-linfo"><h3>{title}</h3>'
            '<p>活动时间为2026年12月6日，报名详见正文。</p></div></a></li>')


def listing(rows=None, next_page=""):
    pager = f'<span class="p_pages"><span class="p_next"><a href="{next_page}">下页</a></span></span>'
    return '<div class="text-list"><ul>' + (listing_row() if rows is None else rows) + '</ul></div>' + (
        pager if next_page else '')


def article(body="<p>合成通知正文，活动在2026年12月6日举行。</p>", extra="", *, title="合成校团委通知",
            date="2026-11-12"):
    return ('<nav>站点导航</nav><div class="art-main"><form name="_newscontent_fromname">'
            f'<div class="art-tit"><h3>{title}</h3><p><span>信息来源：</span>'
            f'<span>发布日期：{date}</span></p></div>'
            f'<div id="vsb_content"><div class="v_news_content">{body}</div></div>'
            f'<div id="div_vote_id"></div>{extra}'
            '<div class="art-info"><div class="pnext"><a href="/next.pdf">下一条</a></div></div>'
            '</form></div><footer><a href="/footer.pdf">页脚附件</a></footer>')


def test_xtw_is_available_through_the_existing_anonymous_public_source():
    assert checked_url("public", ARTICLE) == ARTICLE
    paths = {url for _, url in PUBLIC_LISTINGS}
    assert {LISTING, BASE + "/bszy/gzzd.htm", BASE + "/bszy/zlxz.htm",
            BASE + "/index17X/cxcz/tzb.htm"} <= paths


def test_listing_uses_split_publication_date_instead_of_an_event_in_the_summary():
    record = parse_public(listing(), LISTING, "校团委通知公告", 5)[0]
    assert record["published_at"] == "2026-11-12"
    assert record["title"] == "合成校团委通知"
    assert record["id"] == item_id("public", "notice", ARTICLE)
    assert "报名详见正文" in record["summary"]


@pytest.mark.parametrize("year,month_day", [("", "11/12"), ("2026", "02/30"), ("2026", "13/01")])
def test_bad_listing_date_cannot_be_filled_from_summary_text(year, month_day):
    with pytest.raises(AppError) as error:
        parse_public(listing(listing_row(year=year, month_day=month_day)), LISTING, "校团委通知公告", 5)
    assert error.value.code == "schema_changed"


def test_listing_ignores_sidebar_articles_and_rejects_conflicting_duplicate_rows():
    outside = '<aside><a href="/info/1048/999.htm">侧栏推荐</a></aside>'
    assert len(parse_public(outside + listing(listing_row() * 2), LISTING, "校团委通知公告", 5)) == 1
    with pytest.raises(AppError):
        parse_public(listing(listing_row() + listing_row(title="另一条合成通知")), LISTING, "校团委通知公告", 5)


def test_article_reads_labeled_metadata_and_separate_vsb_attachment_list():
    html = article(extra=f'<ul><li>附件【<a href="{DOWNLOAD}">合成制度.pdf</a>】已下载3次</li></ul>')
    record = parse_public_article(html, ARTICLE)
    assert record["title"] == "合成校团委通知" and record["published_at"] == "2026-11-12"
    assert record["body"] == "合成通知正文，活动在2026年12月6日举行。"
    assert record["attachments"] == [{"name": "合成制度.pdf", "url": DOWNLOAD}]


def test_alternate_vsb_body_used_by_the_climbing_plan_keeps_its_text_and_attachments():
    html = article(extra=f'<ul><li><a href="{DOWNLOAD}">合成攀登计划.pdf</a></li></ul>').replace(
        'id="vsb_content"', 'id="vsb_content_2"')
    record = parse_public_article(html, BASE + "/info/1088/12345.htm")
    assert record["body"] == "合成通知正文，活动在2026年12月6日举行。"
    assert record["attachments"] == [{"name": "合成攀登计划.pdf", "url": DOWNLOAD}]


def test_two_observed_vsb_bodies_are_ambiguous_instead_of_selecting_the_first():
    html = article().replace('<div id="div_vote_id">', '<div id="vsb_content_2">歧义正文</div><div id="div_vote_id">')
    with pytest.raises(AppError) as error:
        parse_public_article(html, ARTICLE)
    assert error.value.code == "schema_changed"


def test_attachment_only_article_is_readable_and_duplicate_links_are_deduplicated():
    link = f'<a href="{DOWNLOAD}">合成制度.pdf</a>'
    record = parse_public_article(article(body="", extra=f'<ul><li>{link}{link}</li></ul>'), ARTICLE)
    assert record["body"] == "" and len(record["attachments"]) == 1


@pytest.mark.parametrize("suffix", ["xlsx", "pptx", "doc", "docx", "zip", "rar"])
def test_other_attachment_formats_are_listed_without_claiming_text_extraction(suffix):
    record = parse_public_article(article(extra=f'<ul><li><a href="/files/example.{suffix}">合成附件</a></li></ul>'), ARTICLE)
    assert record["attachments"] == [{"name": "合成附件", "url": f"/files/example.{suffix}"}]


def test_attachments_do_not_follow_external_or_authentication_urls():
    links = ''.join(f'<a href="{href}">不应导出</a>' for href in (
        "https://example.org/files/test.pdf", "https://www.stu.edu.cn/files/test.pdf",
        "/files/test.pdf?ticket=SYNTHETIC", "/system/_content/download.jsp?urltype=unknown&owner=1",
        "/download-login?password=SYNTHETIC"))
    assert parse_public_article(article(extra=links), ARTICLE)["attachments"] == []


@pytest.mark.parametrize("html", [article(title=""), article(date="2026-02-30"),
                                 article().replace('发布日期：', '活动日期：'),
                                 article().replace('<h3>', '<h3>歧义</h3><h3>'),
                                 '<main><p>未知的校团委首页模板</p></main>'])
def test_article_requires_the_observed_unique_title_date_and_body(html):
    with pytest.raises(AppError) as error:
        parse_public_article(html, ARTICLE)
    assert error.value.code == "schema_changed"


def test_second_page_failure_keeps_the_first_page_and_reports_its_scope(monkeypatch):
    from test_notice_service import factory

    monkeypatch.setattr(service, "PUBLIC_LISTINGS", (("校团委通知公告", LISTING),))
    page_two = urljoin(LISTING, "tzgg/238.htm")
    calls = []
    pages = {LISTING: listing(next_page="tzgg/238.htm"),
             page_two: AppError("network_error", "合成网络错误", "public"),
             QUICK_LINKS:
             '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}
    result = service.public(20, http_factory=factory(pages, calls))
    assert any(item.get("url") == ARTICLE for item in result.items)
    assert result.errors[0]["status"] == "network_error"
    scope = result.coverage["listings"][0]
    assert scope["pages_read"] == 1 and scope["status"] == "partial"


def test_pagination_is_bounded_deduplicated_and_uses_observed_reverse_page_numbers(monkeypatch):
    from test_notice_service import factory

    monkeypatch.setattr(service, "PUBLIC_LISTINGS", (("校团委通知公告", LISTING),))
    pages = {LISTING: listing(listing_row(), "tzgg/238.htm"),
             BASE + "/index/tzgg/238.htm": listing(listing_row() + listing_row(12346), "237.htm"),
             BASE + "/index/tzgg/237.htm": listing(listing_row(12347), "236.htm"),
             "https://www.stu.edu.cn/kstd.htm":
             '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}
    calls = []
    result = service.public(50, http_factory=factory(pages, calls))
    notices = [item for item in result.items if item["kind"] == "notice"]
    assert len(notices) == 3
    scope = result.coverage["listings"][0]
    assert scope["pages_read"] == 3 and scope["has_more"] is True
    assert len([url for _, url in calls if url.startswith(BASE)]) == 3


def test_pagination_stops_at_the_requested_limit_and_reports_unread_items(monkeypatch):
    from test_notice_service import factory

    monkeypatch.setattr(service, "PUBLIC_LISTINGS", (("校团委通知公告", LISTING),))
    pages = {LISTING: listing(listing_row() + listing_row(12346), "tzgg/238.htm"), QUICK_LINKS:
             '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}
    calls = []
    result = service.public(1, http_factory=factory(pages, calls))
    assert sum(item["kind"] == "notice" for item in result.items) == 1
    assert result.coverage["listings"][0]["has_more"] is True
    assert len([url for _, url in calls if url.startswith(BASE)]) == 1


def test_pagination_loop_keeps_read_notices_and_stops_without_a_repeat_request(monkeypatch):
    from test_notice_service import factory

    monkeypatch.setattr(service, "PUBLIC_LISTINGS", (("校团委通知公告", LISTING),))
    pages = {LISTING: listing(next_page="tzgg/238.htm"),
             BASE + "/index/tzgg/238.htm": listing(listing_row(12346), "238.htm"), QUICK_LINKS:
             '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}
    calls = []
    result = service.public(20, http_factory=factory(pages, calls))
    assert sum(item["kind"] == "notice" for item in result.items) == 2
    assert result.errors[0]["status"] == "schema_changed"
    assert len([url for _, url in calls if url.startswith(BASE)]) == 2


@pytest.mark.parametrize("next_page", ["https://example.org/index/tzgg/238.htm",
                                      "/index/other/238.htm", "/index/tzgg/238.htm?ticket=SYNTHETIC"])
def test_pagination_never_requests_a_different_column_or_unsafe_url(monkeypatch, next_page):
    from test_notice_service import factory

    monkeypatch.setattr(service, "PUBLIC_LISTINGS", (("校团委通知公告", LISTING),))
    pages = {LISTING: listing(next_page=next_page), "https://www.stu.edu.cn/kstd.htm":
             '<div class="n_kuaisu"><div class="box"><a href="https://r.stu.edu.cn/">综合报修</a></div></div>'}
    calls = []
    result = service.public(20, http_factory=factory(pages, calls))
    assert result.errors[0]["status"] == "schema_changed"
    assert len([url for _, url in calls if url.startswith(BASE)]) == 1


@pytest.mark.parametrize("content_type,body,code", [
    ("text/html; charset=utf-8", '<h1>请输入验证码下载附件</h1><input id="codeValue">', "interaction_required"),
    ("application/octet-stream", '<!DOCTYPE html><html><input name="codeValue"></html>', "interaction_required"),
    ("text/html", '<title>服务器内部错误</title><p>稍后再试</p>', "attachment_unreadable"),
])
def test_attachment_read_does_not_report_a_download_challenge_as_file_text(app, monkeypatch, content_type, body, code):
    from stu_mcp.network import CampusHTTP

    record = {"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知", "url": ARTICLE,
              "body": "保留的合成正文", "attachments": [{"name": "合成制度.pdf", "url": DOWNLOAD}]}
    app.store.save_batch("public", [record])
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=httpx.MockTransport(respond)))
    if code in {"interaction_required", "attachment_unreadable"}:
        result = app.attachment(record["id"])
        assert result["ok"] is False and result["content_ready"] is False
        assert result["status"] == code and result["retryable"] is False
        assert result["next_action"] == "show_source_link"
        assert result["source_url"] == ARTICLE and result["source_url"] != urljoin(ARTICLE, DOWNLOAD)
        assert result["title"] == record["title"] and result["name"] == "合成制度.pdf"
        assert result["content_trust"] == "untrusted_source_data"
        assert "通知正文" in result["message"]
        assert "text" not in result
    else:
        with pytest.raises(AppError) as error:
            app.attachment(record["id"])
        assert error.value.code == code
    assert len(requests) == 1
    assert app.store.get(record["id"])["attachments"] == record["attachments"]


def test_cli_captcha_result_hands_the_user_the_article_link_and_keeps_failure_exit_code(app, monkeypatch, capsys):
    import json

    from stu_mcp.cli import main
    from stu_mcp.network import CampusHTTP

    app.store.save_batch("public", [{"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知",
                                    "url": ARTICLE, "attachments": [{"name": "合成制度.pdf", "url": DOWNLOAD}]}])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text='<input id="codeValue">',
                                                           headers={"content-type": "text/html"}))
    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=transport))
    monkeypatch.setattr("stu_mcp.cli.App", lambda: app)
    assert main(["attachment", "public:notice:synthetic"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["source_url"] == ARTICLE and result["next_action"] == "show_source_link"
    assert result["status"] == "interaction_required" and result["name"] == "合成制度.pdf"


@pytest.mark.parametrize("article_url", [ARTICLE + "?ticket=SYNTHETIC", "https://example.org/info/1/2.htm",
                                         "https://user:password@xtw.stu.edu.cn/info/1048/12345.htm"])
def test_captcha_handoff_does_not_export_an_unsafe_cached_article_link(app, monkeypatch, article_url):
    from stu_mcp.network import CampusHTTP

    app.store.save_batch("public", [{"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知",
                                    "url": article_url, "attachments": [{"name": "合成制度.pdf",
                                                                          "url": urljoin(BASE, DOWNLOAD)}]}])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text='<input id="codeValue">',
                                                           headers={"content-type": "text/html"}))
    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=transport))
    with pytest.raises(AppError) as error:
        app.attachment("public:notice:synthetic")
    assert error.value.code == "unsafe_url"
    assert "source_url" not in error.value.result()


def test_readable_text_attachment_still_uses_the_existing_tool(app, monkeypatch):
    from stu_mcp.network import CampusHTTP

    app.store.save_batch("public", [{"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知",
                                    "url": ARTICLE, "attachments": [{"name": "合成附件.txt", "url": DOWNLOAD}]}])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text="合成附件正文",
                                                           headers={"content-type": "text/plain; charset=utf-8"}))
    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=transport))
    assert app.attachment("public:notice:synthetic")["text"] == "合成附件正文"
