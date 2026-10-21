"""On-demand campus adapters. No schedulers, model calls, or production dependencies."""
from __future__ import annotations

from datetime import datetime

from .collection import Article as Article
from .collection import Collection as Collection
from .features.jw.service import jw as collect_jw
from .features.mystu.service import mystu as collect_mystu
from .features.notices import service as notices
from .network import CampusHTTP
from .pagination import complete_list as complete_list
from .parsing import CST, clean, item_id, stamp, text_body
from .runtime import AppError
from .sources import (
    YUKETANG_BASE,
)
from .sync import CourseSync
from .vault import Vault
from .webvpn import protected_access


def public(limit: int) -> Collection:
    return notices.public(limit, http_factory=CampusHTTP)


def oa(vault: Vault, limit: int) -> Collection:
    return notices.oa(vault, limit, http_factory=CampusHTTP, protected_reader=protected_access)


def jw(vault: Vault, limit: int, semester: str) -> Collection:
    return collect_jw(vault, limit, semester, http_factory=CampusHTTP)


def default_semester() -> str:
    today = datetime.now(CST)
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-{year + 1}-{'1' if today.month >= 8 or today.month == 1 else '2'}"


def mystu(vault: Vault, limit: int) -> Collection:
    return collect_mystu(vault, limit, http_factory=CampusHTTP)


def yuketang(vault: Vault, limit: int) -> Collection:
    result = Collection(private=True, limited=True, coverage={"scope": "latest_available_term",
                                                             "courses": limit, "activities_per_course": 50})
    with CampusHTTP("yuketang", vault.load("yuketang")) as http:
        payload = http.json(YUKETANG_BASE + "/v2/api/web/courses/list?identity=2")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise AppError("schema_changed", "雨课堂未返回课程列表。", "yuketang")
        courses = data["list"]
        if any(not isinstance(c, dict) or not str(c.get("classroom_id") or "").isdigit() for c in courses):
            raise AppError("schema_changed", "雨课堂课程缺少可识别的记录。", "yuketang")
        terms = [c.get("term") for c in courses if isinstance(c.get("term"), int)]
        inventory_complete = complete_list(data, len(courses)) and complete_list(payload, len(courses))
        inventory_complete &= len(terms) == len(courses)
        semester = str(max(terms)) if terms else None
        if terms:
            latest = max(terms)
            courses = [c for c in courses if c.get("term") == latest]
        result.sync = CourseSync(
            course_ids=frozenset(str(c["classroom_id"]) for c in courses) if inventory_complete else None,
            semester=semester)
        result.coverage.update(semester=semester, inventory_complete=inventory_complete,
                               selected_courses=len(courses))
        for c in courses[:limit]:
            cid = str(c.get("classroom_id") or "")
            if not cid.isdigit():
                continue
            name = clean((c.get("course") or {}).get("name") or c.get("name"))
            course_url = YUKETANG_BASE + f"/v2/web/studentLog/{cid}"
            result.items.append({"id": item_id("yuketang", "course", cid), "kind": "course", "title": name,
                                 "url": course_url, "term": c.get("term"), "semester": semester, "course_id": cid,
                                 "teacher": clean((c.get("teacher") or {}).get("name"))})
            try:
                feed = http.json(YUKETANG_BASE + f"/v2/api/web/logs/learn/{cid}?actype=-1&page=0&offset=50&sort=-1")
                feed_data = feed.get("data")
                if not isinstance(feed_data, dict) or not isinstance(feed_data.get("activities"), list):
                    raise AppError("schema_changed", "雨课堂未返回可识别的课程活动列表。", "yuketang")
                activities = feed_data["activities"]
                activity_complete = complete_list(feed_data, len(activities), 50) and complete_list(
                    feed, len(activities))
                for activity in activities[:50]:
                    if not isinstance(activity, dict):
                        raise AppError("schema_changed", "雨课堂活动记录结构发生变化。", "yuketang")
                    title = clean(activity.get("title"))
                    if not title:
                        raise AppError("schema_changed", "雨课堂活动缺少标题，未把解析失败当作空列表。", "yuketang")
                    content = activity.get("content") or {}
                    if not isinstance(content, dict):
                        raise AppError("schema_changed", "雨课堂活动内容字段发生变化。", "yuketang")
                    kind = "task" if activity.get("type") in (19, 3) else "resource"
                    leaf = str(content.get("leaf_id") or "")
                    url = YUKETANG_BASE + f"/ai-workspace/lms-graph/{cid}/exercise/{leaf}?is_chapter=1" if leaf.isdigit() else course_url
                    result.items.append({"id": item_id("yuketang", kind, cid, activity.get("id") or title),
                                         "kind": kind, "title": title, "course": name, "url": url,
                                         "course_id": cid, "semester": semester, "term": c.get("term"),
                                         "activity_type": activity.get("type"), "leaf_id": leaf or None,
                                         "due_at": stamp(content.get("score_d")), "status": "todo",
                                         "published_at": stamp(activity.get("create_time"))})
                if activity_complete:
                    result.sync.complete_courses.add(cid)
            except AppError as exc:
                result.fail("课程活动", exc, stage="course_activities", course_id=cid)
            # An activity failure must not suppress this course's independent announcements.
            try:
                announcement = http.json(YUKETANG_BASE +
                                         f"/v/discussion/v2/announcements/?cid={cid}&limit=20&offset=0&type=9")
                ann_data = announcement.get("data")
                if not isinstance(ann_data, dict) or not isinstance(ann_data.get("data"), list):
                    raise AppError("schema_changed", "雨课堂未返回可识别的课程公告列表。", "yuketang")
                for ann in ann_data["data"][:20]:
                    if not isinstance(ann, dict):
                        raise AppError("schema_changed", "雨课堂公告记录结构发生变化。", "yuketang")
                    body = text_body(str(ann.get("content") or ""), 10000)
                    result.items.append({"id": item_id("yuketang", "notice", cid, ann.get("id")),
                                         "kind": "notice", "title": clean(ann.get("title") or body)[:200],
                                         "course": name, "body": body, "url": course_url,
                                         "published_at": stamp(ann.get("publish_time") or ann.get("create_time"))})
            except AppError as exc:
                result.fail("课程公告", exc, stage="course_announcements", course_id=cid)
    result.coverage.update(complete_activity_courses=len(result.sync.complete_courses),
                           course_snapshot_complete=result.sync.complete)
    return result


def article(record: dict, vault: Vault) -> Article:
    return notices.article(record, vault, http_factory=CampusHTTP, protected_reader=protected_access)
