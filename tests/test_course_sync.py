import json
from urllib.parse import parse_qs, urlparse

import pytest

from stu_mcp import collectors
from stu_mcp.parsers import item_id
from stu_mcp.runtime import AppError
from stu_mcp.sync import CourseSync


def course(cid="1", year=2026, term=1):
    return {"id": cid, "name": f"合成课程 {cid}", "attendanceYear": year, "attendanceSemester": term,
            "url": f"https://my.stu.edu.cn/course/view.php?id={cid}"}


def task(title):
    return {"activityTitle": title, "activityCategory": "assignment"}


@pytest.fixture
def campus(app, session, monkeypatch):
    state = {"courses": [course()], "activities": {"1": [task("old-task")]}, "calendar_error": False}
    app.vault.save("mystu", session)

    class FakeHTTP:
        def __init__(self, source, *_):
            assert source == "mystu"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def json(self, url):
            path, query = urlparse(url).path, parse_qs(urlparse(url).query)
            if path.endswith("/user/validate"):
                return {"errcode": 0}
            if path.endswith("/course/query"):
                return {"items": state["courses"], **state.get("inventory_metadata", {})}
            if path.endswith("/courseactivity/query"):
                response = state["activities"][query["moodleCourseId"][0]]
                if isinstance(response, AppError):
                    raise response
                return {"courseActivities": response} if isinstance(response, list) else response
            if path.endswith("/userschedule/query"):
                if state["calendar_error"]:
                    raise AppError("network_error", "合成日程失败", "mystu")
                return {"items": []}
            raise AssertionError(url)

        def text(self, url):
            return state.get("elc_html", '<div class="course-content"></div>')

    monkeypatch.setattr(collectors, "CampusHTTP", FakeHTTP)
    return state


def titles(app):
    return {i["title"] for i in app.store.list(sources=("mystu",), kind="task", _all_items=True)["items"]}


def test_switching_term_retires_old_tasks_and_courses_even_if_new_activity_fails(app, campus):
    app.refresh("mystu")
    campus["courses"] = [course("2", 2027, 1)]
    campus["activities"]["2"] = AppError("network_error", "合成读取失败", "mystu")
    refreshed = app.refresh("mystu")
    assert refreshed["status"] == "partial"
    assert titles(app) == set()
    assert [i["course_id"] for i in app.query("course", source="mystu")["items"]] == ["2"]
    campus["activities"]["2"] = [task("new-task")]
    app.refresh("mystu")
    result = app.query("task", source="mystu")
    assert titles(app) == {"new-task"}
    assert result["items"][0]["semester"] == "2027-1"
    assert result["scopes"][0]["semester"] == "2027-1"


@pytest.mark.parametrize("empty_inventory", [False, True])
def test_confirmed_empty_clears_only_course_snapshot(app, campus, empty_inventory):
    app.refresh("mystu")
    app.store.save_batch("mystu", [{"id": "calendar-one", "kind": "event", "title": "合成日程"}], private=True)
    if empty_inventory:
        campus["courses"] = []
    else:
        campus["activities"]["1"] = []
    assert app.refresh("mystu")["coverage"]["course_snapshot_complete"] is True
    assert titles(app) == set()
    assert app.query("event", source="mystu")["total_count"] == 1


def test_bounded_or_failed_course_retains_its_tasks_but_complete_course_prunes(app, campus):
    campus["courses"] = [course("1"), course("2")]
    campus["activities"]["2"] = [task("unread-task")]
    app.refresh("mystu")
    campus["activities"]["1"] = []
    app.refresh("mystu", limit=1)
    assert titles(app) == {"unread-task"}
    campus["activities"]["2"] = AppError("network_error", "合成读取失败", "mystu")
    app.refresh("mystu")
    assert titles(app) == {"unread-task"}


@pytest.mark.parametrize("response", [{}, {"courseActivities": None}, {"courseActivities": [{"unknown": 1}]}])
def test_missing_or_unparseable_activity_fields_are_not_empty_snapshots(app, campus, response):
    app.refresh("mystu")
    campus["activities"]["1"] = response
    refreshed = app.refresh("mystu")
    assert refreshed["status"] == "partial" and refreshed["errors"][0]["status"] == "schema_changed"
    assert titles(app) == {"old-task"}


@pytest.mark.parametrize("response", [
    {"courseActivities": [], "hasMore": True},
    {"courseActivities": [], "total": 7},
    {"courseActivities": [task(str(i)) for i in range(50)]},
])
def test_truncated_activity_response_preserves_records_outside_page(app, campus, response):
    app.refresh("mystu")
    campus["activities"]["1"] = response
    result = app.refresh("mystu")
    assert result["limited"] is True
    assert "old-task" in titles(app)


@pytest.mark.parametrize("metadata", [{"has_more": True}, {"pagination": {"total_pages": 2}}])
def test_incomplete_inventory_does_not_clear_other_courses(app, campus, metadata):
    app.refresh("mystu")
    campus["courses"] = []
    campus["inventory_metadata"] = metadata
    result = app.refresh("mystu")
    assert result["coverage"]["inventory_complete"] is False
    assert titles(app) == {"old-task"}


@pytest.mark.parametrize("html", ['<div class="course-content"></div>', '<h1>合成错误页面</h1>'])
def test_elc_html_is_not_proof_of_a_complete_empty_activity_snapshot(app, campus, html):
    app.refresh("mystu")
    campus["courses"][0]["url"] = "https://my.stu.edu.cn/courses/elc/course/view.php?id=1"
    campus["elc_html"] = html
    refreshed = app.refresh("mystu")
    assert refreshed["coverage"]["course_snapshot_complete"] is False
    assert titles(app) == {"old-task"}


