"""Synthetic first-login and persistence checks; never contact school endpoints."""
import gzip
import logging
from urllib.parse import parse_qs

import httpx
import pytest

from stu_mcp.auth_http import Candidate, Credentials, login_http
from stu_mcp.auth_http.cas import (
    ELC_SERVICE,
    SERVICES,
    SSO,
    acquire_state,
    parse_form,
    validate_identity,
)
from stu_mcp.auth_http.transport import HTTPFlow
from stu_mcp.runtime import AppError

USERNAME, PASSWORD = "synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD"
FORM = ('<form method="post"><input name="username"><input name="password" type="password">'
        '<input name="lt" type="hidden" value="synthetic-lt">'
        '<input name="execution" type="hidden" value="synthetic-execution">'
        '<input name="_eventId" type="hidden" value="submit"></form>')


def response(request, status=200, *, content=b"", headers=None, json=None):
    return httpx.Response(status, content=content if json is None else None, headers=headers, json=json, request=request)


def mystu_transport(*, fail_post=False, identity=None, challenge=False, unsafe_callback=False, logout=None):
    calls, authenticated = [], False

    def handler(request):
        nonlocal authenticated
        calls.append(request)
        host, path = request.url.host, request.url.path
        query = dict(request.url.params)
        if host == "sso.stu.edu.cn":
            assert "school_session=" not in request.headers.get("cookie", "")
            if request.method == "POST":
                if fail_post:
                    raise httpx.ReadTimeout("synthetic secret must not escape", request=request)
                assert parse_qs(request.content.decode())["password"] == [PASSWORD]
                authenticated = True
                if logout:
                    logout()
                target = "https://evil.example/" if unsafe_callback else SERVICES["mystu"]
                return response(request, 302, headers={"location": target + "?ticket=synthetic-ticket"})
            if authenticated and query.get("service") == ELC_SERVICE:
                return response(request, 302, headers={"location": ELC_SERVICE + "?ticket=synthetic-elc-ticket"})
            return response(request, content=(FORM + ('<input name="captcha">' if challenge else "")).encode(),
                            headers={"set-cookie": "sso_secret=SYNTHETIC_SSO; Domain=.stu.edu.cn; Path=/; Secure"})
        assert host == "my.stu.edu.cn"
        assert "sso_secret=" not in request.headers.get("cookie", "")
        if path == "/discussion/my-courses":
            if not authenticated:
                return response(request, 302, headers={"location": SSO + "?" + str(httpx.QueryParams({"service": SERVICES["mystu"]})),
                                                       "set-cookie": "school_session=SYNTHETIC_MY; Path=/; Secure"})
            return response(request, content=b"<h1>synthetic courses</h1>")
        if path.endswith("/user/validate"):
            assert request.headers["x-requested-with"] == "XMLHttpRequest"
            return response(request, json=identity if identity is not None else {"id": "synthetic-id", "username": USERNAME})
        if path.endswith("/course/query"):
            return response(request, json={"items": []})
        if path == "/courses/elc/":
            return response(request, 302, headers={"location": SSO + "?" + str(httpx.QueryParams({"service": ELC_SERVICE, "gateway": "true"}))})
        if path == "/courses/elc/login/index.php":
            return response(request, content=b'<a href="/courses/elc/login/logout.php">logout</a>',
                            headers={"set-cookie": "MoodleSession=SYNTHETIC_ELC; Path=/courses/elc/; Secure"})
        raise AssertionError("unexpected fixed endpoint")
    return httpx.MockTransport(handler), calls


def test_mystu_new_cas_jar_identity_empty_courses_and_elc_bootstrap():
    transport, calls = mystu_transport()
    candidate = acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert candidate.proof == {"authenticated": True, "identity_verified": True, "courses_verified": True,
                               "course_count": 0, "course_inventory_complete": True, "elc_bootstrapped": True,
                               "moodle_bootstrap": {"elc": {"bootstrapped": True, "status": "verified"}}}
    assert {c["name"] for c in candidate.state["cookies"]} == {"school_session", "MoodleSession"}
    assert all(c["domain"].lstrip(".") == "my.stu.edu.cn" for c in candidate.state["cookies"])
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert PASSWORD not in repr(candidate)


@pytest.mark.parametrize("options,code,post_count", [
    ({"challenge": True}, "interaction_required", 0),
    ({"unsafe_callback": True}, "authentication_schema_changed", 1),
    ({"fail_post": True}, "authentication_outcome_unknown", 1),
    ({"identity": {}}, "authentication_unconfirmed", 1),
    ({"identity": {"id": "id", "username": "other"}}, "authentication_identity_mismatch", 1),
])
def test_cas_unknown_rejection_challenge_and_wrong_identity_never_retry(options, code, post_count):
    transport, calls = mystu_transport(**options)
    with pytest.raises(AppError) as error:
        acquire_state("mystu", USERNAME, PASSWORD, transport=transport)
    assert error.value.code == code
    assert len([r for r in calls if r.method == "POST"]) == post_count
    assert PASSWORD not in str(error.value.result())


