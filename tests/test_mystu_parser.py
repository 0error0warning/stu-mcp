import pytest

from stu_mcp.features.mystu.parser import (
    current_courses,
    parse_activities,
    parse_assignment,
    parse_elc,
    parse_inventory,
    parse_schedule,
    payload_records,
)
from stu_mcp.runtime import AppError

COURSE = {"id": "1", "name": "合成课程", "attendanceYear": 2026, "attendanceSemester": 1,
          "url": "https://my.stu.edu.cn/course/view.php?id=1"}
ELC = ('<div class="course-content"><li class="activity modtype_assign"><div class="activityinstance">'
       '<a href="/courses/elc/mod/assign/view.php?id=10"><span class="instancename">合成作业</span></a>'
       '</div></li></div>')


def test_array_column_reordering_and_extra_fields_keep_course_identity():
    first = parse_inventory({"items": [COURSE]})
    fields = ["unused", "name", "id", "attendanceSemester", "url", "attendanceYear"]
    row = ["合成附加信息", COURSE["name"], "1", 1, COURSE["url"], 2026]
    decoded = payload_records({"fields": ",".join(fields), "items": [row]})
    assert decoded[0]["id"] == "1"
    assert parse_inventory({"items": decoded}) == first


@pytest.mark.parametrize("payload", [
    {}, {"items": None}, {"items": [None]}, {"items": [[1]], "fields": "id,name"},
    {"items": [[1, "x", "extra"]], "fields": "id,name"},
    {"items": [[1, "x"]], "fields": "id,id"}, {"items": [[1, "x"]], "fields": "id, "},
    {"items": [[1]], "fields": ["id"]},
])
def test_missing_or_ambiguous_array_contract_is_not_empty(payload):
    with pytest.raises(AppError) as error:
        payload_records(payload)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("changes", [{"id": None, "url": None}, {"name": ""}, {"teacher": {}},
                                      {"url": {}}, {"name": {"changed": True}}, {"id": True}, {"id": False},
                                      {"attendanceYear": True}, {"attendanceSemester": False},
                                      {"attendanceYear": True, "attendanceSemester": True}])
def test_required_course_contract_stops_before_replacing_inventory(changes):
    with pytest.raises(AppError) as error:
        parse_inventory({"items": [{**COURSE, **changes}]})
    assert error.value.code == "schema_changed"


def test_duplicate_course_id_is_ambiguous_even_if_records_differ():
    with pytest.raises(AppError):
        parse_inventory({"items": [COURSE, {**COURSE, "name": "另一合成课程"}]})


def test_latest_term_unknown_terms_and_confirmed_empty_keep_coverage_semantics():
    old = {**COURSE, "id": "old", "attendanceYear": 2025}
    assert current_courses([old, COURSE]) == [COURSE]
    assert parse_inventory({"items": [old, COURSE]}).semester == "2026-1"
    assert not parse_inventory({"items": [{**COURSE, "attendanceYear": None}]}).complete
    assert not parse_inventory({"items": [], "hasMore": True}).complete
    empty = parse_inventory({"items": []})
    assert empty.courses == [] and empty.complete and empty.semester is None


def test_elc_container_changes_and_unrelated_nodes_keep_activity_output():
    baseline = parse_elc(ELC, COURSE["url"])
    wrapped = '<main><table><tr><td>' + ELC + '</td></tr></table><p>合成页面说明</p></main>'
    assert parse_elc(wrapped, COURSE["url"]) == baseline
    assert baseline[0]["activityCategory"] == "assignment"
    assert baseline[0]["activityUrl"].endswith("/courses/elc/mod/assign/view.php?id=10")


@pytest.mark.parametrize("html,code", [
    ("<h1>合成错误页面</h1>", "schema_changed"),
    ('<input type="password">', "needs_elc_login"),
    (ELC + '<div class="course-content"></div>', "schema_changed"),
    ('<div class="course-content"><li class="activity modtype_assign">合成缺链接</li></div>', "schema_changed"),
    (ELC.replace('</li>', '</li>' + ELC.split('<div class="course-content">')[1].rsplit('</div>', 1)[0]),
     "schema_changed"),
])
def test_elc_unrecognized_or_ambiguous_page_is_not_empty(html, code):
    with pytest.raises(AppError) as error:
        parse_elc(html, COURSE["url"])
    assert error.value.code == code


