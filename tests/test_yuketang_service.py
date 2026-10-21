"""Synthetic JSON, transport failures and encrypted cache checks; no school access."""
from copy import deepcopy
from urllib.parse import parse_qs, urlparse

import pytest

from stu_mcp import collectors
from stu_mcp.features.yuketang.schema import (
    ACTIVITIES_URL_TEMPLATE,
    ANNOUNCEMENTS_URL_TEMPLATE,
    COURSES_URL,
)
from stu_mcp.features.yuketang.service import yuketang
from stu_mcp.parsing import item_id
from stu_mcp.runtime import AppError


def course(cid=1, term=20261):
    return {"classroom_id": cid, "name": f"合成课程 {cid}", "term": term}


def activity(aid=10, **values):
    return {"id": aid, "type": 19, "title": f"合成任务 {aid}", **values}


def announcement(aid=20, **values):
    return {"id": aid, "title": f"合成公告 {aid}", "content": "<p>合成正文</p>", **values}


@pytest.fixture
def school(app, session, monkeypatch):
    saved = deepcopy(session)
    saved["cookies"][0]["domain"] = "changjiang.yuketang.cn"
    app.vault.save("yuketang", saved)
    state = {
        "inventory": {"data": {"list": [course()]}},
        "activities": {"1": {"data": {"activities": [activity()]}}},
        "announcements": {"1": {"data": {"data": [announcement()]}}},
        "requests": [], "contexts": [],
    }

    class SyntheticHTTP:
        def __init__(self, source, saved_session):
            assert source == "yuketang" and saved_session == saved
            state["contexts"].append("open")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            state["contexts"].append("close")

        def json(self, url):
            state["requests"].append(url)
            if url == COURSES_URL:
                response = state["inventory"]
            elif "/logs/learn/" in url:
                cid = urlparse(url).path.rsplit("/", 1)[-1]
                assert url == ACTIVITIES_URL_TEMPLATE.format(course_id=cid)
                response = state["activities"][cid]
            else:
                cid = parse_qs(urlparse(url).query)["cid"][0]
                assert url == ANNOUNCEMENTS_URL_TEMPLATE.format(course_id=cid)
                response = state["announcements"][cid]
            if isinstance(response, Exception):
                raise response
            return deepcopy(response)

    state["factory"] = SyntheticHTTP
    monkeypatch.setattr(collectors, "CampusHTTP", SyntheticHTTP)
    return state


def cached(app, kind):
    return {row["id"] for row in app.store.list(sources=("yuketang",), kind=kind, _all_items=True)["items"]}


@pytest.mark.parametrize("bad_feed", [
    {"data": {}}, {"data": {"activities": None}},
    {"data": {"activities": [activity(content={"token": "SYNTHETIC_SECRET"}), activity(11, title={})]}},
    {"data": {"activities": [activity(content="SYNTHETIC_SECRET")]}},
    {"data": {"activities": [activity(), activity()]}},
    AppError("network_error", "合成网络失败", "yuketang"),
    AppError("access_denied", "合成权限失败", "yuketang", http_status=403),
    AppError("login_expired", "合成会话过期", "yuketang"),
])
def test_activity_failure_keeps_old_tasks_and_still_saves_announcements(app, school, bad_feed):
    app.refresh("yuketang")
    old_tasks = cached(app, "task")
    old_task_records = {tid: app.store.get(tid) for tid in old_tasks}
    school["activities"]["1"] = bad_feed
    school["announcements"]["1"] = {"data": {"data": [announcement(21)]}}
    school["requests"].clear()
    result = app.refresh("yuketang")
    assert len(school["requests"]) == 3
    assert cached(app, "task") == old_tasks
    assert {tid: app.store.get(tid) for tid in old_tasks} == old_task_records
    assert cached(app, "notice") == {item_id("yuketang", "notice", "1", 20),
                                     item_id("yuketang", "notice", "1", 21)}
    assert result["coverage"]["complete_activity_courses"] == 0
    assert result["coverage"]["course_snapshot_complete"] is False
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "course_activities"
    assert result["errors"][0]["course_id"] == "1"
    assert "SYNTHETIC_SECRET" not in str(result)


