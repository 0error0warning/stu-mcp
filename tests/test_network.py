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


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_local_and_redacted(status, session):
    with CampusHTTP("mystu", session, transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="SYNTHETIC_SECRET_IN_ERROR_BODY"))) as http:
        with pytest.raises(AppError) as error:
            http.json("https://my.stu.edu.cn/v3/services/api/course/query")
        assert error.value.code == "login_expired"
        assert "SYNTHETIC_SECRET" not in str(error.value)
