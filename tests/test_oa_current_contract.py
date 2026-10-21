"""Synthetic examples for observed OA route/header contracts; no real notices."""
import pytest

from stu_mcp.features.notices.parser import parse_oa, parse_oa_article, parse_public_article
from stu_mcp.features.notices.schema import OA_ARTICLE_PATH, OA_ARTICLE_PATHS
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError

HOST = "http://oa.stu.edu.cn"
CURRENT = "/page/maint/template/news/newstemplateprotal.jsp"


def listing(href, *, header="标&nbsp;&nbsp;&nbsp;&nbsp;题", title="合成公告"):
    return ('<table><tr><td>' + header + '</td><td>发布单位</td><td>发布日期</td></tr>'
            '<tr><td><a href="' + href + '">' + title + '</a></td><td>合成学院</td><td>2026-10-21</td></tr></table>')


@pytest.mark.parametrize("path", [OA_ARTICLE_PATH, CURRENT])
def test_observed_fullpath_alias_and_spaced_header_keep_record_identity(path):
    url = path + "?docid=123&templateid=7&templatetype=1"
    result = parse_oa(listing(url), HOST, 20)
    assert result == [{"id": item_id("oa", "notice", "123"), "kind": "notice", "docid": "123",
                       "title": "合成公告", "url": HOST + url,
                       "department": "合成学院", "published_at": "2026-10-21"}]
    assert OA_ARTICLE_PATH == "/newstemplateprotal.jsp"
    assert len(OA_ARTICLE_PATHS) == 2


def test_header_whitespace_normalization_does_not_change_business_values():
    result = parse_oa(listing(CURRENT + "?docid=123", title="合成 标题"), HOST, 1)[0]
    assert result["title"] == "合成 标题"
    assert result["department"] == "合成学院"


@pytest.mark.parametrize("query", ["docid=", "docid=&docid=123", "docid=123&docid=",
                                   "docid=123&docid=456", "docid=bad%20id", "templateid=7"])
def test_fullpath_requires_one_nonempty_unambiguous_docid(query):
    with pytest.raises(AppError) as error:
        parse_oa(listing(CURRENT + "?" + query), HOST, 20)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("href", [
    "http://evil.example" + CURRENT + "?docid=123",
    "http://u:p@oa.stu.edu.cn" + CURRENT + "?docid=123",
    "http://oa.stu.edu.cn:8118" + CURRENT + "?docid=123",
    CURRENT + "?docid=123&ticket=SYNTHETIC",
    CURRENT + "?docid=123&TOKEN=",
    "/page/changed/newstemplateprotal.jsp?docid=123",
    "/prefix" + CURRENT + "?docid=123",
])
def test_alias_does_not_relax_hosts_credentials_ports_auth_fields_or_paths(href):
    with pytest.raises(AppError):
        parse_oa(listing(href), HOST, 20)


def test_equivalent_spaced_headers_are_still_ambiguous():
    markup = ('<table><tr><th>标 题</th><th>标题</th><th>部门</th><th>日期</th></tr>'
              '<tr><td><a href="' + CURRENT + '?docid=123">合成公告</a></td>'
              '<td>其他文字</td><td>学院</td><td>2026-10-21</td></tr></table>')
    with pytest.raises(AppError) as error:
        parse_oa(markup, HOST, 20)
    assert error.value.code == "schema_changed"


def test_same_docid_across_old_and_current_paths_remains_one_notice():
    first = listing(OA_ARTICLE_PATH + "?docid=123")
    second = listing(CURRENT + "?docid=123&templateid=7&templatetype=1")
    assert len(parse_oa(first + second, HOST, 20)) == 1


def test_observed_oa_content_field_is_used_without_page_template_text():
    markup = ('<div id="content"><nav>合成导航</nav><div id="divInfo">合成发布信息</div>'
              '<span id="spanContent"><p>合成通知正文。</p><p>第二段。</p></span></div>')
    result = parse_oa_article(markup, HOST)
    assert "合成通知正文。" in result["body"]
    assert "第二段。" in result["body"]
    assert "合成导航" not in result["body"]
    assert "合成发布信息" not in result["body"]
    assert result["attachments"] == []


@pytest.mark.parametrize("content", ["", " ", "<script>synthetic()</script>",
                                    "<nav>导航</nav>", '<a href="/home">导航</a>'])
def test_current_oa_content_must_have_article_text(content):
    with pytest.raises(AppError) as error:
        parse_oa_article('<span id="spanContent">' + content + '</span>', HOST)
    assert error.value.code == "schema_changed"


def test_current_oa_content_must_be_unique_without_generic_wrapper_fallback():
    markup = ('<main><span id="spanContent">合成正文一</span>'
              '<span id="spanContent">合成正文二</span></main>')
    with pytest.raises(AppError) as error:
        parse_oa_article(markup, HOST)
    assert error.value.code == "schema_changed"


def test_current_oa_content_does_not_turn_login_form_into_article():
    markup = ('<form><input type="password" name="password"></form>'
              '<span id="spanContent">请登录后查看</span>')
    with pytest.raises(AppError) as error:
        parse_oa_article(markup, HOST)
    assert error.value.code == "needs_login"


def test_oa_specific_content_field_does_not_expand_public_article_contract():
    with pytest.raises(AppError) as error:
        parse_public_article('<span id="spanContent">合成正文</span>', 'https://www.stu.edu.cn')
    assert error.value.code == "schema_changed"


def test_legacy_oa_article_selector_is_preserved():
    assert parse_oa_article('<div id="docContent">旧格式合成正文</div>', HOST)["body"] == "旧格式合成正文"


@pytest.mark.parametrize("field_name", ["accessory", "accessory0", "accessory12"])
def test_current_numbered_attachment_field_keeps_legacy_download_contract(field_name):
    markup = ('<span id="spanContent">合成正文</span><table><tr id="accessory_dsp_tr0"><td>'
              '<input type="hidden" name="' + field_name + '" value="42">附件1：合成文件 下载'
              '</td></tr></table>')
    result = parse_oa_article(markup, HOST)
    assert result == {"body": "合成正文", "attachments": [{"name": "合成文件", "url": HOST +
                      "/weaver/weaver.file.FileDownload?fileid=42&download=1&requestid=0"}]}


@pytest.mark.parametrize("fields", [
    '<input name="accessory0" value="42"><input name="accessory1" value="43">',
    '<input name="accessory" value="42"><input name="accessory0" value="42">',
    '<input name="accessory0" value="">',
    '<input name="accessory0" value="42,43">',
    '<input name="accessory0" value="４２">',
    '<input name="accessoryx" value="42">',
    '<input name="accessory0suffix" value="42">',
])
def test_numbered_attachment_fields_still_require_one_ascii_decimal_identity(fields):
    markup = ('<span id="spanContent">合成正文</span><table><tr id="accessory_dsp_tr0"><td>' +
              fields + '</td></tr></table>')
    with pytest.raises(AppError) as error:
        parse_oa_article(markup, HOST)
    assert error.value.code == "schema_changed"


def test_unrelated_download_navigation_is_not_an_oa_attachment():
    markup = ('<nav><a href="/download.php?id=42">下载导航</a></nav>'
              '<span id="spanContent">合成正文</span>')
    assert parse_oa_article(markup, HOST) == {"body": "合成正文", "attachments": []}