@pytest.mark.parametrize("payload", [{}, {"id": True, "username": USERNAME}, {"id": "i", "username": ""},
                                      {"id": "i", "username": USERNAME, "authenticated": False}])
def test_identity_requires_observed_positive_fields(payload):
    with pytest.raises(AppError):
        validate_identity(payload, USERNAME)


@pytest.mark.parametrize("change", [
    lambda f: f.replace('method="post"', 'method="get"'),
    lambda f: f.replace('</form>', '<input type="hidden" name="changed" value="x"></form>'),
    lambda f: f.replace('</form>', '<input type="hidden" name="lt" value="duplicate"></form>'),
    lambda f: f.replace('<form ', '<form action="https://evil.example/" '),
])
def test_cas_form_changes_stop_before_credentials(change):
    url = SSO + "?" + str(httpx.QueryParams({"service": SERVICES["mystu"]}))
    page = httpx.Response(200, text=change(FORM), request=httpx.Request("GET", url))
    with pytest.raises(AppError):
        parse_form(page, "mystu", SERVICES["mystu"])


def test_jw_requires_explicit_http_before_any_network():
    transport = httpx.MockTransport(lambda _: pytest.fail("no network before explicit compatibility"))
    with pytest.raises(AppError) as error:
        acquire_state("jw", USERNAME, PASSWORD, transport=transport)
    assert error.value.code == "insecure_transport"


def test_jw_official_http_ticket_bridge_uses_separate_cookies_and_https_proof():
    from stu_mcp.sources import JW_HOME, JW_LOGIN_URL
    calls, logged_in = [], False
    service = JW_LOGIN_URL.replace("https:", "http:", 1)
    bridge = "http://jw.stu.edu.cn/jsxsd/xk/LoginToXk?method=LoginToXk&ticket1=synthetic-bridge"

    def handler(request):
        nonlocal logged_in
        calls.append(request)
        if request.url.host == "sso.stu.edu.cn":
            if request.method == "GET":
                return response(request, content=FORM.encode(), headers={
                    "set-cookie": "sso_secret=SYNTHETIC_SSO; Domain=.stu.edu.cn; Path=/; Secure"})
            assert request.url.scheme == "https"
            assert "jw_session=" not in request.headers.get("cookie", "")
            assert dict(request.url.params)["service"] == service
            return response(request, 302, headers={"location": service + "?ticket=synthetic-ticket"})
        assert request.url.host == "jw.stu.edu.cn"
        assert "sso_secret=" not in request.headers.get("cookie", "")
        if str(request.url) == JW_HOME:
            assert logged_in
            return response(request, content=(b'<a id="NEW_XSD_XJCJ_WDCJ_KCCJCX"></a>'
                                              b'<a id="NEW_XSD_KSBM_WDKS_KSAPCX"></a>'))
        if request.url.path == "/jsxsd/xk/LoginToXk":
            assert dict(request.url.params) == {"method": "LoginToXk", "ticket1": "synthetic-bridge"}
            if request.url.scheme == "http":
                return response(request, 302, headers={"location": str(request.url).replace("http:", "https:", 1)})
            logged_in = True
            return response(request, 302, headers={"location": JW_HOME})
        if "ticket" in request.url.params:
            return response(request, 302, headers={"location": bridge})
        return response(request, content=b"<script>synthetic official navigation</script>", headers={
            "set-cookie": "jw_session=SYNTHETIC_JW; Path=/"})

    candidate = acquire_state("jw", USERNAME, PASSWORD, legacy_jw=True, transport=httpx.MockTransport(handler))
    assert candidate.proof["student_home_verified"]
    assert {c["domain"] for c in candidate.state["cookies"]} == {"jw.stu.edu.cn"}
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert all(r.url.scheme == "https" for r in calls if r.method == "POST")


def test_cas_repair_uses_fixed_service_and_existing_list_proof(monkeypatch):
    from stu_mcp.features.repair import http_adapter
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.host == "sso.stu.edu.cn":
            if request.method == "POST":
                return response(request, 302, headers={"location": SERVICES["repair"] + "?ticket=synthetic-ticket"})
            return response(request, content=FORM.encode())
        if "ticket" in request.url.params:
            return response(request, content=b"synthetic student listing", headers={
                "set-cookie": "repair_session=SYNTHETIC_REPAIR; Path=/; Secure"})
        return response(request, 302, headers={"location": SSO + "?" + str(httpx.QueryParams({"service": SERVICES["repair"]}))})
    monkeypatch.setattr(http_adapter, "verify_login", lambda flow, *, response=None: {
        "authenticated": True, "list_verified": True, "orders": 0})
    candidate = acquire_state("repair", USERNAME, PASSWORD, transport=httpx.MockTransport(handler))
    assert candidate.proof["list_verified"] and candidate.proof["orders"] == 0
    assert {c["domain"] for c in candidate.state["cookies"]} == {"repair.stu.edu.cn"}
    assert len([r for r in calls if r.method == "POST"]) == 1


