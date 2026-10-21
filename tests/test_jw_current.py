from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from bs4 import BeautifulSoup

from stu_mcp import auth, collectors
from stu_mcp.network import CampusHTTP
from stu_mcp.parsers import JW_SCHEMA_VERSION, is_login, jw_authenticated, jw_exam_semester, parse_jw
from stu_mcp.runtime import AppError
from stu_mcp.sources import JW_BASE, JW_HOME, JW_LOGIN_URL

FIXTURES = Path(__file__).parent / "fixtures"
HOME = '<html><div id="NEW_XSD_XJCJ_WDCJ_KCCJCX"></div><div id="NEW_XSD_KSBM_WDKS_KSAPCX"></div></html>'
SSO = "<script languge='javascript'>window.location.href='https://sso.stu.edu.cn/login?service=synthetic'</script>"
TERMS = '<select name="xnxqid"><option value="2026-2027-1">合成新学期</option><option value="2025-2026-3" selected>合成选定学期</option></select>'


@pytest.fixture
def jw_session(session):
    state = deepcopy(session)
    state["cookies"][0]["domain"] = "jw.stu.edu.cn"
    return state


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_current_tables_are_mapped_by_headers_and_survive_column_reordering(kind):
    html = (FIXTURES / ("grades-current.html" if kind == "grade" else "exams-current.html")).read_text(encoding="utf-8")
    before = parse_jw(html, kind, "2026-2027-1")
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for cell in cells:
            cell.extract()
        for cell in reversed(cells):
            row.append(cell)
    assert parse_jw(str(soup), kind, "2026-2027-1") == before
    assert before[0]["jw_schema_version"] == JW_SCHEMA_VERSION
    if kind == "grade":
        assert before[0]["credits"] == 2 and before[0]["gpa"] == 4
        assert before[0]["score_marker"] == "正常" and before[0]["hours"] == "32"
        assert before[1]["retake_semester"] == "2026-2027-1"
        assert before[1]["exam_type"] == "补考" and before[1]["group"] == "合成组二"
    else:
        assert before[0]["exam_campus"] == "合成考试校区"
        assert before[0]["location"] == "合成考场 101" and before[0]["seat_number"] == "12"
        assert before[0]["exam_id"] == "SYNTHETIC_EXAM_1"


@pytest.mark.parametrize("kind", ["grade", "exam"])
def test_known_empty_table_is_empty_but_missing_or_short_rows_are_errors(kind):
    soup = BeautifulSoup((FIXTURES / ("grades-current.html" if kind == "grade" else "exams-current.html"))
                         .read_text(encoding="utf-8"), "html.parser")
    rows = soup.select("tr")
    for row in rows[1:]:
        row.decompose()
    assert parse_jw(str(soup), kind) == []
    soup.table.append(BeautifulSoup('<tr><td colspan="16">暂无数据</td></tr>', "html.parser"))
    assert parse_jw(str(soup), kind) == []
    soup.table.append(BeautifulSoup('<tr><td>1</td><td>合成不完整记录</td></tr>', "html.parser"))
    with pytest.raises(AppError) as error:
        parse_jw(str(soup), kind)
    assert error.value.code == "schema_changed"
    with pytest.raises(AppError):
        parse_jw('<table><tr><th>课程名称</th></tr></table>', kind)


def test_current_grade_summary_excludes_old_positional_cache(app, jw_session):
    app.vault.save("jw", jw_session)
    app.store.save_batch("jw", [{"id": "jw:grade:old", "kind": "grade", "title": "合成旧错位缓存",
                                  "score": "90", "credits": 32, "gpa": 64}], private=True)
    assert app.query("grade", source="jw")["unverified_count"] == 1
    assert app.query("grade", source="jw")["items"] == []
    with pytest.raises(AppError) as error:
        app.academic_summary()
    assert error.value.code == "cache_needs_refresh"
    grades = parse_jw((FIXTURES / "grades-current.html").read_text(encoding="utf-8"), "grade")
    app.store.save_batch("jw", grades, private=True)
    summary = app.academic_summary()
    assert summary["course_count"] == 3 and summary["unverified_count"] == 1
    assert summary["weighted_score"]["value"] == 84 and summary["weighted_gpa"]["value"] == 3.4


def test_200_script_redirect_is_expired_and_logout_handler_is_not():
    assert is_login(SSO)
    assert not is_login(HOME + "<script>function logout(){window.location.href='https://sso.stu.edu.cn/login';}</script>")
    assert jw_authenticated(HOME)
    assert not jw_authenticated(SSO)
    with CampusHTTP("jw", {}, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=SSO))) as http, pytest.raises(AppError) as error:
        http.json(JW_BASE + "/synthetic")
    assert error.value.code == "login_expired"


@pytest.mark.parametrize("body,expected", [(HOME, True), (SSO, False)])
def test_login_proof_uses_current_student_home_not_grade_download(monkeypatch, jw_session, body, expected):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=body)
    monkeypatch.setattr(auth, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(handler)))
    assert auth.proof("jw", jw_session, legacy_jw=True) is expected
    assert len(requests) == 1 and requests[0].method == "GET"
    assert str(requests[0].url) == JW_HOME


