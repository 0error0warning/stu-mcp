"""Synthetic source payloads; these tests never connect to the school."""
from copy import deepcopy

import pytest

from stu_mcp.features.yuketang.parser import (
    Course,
    parse_activities,
    parse_announcements,
    parse_inventory,
)
from stu_mcp.features.yuketang.schema import ACTIVITY_LIMIT, ANNOUNCEMENT_LIMIT, COURSES_URL
from stu_mcp.parsing import item_id, stamp
from stu_mcp.runtime import AppError
from stu_mcp.sources import YUKETANG_BASE


def course_row(**values):
    return {"classroom_id": 7, "term": 20261, "course": {"name": "合成课程"},
            "teacher": {"name": "合成教师"}, **values}


def inventory(*rows, **metadata):
    return {"data": {"list": list(rows), **metadata}}


@pytest.fixture
def course():
    return parse_inventory(inventory(course_row())).courses[0]


def activity(**values):
    return {"id": 9, "title": "合成活动", "type": 19,
            "content": {"leaf_id": 11, "score_d": 1792425600}, "create_time": 1792339200, **values}


def activities(*rows, **metadata):
    return {"data": {"activities": list(rows), **metadata}}


def announcement(**values):
    return {"id": 31, "title": "合成公告", "content": "<p>合成正文</p>",
            "publish_time": 1792425600, "create_time": 1792339200, **values}


def announcements(*rows):
    return {"data": {"data": list(rows)}}


def changed(function, *args):
    with pytest.raises(AppError) as failure:
        function(*args)
    assert failure.value.code == "schema_changed"
    assert failure.value.source == "yuketang"
    assert "SYNTHETIC_SECRET" not in str(failure.value.result())


def test_inventory_keeps_native_latest_term_and_observed_nested_and_flat_names():
    result = parse_inventory(inventory(
        course_row(classroom_id=6, term=20252),
        course_row(),
        course_row(classroom_id="8", course=None, name="平面课程", teacher=None),
    ))
    assert result.semester == "20261" and result.complete
    assert result.courses == [
        Course("7", "合成课程", "合成教师", 20261, YUKETANG_BASE + "/v2/web/studentLog/7"),
        Course("8", "平面课程", "", 20261, YUKETANG_BASE + "/v2/web/studentLog/8"),
    ]
    assert COURSES_URL == YUKETANG_BASE + "/v2/api/web/courses/list?identity=2"


def test_inventory_ignores_unknown_fields_without_turning_objects_into_text():
    payload = inventory(course_row(unknown={"token": "SYNTHETIC_SECRET"}))
    payload["unknown"] = {"cookie": "SYNTHETIC_SECRET"}
    result = parse_inventory(payload)
    assert result.complete and "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": []},
                                      {"data": {}}, {"data": {"list": None}},
                                      {"data": {"list": {}}}, {"data": {"list": [None]}}])
def test_inventory_requires_known_envelope_and_list(payload):
    changed(parse_inventory, payload)


@pytest.mark.parametrize("values", [
    {"classroom_id": None}, {"classroom_id": True}, {"classroom_id": 0}, {"classroom_id": []},
    {"classroom_id": {"token": "SYNTHETIC_SECRET"}}, {"classroom_id": "seven"},
    {"classroom_id": " 7 "}, {"classroom_id": "７"},
    {"classroom_id": 7.0}, {"term": True}, {"term": []},
    {"course": []}, {"course": "SYNTHETIC_SECRET"},
    {"course": {"name": {"token": "SYNTHETIC_SECRET"}}},
    {"course": {"name": True}}, {"course": {"name": 7}},
    {"course": None, "name": None}, {"course": None, "name": []},
    {"teacher": "SYNTHETIC_SECRET"}, {"teacher": []},
    {"teacher": {"name": {"cookie": "SYNTHETIC_SECRET"}}},
    {"teacher": {"name": True}},
])
def test_inventory_rejects_field_type_drift_and_sensitive_objects(values):
    changed(parse_inventory, inventory(course_row(**values)))


def test_inventory_rejects_duplicate_ids_across_terms_and_preserves_nested_title_priority():
    changed(parse_inventory, inventory(course_row(), course_row(term=20252)))
    assert parse_inventory(inventory(course_row(name="另外一门课程"))).courses[0].title == "合成课程"
    assert parse_inventory(inventory(course_row(name=" 合成课程 "))).complete


def test_inventory_validates_old_terms_before_proving_complete_inventory():
    changed(parse_inventory, inventory(course_row(), course_row(classroom_id=6, term=20252, teacher=[])))


@pytest.mark.parametrize("metadata", [
    {"has_more": True}, {"total": 2}, {"pagination": {"total_pages": 2}},
    {"total": True}, {"total": {}}, {"total": 1.5}, {"pagination": []},
    {"pagination": {"total": {"token": "SYNTHETIC_SECRET"}}}, {"has_more": "false"},
])
def test_inventory_uncertain_pagination_does_not_authorize_pruning(metadata):
    result = parse_inventory(inventory(course_row(), **metadata))
    assert result.courses and not result.complete