def test_transport_gzip_bounds_scope_and_private_logging(caplog):
    secret_url = "https://sso.stu.edu.cn/login?ticket=SYNTHETIC_PRIVATE_TICKET"
    def handler(request):
        logging.getLogger("httpx").info("private %s", secret_url)
        return response(request, content=gzip.compress(b"decoded"), headers={"content-encoding": "gzip"})
    caplog.set_level(logging.DEBUG)
    with HTTPFlow("mystu", ("sso.stu.edu.cn",), transport=httpx.MockTransport(handler), max_requests=1) as flow:
        assert flow.get(secret_url).text == "decoded"
        with pytest.raises(AppError, match="上限"):
            flow.get(secret_url)
    assert "SYNTHETIC_PRIVATE_TICKET" not in caplog.text
    with HTTPFlow("mystu", ("sso.stu.edu.cn",), transport=httpx.MockTransport(handler)) as flow:
        for url in ("https://evil.example/", "http://sso.stu.edu.cn/", "https://u:p@sso.stu.edu.cn/", {},
                    "https://sso.stu.edu.cn/#fragment"):
            with pytest.raises(AppError):
                flow.get(url)


def test_orchestration_saves_encrypted_scoped_session_and_clears_only_own_cache(app):
    app.store.save_batch("mystu", [{"id": "old-course", "kind": "course", "title": "old"}], private=True)
    app.store.save_batch("public", [{"id": "public", "kind": "notice", "title": "public"}])
    transport, _ = mystu_transport()
    result = login_http(app.vault, "mystu", credentials=Credentials(USERNAME, PASSWORD), transport=transport)
    assert result["verified_live"] and result["method"] == "http"
    assert app.vault.load("mystu")["cookies"]
    assert len(app.store.list(sources=("mystu",))["items"]) == 0
    assert len(app.store.list(sources=("public",))["items"]) == 1
    assert PASSWORD.encode() not in app.runtime.session_file("mystu").read_bytes()
    assert PASSWORD not in str(result) and USERNAME not in str(result)


@pytest.mark.parametrize("existing", [False, True])
def test_logout_during_http_auth_cannot_restore_session_or_erase_cache(app, existing):
    if existing:
        app.vault.save("mystu", {"cookies": [], "origins": []})
    def logout():
        app.logout("mystu")
    transport, _ = mystu_transport(logout=logout)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "mystu", credentials=Credentials(USERNAME, PASSWORD), transport=transport)
    assert error.value.code == "session_changed"
    assert not app.runtime.session_file("mystu").exists()


def test_failed_http_login_preserves_existing_session_and_cache(app, session):
    app.vault.save("mystu", session)
    app.store.save_batch("mystu", [{"id": "old-course", "kind": "course", "title": "old"}], private=True)
    fingerprint = app.vault.fingerprint("mystu")
    transport, _ = mystu_transport(fail_post=True)
    with pytest.raises(AppError):
        login_http(app.vault, "mystu", credentials=Credentials(USERNAME, PASSWORD), transport=transport)
    assert app.vault.fingerprint("mystu") == fingerprint
    assert len(app.store.list(sources=("mystu",))["items"]) == 1


def test_another_login_during_auth_cannot_be_overwritten_or_have_cache_erased(app, session):
    def replacement():
        app.vault.save("mystu", session)
        app.store.save_batch("mystu", [{"id": "new-account-course", "kind": "course", "title": "new"}], private=True)
    transport, _ = mystu_transport(logout=replacement)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "mystu", credentials=Credentials(USERNAME, PASSWORD), transport=transport)
    assert error.value.code == "session_changed"
    assert app.vault.load("mystu") == session
    assert app.store.list(sources=("mystu",))["items"][0]["id"] == "new-account-course"


def test_storage_failure_occurs_before_requesting_human_credentials(app, monkeypatch):
    def unavailable():
        raise OSError("synthetic private")
    monkeypatch.setattr(app.vault, "key_store", unavailable)
    interaction = type("NoInput", (), {"credentials": lambda *_: pytest.fail("no credential input")})()
    with pytest.raises(AppError) as error:
        login_http(app.vault, "mystu", interaction=interaction)
    assert error.value.code == "secure_storage_unavailable"
    assert "synthetic private" not in str(error.value)


def test_yuketang_header_only_candidate_uses_guarded_encrypted_save(app, monkeypatch):
    from stu_mcp.auth_http import yuketang
    monkeypatch.setattr(yuketang, "acquire_state", lambda **_: Candidate(
        {"cookies": [], "origins": [], "yuketang_authorization": "Bearer SYNTHETIC_PRIVATE"},
        {"authenticated": True, "endpoint": "student_courses"}))
    interaction = type("NoCredentials", (), {"show_qr": lambda *_: None})()
    result = login_http(app.vault, "yuketang", interaction=interaction)
    assert result["status"] == "session_saved"
    assert app.vault.load("yuketang")["yuketang_authorization"] == "Bearer SYNTHETIC_PRIVATE"
    assert "SYNTHETIC_PRIVATE" not in str(result)
