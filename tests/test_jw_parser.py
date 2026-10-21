"""Synthetic school table mutations; these tests never contact a campus service."""
from copy import deepcopy
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from stu_mcp.features.jw.parser import jw_authenticated, jw_exam_semester, parse_jw
from stu_mcp.features.jw.schema import JW_COLUMNS, JW_SCHEMA_VERSION
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError

FIXTURES = Path(__file__).parent / "fixtures"
HOME = '<div id="NEW_XSD_XJCJ_WDCJ_KCCJCX"></div><div id="NEW_XSD_KSBM_WDKS_KSAPCX"></div>'
SSO = "<script>window.location.href='https://sso.stu.edu.cn/login?service=synthetic';</script>"
TERM = "2026-2027-1"


def table(kind):
    filename = "grades-current.html" if kind == "grade" else "exams-current.html"
    return BeautifulSoup((FIXTURES / filename).read_text(encoding="utf-8"), "html.parser")


def cells(row):
    return row.find_all(["td", "th"], recursive=False)


def column(soup, label):
    return next(index for index, cell in enumerate(cells(soup.tr)) if cell.get_text() == label)


def rejects(html, kind="grade", code="schema_changed"):
    with pytest.raises(AppError) as error:
        parse_jw(str(html), kind, TERM)
    assert (error.value.code, error.value.source) == (code, "jw")


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("mutation", ["extra_column", "reverse", "whitespace", "aliases", "td_headers",
                                     "repeated_headers", "row_heading", "table_sections"])
def test_table_changes_keep_records_and_stable_ids(kind, mutation):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    if mutation == "extra_column":
        for index, row in enumerate(soup.select("tr")):
            cell = soup.new_tag("th" if index == 0 else "td")
            cell.string = "学校新增显示列" if index == 0 else "合成额外内容"
            cells(row)[2].insert_before(cell)
    elif mutation == "reverse":
        for row in soup.select("tr"):
            for cell in reversed(cells(row)):
                row.append(cell.extract())
    elif mutation == "whitespace":
        for cell in cells(soup.tr):
            cell.string = " \n\u3000".join(cell.get_text())
    elif mutation == "aliases":
        aliases = {name: names[-1] for names in JW_COLUMNS[kind].values() for name in names}
        for cell in cells(soup.tr):
            cell.string = aliases.get(cell.get_text(), cell.get_text())
    elif mutation == "td_headers":
        for cell in cells(soup.tr):
            cell.name = "td"
    elif mutation == "repeated_headers":
        repeated = deepcopy(soup.tr)
        for cell in cells(repeated):
            cell.name = "td"
        soup.select("tr")[1].insert_after(repeated)
    elif mutation == "row_heading":
        for row in soup.select("tr")[1:]:
            cells(row)[0].name = "th"
    elif mutation == "table_sections":
        header = soup.tr.extract()
        head = soup.new_tag("thead")
        head.append(header)
        body = soup.new_tag("tbody")
        for row in list(soup.select("tr")):
            body.append(row.extract())
        soup.table.append(head)
        soup.table.append(body)
    assert parse_jw(str(soup), kind, TERM) == expected


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_layout_table_owns_no_inner_rows_and_does_not_duplicate_records(kind):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    wrapped = f"<table><tr><td><section><div>{soup}</div></section></td></tr></table>"
    assert parse_jw(wrapped, kind, TERM) == expected


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_a_late_header_does_not_turn_preceding_data_rows_into_an_empty_table(kind):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    header = soup.tr.extract()
    head = soup.new_tag("thead")
    head.append(header)
    soup.table.append(head)
    assert parse_jw(str(soup), kind, TERM) == expected


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_a_damaged_row_above_the_header_is_not_silently_ignored(kind):
    soup = table(kind)
    soup.tr.insert_before(BeautifulSoup("<tr><td>合成损坏记录</td><td>1</td></tr>", "html.parser").tr)
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("empty_second", [False, True])
def test_two_independent_candidate_tables_are_ambiguous_even_when_one_is_empty(kind, empty_second):
    first, second = table(kind), table(kind)
    if empty_second:
        for row in second.select("tr")[1:]:
            row.decompose()
    rejects(str(first) + str(second), kind)


