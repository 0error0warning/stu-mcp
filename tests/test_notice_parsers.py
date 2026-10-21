from urllib.parse import urljoin

import pytest

from stu_mcp.features.notices.parser import (
    parse_links,
    parse_oa,
    parse_oa_article,
    parse_public,
    parse_public_article,
)
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError

OA = "http://oa.stu.edu.cn"
PUBLIC = "https://www.stu.edu.cn"
LINK = '<a href="/newstemplateprotal.jsp?docid=DEMO">合成 OA 通知</a>'


def table(columns, values):
    return "<table><tr>" + "".join(f"<th>{name}</th>" for name in columns) + "</tr><tr>" + "".join(
        f"<td>{value}</td>" for value in values) + "</tr></table>"


@pytest.mark.parametrize("headers,values", [
    (["标题", "部门", "日期"], [LINK, "合成学院", "2026-10-20"]),
    (["发布日期", "阅读量", "发布单位", "通知标题"], ["2026-10-20", "100", "合成学院", LINK]),
    (["主题", "发布时间", "发文单位", "操作"], [LINK, "2026-10-20 12:30", "合成学院", "查看"]),
])
def test_oa_headers_follow_names_instead_of_column_positions(headers, values):
    record = parse_oa(table(headers, values), OA, 5)[0]
    assert record == {"id": item_id("oa", "notice", "DEMO"), "kind": "notice", "docid": "DEMO",
                      "title": "合成 OA 通知", "url": OA + "/newstemplateprotal.jsp?docid=DEMO",
                      "department": "合成学院", "published_at": "2026-10-20"}


@pytest.mark.parametrize("body,department,date", [
    (f"<table><tr><td>{LINK}</td></tr></table>", "", None),
    (f"<table><tr><td><div>{LINK}</div></td><td><b>合成学院</b></td><td>2026-10-20</td></tr></table>",
     "合成学院", "2026-10-20"),
])
def test_oa_observed_headerless_layouts_remain_compatible(body, department, date):
    record = parse_oa(body, OA, 5)[0]
    assert record["department"] == department and record["published_at"] == date


def test_oa_anonymous_listing_can_share_a_login_form():
    html = '<form><input type="password"></form>' + table(
        ["标题", "部门", "日期"], [LINK, "合成学院", "2026-10-20"])
    assert parse_oa(html, OA, 1)[0]["docid"] == "DEMO"


def test_oa_table_title_is_decoration_and_does_not_hide_named_headers():
    html = table(["标题", "部门", "日期"], [LINK, "合成学院", "2026-10-20"]).replace(
        "<table>", '<table><tr><th colspan="3">通知公告</th></tr>')
    assert parse_oa(html, OA, 5)[0]["department"] == "合成学院"


@pytest.mark.parametrize("html", [
    table(["标题", "部门", "部门", "日期"], [LINK, "甲", "乙", "2026-10-20"]),
    table(["标题", "阅读量", "日期"], [LINK, "3", "2026-10-20"]),
    '<table><tr><td>标题</td><td>新字段</td><td>新日期</td></tr>'
    f'<tr><td>{LINK}</td><td>学院</td><td>2026-10-20</td></tr></table>',
    table(["标题", "部门", "日期"], [LINK, "学院"]),
    f"<table><tr><td>新增列</td><td>{LINK}</td><td>学院</td><td>2026-10-20</td></tr></table>",
    f"<table><tr><td>{LINK}</td><td>学院</td></tr></table>",
    f"<div>{LINK}</div>",
    table(["标题", "部门", "日期"], ["另一个链接", LINK, "2026-10-20"]),
])
def test_oa_ambiguous_changed_tables_fail_instead_of_shifting_fields(html):
    with pytest.raises(AppError) as error:
        parse_oa(html, OA, 5)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("href", ["/newstemplateprotal.jsp", "/newstemplateprotal.jsp?docid=A&docid=B",
                                 "/newstemplateprotal.jsp?docid=bad%20id"])
def test_oa_requires_one_document_identity(href):
    with pytest.raises(AppError) as error:
        parse_oa(f'<table><tr><td><a href="{href}">合成标题</a></td></tr></table>', OA, 5)
    assert error.value.code == "schema_changed"


def test_oa_duplicate_identity_conflict_is_not_silently_deduplicated():
    html = f"<table><tr><td>{LINK}</td></tr><tr><td>{LINK.replace('合成 OA 通知', '不同标题')}</td></tr></table>"
    with pytest.raises(AppError) as error:
        parse_oa(html, OA, 5)
    assert error.value.code == "schema_changed"


