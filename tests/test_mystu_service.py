from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from stu_mcp.features.mystu.service import mystu
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError

COURSE = {"id": "1", "name": "合成课程", "attendanceYear": 2026, "attendanceSemester": 1,
          "url": "https://my.stu.edu.cn/course/view.php?id=1", "teacher": "合成教师"}
ASSIGNMENT = "https://my.stu.edu.cn/courses/elc/mod/assign/view.php?id=11"


@pytest.fixture
def synthetic_school():
    state = {"courses": [deepcopy(COURSE)], "activities": {"1": [
        {"activityTitle": "合成作业", "activityCategory": "assignment", "activityUrl": ASSIGNMENT}]},
        "detail": {ASSIGNMENT: '<div id="intro">合成作业说明</div>'}, "schedule": {"items": []}, "requests": []}
    session = {"synthetic": "never-a-real-school-session"}

    class HTTP:
        def __init__(self, source, loaded):
            assert source == "mystu" and loaded is session

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def json(self, url):
            state["requests"].append(("json", url))
            parsed, query = urlparse(url), parse_qs(urlparse(url).query)
            assert parsed.scheme == "https" and parsed.hostname == "my.stu.edu.cn"
            if parsed.path.endswith("/user/validate"):
                return {"errcode": 0}
            if parsed.path.endswith("/course/query"):
                return {"items": state["courses"], **state.get("inventory_metadata", {})}
            if parsed.path.endswith("/courseactivity/query"):
                response = state["activities"][query["moodleCourseId"][0]]
                if isinstance(response, AppError):
                    raise response
                return {"courseActivities": response} if isinstance(response, list) else response
            assert parsed.path.endswith("/userschedule/query")
            response = state["schedule"]
            if isinstance(response, AppError):
                raise response
            return response

        def text(self, url):
            state["requests"].append(("text", url))
            response = state["detail"][url]
            if isinstance(response, AppError):
                raise response
            return response

    return state, SimpleNamespace(load=lambda source: session), HTTP


def task_items(result):
    return [item for item in result.items if item["kind"] == "task"]


def test_tool_records_keep_ids_fields_and_read_without_deadline_distinction(synthetic_school):
    state, vault, factory = synthetic_school
    result = mystu(vault, 10, http_factory=factory)
    task = task_items(result)[0]
    assert result.private and result.status == "ok"
    assert task == {"id": item_id("mystu", "task", "1", ASSIGNMENT), "kind": "task",
                    "detail_status": "read", "due_at_status": "not_found_in_detail", "title": "合成作业",
                    "course": "合成课程", "course_id": "1", "semester": "2026-1", "year": 2026, "term": 1,
                    "url": ASSIGNMENT, "category": "assignment", "due_at": None, "school_status": None,
                    "status": "todo", "body": "合成作业说明"}
    assert result.sync.complete and result.sync.complete_courses == {"1"}
    assert len(state["requests"]) == 5


@pytest.mark.parametrize("detail,code", [
    ("<h1>合成错误页面</h1>", "schema_changed"),
    ('<input type="password">', "resource_login_required"),
    (AppError("login_expired", "合成登录失败", "mystu"), "resource_login_required"),
])
def test_unknown_or_login_detail_is_unavailable_without_poisoning_course_session(synthetic_school, detail, code):
    state, vault, factory = synthetic_school
    state["detail"][ASSIGNMENT] = detail
    result = mystu(vault, 10, http_factory=factory)
    task = task_items(result)[0]
    assert task["detail_status"] == "unavailable" and task["due_at_status"] == "detail_unavailable"
    assert task["detail_error"]["status"] == code
    assert result.status == "partial" and result.errors[0]["stage"] == "task_detail"
    assert result.errors[0]["item_id"] == task["id"]
    assert result.sync.complete


def test_one_unavailable_detail_does_not_suppress_next_task_or_api_due_date(synthetic_school):
    state, vault, factory = synthetic_school
    second = ASSIGNMENT.replace("11", "12")
    state["activities"]["1"] += [{"activityTitle": "第二合成作业", "activityCategory": "quiz", "activityUrl": second}]
    state["activities"]["1"][0]["additionalDueDate"] = 1780000000000
    state["detail"][ASSIGNMENT] = "<h1>合成错误页</h1>"
    state["detail"][second] = '<dl><dt>截止时间</dt><dd>2026年10月10日 23:59</dd></dl>'
    result = mystu(vault, 10, http_factory=factory)
    first, other = task_items(result)
    assert first["detail_status"] == "unavailable" and first["due_at_status"] == "available"
    assert other["detail_status"] == "read" and other["due_at"] == "2026-10-10T23:59:00+08:00"
    assert len(result.errors) == 1


