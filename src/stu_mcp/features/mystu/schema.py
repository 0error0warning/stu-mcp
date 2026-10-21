"""Observed MySTU API and ELC page contracts; changes belong at this boundary."""

from ...sources import MYSTU_API

VALIDATE_URL = MYSTU_API + "/user/validate?ver=1.1"
COURSES_URL = MYSTU_API + "/course/query"
ACTIVITIES_URL = MYSTU_API + "/courseactivity/query"
SCHEDULE_URL = MYSTU_API + "/userschedule/query"

ITEMS_FIELD = "items"
ARRAY_FIELDS_FIELD = "fields"
COURSE_FIELDS = {
    "id": "id", "url": "url", "title": ("name", "groupName"),
    "year": "attendanceYear", "term": "attendanceSemester", "teacher": "teacher",
}
ACTIVITY_LIST_FIELD = "courseActivities"
ACTIVITY_FIELDS = {
    "title": "activityTitle", "url": "activityUrl", "category": "activityCategory",
    "due_at": "additionalDueDate", "description": "description",
}
SCHEDULE_FIELDS = {
    "id": "id", "title": ("title", "name"), "start_at": "startTime", "end_at": "endTime",
    "location": "location",
}
TASK_CATEGORIES = frozenset({"assignment", "assign", "quiz"})
ACTIVITY_LIMIT = 50
DETAIL_LIMIT = 20
EVENT_LIMIT = 50
ACTIVITY_QUERY_DEFAULTS = {"category": "undefined", "lang": "zh-CN"}

ELC_COURSE_PATH = "/courses/elc/"
COURSE_CONTENT_SELECTOR = ".course-content"
ACTIVITY_SELECTOR = ".course-content li.activity, .course-content .activity[class*='modtype_']"
ACTIVITY_LINK_SELECTOR = ".activityinstance a[href], a[href]"
ACTIVITY_TITLE_SELECTOR = ".instancename"
DESCRIPTION_SELECTOR = "#intro, .activity-description"
ASSIGNMENT_PAGE_SELECTOR = (
    "#page-mod-assign-view, #page-mod-quiz-view, .path-mod-assign, .path-mod-quiz, "
    "#intro, .activity-description, .submissionstatustable, .quizinfo"
)
DETAIL_LABELS = {
    "due_at": r"^(?:due date|截止(?:日期|时间)?|到期(?:日期|时间)?|closes|关闭(?:日期|时间)?)[：:]?$",
    "school_status": r"^(?:submission status|提交状态|completion status|完成状态)[：:]?$",
}