def test_oa_exact_duplicate_is_deduplicated_and_bounded():
    html = f"<table><tr><td>{LINK}</td></tr><tr><td>{LINK}</td></tr></table>"
    assert len(parse_oa(html, OA, 5)) == 1
    assert len(parse_oa(html + html.replace("DEMO", "OTHER"), OA, 1)) == 1


@pytest.mark.parametrize("html", ['<form id="searchForm"></form>',
                                 '<form id="searchForm"><h1>服务升级</h1></form>',
                                 '<form><input type="password"></form>', '<h1>网络错误</h1>'])
def test_oa_unknown_and_login_templates_are_not_empty_lists(html):
    with pytest.raises(AppError) as error:
        parse_oa(html, OA, 5)
    assert error.value.code == "oa_unavailable"


def test_oa_recognized_empty_marker_requires_the_listing_form():
    assert parse_oa('<form id="searchForm"></form><p>暂无通知</p>', OA, 5) == []
    with pytest.raises(AppError):
        parse_oa('<p>暂无通知</p>', OA, 5)


@pytest.mark.parametrize("tag", ["section", "div", "aside"])
def test_service_links_survive_container_tag_and_wrapper_changes(tag):
    html = f'<{tag} class="n_kuaisu"><div><div class="box"><span><a href="https://r.stu.edu.cn/">综合报修</a></span></div></div></{tag}>'
    assert parse_links(html, PUBLIC + "/kstd.htm") == [
        {"id": item_id("public", "service", "https://r.stu.edu.cn/"), "kind": "service",
         "title": "综合报修", "url": "https://r.stu.edu.cn/"}]


@pytest.mark.parametrize("html", ["<main>新版目录</main>", '<div class="n_kuaisu"><div class="box"></div></div>'])
def test_service_directory_contract_loss_is_not_a_silent_empty_result(html):
    with pytest.raises(AppError) as error:
        parse_links(html, PUBLIC)
    assert error.value.code == "schema_changed"


def test_service_links_are_deduplicated_and_do_not_export_authentication_callbacks():
    html = '<div class="n_kuaisu"><div class="box">' + "".join(
        f'<a href="{href}">服务入口</a>' for href in (
            "https://repair.stu.edu.cn/", "https://repair.stu.edu.cn/",
            "https://repair.stu.edu.cn/student.aspx?ticket=SYNTHETIC", "javascript:alert(1)",
            "https://u:p@repair.stu.edu.cn/", "#", "")) + "</div></div>"
    assert len(parse_links(html, PUBLIC)) == 1


def test_public_listing_retains_ids_and_recognizes_both_observed_url_styles():
    for base, href in [(PUBLIC, "/info/1001/2001.htm"),
                       ("https://xsc.stu.edu.cn/NoticeList.aspx?NewsTypeID=3", "News.aspx?ID=123")]:
        url = urljoin(base, href)
        record = parse_public(f'<section><li><span><a href="{href}">合成学生通知</a></span>2026-10-20</li></section>',
                              base, "学生通知", 5)[0]
        assert record["id"] == item_id("public", "notice", url)
        assert record["url"] == url and record["published_at"] == "2026-10-20"


@pytest.mark.parametrize("html", ["<h1>维护中</h1>", '<a href="https://example.org/info/1/2.htm">外站通知</a>',
                                 '<a href="/info/1/2.htm?ticket=SYNTHETIC">认证回调</a>'])
def test_public_listings_do_not_accept_unknown_or_unsafe_pages(html):
    with pytest.raises(AppError) as error:
        parse_public(html, PUBLIC, "学校要闻", 5)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("container", ["<div id='docContent'>{}</div>", "<article>{}</article>",
                                      "<main><div id='vsb_content'>{}</div></main>",
                                      "<main>{}</main>",
                                      "<div id='content'><div class='v_news_content'>{}</div></div>"])
def test_article_body_survives_wrappers_and_ignores_navigation(container):
    html = "<nav>导航内容</nav>" + container.format("<p>合成通知正文</p>") + "<footer>页脚内容</footer>"
    assert parse_oa_article(html, OA) == {"body": "合成通知正文", "attachments": []}
    assert parse_public_article(html, PUBLIC) == {"body": "合成通知正文", "attachments": []}


