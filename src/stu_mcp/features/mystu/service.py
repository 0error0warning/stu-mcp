"""MySTU collection policy, independent of school API fields and HTML selectors."""
from __future__ import annotations

from ...collection import Collection
from ...network import CampusHTTP
from ...parsing import item_id
from ...runtime import AppError
from ...sync import CourseSync
from ...vault import Vault
from .adapter import MystuAdapter
from .schema import ACTIVITY_LIMIT, DETAIL_LIMIT


def mystu(vault: Vault, limit: int, *, http_factory=CampusHTTP) -> Collection:
    result = Collection(private=True, coverage={"scope": "latest_term", "max_courses": limit,
                                                "activities_per_course": ACTIVITY_LIMIT,
                                                "detail_limit": DETAIL_LIMIT})
    detail_count = 0
    with MystuAdapter(vault, http_factory=http_factory) as adapter:
        inventory = adapter.inventory()
        semester, selected = inventory.semester, inventory.courses
        result.sync = CourseSync(
            course_ids=frozenset(course.id for course in selected) if inventory.complete else None,
            semester=semester)
        result.coverage.update(semester=semester, inventory_complete=inventory.complete,
                               selected_courses=len(selected))
        result.limited = len(selected) > limit or not inventory.complete
        for course in selected[:limit]:
            cid, name = course.id, course.title
            try:
                adapter.check_url(course.url)
                provenance = {"course_id": cid, "semester": semester, "year": course.year, "term": course.term}
                result.items.append({"id": item_id("mystu", "course", cid), "kind": "course", "title": name,
                                     "url": course.url or None, **provenance, "teacher": course.teacher})
                activities = adapter.activities(course)
                if activities is None:
                    result.limited = True
                    continue
                result.limited |= not activities.complete
                for activity in activities.items:
                    link, kind = activity.url, activity.kind
                    detail = {}
                    aid = item_id("mystu", kind, cid, link or activity.title)
                    detail_state = {"detail_status": "not_read"} if kind == "task" else {}
                    adapter.check_url(link)
                    if kind == "task" and link and detail_count < DETAIL_LIMIT:
                        detail_count += 1
                        try:
                            detail = adapter.assignment(link)
                            detail_state = {"detail_status": "read"}
                        except AppError as exc:
                            if exc.code in {"login_expired", "needs_login", "needs_elc_login"}:
                                exc = AppError("resource_login_required",
                                               "此活动返回登录页；不能据此判断整个 MySTU 会话失效，请先核对该活动原页面。",
                                               "mystu", http_status=exc.http_status)
                            detail_state = {"detail_status": "unavailable", "detail_error": exc.result()}
                            result.fail("作业详情", exc, stage="task_detail", course_id=cid, item_id=aid)
                    elif kind == "task" and link:
                        result.limited = True
                        detail_state = {"detail_status": "limit_reached"}
                    due = detail.get("due_at") or activity.due_at
                    if kind == "task":
                        detail_state["due_at_status"] = ("available" if due else "not_found_in_detail"
                                                         if detail_state["detail_status"] == "read"
                                                         else "detail_" + detail_state["detail_status"])
                    result.items.append({"id": aid, "kind": kind, **detail_state, "title": activity.title,
                                         "course": name, **provenance, "url": link or None,
                                         "category": activity.category, "due_at": due,
                                         "school_status": detail.get("school_status"), "status": "todo",
                                         "body": detail.get("description") or activity.description})
                if activities.complete:
                    result.sync.complete_courses.add(cid)
            except AppError as exc:
                result.fail("课程活动", exc, stage="course_activities", course_id=cid)
        try:
            events, limited = adapter.schedule()
            result.limited |= limited
            result.items.extend(events)
        except AppError as exc:
            result.fail("个人日程", exc, stage="schedule")
    result.coverage.update(complete_activity_courses=len(result.sync.complete_courses),
                           course_snapshot_complete=result.sync.complete)
    return result