def test_inventory_outer_pagination_and_missing_terms_are_not_complete():
    payload = inventory(course_row()) | {"hasMore": True}
    assert not parse_inventory(payload).complete
    result = parse_inventory(inventory(course_row(term=None)))
    assert result.semester is None and not result.complete and result.courses[0].term is None
    assert parse_inventory(inventory()).complete


def test_inventory_preserves_string_terms_without_inventing_a_semester_or_cleanup_scope():
    result = parse_inventory(inventory(course_row(term="20261")))
    assert result.courses[0].term == "20261" and result.semester is None and not result.complete
    result = parse_inventory(inventory(course_row(), course_row(classroom_id=8, term="20262")))
    assert result.semester == "20261" and [course.id for course in result.courses] == ["7"]
    assert not result.complete


def test_activity_normalization_preserves_existing_record_fields_ids_and_url(course):
    result = parse_activities(activities(activity()), course, "20261")
    assert result.complete
    assert result.items == [{
        "id": item_id("yuketang", "task", "7", 9), "kind": "task", "title": "合成活动",
        "course": "合成课程", "url": YUKETANG_BASE + "/ai-workspace/lms-graph/7/exercise/11?is_chapter=1",
        "course_id": "7", "semester": "20261", "term": 20261, "activity_type": 19,
        "leaf_id": "11", "due_at": stamp(1792425600), "status": "todo",
        "published_at": stamp(1792339200),
    }]


@pytest.mark.parametrize("raw_type,kind", [(3, "task"), (19, "task"), (21, "resource"),
                                          ("new_type", "resource"), ("19", "resource")])
def test_activity_unknown_scalar_types_stay_resources_without_coercion(course, raw_type, kind):
    result = parse_activities(activities(activity(type=raw_type)), course, "20261")
    assert result.complete is (type(raw_type) is int)
    assert result.items[0]["kind"] == kind
    assert result.items[0]["activity_type"] == raw_type


def test_activity_optional_times_leaf_and_id_keep_existing_fallbacks(course):
    result = parse_activities(activities(activity(id=None, content=None, create_time=None)), course, None)
    item = result.items[0]
    assert item["id"] == item_id("yuketang", "task", course.id, "合成活动")
    assert item["due_at"] is item["published_at"] is item["leaf_id"] is None
    assert item["url"] == course.url
    assert parse_activities(activities(activity(content={"leaf_id": "opaque"})), course, None).items[0][
        "url"] == course.url


def test_activity_zero_id_and_leaf_keep_old_fallback_and_strings_keep_their_stable_identity(course):
    result = parse_activities(activities(activity(id=0, content={"leaf_id": 0})), course, "20261").items[0]
    assert result["id"] == item_id("yuketang", "task", course.id, "合成活动")
    assert result["leaf_id"] is None and result["url"] == course.url
    raw_id = " 9 "
    result = parse_activities(activities(activity(id=raw_id)), course, "20261").items[0]
    assert result["id"] == item_id("yuketang", "task", course.id, raw_id)


@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": []}, {"data": {}},
                                      {"data": {"activities": None}}, {"data": {"activities": {}}},
                                      {"data": {"activities": [None]}}])
def test_activity_requires_known_envelope_and_list(course, payload):
    changed(parse_activities, payload, course, "20261")


@pytest.mark.parametrize("values", [
    {"title": None}, {"title": True}, {"title": {"token": "SYNTHETIC_SECRET"}},
    {"id": True}, {"id": []}, {"id": {}}, {"id": {"cookie": "SYNTHETIC_SECRET"}}, {"type": False},
    {"type": {"token": "SYNTHETIC_SECRET"}}, {"type": 19.0}, {"content": []},
    {"content": "SYNTHETIC_SECRET"}, {"content": {"leaf_id": True}}, {"content": {"leaf_id": []}},
    {"content": {"leaf_id": {"token": "SYNTHETIC_SECRET"}}},
    {"content": {"score_d": {"token": "SYNTHETIC_SECRET"}}},
    {"content": {"score_d": True}}, {"content": {"score_d": "not-a-time"}},
    {"content": {"score_d": float("inf")}}, {"create_time": []},
    {"create_time": False}, {"create_time": "nan"},
])
def test_activity_type_drift_is_a_fixed_schema_error_not_partial_records(course, values):
    changed(parse_activities, activities(activity(**values)), course, "20261")


def test_activity_duplicate_identity_and_fallback_identity_collision_are_rejected(course):
    changed(parse_activities, activities(activity(), activity(type=21)), course, "20261")
    changed(parse_activities, activities(activity(id=None), activity(id="合成活动")), course, "20261")