def test_calendar_failure_does_not_prevent_safe_activity_cleanup(app, campus):
    app.refresh("mystu")
    campus["activities"]["1"] = []
    campus["calendar_error"] = True
    assert app.refresh("mystu")["status"] == "partial"
    assert titles(app) == set()


def test_legacy_records_are_unverified_until_complete_snapshot_and_overrides_survive(app, campus):
    legacy = {"id": "legacy-task", "kind": "task", "title": "没有学期和课程标识的旧任务"}
    app.store.save_batch("mystu", [legacy], private=True)
    campus["courses"] = [course("1"), course("2")]
    campus["activities"]["2"] = AppError("network_error", "合成失败", "mystu")
    app.refresh("mystu")
    page = app.query("task", source="mystu")
    assert page["unverified_count"] == 1 and titles(app) == {"old-task"}
    assert app.store.get("legacy-task")["title"] == legacy["title"]
    tid = item_id("mystu", "task", "1", "old-task")
    app.store.set_task_status(tid, "done")
    app.refresh("mystu")
    assert app.query("task", source="mystu")["items"][0]["status"] == "done"
    campus["activities"]["2"] = []
    app.refresh("mystu")
    with pytest.raises(AppError, match="尚无此记录"):
        app.store.get("legacy-task")
    campus["activities"]["1"] = []
    app.refresh("mystu")
    with app.store.connect() as conn:
        assert conn.execute("SELECT * FROM task_overrides").fetchall() == []


def test_sync_metadata_is_encrypted_jw_history_is_retained_and_logout_clears_scope(app, campus):
    app.store.save_batch("jw", [{"id": "old-grade", "kind": "grade", "title": "合成旧成绩"}], private=True)
    app.store.save_batch("jw", [{"id": "new-grade", "kind": "grade", "title": "合成新成绩"}], private=True)
    app.store.save_batch("yuketang", [{"id": "other-task", "kind": "task", "title": "其他来源"}], private=True)
    app.refresh("mystu")
    with app.store.connect() as conn:
        payload = bytes(conn.execute("SELECT payload FROM course_scopes").fetchone()[0])
        assert b"course_ids" not in payload
    assert app.query("grade", source="jw")["total_count"] == 2
    assert app.query("task", source="yuketang")["total_count"] == 1
    app.logout("mystu")
    with app.store.connect() as conn:
        assert conn.execute("SELECT * FROM course_scopes").fetchall() == []


def test_course_sync_pruning_is_atomic_if_an_old_record_cannot_be_decrypted(app, campus):
    app.refresh("mystu")
    with app.store.connect() as conn:
        conn.execute("UPDATE records SET payload=? WHERE kind='task'", (b"corrupt-synthetic-payload",))
    campus["courses"] = []
    with pytest.raises(AppError):
        app.refresh("mystu")
    assert app.query("course", source="mystu")["total_count"] == 1
    with app.store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM records WHERE kind='task'").fetchone()[0] == 1


def test_unreadable_scope_does_not_return_unfiltered_old_tasks(app, campus):
    app.refresh("mystu")
    with app.store.connect() as conn:
        conn.execute("UPDATE course_scopes SET payload=?", (b"corrupt-synthetic-scope",))
    page = app.query("task", source="mystu")
    assert page["items"] == []
    assert page["unavailable"][0]["status"] == "session_invalid"


@pytest.mark.parametrize("metadata", [{"attendanceYear": None}, {"attendanceSemester": None}])
def test_unknown_term_is_not_a_complete_inventory(app, campus, metadata):
    app.refresh("mystu")
    campus["courses"] = [{**course("2"), **metadata}]
    campus["activities"]["2"] = []
    result = app.refresh("mystu")
    assert result["coverage"]["inventory_complete"] is False
    assert titles(app) == {"old-task"}


@pytest.mark.parametrize("feed,removes", [
    ({"data": {"activities": []}}, True),
    ({"data": {"activities": [], "has_more": True}}, False),
    ({"data": {"activities": [], "total": 10}}, False),
    ({"data": {}}, False),
    ({"data": {"activities": None}}, False),
    ({"data": {"activities": [{"unknown": 1}]}}, False),
])
def test_yuketang_empty_vs_partial_or_schema_failure(app, session, monkeypatch, feed, removes):
    app.vault.save("yuketang", session)
    state = {"feed": {"data": {"activities": [{"id": 10, "type": 19, "title": "雨课堂合成任务"}]}}}

    class FakeHTTP:
        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def json(self, url):
            if "/courses/list" in url:
                return {"data": {"list": [{"classroom_id": 1, "term": 20261, "name": "合成课"}]}}
            if "/logs/learn/" in url:
                return state["feed"]
            return {"data": {"data": []}}

    monkeypatch.setattr(collectors, "CampusHTTP", FakeHTTP)
    app.refresh("yuketang")
    assert app.query("task", source="yuketang")["items"][0]["semester"] == "20261"
    state["feed"] = feed
    refreshed = app.refresh("yuketang")
    assert refreshed["coverage"]["course_snapshot_complete"] is removes
    assert bool(app.query("task", source="yuketang")["items"]) is not removes


def test_unscoped_upsert_is_never_an_empty_snapshot(app):
    app.store.save_batch("mystu", [{"id": "unscoped-task", "kind": "task", "title": "保留"}], private=True)
    app.store.save_batch("mystu", [], private=True)
    assert app.query("task", source="mystu")["total_count"] == 1
    with pytest.raises(AppError, match="不支持课程范围"):
        app.store.save_batch("jw", [], private=True, sync=CourseSync(course_ids=frozenset()))
    assert "course_ids" not in json.dumps(app.store.freshness())
