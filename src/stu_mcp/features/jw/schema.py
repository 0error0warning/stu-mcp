"""Observed academic query endpoints, form fields and table column contracts."""

from ...sources import JW_BASE

JW_SCHEMA_VERSION = 2
JW_GRADE_ROW_LIMIT = 200
JW_GRADE_URL = JW_BASE + "/kscj/cjcx_list"
JW_EXAM_QUERY_URL = JW_BASE + "/xsks/xsksap_query"
JW_EXAM_LIST_URL = JW_BASE + "/xsks/xsksap_list"
JW_GRADE_QUERY_DEFAULTS = {"kcmc": "", "kcxz": "", "kspage": "1", "jspage": "200"}
JW_EXAM_QUERY_DEFAULTS = {"xqlb": "", "xqlbmc": ""}

JW_HOME_MARKERS = ("#NEW_XSD_XJCJ_WDCJ_KCCJCX", "#NEW_XSD_KSBM_WDKS_KSAPCX")
JW_SSO_HOST = "sso.stu.edu.cn"
JW_TERM_SELECTOR = "select[name=xnxqid],select#xnxqid"
JW_TERM_PATTERN = r"20\d{2}-20\d{2}-[123]"

JW_COLUMNS = {
    "grade": {
        "semester": ("开课学期", "学期"), "course_code": ("课程编号", "课程号", "课程代码"),
        "title": ("课程名称", "课程名"), "score": ("成绩", "总评成绩"),
        "score_marker": ("成绩标识",), "credits": ("学分",), "hours": ("总学时", "学时"),
        "gpa": ("绩点",), "retake_semester": ("补重学期",),
        "exam_method": ("考核方式", "考试方式"), "exam_type": ("考试性质", "考试类型"),
        "course_attribute": ("课程属性", "属性"), "course_nature": ("课程性质", "性质"),
        "category": ("通选课类别", "类别"), "group": ("分组名称",),
    },
    "exam": {
        "campus": ("校区",), "exam_campus": ("考试校区",), "exam_session": ("考试场次",),
        "course_code": ("课程编号", "课程号", "课程代码"), "title": ("课程名称", "课程名"),
        "teacher": ("授课教师", "教师"), "exam_time": ("考试时间",),
        "location": ("考场", "考试地点"), "seat_number": ("座位号",),
        "exam_id": ("准考证号", "考试编号"), "notes": ("备注",),
    },
}
JW_REQUIRED_COLUMNS = {
    "grade": frozenset({"semester", "course_code", "title", "score", "credits", "gpa"}),
    "exam": frozenset({"course_code", "title", "exam_time", "location"}),
}
# These apply to a complete, otherwise empty row, never a substring in a course title.
JW_EMPTY_ROW_PATTERN = (
    r"(?:未查询到(?:任何|相关|符合条件的)?(?:记录|数据)?|"
    r"无数据|暂无(?:相关)?(?:记录|数据)|"
    r"没有(?:查询到)?(?:任何|相关|符合条件的)?(?:记录|数据))[!！。.]*"
)
JW_SUMMARY_LABELS = frozenset({"合计", "总计", "平均", "平均成绩", "平均绩点", "总学分"})
JW_SUMMARY_INLINE_PATTERN = (
    r"(?:合计|总计|平均|平均成绩|平均绩点|总学分)[：:][+-]?\d+(?:\.\d+)?(?:门|学分|人|项|分)?"
)