@pytest.mark.parametrize("kind,label,alias", [("grade", "成绩", "总评成绩"),
                                            ("grade", "分组名称", "分组名称"),
                                            ("exam", "考场", "考试地点"),
                                            ("exam", "准考证号", "考试编号")])
def test_duplicate_semantic_columns_are_rejected_even_when_values_agree(kind, label, alias):
    soup = table(kind)
    index = column(soup, label)
    for number, row in enumerate(soup.select("tr")):
        duplicate = deepcopy(cells(row)[index])
        if number == 0:
            duplicate.string = alias
        row.append(duplicate)
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("mutation", ["missing_header", "short_row", "surplus_cell", "rowspan",
                                     "colspan", "bad_span", "nested_data_table", "conflicting_header",
                                     "partially_changed_repeated_header", "huge_span"])
def test_ambiguous_or_damaged_records_never_return_partial_results(kind, mutation):
    soup = table(kind)
    row = soup.select("tr")[-1]
    if mutation == "missing_header":
        cells(soup.tr)[column(soup, "课程编号")].string = "学校更改后的未知字段"
    elif mutation == "short_row":
        cells(row)[-1].decompose()
    elif mutation == "surplus_cell":
        row.append(soup.new_tag("td"))
    elif mutation in {"rowspan", "colspan"}:
        cells(row)[0][mutation] = "2"
    elif mutation == "bad_span":
        cells(row)[0]["rowspan"] = "0"
    elif mutation == "huge_span":
        cells(row)[0]["colspan"] = "9" * 5000
    elif mutation == "nested_data_table":
        cells(row)[column(soup, "课程名称")].append(
            BeautifulSoup("<table><tr><td>合成内层值</td></tr></table>", "html.parser"))
    elif mutation == "conflicting_header":
        repeated = deepcopy(soup.tr)
        first, last = cells(repeated)[column(soup, "课程编号")], cells(repeated)[column(soup, "课程名称")]
        first.string, last.string = last.get_text(), first.get_text()
        soup.table.append(repeated)
    elif mutation == "partially_changed_repeated_header":
        repeated = deepcopy(soup.tr)
        for cell in cells(repeated):
            cell.name = "td"
        cells(repeated)[column(soup, "成绩" if kind == "grade" else "考试时间")].string = "合成新字段"
        soup.table.append(repeated)
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("span", ["rowspan", "colspan"])
def test_merged_required_headers_are_rejected(kind, span):
    soup = table(kind)
    cells(soup.tr)[column(soup, "课程编号")][span] = "2"
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_decoration_above_header_is_allowed_but_a_carried_rowspan_is_not(kind):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    decoration = BeautifulSoup('<tr><th colspan="99">合成成绩或考试列表</th></tr>', "html.parser").tr
    soup.tr.insert_before(decoration)
    assert parse_jw(str(soup), kind, TERM) == expected
    decoration.th["rowspan"] = "2"
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("marker", ["", '<tr><td colspan="99">暂无数据</td></tr>',
                                   '<tr><th colspan="99">暂 无 数 据</th></tr>',
                                   "<tr><td>未查询到相关记录！</td></tr>"])
