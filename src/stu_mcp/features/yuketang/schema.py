"""Observed Rain Classroom course-query contracts, kept separate from workflows."""

from ...sources import YUKETANG_BASE

COURSES_URL = YUKETANG_BASE + "/v2/api/web/courses/list?identity=2"
ACTIVITIES_URL_TEMPLATE = (
    YUKETANG_BASE + "/v2/api/web/logs/learn/{course_id}?actype=-1&page=0&offset=50&sort=-1"
)
ANNOUNCEMENTS_URL_TEMPLATE = (
    YUKETANG_BASE + "/v/discussion/v2/announcements/?cid={course_id}&limit=20&offset=0&type=9"
)
COURSE_URL_TEMPLATE = YUKETANG_BASE + "/v2/web/studentLog/{course_id}"
EXERCISE_URL_TEMPLATE = (
    YUKETANG_BASE + "/ai-workspace/lms-graph/{course_id}/exercise/{leaf_id}?is_chapter=1"
)

ACTIVITY_LIMIT = 50
ANNOUNCEMENT_LIMIT = 20
TASK_TYPES = frozenset({3, 19})

COURSE_LIST_FIELD = "list"
ACTIVITY_LIST_FIELD = "activities"
ANNOUNCEMENT_LIST_FIELD = "data"

MORE_FIELDS = ("has_more", "hasMore", "has_next", "hasNext", "has_next_page", "next", "nextPage")
TOTAL_FIELDS = ("total", "total_count", "totalCount", "count")
PAGE_COUNT_FIELDS = ("total_pages", "totalPages", "page_count", "pageCount")