@pytest.mark.parametrize("html", [
    '<div id="intro">合成作业说明，未设置截止时间。</div>',
    '<body id="page-mod-assign-view"><main>合成没有截止时间的作业</main></body>',
    '<div class="submissionstatustable"><dl><dt>提交状态</dt><dd>未提交</dd></dl></div>',
])
def test_recognized_assignment_without_deadline_remains_a_successful_read(html):
    result = parse_assignment(html)
    assert result["due_at"] is None
    assert set(result) == {"due_at", "school_status", "description"}


def test_assignment_container_order_and_optional_fields_keep_recognized_values():
    first = ('<div id="intro">合成说明</div><table><tr><td>截止时间</td><td>2026年10月10日 23:59</td></tr>'
             '<tr><td>提交状态</td><td>未提交</td></tr></table>')
    changed = ('<table><tr><td><section><dl><dt>提交状态</dt><dd>未提交</dd>'
               '<dt>合成附加字段</dt><dd>附加值</dd><dt>截止时间</dt><dd>2026年10月10日 23:59</dd>'
               '</dl></section></td></tr></table><main><div id="intro">合成说明</div></main>')
    assert parse_assignment(changed) == parse_assignment(first)
    assert parse_assignment(first)["due_at"] == "2026-10-10T23:59:00+08:00"


def test_nested_description_wrappers_are_one_region_and_empty_due_is_recognized():
    html = '<section class="activity-description"><div id="intro">合成说明</div></section>'
    assert parse_assignment(html)["description"] == "合成说明"
    assert parse_assignment('<table><tr><td>截止时间</td><td></td></tr></table>')["due_at"] is None


@pytest.mark.parametrize("html,code", [
    ("<h1>合成错误页面</h1>", "schema_changed"), ("", "schema_changed"),
    ('<input type="password">', "needs_elc_login"),
    ('<div id="intro">a</div><div class="activity-description">b</div>', "schema_changed"),
    ('<dl><dt>截止时间</dt><dd>2026年10月10日 23:59</dd>'
     '<dt>Due date</dt><dd>2026年10月11日 23:59</dd></dl>', "schema_changed"),
])
def test_assignment_unknown_login_or_ambiguous_details_never_look_read(html, code):
    with pytest.raises(AppError) as error:
        parse_assignment(html)
    assert error.value.code == code


def test_user_description_table_does_not_supply_school_metadata():
    html = ('<div id="intro"><table><tr><td>截止时间</td><td>合成伪造截止</td></tr></table></div>'
            '<dl><dt>截止时间</dt><dd>2026年10月10日 23:59</dd></dl>')
    assert parse_assignment(html)["due_at"] == "2026-10-10T23:59:00+08:00"


@pytest.mark.parametrize("payload", [
    {}, {"courseActivities": None}, {"courseActivities": [None]},
    {"courseActivities": [{"activityTitle": ""}]},
    {"courseActivities": [{"activityTitle": "合成任务", "activityUrl": {}}]},
    {"courseActivities": [{"activityTitle": True}]},
    {"courseActivities": [{"activityTitle": "合成任务", "additionalDueDate": True}]},
    {"courseActivities": [{"activityTitle": "相同合成活动"}, {"activityTitle": "相同合成活动"}]},
])
def test_activity_critical_changes_and_duplicate_identity_stop_the_snapshot(payload):
    with pytest.raises(AppError) as error:
        parse_activities(payload)
    assert error.value.code == "schema_changed"


def test_partial_activity_pages_never_become_complete_snapshots():
    empty = parse_activities({"courseActivities": []})
    assert empty.items == [] and empty.complete
    assert not parse_activities({"courseActivities": [], "hasMore": True}).complete
    rows = [{"activityTitle": f"合成任务 {i}"} for i in range(50)]
    assert not parse_activities({"courseActivities": rows}).complete


def test_schedule_array_mapping_keeps_existing_ids_and_event_fields():
    event = {"id": 7, "title": "合成日程", "startTime": 1780000000000, "endTime": 1780003600000,
             "location": "合成教室"}
    expected = parse_schedule({"items": [event]})
    keys = list(reversed(event))
    assert parse_schedule({"fields": ",".join(keys), "items": [[event[key] for key in keys]]}) == expected
    assert not expected[1] and expected[0][0]["kind"] == "event"
    assert parse_schedule({"items": []}) == ([], False)


@pytest.mark.parametrize("field", ["id", "startTime", "endTime"])
def test_schedule_boolean_identity_and_times_are_not_valid_numbers(field):
    with pytest.raises(AppError) as error:
        parse_schedule({"items": [{"id": 7, "title": "合成日程", field: True}]})
    assert error.value.code == "schema_changed"
