import pytest

from stu_mcp import collectors
from stu_mcp.parsers import (
    current_courses,
    parse_assignment,
    parse_elc,
    parse_jw,
    parse_oa,
    parse_public,
    payload_records,
)
from stu_mcp.runtime import AppError


def test_public_feature_does_not_touch_keyring(app, monkeypatch):
    class UnavailableKeys:
        def get_password(self, *_):
            raise AssertionError("public access must not read a keyring")
    app.vault._store = UnavailableKeys()
    monkeypatch.setattr(collectors, "public", lambda _: collectors.Collection(
        [{"id": "public:notice:demo", "kind": "notice", "title": "公开合成通知"}]))
    assert app.refresh("public")["saved"] == 1
    assert app.query("notice", source="public")["items"][0]["title"] == "公开合成通知"
    with pytest.raises(AppError) as error:
        app.refresh("jw")
    assert error.value.code == "needs_login"
    assert app.query("notice", source="public")["total_count"] == 1


def test_anonymous_oa_does_not_require_vault(app, monkeypatch):
    html = '<table><tr><td><a href="/newstemplateprotal.jsp?docid=DEMO1">合成 OA 通知</a></td><td>合成学院</td><td>2026-10-05</td></tr></table>'
    class AnonymousHTTP:
        def __init__(self, source):
            self.client = self
        def text(self, url):
            return html
        def close(self):
            pass
    monkeypatch.setattr(collectors, "CampusHTTP", AnonymousHTTP)
    monkeypatch.setattr(app.vault, "load", lambda _: pytest.fail("anonymous OA must not load authentication"))
    result = app.refresh("oa")
    assert result["saved"] == 1
    assert result["coverage"]["access"] == "anonymous_http"
    assert app.query("notice", source="oa")["items"][0]["department"] == "合成学院"


def test_grade_parser_and_weighted_summary(app, grades_html):
    grades = parse_jw(grades_html, "grade")
    assert len(grades) == 3
    assert grades[0]["score"] == "90"
    assert grades[2]["gpa"] is None
    app.store.save_batch("jw", grades, private=True)
    result = app.academic_summary()
    assert result["weighted_score"]["value"] == 84
    assert result["weighted_gpa"]["value"] == 3.4
    assert result["weighted_score"]["included_count"] == 2


def test_summary_reads_every_page(app):
    grades = [{"id": f"jw:grade:{i}", "kind": "grade", "title": str(i), "score": i, "credits": 1,
               "gpa": 2, "semester": "2026-2027-1"} for i in range(125)]
    app.store.save_batch("jw", grades, private=True)
    assert app.academic_summary()["weighted_score"]["value"] == 62
    assert app.academic_summary()["course_count"] == 125


@pytest.mark.parametrize("html,code", [('<input type="password">', "login_expired"),
                                        ("<h1>学校错误页面</h1>", "schema_changed"),
                                        ("<table><tr><td>不认识的结构</td></tr></table>", "schema_changed")])
def test_parser_does_not_misreport_failure_as_empty(html, code):
    with pytest.raises(AppError) as error:
        parse_jw(html, "grade")
    assert error.value.code == code


def test_mystu_terms_and_array_records():
    records = payload_records({"fields": "id,name,attendanceYear,attendanceSemester", "items": [
        [1, "旧合成课", 2025, 2], [2, "新合成课", 2026, 1]]})
    assert current_courses(records)[0]["name"] == "新合成课"


def test_elc_assignments_and_dates():
    html = '<div class="course-content"><li class="activity modtype_assign"><div class="activityinstance"><a href="/courses/elc/mod/assign/view.php?id=100"><span class="instancename">合成作业</span></a></div></li></div>'
    activities = parse_elc(html, "https://my.stu.edu.cn/courses/elc/course/view.php?id=1")
    assert activities[0]["activityCategory"] == "assignment"
    detail = parse_assignment('<div id="intro">合成说明</div><table><tr><td>截止时间</td><td>2026年10月10日 星期六 23:59</td></tr><tr><td>提交状态</td><td>未提交</td></tr></table>')
    assert detail["due_at"] == "2026-10-10T23:59:00+08:00"
    assert detail["school_status"] == "未提交"


def test_unknown_oa_page_is_not_empty():
    with pytest.raises(AppError):
        parse_oa("<h1>网络错误</h1>", "http://oa.stu.edu.cn", 20)


