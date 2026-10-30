"""Synthetic medical timetable contracts; no school login or network requests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy

import pytest

from stu_mcp.features.med_jw.parser import parse_timetable
from stu_mcp.features.med_jw.schema import (
    MED_JW_CAPTCHA_PATH,
    MED_JW_INFO_PATH,
    MED_JW_LOGIN_PATH,
    MED_JW_READ_ROUTES,
    MED_JW_TIMETABLE_BODY,
    MED_JW_TIMETABLE_PATH,
)
from stu_mcp.runtime import AppError


def lesson(**changes):
    return {"kcmc": "合成医学课程", "kcbh": "SYN-MED-1", "jxbmc": "合成教学班甲",
            "teaxms": "合成教师甲", "szxqmc": "合成校区", "jzwmc": "合成楼甲", "jxcdmc": "101",
            "xq": 1, "zc": 1, "jcdm": "0102", "jcdm2": "01,02",
            "qssj": "08:00:00", "jssj": "09:40:00", **changes}


def response(*rows, encoded=False, **changes):
    days = [{"01": list(rows)}, {}, {}, {}, {}, {}, {}]
    return {"code": 200, "xnxqdm": "SUMC-NATIVE-TERM", "zc": 8, "maxzc": 20,
            "firstDayOfWeek": "2026-08-31", "rq": "2026-10-19",
            "xldata": [{"zc": 1, "qsrq": "2026-08-31", "jsrq": "2026-09-06"}],
            "kbList": json.dumps(days, ensure_ascii=False) if encoded else days, **changes}


def all_meetings(result):
    return [meeting for course in result["courses"] for meeting in course["meetings"]]


def test_weekly_records_merge_without_calendar_or_app_dependencies():
    result = parse_timetable(response(lesson(zc=1, qsrq="2026-08-31"),
                                     lesson(zc=2, qsrq="2026-09-07"), encoded=True))
    assert result["semester"] == result["native_semester"] == "SUMC-NATIVE-TERM"
    assert result["current_week"] == 8 and result["max_week"] == 20
    assert result["first_day_of_week"] == "2026-08-31" and result["today"] == "2026-10-19"
    assert result["calendar_weeks"] == [{"week": 1, "start_date": "2026-08-31", "end_date": "2026-09-06"}]
    assert result["pending"] == result["unplaced_details"] == []
    assert result["coverage"]["complete"] is True
    assert result["coverage"]["calendar_verified"] is False
    assert result["coverage"]["period_times_verified"] is False
    assert result["available_semesters"] == []
    course, = result["courses"]
    assert course["course_code"] == "SYN-MED-1" and course["class_name"] == "合成教学班甲"
    meeting, = course["meetings"]
    assert meeting["weeks"] == [1, 2] and meeting["periods"] == [1, 2]
    assert meeting["location"] == "合成校区 合成楼甲 101"
    assert meeting["date_ranges"] == [
        {"weeks": [1], "start_date": "2026-08-31", "end_date": ""},
        {"weeks": [2], "start_date": "2026-09-07", "end_date": ""},
    ]
    assert "hue" not in course and "className" not in course and "rawTime" not in meeting


@pytest.mark.parametrize("payload", [
    None, [], "not-json", {}, {"code": 200}, {"code": 200, "kbList": None},
    {"code": 200, "kbList": "not-json"}, {"code": 200, "kbList": "null"},
    {"code": 200, "kbList": {}}, {"code": 200, "kbList": [{}]},
    {"code": 200, "kbList": [{}] * 8}, {"code": True, "kbList": []},
    {"code": 200.0, "kbList": []}, {"code": None, "kbList": []},
    {"code": 200, "kbList": '[{"01":[],"01":[]},{},{},{},{},{},{}]'},
])
def test_broken_envelope_or_container_never_becomes_an_empty_timetable(payload):
    with pytest.raises(AppError) as error:
        parse_timetable(payload)
    assert error.value.code == "schema_changed" and error.value.source == "med_jw"


@pytest.mark.parametrize("code", [401, "401", 501, "501"])
def test_expired_business_response_is_not_empty_even_with_a_timetable(code):
    with pytest.raises(AppError) as error:
        parse_timetable(response(lesson(), code=code))
    assert error.value.code == "login_expired" and error.value.source == "med_jw"


@pytest.mark.parametrize("code", [500, "500", 403, "200 "])
def test_other_business_failures_do_not_return_success(code):
    with pytest.raises(AppError) as error:
        parse_timetable(response(lesson(), code=code, msg="SYNTHETIC-PRIVATE-MESSAGE"))
    assert error.value.code == "source_error"
    assert "SYNTHETIC-PRIVATE-MESSAGE" not in error.value.message


@pytest.mark.parametrize("empty", [[], "[]", [{}, {}, {}, {}, {}, {}, {}], [[], [], [], [], [], [], []]])
def test_explicit_empty_timetable_is_distinct_from_unreadable_data(empty):
    result = parse_timetable({"code": 200, "kbList": empty})
    assert result["courses"] == result["pending"] == []
    assert result["coverage"]["complete"] is True
    assert result["semester"] is result["native_semester"] is None
    assert result["current_week"] is result["first_day_of_week"] is None


@pytest.mark.parametrize("changes", [
    {"kcmc": ""}, {"kcmc": {"unexpected": "shape"}}, {"xq": 0}, {"xq": 8}, {"xq": True},
    {"zc": "unknown"}, {"zc": 0}, {"zc": 61}, {"zc": True},
    {"jcdm2": "01,bad,02"}, {"jcdm2": "01,31"}, {"jcdm2": "02,01"},
    {"jcdm2": "01,01"}, {"jcdm2": "", "jcdm": ""}, {"jcdm2": "1-2"},
    {"qssj": "not-a-time"}, {"qssj": "10:00:00"}, {"jssj": ""},
    {"qsrq": "2026-02-30"}, {"qsrq": "2026-10-20", "jsrq": "2026-10-19"},
    {"teaxms": ["unexpected", "shape"]},
    {"kcmc": "\ud800"},
])
def test_bad_rows_keep_good_data_and_report_partial_coverage(changes):
    payload = response(lesson(), lesson(**{"kcmc": "SYNTHETIC-PRIVATE-COURSE", **changes}))
    original = deepcopy(payload)
    result = parse_timetable(payload)
    assert payload == original
    assert len(result["courses"]) == 1 and result["courses"][0]["title"] == "合成医学课程"
    assert result["coverage"]["row_count"] == 2
    assert result["coverage"]["parsed_row_count"] == result["coverage"]["rejected_row_count"] == 1
    assert result["coverage"]["complete"] is False and result["pending"]
    assert result["unplaced_details"] == [{"day_index": 1, "bucket": "01", "row_index": 1,
                                           "reason": "unrecognized_arrangement"}]
    assert "SYNTHETIC-PRIVATE-COURSE" not in json.dumps(result["pending"])


def test_all_bad_rows_return_partial_empty_not_complete_empty():
    result = parse_timetable(response(lesson(zc="unknown"), "not-a-row"))
    assert result["courses"] == [] and result["pending"]
    assert result["coverage"]["complete"] is False and result["coverage"]["rejected_row_count"] == 2


@pytest.mark.parametrize("bad_day", [None, "bad", [lesson()], {"01": "bad"}, {"new_bucket": []}])
def test_unrecognized_day_or_bucket_cannot_disappear_without_partial_status(bad_day):
    payload = response(lesson())
    payload["kbList"][2] = bad_day
    result = parse_timetable(payload)
    assert len(result["courses"]) == 1 and result["pending"]
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["rejected_container_count"] == 1


@pytest.mark.parametrize("changes", [
    {"jxcdmc": "102"}, {"jzwmc": "合成楼乙"}, {"szxqmc": "合成另一校区"},
    {"teaxms": "合成教师乙"}, {"qssj": "08:10:00", "jssj": "09:50:00"},
    {"xmmc": "合成项目乙"}, {"kxh": "02"}, {"jcdm2": "01,03"},
    {"lch": "2"}, {"address": "合成另一地址"}, {"tasktype": 2}, {"tkbz": "2"},
])
def test_different_locations_teachers_projects_or_times_are_not_merged(changes):
    result = parse_timetable(response(lesson(zc=1), lesson(zc=2, **changes)))
    course, = result["courses"]
    assert len(course["meetings"]) == 2
    assert sorted(m["weeks"] for m in course["meetings"]) == [[1], [2]]
    assert len({m["id"] for m in course["meetings"]}) == 2


def test_different_teaching_classes_keep_their_own_course_identity():
    result = parse_timetable(response(lesson(), lesson(jxbmc="合成教学班乙", zc=2)))
    assert len(result["courses"]) == 2
    assert {c["class_name"] for c in result["courses"]} == {"合成教学班甲", "合成教学班乙"}
    assert len({c["id"] for c in result["courses"]}) == 2


@pytest.mark.parametrize("raw,expected", [
    (17, [17]), ("17", [17]), ("1-4周", [1, 2, 3, 4]),
    ("1-5周(单)", [1, 3, 5]), ("1-6(双周)", [2, 4, 6]), ("1、3、5周", [1, 3, 5]),
])
def test_only_explicit_week_expressions_are_expanded(raw, expected):
    result = parse_timetable(response(lesson(zc=raw)))
    assert all_meetings(result)[0]["weeks"] == expected and not result["pending"]


def test_record_weekday_is_authoritative_and_missing_weekday_uses_its_day_bucket():
    row = lesson(xq=3, jcdm2="", jcdm="0304")
    result = parse_timetable(response(row))
    assert all_meetings(result)[0]["weekday"] == 3
    assert all_meetings(result)[0]["periods"] == [3, 4]
    del row["xq"]
    assert all_meetings(parse_timetable(response(row)))[0]["weekday"] == 1


def test_ids_and_output_do_not_depend_on_row_order_or_python_hash_seed():
    rows = [lesson(zc=2), lesson(zc=1), lesson(zc=3, jzwmc="另一栋楼")]
    assert parse_timetable(response(*rows)) == parse_timetable(response(*reversed(rows)))
    script = (
        "import json; from stu_mcp.features.med_jw.parser import parse_timetable; "
        f"result = parse_timetable(json.loads({json.dumps(response(*rows))!r})); "
        "print(json.dumps(result, sort_keys=True))"
    )
    outputs = [subprocess.check_output([sys.executable, "-c", script],
               env=dict(os.environ, PYTHONHASHSEED=str(seed))) for seed in (1, 2)]
    assert outputs[0] == outputs[1]


def test_native_semesters_remain_distinct_without_main_campus_translation():
    original = parse_timetable(response(lesson(), xnxqdm="MED-A"))
    changed = parse_timetable(response(lesson(), xnxqdm="MED-B"))
    assert original["semester"] == "MED-A" and changed["semester"] == "MED-B"
    assert original["courses"][0]["id"] != changed["courses"][0]["id"]
    result = parse_timetable(response(lesson(), zc=0))
    assert result["current_week"] == 0


@pytest.mark.parametrize("changes", [{"xnxqdm": {}}, {"zc": "unknown"}, {"maxzc": False},
                                      {"xldata": None}, {"xldata": [{"zc": "bad"}]}])
def test_invalid_metadata_is_explicit_without_discarding_courses(changes):
    result = parse_timetable(response(lesson(), **changes))
    assert len(result["courses"]) == 1 and result["pending"]
    assert result["coverage"]["complete"] is False


def test_parser_row_limit_cannot_produce_a_successful_truncated_result(monkeypatch):
    monkeypatch.setattr("stu_mcp.features.med_jw.parser.MED_JW_MAX_ROWS", 1)
    with pytest.raises(AppError) as error:
        parse_timetable(response(lesson(), lesson(zc=2)))
    assert error.value.code == "schema_changed"


def test_json_byte_limit_precedes_parsing(monkeypatch):
    monkeypatch.setattr("stu_mcp.features.med_jw.parser.MED_JW_MAX_JSON_BYTES", 1)
    with pytest.raises(AppError) as error:
        parse_timetable(response(lesson(), encoded=True))
    assert error.value.code == "schema_changed"


def test_schema_read_routes_do_not_expand_to_login_or_other_school_operations():
    expected = frozenset({("POST", MED_JW_TIMETABLE_PATH), ("GET", MED_JW_INFO_PATH)})
    assert expected == MED_JW_READ_ROUTES
    assert MED_JW_TIMETABLE_BODY == {"zc": "all", "jc": "", "teadm": ""}
    assert all(path not in (MED_JW_LOGIN_PATH, MED_JW_CAPTCHA_PATH) for _, path in MED_JW_READ_ROUTES)