@pytest.mark.parametrize("metadata", [{"hasMore": True}, {"total": 8},
                                      {"pagination": {"page_count": 3}}, {"total": False}])
def test_activity_partial_pages_return_items_without_complete_snapshot(course, metadata):
    result = parse_activities(activities(activity(), **metadata), course, "20261")
    assert result.items and not result.complete


def test_activity_capacity_limits_output_but_validates_all_records(course):
    rows = [activity(id=index) for index in range(ACTIVITY_LIMIT + 1)]
    result = parse_activities(activities(*rows), course, "20261")
    assert len(result.items) == ACTIVITY_LIMIT and not result.complete
    rows[-1]["title"] = {"token": "SYNTHETIC_SECRET"}
    changed(parse_activities, activities(*rows), course, "20261")


def test_activity_missing_type_cannot_prove_deletion_of_old_tasks(course):
    row = activity()
    row.pop("type")
    result = parse_activities(activities(row), course, "20261")
    assert not result.complete and result.items[0]["kind"] == "resource"
    assert parse_activities(activities(), course, "20261").complete


@pytest.mark.parametrize("value", [None, "", 0, "0", -1])
def test_optional_activity_time_sentinels_remain_none(course, value):
    row = activity(content={"score_d": value}, create_time=value)
    result = parse_activities(activities(row), course, "20261").items[0]
    assert result["due_at"] is None and result["published_at"] is None


def test_announcement_normalization_preserves_existing_notice_contract(course):
    result = parse_announcements(announcements(announcement()), course)
    assert result == [{
        "id": item_id("yuketang", "notice", course.id, 31), "kind": "notice", "title": "合成公告",
        "course": "合成课程", "body": "合成正文", "url": course.url,
        "published_at": stamp(1792425600),
    }]
    assert parse_announcements(announcements(), course) == []


def test_announcement_ids_are_course_scoped_and_optional_time_is_not_invented(course):
    row = announcement(title=None, content="<p>正文标题</p>", publish_time=None, create_time=None)
    result = parse_announcements(announcements(row), course)[0]
    assert result["title"] == "正文标题" and result["published_at"] is None
    other_course = Course("8", course.title, course.teacher, course.term, course.url)
    assert parse_announcements(announcements(row), other_course)[0]["id"] != result["id"]


@pytest.mark.parametrize("value,uses_created", [(None, True), ("", True), (0, True), ("0", False)])
def test_announcement_publish_time_fallback_preserves_existing_scalar_semantics(course, value, uses_created):
    result = parse_announcements(announcements(announcement(publish_time=value)), course)[0]
    assert result["published_at"] == (stamp(1792339200) if uses_created else None)


def test_announcement_nonempty_string_id_is_not_rewritten_by_normalization(course):
    result = parse_announcements(announcements(announcement(id=" 31 ")), course)[0]
    assert result["id"] == item_id("yuketang", "notice", course.id, " 31 ")


@pytest.mark.parametrize("payload", [None, [], {}, {"data": None}, {"data": []}, {"data": {}},
                                      {"data": {"data": None}}, {"data": {"data": {}}},
                                      {"data": {"data": [None]}}])
def test_announcements_require_known_envelope_and_list(course, payload):
    changed(parse_announcements, payload, course)


@pytest.mark.parametrize("values", [
    {"id": None}, {"id": ""}, {"id": True}, {"id": []},
    {"id": {"cookie": "SYNTHETIC_SECRET"}}, {"title": []},
    {"title": {"token": "SYNTHETIC_SECRET"}}, {"content": {"token": "SYNTHETIC_SECRET"}},
    {"content": False}, {"publish_time": True}, {"create_time": []},
    {"publish_time": "NaN"}, {"title": None, "content": None},
])
def test_announcement_type_drift_or_missing_identity_is_not_an_empty_notice(course, values):
    changed(parse_announcements, announcements(announcement(**values)), course)


def test_announcements_reject_duplicate_id_before_returning_or_limiting(course):
    changed(parse_announcements, announcements(announcement(), announcement(title="另一标题")), course)
    rows = [announcement(id=index) for index in range(ANNOUNCEMENT_LIMIT + 1)]
    assert len(parse_announcements(announcements(*rows), course)) == ANNOUNCEMENT_LIMIT
    rows[-1]["id"] = rows[0]["id"]
    changed(parse_announcements, announcements(*rows), course)


def test_all_source_parsers_are_pure_and_ignore_extra_sensitive_metadata(course):
    payload = activities(activity(unknown={"token": "SYNTHETIC_SECRET"}))
    before = deepcopy(payload)
    result = parse_activities(payload, course, "20261")
    assert payload == before and "SYNTHETIC_SECRET" not in repr(result)
    payload = announcements(announcement(unknown={"cookie": "SYNTHETIC_SECRET"}))
    before = deepcopy(payload)
    result = parse_announcements(payload, course)
    assert payload == before and "SYNTHETIC_SECRET" not in repr(result)