def test_student_affairs_news_url():
    records = parse_public('<li><a href="News.aspx?ID=123">合成学生通知</a>2026-10-05</li>',
                           "https://xsc.stu.edu.cn/NoticeList.aspx?NewsTypeID=3", "学生通知", 5)
    assert records[0]["url"] == "https://xsc.stu.edu.cn/News.aspx?ID=123"


def test_local_task_status_does_not_claim_school_submission(app):
    app.store.save_batch("mystu", [{"id": "mystu:task:demo", "kind": "task", "title": "合成任务",
                                   "school_status": "未提交"}], private=True)
    app.store.set_task_status("mystu:task:demo", "done")
    item = app.query("task", source="mystu")["items"][0]
    assert item["status"] == "done"
    assert item["school_status"] == "未提交"


def test_refresh_failure_preserves_cache_and_has_safe_status(app, monkeypatch):
    app.store.save_batch("public", [{"id": "public:notice:old", "kind": "notice", "title": "旧合成通知"}])
    def broken(_):
        raise ValueError("SYNTHETIC_TOKEN_MUST_NOT_LEAK")
    monkeypatch.setattr(collectors, "public", broken)
    with pytest.raises(AppError) as error:
        app.refresh("public")
    assert error.value.code == "source_error"
    assert "SYNTHETIC_TOKEN" not in str(error.value)
    assert app.query("notice", source="public")["total_count"] == 1
    assert app.store.freshness()[0]["status"] == "source_error"


@pytest.mark.parametrize("source,private", [("public", False), ("oa", False), ("oa", True)])
def test_notice_listing_preserves_detail_search_and_its_original_freshness(app, session, monkeypatch, source, private):
    tick = ["2026-10-06T00:00:00+00:00"]
    monkeypatch.setattr("stu_mcp.store.now", lambda: tick[0])
    if private:
        app.vault.save("webvpn", session)
    version = app.vault.fingerprint("webvpn") if private else None
    listing = {"id": f"{source}:notice:synthetic", "kind": "notice", "title": "合成通知",
               "url": ("https://oa-stu-edu-cn.webvpn.stu.edu.cn/synthetic" if private else
                       "http://oa.stu.edu.cn/synthetic" if source == "oa" else "https://www.stu.edu.cn/info/1/2.htm")}
    monkeypatch.setattr(collectors, source, lambda *_: collectors.Collection(
        [listing.copy()], private=private, session_version=version))
    detail = {"body": "SYNTHETIC_ELIGIBILITY", "attachments": [{"name": "合成附件", "url": "/synthetic.pdf"}]}
    monkeypatch.setattr(collectors, "article", lambda *_: collectors.Article(detail.copy(), version))
    app.refresh(source)
    fetched = app.notice(listing["id"], refresh=True)["item"]
    assert fetched["detail_collected_at"] == tick[0]
    tick[0] = "2026-10-06T01:00:00+00:00"
    listing["title"] = "更新的合成通知标题"
    app.refresh(source)
    cached = app.notice(listing["id"])["item"]
    assert cached["title"] == listing["title"]
    assert cached["body"] == detail["body"] and cached["attachments"] == detail["attachments"]
    assert cached["collected_at"] == tick[0]
    assert cached["detail_collected_at"] == fetched["detail_collected_at"]
    assert app.query("notice", query="SYNTHETIC_ELIGIBILITY", source=source)["total_count"] == 1

    detail.update(body="", attachments=[])
    cleared = app.notice(listing["id"], refresh=True)["item"]
    assert cleared["body"] == "" and cleared["attachments"] == []
    assert cleared["detail_collected_at"] == tick[0]
    assert app.query("notice", query="SYNTHETIC_ELIGIBILITY", source=source)["total_count"] == 0


@pytest.mark.parametrize("old_private,new_private,same_url", [(True, False, True), (False, True, True),
                                                            (False, False, False)])
def test_notice_details_do_not_cross_access_or_url_boundaries(app, old_private, new_private, same_url):
    listing = {"id": "oa:notice:synthetic", "kind": "notice", "title": "合成通知",
               "url": "https://oa-stu-edu-cn.webvpn.stu.edu.cn/synthetic"}
    app.store.save_batch("oa", [{**listing, "body": "SYNTHETIC_PROTECTED_DETAIL", "attachments": []}], private=old_private)
    if not same_url:
        listing["url"] = "http://oa.stu.edu.cn/synthetic"
    app.store.save_batch("oa", [listing], private=new_private)
    cached = app.store.get(listing["id"])
    assert not {"body", "attachments", "detail_collected_at"}.intersection(cached)