def test_unsupported_student_home_reports_error_instead_of_waiting_forever(monkeypatch, jw_session):
    monkeypatch.setattr(auth, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, text="<h1>合成未知页面</h1>"))))
    with pytest.raises(AppError) as error:
        auth.proof("jw", jw_session)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("compat", [False, True])
@pytest.mark.usefixtures("synthetic_login_interaction")
def test_manual_login_uses_the_new_entry_and_saves_verified_session(app, jw_session, monkeypatch, compat):
    app.runtime.save_preferences({"jw_http_compat": compat})
    visits = []
    page = SimpleNamespace(url=JW_HOME, goto=lambda url, **_: visits.append(url), wait_for_timeout=lambda _: None,
                           content=lambda: HOME, locator=lambda _: SimpleNamespace(count=lambda: 0), is_closed=lambda: False)
    context = SimpleNamespace(route=lambda *_: None, new_page=lambda: page, storage_state=lambda: jw_session)
    browser = SimpleNamespace(new_context=lambda **_: context, is_connected=lambda: True, close=lambda: None)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **_: browser))
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(playwright))
    monkeypatch.setattr(auth, "prepare_browser", lambda *_: None)
    monkeypatch.setattr(auth, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, text=HOME))))
    assert auth.interactive_login(app.vault, "jw")["status"] == "session_saved"
    if compat:
        assert urlparse(visits[0]).hostname == "sso.stu.edu.cn"
        assert parse_qs(urlparse(visits[0]).query)["service"] == [JW_LOGIN_URL.replace("https:", "http:", 1)]
    else:
        assert visits == [JW_LOGIN_URL]
    assert app.vault.load("jw") == jw_session


def test_school_selected_exam_semester_and_missing_form():
    assert jw_exam_semester(TERMS) == "2025-2026-3"
    with pytest.raises(AppError) as error:
        jw_exam_semester("<h1>合成未知页面</h1>")
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("semester", ["", "2026-2027-1", "2025-2026-3"])
def test_refresh_uses_actual_query_forms_https_and_source_term(app, jw_session, monkeypatch, semester):
    app.vault.save("jw", jw_session)
    app.runtime.save_preferences({"jw_http_compat": True})
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/cjcx_list"):
            return httpx.Response(200, text=(FIXTURES / "grades-current.html").read_text(encoding="utf-8"))
        if request.url.path.endswith("/xsksap_query"):
            return httpx.Response(200, text=TERMS)
        assert request.url.path.endswith("/xsksap_list")
        fields = parse_qs(request.content.decode(), keep_blank_values=True)
        assert fields == {"xnxqid": [semester or "2025-2026-3"], "xqlb": [""], "xqlbmc": [""]}
        return httpx.Response(200, text=(FIXTURES / "exams-current.html").read_text(encoding="utf-8"))
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(handler)))
    result = app.refresh("jw", limit=1, semester=semester)
    assert result["errors"] == [] and result["coverage"]["transport"] == "https"
    assert all(request.url.scheme == "https" for request in requests)
    assert any(request.url.path.endswith("/xsksap_query") for request in requests) is (not semester)
    assert app.query("exam", source="jw")["total_count"] == 1
    expected_grades = 3 if not semester else 2 if semester == "2026-2027-1" else 0
    assert app.query("grade", source="jw")["total_count"] == expected_grades


def test_broken_grade_schema_preserves_previous_verified_cache(app, jw_session, monkeypatch):
    app.vault.save("jw", jw_session)
    grades = parse_jw((FIXTURES / "grades-current.html").read_text(encoding="utf-8"), "grade")
    app.store.save_batch("jw", grades, private=True)
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="<table><tr><th>合成未知字段</th></tr></table>"))))
    with pytest.raises(AppError) as error:
        app.refresh("jw")
    assert error.value.code == "schema_changed"
    assert app.query("grade", source="jw")["total_count"] == 3


def test_exam_form_http_redirect_is_reported_even_when_tables_finish_over_https(app, jw_session, monkeypatch):
    app.vault.save("jw", jw_session)
    app.runtime.save_preferences({"jw_http_compat": True})
    def handler(request):
        if request.url.path.endswith("/cjcx_list"):
            return httpx.Response(200, text=(FIXTURES / "grades-current.html").read_text(encoding="utf-8"))
        if request.url.path.endswith("/xsksap_query"):
            return httpx.Response(302, headers={"location": "http://jw.stu.edu.cn/jsxsd/synthetic-term"})
        if request.url.path.endswith("/synthetic-term"):
            return httpx.Response(200, text=TERMS)
        assert request.url.scheme == "https" and request.url.path.endswith("/xsksap_list")
        return httpx.Response(200, text=(FIXTURES / "exams-current.html").read_text(encoding="utf-8"))
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(handler)))
    result = app.refresh("jw")
    assert result["errors"] == [] and result["coverage"]["transport"] == "school_legacy_http"


def test_expired_exam_page_keeps_grades_and_reports_partial_failure(app, jw_session, monkeypatch):
    app.vault.save("jw", jw_session)
    def handler(request):
        body = (FIXTURES / "grades-current.html").read_text(encoding="utf-8") if "kscj" in request.url.path else SSO
        return httpx.Response(200, text=body)
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(handler)))
    result = app.refresh("jw")
    assert result["status"] == "partial"
    assert result["errors"][0]["status"] == "login_expired"
    assert app.query("grade", source="jw")["total_count"] == 3
