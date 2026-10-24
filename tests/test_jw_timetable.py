"""Synthetic theory-page contracts; no real timetable or authentication material."""
from copy import deepcopy
from html import escape
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from stu_mcp.features.jw.schema import JW_TIMETABLE_URL
from stu_mcp.features.jw.service import academic_timetable
from stu_mcp.features.jw.timetable import meeting_time, parse_timetable, timetable_form
from stu_mcp.features.timetable.export import convert
from stu_mcp.runtime import AppError, key_lock

TERM = "2026-2027-1"
OLD_TERM = "2025-2026-3"


def form(term=TERM, week=""):
    return ('<form id="Form1" action="" method="post">'
            '<input type="hidden" name="cj0701id" value="synthetic-form-state">'
            '<input type="hidden" name="demo" value="">'
            '<select name="xnxq01id">' + ''.join(
                f'<option value="{t}" {"selected" if t == term else ""}>{t}</option>'
                for t in (TERM, OLD_TERM)) + '</select><select name="zc">' + ''.join(
                f'<option value="{w}" {"selected" if w == week else ""}>{w or "全部"}</option>'
                for w in ("", "1", "2")) + '</select>'
            '<select name="kbjcmsid"><option value="synthetic-period-mode">默认节次模式</option></select>'
            '<input type="checkbox" name="sfFD" value="1" checked>'
            '<input type="checkbox" name="wkbkc" value="1" checked>'
            '<input type="checkbox" name="xstzd" value="1">'
            '<input type="checkbox" name="xswk" value="1"></form>')


def inventory(table_id, records):
    labels = ("序号", "上课班级", "课程编号", "课程名称", "授课教师", "排课人数")
    heading = "无课表课程" if table_id == "dataTables" else "有课表课程"
    header = f'<tr><th colspan="6">{heading}</th></tr><tr>' + ''.join(
        f'<th>{label}</th>' for label in labels) + '</tr>'
    rows = ''.join('<tr><th>1</th>' + ''.join(f'<td>{escape(v)}</td>' for v in row) +
                   '<td>30</td></tr>' for row in records)
    return f'<table id="{table_id}">{header}{rows}</table>'


def block(title="合成课程", teacher="教师甲", timing="1-4(周)[01-02节]", class_name="班甲",
          number="SYNTHETIC-NOTICE-A", room="教室一"):
    fields = [(None, title), ("教师", teacher), ("周次(节次)", timing), ("教学楼", "合成楼"),
              ("教室", room), ("通知单编号", "通知单编号：" + number),
              ("班级", "班级：" + class_name), ("备注", "备注：")]
    return ''.join('<div class="item-box"><img src="not-fetched"></div><font' +
                   (f' title="{label}"' if label else '') + '>' + escape(text) + '</font><br>'
                   for label, text in fields)


def theory(*, term=TERM, week="", arranged=None, unarranged=None, cells=None):
    arranged = [("班甲", "SYN-A", "合成课程", "教师甲")] if arranged is None else arranged
    unarranged = [] if unarranged is None else unarranged
    cells = {1: block()} if cells is None else cells
    grid = ('<table id="timetable"><tr><th></th>' + ''.join(
        f'<th>星期{d}</th>' for d in '一二三四五六日') +
        '</tr><tr><th>第一大节 (01,02,03小节)</th>' + ''.join(
            '<td><div class="kbcontent1">简略显示，不作为第二份数据</div><div class="kbcontent">' +
            cells.get(day, '') + '</div><div class="kbcontent"></div></td>' for day in range(1, 8)) +
        '</tr><tr><th>备注:</th><td colspan="7"></td></tr></table>')
    return form(term, week) + grid + inventory("dataTables", unarranged) + inventory("dataTables2", arranged)


def test_realistic_multiple_teachers_weeks_locations_and_unarranged():
    html = theory(arranged=[("班甲", "SYN-A", "合成课程", "教师甲"), ("班甲", "SYN-A", "合成课程", "教师乙")],
                  unarranged=[("班乙", "SYN-B", "未排课程", "教师丙")],
                  cells={2: block() + '---------------------<br>' + block(
                      teacher="教师乙", timing="5,7,9(周)[01-02节]", room="教室二"), 4: block()})
    result = parse_timetable(html, TERM)
    assert result["coverage"]["course_count"] == 1
    assert result["coverage"]["meeting_count"] == 3
    assert result["coverage"]["unarranged_count"] == 1
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["calendar_verified"] is False
    assert result["pending"] and "meetings" not in result["unarranged"][0]
    course = result["courses"][0]
    assert course["teachers"] == ["教师乙", "教师甲"]
    assert [(m["weekday"], m["weeks"]) for m in course["meetings"]] == [
        (2, [1, 2, 3, 4]), (2, [5, 7, 9]), (4, [1, 2, 3, 4])]
    assert course["meetings"][1]["location"] == "合成楼 教室二"


