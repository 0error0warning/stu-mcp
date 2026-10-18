import gzip

import httpx
import pytest

from stu_mcp.network import CampusHTTP, checked_url, scoped_state
from stu_mcp.runtime import AppError


@pytest.mark.parametrize("url", ["https://evil.example/", "https://www.stu.edu.cn.evil.example/",
                                     "http://www.stu.edu.cn/", "https://user:password@www.stu.edu.cn/",
                                     "https://www.stu.edu.cn:8888/", "file:///etc/passwd",
                                     "https://www.stu.edu.cn/?access_token=synthetic"])
def test_url_policy(url):
    with pytest.raises(AppError):
        checked_url("public", url)


def test_oa_http_only_allows_anonymous_access():
    checked_url("oa", "http://oa.stu.edu.cn/login/Login.jsp")
    with pytest.raises(AppError) as error:
        checked_url("oa", "http://oa.stu.edu.cn/login/Login.jsp", authenticated=True)
    assert error.value.code == "insecure_transport"


def test_redirect_cannot_exfiltrate_session(session):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(handler)) as http, pytest.raises(AppError):
        http.text("https://my.stu.edu.cn/v3/services/api/course/query")
    assert len(sent) == 1
    assert sent[0].url.host == "my.stu.edu.cn"


def test_no_session_is_sent_to_plaintext_redirect(session):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(302, headers={"location": "http://my.stu.edu.cn/page"})
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(handler)) as http, pytest.raises(AppError) as error:
        http.text("https://my.stu.edu.cn/page")
    assert error.value.code == "insecure_transport"
    assert len(sent) == 1


def test_expired_cookie_is_not_transmitted(session):
    session["cookies"][0]["expires"] = 1
    seen = []
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(
            lambda r: (seen.append(r) or httpx.Response(200, text="ok")))) as http:
        assert http.text("https://my.stu.edu.cn/page") == "ok"
    assert "cookie" not in seen[0].headers


def test_state_is_scoped_to_service(session):
    session["cookies"].append({"name": "bad", "value": "synthetic", "domain": "evil.example"})
    session["origins"] = [{"origin": "https://evil.example", "localStorage": []}]
    assert len(scoped_state(session, "mystu")["cookies"]) == 1
    assert scoped_state(session, "mystu")["origins"] == []
    assert scoped_state(session, "jw")["cookies"] == []


def test_response_and_request_budgets():
    with CampusHTTP("public", transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"123456"))) as http:
        with pytest.raises(AppError) as error:
            http.request("https://www.stu.edu.cn/", max_bytes=5)
        assert error.value.code == "response_too_large"
        http.requests = 100
        with pytest.raises(AppError) as error:
            http.text("https://www.stu.edu.cn/")
        assert error.value.code == "request_limit"


def test_compressed_response_is_decoded_once():
    payload = gzip.compress("合成中文网页".encode())
    with CampusHTTP("public", transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=payload, headers={"Content-Encoding": "gzip", "Content-Type": "text/html; charset=utf-8"}))) as http:
        assert http.text("https://www.stu.edu.cn/") == "合成中文网页"


def test_wall_clock_budget():
    with CampusHTTP("public", transport=httpx.MockTransport(lambda _: httpx.Response(200))) as http:
        http.deadline = 0
        with pytest.raises(AppError) as error:
            http.text("https://www.stu.edu.cn/")
        assert error.value.code == "request_deadline"


@pytest.mark.parametrize("status,code", [(401, "login_expired"), (403, "access_denied"),
                                        (429, "rate_limited"), (404, "not_found"),
                                        (503, "source_unavailable"), (400, "source_rejected")])
def test_auth_failure_is_local_and_redacted(status, code, session):
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="SYNTHETIC_SECRET_IN_ERROR_BODY"))) as http:
        with pytest.raises(AppError) as error:
            http.json("https://my.stu.edu.cn/v3/services/api/course/query")
        assert error.value.code == code
        assert error.value.result()["http_status"] == status
        assert "SYNTHETIC_SECRET" not in str(error.value)


@pytest.mark.parametrize("header,expected", [("60", 60), ("999999999", 86400), ("invalid-secret", None),
                                            ("Wed, 21 Oct 2015 07:28:00 GMT", 0)])
def test_rate_limit_reports_bounded_delay_without_retrying(header, expected):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": header})
    with CampusHTTP("yuketang", transport=httpx.MockTransport(handler)) as http, pytest.raises(AppError) as error:
        http.json("https://changjiang.yuketang.cn/v2/api/web/courses/list?identity=2")
    result = error.value.result()
    assert result["next_action"] == "wait_then_retry" and result["retryable"]
    assert result.get("retry_after_seconds") == expected
    assert len(seen) == 1


@pytest.mark.parametrize("error_type,code", [(httpx.ReadTimeout, "request_timeout"),
                                            (httpx.ConnectError, "network_error")])
def test_transport_failures_have_distinct_safe_actions(error_type, code):
    def handler(request):
        raise error_type("SYNTHETIC_SECRET", request=request)
    with CampusHTTP("yuketang", transport=httpx.MockTransport(handler)) as http, pytest.raises(AppError) as error:
        http.text("https://changjiang.yuketang.cn/")
    assert error.value.code == code and error.value.result()["retryable"]
    assert "SYNTHETIC_SECRET" not in str(error.value.result())


@pytest.mark.parametrize("payload,code", [({"errcode": 401000}, "login_expired"),
                                          ({"code": "401000"}, "login_expired"),
                                          ({"success": False}, "source_rejected"),
                                          ({"code": 500}, "source_rejected"),
                                          ({"success": "true"}, "schema_changed")])
def test_yuketang_http_200_business_errors_are_not_empty_courses(session, payload, code):
    payload["message"] = "SYNTHETIC_SECRET"
    with CampusHTTP("yuketang", session, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=payload))) as http, pytest.raises(AppError) as error:
        http.json("https://changjiang.yuketang.cn/v2/api/web/courses/list?identity=2")
    assert error.value.code == code
    assert "SYNTHETIC_SECRET" not in str(error.value.result())


@pytest.mark.parametrize("payload", [{"errcode": 0, "data": {}}, {"code": 0, "data": {}},
                                      {"success": True, "data": {}}])
def test_yuketang_envelope_families(payload):
    with CampusHTTP("yuketang", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as http:
        assert http.json("https://changjiang.yuketang.cn/") == payload


def test_activity_password_does_not_invalidate_mystu_session(session):
    html = '<input type="password" name="quizpassword">'
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=html))) as http, pytest.raises(AppError) as error:
        http.text("https://my.stu.edu.cn/courses/elc/mod/quiz/view.php?id=1")
    assert error.value.code == "activity_password_required"
    assert error.value.result()["next_action"] == "open_source_page"


def test_http_200_immediate_sso_redirect_is_login_failure(session):
    html = "<script>window.location.href='https://sso.stu.edu.cn/login';</script>"
    with CampusHTTP("jw", session, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=html))) as http, pytest.raises(AppError) as error:
        http.text("https://jw.stu.edu.cn/jsxsd/kscj/cjcx_list")
    assert error.value.code == "login_expired"


def test_anonymous_oa_board_may_share_page_with_login_form():
    html = '<input type="password"><a href="/newstemplateprotal.jsp?docid=1">合成公开通知</a>'
    with CampusHTTP("oa", transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html))) as http:
        assert http.text("http://oa.stu.edu.cn/login/Login.jsp?logintype=1") == html