@pytest.mark.parametrize("response", [{}, {"courseActivities": None},
                                      {"courseActivities": [{"unknown": "changed"}]}])
def test_broken_activity_schema_does_not_authorize_task_pruning(synthetic_school, response):
    state, vault, factory = synthetic_school
    state["activities"]["1"] = response
    result = mystu(vault, 10, http_factory=factory)
    assert result.status == "partial" and result.errors[0]["status"] == "schema_changed"
    assert result.sync.course_ids == frozenset({"1"}) and not result.sync.complete_courses
    assert not result.sync.obsolete({"id": "old-task", "kind": "task", "course_id": "1"}, set())


def test_elc_html_never_claims_complete_course_or_removes_unseen_tasks(synthetic_school):
    state, vault, factory = synthetic_school
    url = "https://my.stu.edu.cn/courses/elc/course/view.php?id=1"
    state["courses"][0]["url"] = url
    state["detail"][url] = '<main><div class="course-content"></div></main>'
    result = mystu(vault, 10, http_factory=factory)
    assert result.limited and not result.sync.complete
    assert not result.sync.obsolete({"id": "old-task", "kind": "task", "course_id": "1"}, set())


def test_schedule_schema_error_is_partial_and_does_not_block_activity_cleanup(synthetic_school):
    state, vault, factory = synthetic_school
    state["activities"]["1"] = []
    state["schedule"] = {"changed": []}
    result = mystu(vault, 10, http_factory=factory)
    assert result.status == "partial" and result.errors[0]["stage"] == "schedule"
    assert result.sync.complete and result.sync.obsolete({"id": "old-task", "kind": "task"}, set())


def test_course_limit_and_partial_pages_keep_unseen_courses_tasks(synthetic_school):
    state, vault, factory = synthetic_school
    state["courses"] += [{**COURSE, "id": "2", "url": COURSE["url"].replace("1", "2")}]
    state["activities"]["1"] = {"courseActivities": [], "hasMore": True}
    result = mystu(vault, 1, http_factory=factory)
    assert result.limited and result.sync.course_ids == frozenset({"1", "2"})
    assert not result.sync.complete_courses
    assert not result.sync.obsolete({"id": "unseen", "kind": "task", "course_id": "2"}, set())


def test_unsafe_course_and_activity_links_are_rejected_before_reading(synthetic_school):
    state, vault, factory = synthetic_school
    state["activities"]["1"][0]["activityUrl"] = "https://evil.example/synthetic"
    result = mystu(vault, 10, http_factory=factory)
    assert result.errors[0]["status"] == "unsafe_url" and not result.sync.complete_courses
    assert not any(method == "text" for method, _ in state["requests"])
    state["requests"].clear()
    state["courses"][0]["url"] = "https://evil.example/synthetic"
    result = mystu(vault, 10, http_factory=factory)
    assert result.errors[0]["status"] == "unsafe_url"
    assert not any("courseactivity" in url or method == "text" for method, url in state["requests"])


@pytest.mark.parametrize("field", ["attendanceYear", "attendanceSemester"])
def test_boolean_term_change_preserves_previous_cached_course_and_tasks(app, session, monkeypatch,
                                                                      synthetic_school, field):
    from stu_mcp import collectors

    state, vault, factory = synthetic_school
    # Use the normal App/store transaction with only the source HTTP factory replaced.
    app.vault.save("mystu", session)
    monkeypatch.setattr(collectors, "mystu", lambda _vault, limit: mystu(vault, limit, http_factory=factory))
    app.refresh("mystu")
    cached = {item["id"] for item in app.query("task", source="mystu")["items"]}
    assert cached
    state["courses"][0][field] = True
    with pytest.raises(AppError) as error:
        app.refresh("mystu")
    assert error.value.code == "schema_changed"
    assert {item["id"] for item in app.query("task", source="mystu")["items"]} == cached
    assert app.query("course", source="mystu")["items"][0]["semester"] == "2026-1"