@pytest.mark.parametrize("raw,weeks,periods", [
    ("3-18(周)[03-04-05节]", list(range(3, 19)), [[3, 4, 5]]),
    ("3,5,7,9(周)[08-09节]", [3, 5, 7, 9], [[8, 9]]),
    ("1-7(单周)[01-02节]", [1, 3, 5, 7], [[1, 2]]),
    ("1-8(周)(双)[01-02节]", [2, 4, 6, 8], [[1, 2]]),
    ("1、3、5（周）［01-03节］", [1, 3, 5], [[1], [3]]),
])
def test_explicit_week_sets_and_period_enumeration(raw, weeks, periods):
    assert meeting_time(raw) == (weeks, periods)


@pytest.mark.parametrize("raw", ["待定", "1-60(周)[01-01节]", "0-3(周)[01节]", "1-61(周)[01节]",
                                 "7-1(周)[01节]", "1,课(周)[01节]", "1-3(周)[02-01节]",
                                 "1-3(周)[01,,03节]", "2(单周)[01节]", "1-3(周)[31节]"])
def test_unknown_or_ambiguous_time_is_not_silently_omitted(raw):
    with pytest.raises(AppError) as error:
        meeting_time(raw)
    assert error.value.code == "schema_changed" and raw not in error.value.message


def test_form_uses_live_values_and_all_weeks_without_default_guessing():
    result = timetable_form(form(OLD_TERM, "2").replace('name="wkbkc" value="1" checked',
                                                       'name="wkbkc" value="1"'))
    assert result.semester == OLD_TERM
    assert result.data == {"cj0701id": "synthetic-form-state", "demo": "", "xnxq01id": OLD_TERM,
                           "zc": "", "kbjcmsid": "synthetic-period-mode", "sfFD": "1", "wkbkc": "1"}
    assert [s["semester"] for s in result.semesters] == [TERM, OLD_TERM]


@pytest.mark.parametrize("mutate", [
    lambda h: h + form(), lambda h: h.replace('action=""', 'action="/write-record"'),
    lambda h: h.replace('name="demo"', 'name="password"'),
    lambda h: h.replace('name="zc"', 'name="newWeek"'),
    lambda h: h.replace('<select name="zc">', '<select name="zc" multiple>'),
    lambda h: h.replace('name="wkbkc"', 'name="removed"'),
    lambda h: h.replace('name="cj0701id"', 'name="demo"'),
    lambda h: h.replace(f'<option value="{OLD_TERM}"', f'<option value="{TERM}"'),
])
def test_changed_form_cannot_send_an_unreviewed_post(mutate):
    with pytest.raises(AppError) as error:
        timetable_form(mutate(form()))
    assert error.value.code == "schema_changed"


def test_reordered_columns_and_courses_preserve_identity():
    html = theory(arranged=[("班甲", "SYN-A", "合成课程", "教师甲"), ("班乙", "SYN-B", "合成课程", "教师甲")],
                  cells={1: block(), 5: block(class_name="班乙", number="SYNTHETIC-B")})
    expected = parse_timetable(html, TERM)
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.select("#dataTables,#dataTables2"):
        for row in table.select("tr")[1:]:
            cells = row.find_all(["th", "td"], recursive=False)
            for cell in reversed(cells):
                row.append(cell.extract())
    assert parse_timetable(str(soup), TERM) == expected
    assert len({c["id"] for c in expected["courses"]}) == 2


def test_course_rows_before_the_header_are_read_instead_of_silently_dropped():
    html = theory()
    expected = parse_timetable(html, TERM)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("#dataTables2")
    table.append(table.select("tr")[1].extract())
    assert parse_timetable(str(soup), TERM) == expected


def test_identity_survives_teacher_and_room_edits_but_not_ambiguous_parallel_records():
    original = parse_timetable(theory(), TERM)
    changed = parse_timetable(theory(arranged=[("班甲", "SYN-A", "合成课程", "教师乙")],
                                     cells={1: block(teacher="教师乙", room="另一教室")}), TERM)
    assert original["courses"][0]["id"] == changed["courses"][0]["id"]
    assert original["courses"][0]["meetings"][0]["id"] == changed["courses"][0]["meetings"][0]["id"]
    recurrence = parse_timetable(theory(cells={1: block(timing="1-5(周)[01-02节]")}), TERM)
    assert original["courses"][0]["meetings"][0]["id"] != recurrence["courses"][0]["meetings"][0]["id"]
    ambiguous = theory(arranged=[("班甲", "SYN-A", "合成课程", t) for t in ("教师甲", "教师乙")],
                       cells={1: block() + block(teacher="教师乙", room="另一教室")})
    with pytest.raises(AppError) as error:
        parse_timetable(ambiguous, TERM)
    assert error.value.code == "schema_changed"