def test_recognized_table_with_explicit_empty_row_or_no_rows_is_empty(kind, marker):
    soup = table(kind)
    for row in soup.select("tr")[1:]:
        row.decompose()
    if marker:
        soup.table.append(BeautifulSoup(marker, "html.parser"))
    assert parse_jw(str(soup), kind, TERM) == []


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("title", ["暂无数据", "合计", "平均成绩研究", "没有记录的数据分析"])
def test_course_names_containing_empty_or_total_words_do_not_hide_damaged_rows(kind, title):
    soup = table(kind)
    row = soup.select("tr")[-1]
    cells(row)[column(soup, "课程名称")].string = title
    cells(row)[column(soup, "课程编号")].string = ""
    rejects(soup, kind)
    for cell in cells(row):
        cell.string = ""
    cells(row)[column(soup, "课程名称")].string = title
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("title", ["合计与平均成绩分析", "平均绩点：3.2", "合计：6学分"])
def test_complete_course_title_with_total_words_is_a_record(kind, title):
    soup = table(kind)
    cells(soup.select("tr")[-1])[column(soup, "课程名称")].string = title
    records = parse_jw(str(soup), kind, TERM)
    assert records[-1]["title"] == title


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("summary", ["合计：6学分", "平均绩点：3.2", "平均绩点 : 3.2"])
@pytest.mark.parametrize("cell", ['<td colspan="16">{}</td>', '<th colspan="16">{}</th>', '<td>{}</td>'])
def test_standalone_numeric_summary_is_structural_and_not_a_course_title_substring(kind, summary, cell):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    soup.table.append(BeautifulSoup("<tr>" + cell.format(summary) + "</tr>", "html.parser"))
    assert parse_jw(str(soup), kind, TERM) == expected


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_numeric_summary_text_does_not_hide_an_incomplete_course_row_with_an_identity(kind):
    soup = table(kind)
    row = soup.select("tr")[-1]
    cells(row)[column(soup, "课程名称")].string = "平均绩点：3.2"
    cells(row)[-1].decompose()
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_explicit_merged_total_does_not_become_a_course(kind):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    soup.table.append(BeautifulSoup('<tr><td colspan="8">合计</td><td>6</td></tr>', "html.parser"))
    assert parse_jw(str(soup), kind, TERM) == expected


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_complete_total_row_needs_empty_course_identity(kind):
    soup = table(kind)
    expected = parse_jw(str(soup), kind, TERM)
    total = deepcopy(soup.select("tr")[-1])
    for cell in cells(total):
        cell.string = ""
    cells(total)[0].string = "总计"
    soup.table.append(total)
    assert parse_jw(str(soup), kind, TERM) == expected
    cells(total)[column(soup, "课程名称")].string = "合成残缺课程"
    rejects(soup, kind)


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("changed", [False, True])
def test_duplicate_record_identity_is_ambiguous_instead_of_overwritten(kind, changed):
    soup = table(kind)
    duplicate = deepcopy(soup.select("tr")[1])
    if changed:
        cells(duplicate)[column(soup, "课程名称")].string = "合成冲突记录"
    soup.table.append(duplicate)
    rejects(soup, kind)


def test_retake_and_group_rows_keep_the_existing_grade_identity_rule():
    soup = table("grade")
    original = soup.select("tr")[1]
    for exam_type, group in [("补考", "合成组一"), ("正常考试", "另一个合成分组")]:
        another = deepcopy(original)
        cells(another)[column(soup, "考试性质")].string = exam_type
        cells(another)[column(soup, "分组名称")].string = group
        soup.table.append(another)
    records = parse_jw(str(soup), "grade")
    assert len(records) == 5 and len({record["id"] for record in records}) == 5
    assert records[0]["id"] == item_id("jw", "grade", "2026-2027-1", "DEMO001", "正常考试", "合成组一")
    assert all(record["jw_schema_version"] == JW_SCHEMA_VERSION == 2 for record in records)


def test_multiple_exam_times_for_one_course_are_distinct_but_same_time_collisions_are_not():
    soup = table("exam")
    first, second = soup.select("tr")[1:]
    cells(second)[column(soup, "课程编号")].string = "DEMO001"
    records = parse_jw(str(soup), "exam", TERM)
    assert len(records) == len({record["id"] for record in records}) == 2
    assert records[0]["id"] == item_id("jw", "exam", TERM, "DEMO001", "2026-11-01 09:00-11:00")
    cells(second)[column(soup, "考试时间")].string = cells(first)[column(soup, "考试时间")].get_text()
    rejects(soup, "exam")


@pytest.mark.parametrize("value", ["", "待公布", "NaN", "inf", "-inf", "无法解析"])
def test_grade_nonnumeric_credits_and_gpa_remain_none_without_changing_score(value):
    soup = table("grade")
    row = soup.select("tr")[1]
    cells(row)[column(soup, "成绩")].string = "优秀"
    for label in ("学分", "绩点"):
        cells(row)[column(soup, label)].string = value
    record = parse_jw(str(soup), "grade")[0]
    assert record["score"] == "优秀" and record["credits"] is None and record["gpa"] is None


def test_unpublished_exam_details_remain_blank_fields_on_a_real_course_record():
    soup = table("exam")
    row = soup.select("tr")[1]
    for label in ("考试时间", "考场"):
        cells(row)[column(soup, label)].string = ""
    records = parse_jw(str(soup), "exam", TERM)
    assert len(records) == 2 and records[0]["exam_time"] == records[0]["location"] == ""