@pytest.mark.parametrize("html,code", [
    ("<h1>服务器内部错误</h1>", "source_unavailable"),
    ("<title>503 Service Unavailable</title><div id='docContent'>稍后再试</div>", "source_unavailable"),
    ("<input type='password'><form>登录</form>", "needs_login"),
    ("<title>统一身份认证</title><main id='content'><p>请登录后查看通知</p><form><input type='password'></form></main>",
     "needs_login"),
    ("<main><p>请登录后查看通知</p><script>window.location.href='https://sso.stu.edu.cn/login';</script></main>",
     "needs_login"),
    ("<div>首页模板</div>", "schema_changed"),
    ("<div id='content'><nav><a href='/'>主页</a></nav></div>", "schema_changed"),
    ("<div id='docContent'>甲</div><div id='docContent'>乙</div>", "schema_changed"),
])
def test_articles_do_not_save_error_login_or_template_pages_as_full_text(html, code):
    for parser, base in ((parse_oa_article, OA), (parse_public_article, PUBLIC)):
        with pytest.raises(AppError) as error:
            parser(html, base)
        assert error.value.code == code


def test_error_words_in_real_article_text_do_not_make_the_page_an_error():
    html = '<div id="docContent"><p>发生网络错误时请联系服务部门。</p></div>'
    assert "网络错误" in parse_oa_article(html, OA)["body"]


def test_oa_attachment_keeps_its_verified_identity_and_survives_row_tag_changes():
    html = '<div id="docContent">合成正文</div><div id="accessory_dsp_tr1"><span><input name="accessory" value="42"></span>附件1：合成附件 下载</div>'
    assert parse_oa_article(html, OA) == {
        "body": "合成正文", "attachments": [{"name": "合成附件", "url": OA +
         "/weaver/weaver.file.FileDownload?fileid=42&download=1&requestid=0"}]}


@pytest.mark.parametrize("fields", ['<input name="accessory" value="not-a-file">',
                                  '<input name="renamed_accessory" value="42">',
                                  '',
                                  '<input name="accessory" value="42"><input name="accessory" value="43">'])
def test_oa_ambiguous_attachments_fail_instead_of_guessing(fields):
    html = f'<div id="docContent">合成正文</div><div id="accessory_dsp_tr1">{fields}</div>'
    with pytest.raises(AppError) as error:
        parse_oa_article(html, OA)
    assert error.value.code == "schema_changed"


def test_public_attachments_are_scoped_to_the_article_and_remain_relative():
    html = ('<nav><a href="/navigation.pdf">非正文附件</a></nav><article><p>合成正文</p>'
            '<a href="/files/test.pdf">合成附件</a><a href="https://example.org/evil.pdf">外站</a>'
            '<a href="/files/download?ticket=SYNTHETIC">回调</a></article>')
    assert parse_public_article(html, PUBLIC)["attachments"] == [{"name": "合成附件", "url": "/files/test.pdf"}]


def test_public_article_may_consist_only_of_a_valid_attachment():
    html = '<div id="vsb_content"><p><a href="/files/synthetic.pdf">合成附件</a></p></div>'
    assert parse_public_article(html, PUBLIC) == {
        "body": "合成附件", "attachments": [{"name": "合成附件", "url": "/files/synthetic.pdf"}]}


def test_oa_empty_recognized_body_may_have_a_separate_valid_attachment():
    html = '<div id="docContent"></div><div id="accessory_dsp_tr1"><input name="accessory" value="42">合成附件</div>'
    assert parse_oa_article(html, OA) == {"body": "", "attachments": [{"name": "合成附件", "url": OA +
        "/weaver/weaver.file.FileDownload?fileid=42&download=1&requestid=0"}]}


def test_oa_attachment_without_a_recognized_article_container_does_not_make_a_template_an_article():
    html = '<div>未知模板</div><div id="accessory_dsp_tr1"><input name="accessory" value="42">合成附件</div>'
    with pytest.raises(AppError) as error:
        parse_oa_article(html, OA)
    assert error.value.code == "schema_changed"


def test_attachment_navigation_alone_does_not_make_an_article():
    html = '<main><nav><a href="/files/synthetic.pdf">合成附件</a></nav></main>'
    with pytest.raises(AppError) as error:
        parse_public_article(html, PUBLIC)
    assert error.value.code == "schema_changed"


def test_public_article_does_not_include_attachment_links_from_nested_navigation():
    html = '<article><p>合成正文</p><nav><a href="/files/navigation.pdf">导航附件</a></nav><a href="/files/article.pdf">正文附件</a></article>'
    assert parse_public_article(html, PUBLIC)["attachments"] == [{"name": "正文附件", "url": "/files/article.pdf"}]