def test_planned_teacher_without_grid_is_a_partial_result_not_an_empty_arrangement():
    html = theory(arranged=[("班甲", "SYN-A", "合成课程", t) for t in ("教师甲", "教师乙", "教师丙")],
                  cells={1: block(), 2: block(teacher="教师乙")})
    result = parse_timetable(html, TERM)
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["meeting_count"] == 2
    assert result["coverage"]["unplaced_detail_count"] == 1
    assert result["unplaced_details"][0]["teacher"] == "教师丙"
    assert result["pending"] and "教师丙" not in result["pending"][0]


@pytest.mark.parametrize("change", ["nested", "span", "unknown_title", "text", "tooltip_text",
                                   "tooltip_table", "unknown_font"])
def test_unknown_business_rows_and_visible_content_fail_clearly(change):
    soup = BeautifulSoup(theory(), "html.parser")
    if change == "nested":
        soup.select_one("#dataTables2 tr:last-child td").append(BeautifulSoup(
            '<table><tr><td>新业务</td></tr></table>', "html.parser"))
    elif change == "span":
        soup.select_one("#dataTables2 tr:last-child td")["rowspan"] = "2"
    elif change == "unknown_title":
        soup.select_one("#dataTables2 tr:first-child th").string = "新的业务行"
    elif change == "text":
        soup.select_one(".kbcontent").append("新的安排内容")
    elif change == "tooltip_text":
        soup.select_one(".item-box").append("新的安排内容")
    elif change == "tooltip_table":
        soup.select_one(".item-box").append(BeautifulSoup('<table><tr><td></td></tr></table>', "html.parser"))
    else:
        soup.select_one(".kbcontent").append(BeautifulSoup('<font title="校区">新字段</font>', "html.parser"))
    with pytest.raises(AppError) as error:
        parse_timetable(str(soup), TERM)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("change", ["duplicate_header", "duplicate_table", "duplicate_course", "missing_grid",
                                   "duplicate_meeting", "unknown_block", "bad_join", "missing_meeting",
                                   "wrong_week", "wrong_semester", "outside_grid", "overlapping_inventory"])
def test_no_successful_partial_parse_on_structure_or_identity_drift(change):
    html = theory()
    if change == "duplicate_header":
        html = html.replace("排课人数", "课程名称")
    elif change == "duplicate_table":
        html += inventory("dataTables2", [])
    elif change == "duplicate_course":
        html = theory(arranged=[("班甲", "SYN-A", "合成课程", "教师甲")] * 2)
    elif change == "missing_grid":
        html = html.replace('id="timetable"', 'id="other"')
    elif change == "duplicate_meeting":
        html = theory(cells={1: block() * 2})
    elif change == "unknown_block":
        html = theory(cells={1: block() + '<span>未识别安排</span>'})
    elif change == "bad_join":
        html = theory(cells={1: block(class_name="另一个班")})
    elif change == "missing_meeting":
        html = theory(cells={})
    elif change == "wrong_week":
        html = theory(week="1")
    elif change == "wrong_semester":
        html = theory(term=OLD_TERM)
    elif change == "outside_grid":
        html = theory(cells={1: block(timing="1-2(周)[04节]")})
    else:
        html = theory(unarranged=[("班甲", "SYN-A", "合成课程", "教师甲")])
    with pytest.raises(AppError) as error:
        parse_timetable(html, TERM)
    assert error.value.code == "schema_changed"


def test_login_html_and_unknown_html_are_not_empty_schedules():
    with pytest.raises(AppError) as error:
        parse_timetable('<title>统一身份认证</title><input type="password">', TERM)
    assert error.value.code == "login_expired"
    with pytest.raises(AppError) as error:
        parse_timetable('<h1>网站正在维护</h1>', TERM)
    assert error.value.code == "schema_changed"
    result = parse_timetable(theory(arranged=[], cells={}), TERM)
    assert result["coverage"]["complete"] is True
    assert result["courses"] == result["unarranged"] == result["pending"] == []