@pytest.mark.parametrize("kind", ["grade", "exam"])
@pytest.mark.parametrize("html,code", [(SSO, "login_expired"), ('<input type="password">', "login_expired"),
                                       ("<h1>合成服务错误</h1>", "schema_changed"),
                                       ("<table><tr><td>暂无数据</td></tr></table>", "schema_changed")])
def test_login_and_unknown_pages_are_never_successful_empty_reads(kind, html, code):
    rejects(html, kind, code)


@pytest.mark.parametrize("attribute", ['name="xnxqid"', 'id="xnxqid"', 'id="xnxqid" name="xnxqid"'])
def test_exam_semester_control_uses_one_selected_option_or_the_existing_first_option(attribute):
    field = (f'<select {attribute}><optgroup label="合成学期"><option value="2026-2027-1">一</option>'
             '<option value="2025-2026-3" selected>三</option></optgroup></select>')
    assert jw_exam_semester(field) == "2025-2026-3"
    assert jw_exam_semester(field.replace(" selected", "")) == "2026-2027-1"


@pytest.mark.parametrize("placeholder", ['<option value="">请选择学期</option>',
                                         '<option value="unknown">合成其他选项</option>',
                                         '<option>请选择学期</option>'])
def test_unselected_semester_placeholder_does_not_change_a_valid_selection(placeholder):
    field = ('<select name="xnxqid">' + placeholder +
             '<option value="2026-2027-1" selected>合成学期</option></select>')
    assert jw_exam_semester(field) == "2026-2027-1"
    if 'value=' not in placeholder:
        assert jw_exam_semester(field.replace(" selected", "")) == "2026-2027-1"
        return
    with pytest.raises(AppError) as error:
        jw_exam_semester(field.replace(" selected", ""))
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("body", [
    '<select name="xnxqid"></select>',
    '<select name="xnxqid"><option>合成无值选项</option></select>',
    '<select name="xnxqid"><option value="">请选择</option></select>',
    '<select name="xnxqid"><option value="2026-2027-4">合成未知学期</option></select>',
    '<select name="xnxqid"><option value="2026-2027-1">一</option><option value="unknown" selected>合成异常值</option></select>',
    '<select name="xnxqid"><option selected>合成无值选项</option><option value="2026-2027-1">一</option></select>',
    '<select name="xnxqid"><option value="2026-2027-1">一</option><option value="2026-2027-1" selected>重复</option></select>',
    '<select name="xnxqid"><option value="2026-2027-1" selected>一</option><option value="2025-2026-3" selected>三</option></select>',
    '<select name="xnxqid" multiple><option value="2026-2027-1" selected>一</option></select>',
    '<select name="xnxqid"><option value="2026-2027-1">一</option></select><select id="xnxqid"><option value="2025-2026-3">三</option></select>',
    '<h1>合成未知学期页面</h1>',
])
def test_invalid_or_ambiguous_exam_semester_form_is_rejected(body):
    with pytest.raises(AppError) as error:
        jw_exam_semester(body)
    assert (error.value.code, error.value.source) == ("schema_changed", "jw")


def test_exam_semester_sso_page_is_expired():
    with pytest.raises(AppError) as error:
        jw_exam_semester(SSO)
    assert error.value.code == "login_expired"


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_unknown_merged_record_before_a_late_header_is_not_decoration(kind):
    soup = table(kind)
    header = soup.table.find("tr").extract()
    for row in soup.table.find_all("tr"):
        row.decompose()
    soup.table.append(BeautifulSoup('<tr><td colspan="16">合成无法映射的记录</td></tr>', "html.parser").tr)
    soup.table.append(header)
    rejects(str(soup), kind)


def test_authenticated_home_requires_expected_markers_and_tolerates_duplicate_navigation():
    assert jw_authenticated(f"<section>{HOME}</section>")
    assert jw_authenticated(HOME + HOME)
    assert not jw_authenticated(SSO)
    assert not jw_authenticated(HOME + '<input type="password">')
    assert jw_authenticated(HOME + "<script>function logout(){window.location.href='https://sso.stu.edu.cn/login';}</script>")
    for body in ("<h1>合成未知主页</h1>", '<div id="NEW_XSD_XJCJ_WDCJ_KCCJCX"></div>'):
        with pytest.raises(AppError) as error:
            jw_authenticated(body)
        assert error.value.code == "schema_changed"
