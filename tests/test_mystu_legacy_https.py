"""School's legacy ELC URL is upgraded without weakening transport policy."""
import pytest

from stu_mcp.features.mystu.parser import parse_elc, parse_inventory
from stu_mcp.network import checked_url
from stu_mcp.runtime import AppError


def inventory(url):
    return parse_inventory({"items": [{"id": "synthetic-course", "name": "合成课程",
        "attendanceYear": 2026, "attendanceSemester": 1, "url": url}]})


@pytest.mark.parametrize("origin", ["http://my.stu.edu.cn", "http://my.stu.edu.cn:80"])
def test_legacy_elc_url_remains_same_course_on_verified_https(origin):
    course = inventory(origin + "/courses/elc/course/view.php?id=123").courses[0]
    assert course.id == "synthetic-course"
    assert course.url == "https://my.stu.edu.cn/courses/elc/course/view.php?id=123"
    assert checked_url("mystu", course.url) == course.url


@pytest.mark.parametrize("url", [
    "http://my.stu.edu.cn/courses/campus/course/view.php?id=1",
    "http://my.stu.edu.cn.evil.test/courses/elc/course/view.php?id=1",
    "http://my.stu.edu.cn:8118/courses/elc/course/view.php?id=1",
    "http://user:password@my.stu.edu.cn/courses/elc/course/view.php?id=1",
    "http://my.stu.edu.cn/courses/elc/course/view.php?id=1&id=2",
    "http://my.stu.edu.cn/courses/elc/course/view.php?id=1&ticket=synthetic",
    "http://my.stu.edu.cn/courses/elc/course/view.php?id=1#fragment",
])
def test_other_http_routes_are_not_silently_authorized(url):
    course = inventory(url).courses[0]
    assert course.url == url
    with pytest.raises(AppError):
        checked_url("mystu", course.url)


def test_inline_moodle_labels_do_not_become_missing_or_duplicate_activities():
    url = "/courses/elc/mod/resource/view.php?id=10"
    page = ('<div class="course-content"><li class="activity modtype_resource">'
            f'<a href="{url}"><span class="instancename">合成资料</span></a></li>'
            '<li class="activity modtype_label"><p>课程说明</p></li>'
            f'<li class="activity modtype_label"><a href="{url}">说明中引用</a></li></div>')
    rows = parse_elc(page, "https://my.stu.edu.cn/courses/elc/course/view.php?id=1")
    assert len(rows) == 1 and rows[0]["activityTitle"] == "合成资料"


def test_non_label_with_missing_activity_link_still_fails():
    with pytest.raises(AppError, match="缺少链接"):
        parse_elc('<div class="course-content"><li class="activity modtype_quiz">changed</li></div>',
                  "https://my.stu.edu.cn/")