@pytest.mark.parametrize("change", ["unarranged_unchecked", "missing_grid_rows"])
def test_returned_filter_and_grid_coverage_must_be_confirmed(change):
    soup = BeautifulSoup(theory(arranged=[], cells={}), "html.parser")
    if change == "unarranged_unchecked":
        del soup.select_one('input[name="wkbkc"]')["checked"]
    else:
        for row in soup.select("#timetable tr")[1:]:
            row.decompose()
    with pytest.raises(AppError) as error:
        parse_timetable(str(soup), TERM)
    assert error.value.code == "schema_changed"


def test_normalized_courses_feed_the_existing_converter_without_another_projection():
    result = parse_timetable(theory(cells={1: block(timing="1,3(周)[01-03节]")}), TERM)
    assert len(result["courses"][0]["meetings"]) == 2
    # The reviewed calendar and clock evidence are independent synthetic input, never inferred from JW.
    reviewed = {"schema_version": 1, "semester": TERM, "courses": result["courses"],
                "calendar": {"semester": TERM, "version": "synthetic-only", "week1_monday": "2026-09-07",
                             "weeks": 20, "source_url": "https://jwc.stu.edu.cn/synthetic-calendar",
                             "checked_at": "2026-10-24T00:00:00Z", "latest_verified": True},
                "timetable": {"source_url": JW_TIMETABLE_URL, "checked_at": "2026-10-24T00:00:00Z",
                              "complete": True},
                "periods": [{"number": n, "start": f"{7+n:02}:00", "end": f"{7+n:02}:45"}
                            for n in range(1, 4)]}
    manifest, files = convert(reviewed)
    assert manifest["status"] == "generated" and manifest["counts"]["actual_occurrences"] == 4
    assert {"schedule.ics", "wakeup.csv"}.issubset(files)
    reviewed["pending"] = ["合成未排课仍须核对"]
    assert convert(reviewed)[0]["status"] == "blocked"


@pytest.fixture
def school(app, session):
    saved = deepcopy(session)
    saved["cookies"][0]["domain"] = "jw.stu.edu.cn"
    saved["jw_http_compat"] = True
    app.vault.save("jw", saved)
    state = {"requests": [], "options": [], "mutate": None, "form": theory(week="2")}

    class HTTP:
        used_legacy_http = True

        def __init__(self, source, state_value, **kwargs):
            assert source == "jw" and state_value["jw_http_compat"] is True
            state["options"].append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            state["closed"] = True

        def text(self, url):
            assert url == JW_TIMETABLE_URL
            state["requests"].append(("GET", None))
            return state["form"]

        def request(self, url, *, data):
            assert url == JW_TIMETABLE_URL
            state["requests"].append(("POST", data.copy()))
            if state["mutate"]:
                state["mutate"]()
            return SimpleNamespace(text=theory(term=data["xnxq01id"]))

    return state, HTTP


def test_service_reads_only_theory_without_cache_or_grade_refresh(app, school):
    state, factory = school
    result = academic_timetable(app.vault, OLD_TERM, http_factory=factory)
    assert result["ok"] is True and result["source"] == "jw" and result["semester"] == OLD_TERM
    assert result["cached"] is False and result["transport"] == "school_legacy_http"
    assert result["checked_at"].endswith("+00:00")
    assert state["options"] == [{"allow_legacy_http": True}]
    assert state["requests"][1][1]["zc"] == "" and state["requests"][1][1]["xnxq01id"] == OLD_TERM
    assert len(state["requests"]) == 2 and state["closed"]
    assert app.store.freshness() == []


@pytest.mark.parametrize("change", ["logout", "relogin", "generation"])
def test_service_discards_results_after_session_or_logout_generation_change(app, school, change):
    state, factory = school

    def mutate():
        saved = app.vault.load("jw")
        original = app.runtime.session_file("jw").read_bytes()
        with key_lock(app.runtime.home, "jw"):
            if change in {"logout", "generation"}:
                app.vault.logout("jw")
            if change == "generation":
                app.runtime.session_file("jw").write_bytes(original)
        if change == "relogin":
            app.vault.save("jw", saved)

    state["mutate"] = mutate
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, http_factory=factory)
    assert error.value.code == "session_changed" and state["closed"]


@pytest.mark.parametrize("semester", ["garbage", True, "2026-2027-4", "2026-2027-1\n"])
def test_invalid_semester_precedes_authentication(app, semester):
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, semester)
    assert error.value.code == "invalid_semester"


def test_unavailable_term_stops_before_query_and_missing_login_is_explicit(app, school):
    state, factory = school
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, "2020-2021-1", http_factory=factory)
    assert error.value.code == "invalid_semester" and len(state["requests"]) == 1
    with key_lock(app.runtime.home, "jw"):
        app.vault.logout("jw")
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, http_factory=factory)
    assert error.value.code == "needs_login" and len(state["options"]) == 1