@pytest.mark.parametrize("bad_announcements", [
    {"data": {}}, {"data": {"data": None}},
    {"data": {"data": [announcement(21), {"title": "无标识"}]}},
    {"data": {"data": [announcement(content={"token": "SYNTHETIC_SECRET"})]}},
    {"data": {"data": [announcement(), announcement()]}},
    AppError("network_error", "合成网络失败", "yuketang"),
    AppError("access_denied", "合成权限失败", "yuketang", http_status=403),
])
def test_announcement_failure_does_not_block_complete_activity_cleanup(app, school, bad_announcements):
    app.refresh("yuketang")
    old_notices = cached(app, "notice")
    old_notice_records = {nid: app.store.get(nid) for nid in old_notices}
    school["activities"]["1"] = {"data": {"activities": []}}
    school["announcements"]["1"] = bad_announcements
    result = app.refresh("yuketang")
    assert not cached(app, "task")
    assert cached(app, "notice") == old_notices
    assert {nid: app.store.get(nid) for nid in old_notices} == old_notice_records
    assert result["coverage"]["course_snapshot_complete"] is True
    assert result["limited"] is True and result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "course_announcements"
    assert "SYNTHETIC_SECRET" not in str(result)


def test_two_branch_failures_do_not_block_the_next_course(app, school):
    school["inventory"]["data"]["list"].append(course(2))
    school["activities"]["1"] = {"data": {}}
    school["announcements"]["1"] = AppError("source_rejected", "合成拒绝", "yuketang")
    school["activities"]["2"] = {"data": {"activities": [activity(12)]}}
    school["announcements"]["2"] = {"data": {"data": [announcement(22)]}}
    result = app.refresh("yuketang")
    assert len(school["requests"]) == 5
    assert school["contexts"] == ["open", "close"]
    assert len(result["errors"]) == 2
    assert result["coverage"]["complete_activity_courses"] == 1
    assert item_id("yuketang", "task", "2", 12) in cached(app, "task")
    assert item_id("yuketang", "notice", "2", 22) in cached(app, "notice")


@pytest.mark.parametrize("inventory", [
    {"data": {}}, {"data": {"list": None}},
    {"data": {"list": [course(), course()]}},
    {"data": {"list": [course() | {"course": "SYNTHETIC_SECRET"}]}},
    {"data": {"list": [course() | {"teacher": []}]}},
    {"data": {"list": [course(True)]}},
])
def test_inventory_drift_aborts_without_replacing_cached_records(app, school, inventory):
    app.refresh("yuketang")
    before = {kind: cached(app, kind) for kind in ("course", "task", "notice")}
    school["inventory"] = inventory
    school["requests"].clear()
    with pytest.raises(AppError) as exc:
        app.refresh("yuketang")
    assert exc.value.code == "schema_changed"
    assert "SYNTHETIC_SECRET" not in str(exc.value.result())
    assert school["requests"] == [COURSES_URL]
    assert {kind: cached(app, kind) for kind in before} == before
    assert school["contexts"] == ["open", "close", "open", "close"]


@pytest.mark.parametrize("metadata", [
    {"has_more": True}, {"has_more": "false"}, {"total": 10},
    {"pagination": {"total_pages": 2}}, {"pagination": []},
])
@pytest.mark.parametrize("level", ["envelope", "data"])
def test_incomplete_activity_metadata_preserves_unseen_tasks(app, school, metadata, level):
    app.refresh("yuketang")
    school["activities"]["1"] = {"data": {"activities": []}}
    target = school["activities"]["1"]
    (target if level == "envelope" else target["data"]).update(metadata)
    result = app.refresh("yuketang")
    assert result["coverage"]["course_snapshot_complete"] is False
    assert cached(app, "task") == {item_id("yuketang", "task", "1", 10)}


def test_limited_courses_and_full_activity_page_do_not_clear_unread_tasks(app, school):
    school["inventory"]["data"]["list"].append(course(2))
    school["activities"]["2"] = {"data": {"activities": [activity(12)]}}
    school["announcements"]["2"] = {"data": {"data": []}}
    app.refresh("yuketang")
    school["requests"].clear()
    school["activities"]["1"] = {"data": {"activities": [activity(i) for i in range(100, 150)]}}
    result = app.refresh("yuketang", limit=1)
    assert len(school["requests"]) == 3
    assert result["coverage"]["selected_courses"] == 2
    assert result["coverage"]["course_snapshot_complete"] is False
    assert {item_id("yuketang", "task", "1", 10), item_id("yuketang", "task", "2", 12)} <= cached(app, "task")


def test_direct_service_and_compatible_entry_match_without_extra_requests(app, school):
    direct = yuketang(app.vault, 5, http_factory=school["factory"])
    via_old_entry = collectors.yuketang(app.vault, 5)
    assert direct == via_old_entry
    assert len(school["requests"]) == 6
    assert school["contexts"] == ["open", "close", "open", "close"]
