"""Course budgets and independent activity/announcement failure boundaries."""
from __future__ import annotations

from ...collection import Collection
from ...network import CampusHTTP
from ...parsing import item_id
from ...runtime import AppError
from ...sync import CourseSync
from ...vault import Vault
from .adapter import YuketangAdapter
from .schema import ACTIVITY_LIMIT


def yuketang(vault: Vault, limit: int, *, http_factory=CampusHTTP) -> Collection:
    result = Collection(private=True, limited=True, coverage={
        "scope": "latest_available_term", "courses": limit, "activities_per_course": ACTIVITY_LIMIT,
    })
    with YuketangAdapter(vault, http_factory=http_factory) as adapter:
        # Inventory failure aborts before Store can replace any cached course scope.
        inventory = adapter.inventory()
        result.sync = CourseSync(
            course_ids=frozenset(course.id for course in inventory.courses) if inventory.complete else None,
            semester=inventory.semester,
        )
        result.coverage.update(semester=inventory.semester, inventory_complete=inventory.complete,
                               selected_courses=len(inventory.courses))
        for course in inventory.courses[:limit]:
            result.items.append({
                "id": item_id("yuketang", "course", course.id), "kind": "course", "title": course.title,
                "url": course.url, "term": course.term, "semester": inventory.semester,
                "course_id": course.id, "teacher": course.teacher,
            })
            try:
                activities = adapter.activities(course, inventory.semester)
                result.items.extend(activities.items)
                if activities.complete:
                    result.sync.complete_courses.add(course.id)
            except AppError as exc:
                result.fail("课程活动", exc, stage="course_activities", course_id=course.id)
            # Announcements are independent of both activity transport and decoding.
            try:
                result.items.extend(adapter.announcements(course))
            except AppError as exc:
                result.fail("课程公告", exc, stage="course_announcements", course_id=course.id)
    result.coverage.update(complete_activity_courses=len(result.sync.complete_courses),
                           course_snapshot_complete=result.sync.complete)
    return result
