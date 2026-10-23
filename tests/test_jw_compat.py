from types import SimpleNamespace

import httpx
import pytest

from stu_mcp import collectors
from stu_mcp.auth import browser_http_allowed
from stu_mcp.network import CampusHTTP, checked_url
from stu_mcp.runtime import AppError
from stu_mcp.setup_web import SetupServer


def test_http_compat_is_opt_in_and_limited_to_jw():
    target = "http://jw.stu.edu.cn/jsxsd/kscj/cjcx_list"
    with pytest.raises(AppError, match="HTTPS"):
        checked_url("jw", target, authenticated=True)
    assert checked_url("jw", target, authenticated=True, allow_legacy_http=True) == target
    for url in ("http://sso.stu.edu.cn/login", "http://jw.stu.edu.cn:8000/", "http://evil.example/"):
        with pytest.raises(AppError):
            checked_url("jw", url, authenticated=True, allow_legacy_http=True)
    with pytest.raises(AppError):
        CampusHTTP("mystu", allow_legacy_http=True)


def test_legacy_session_preserves_secure_cookie_flags():
    state = {"cookies": [
        {"name": "JSESSIONID", "value": "SYNTHETIC_JW", "domain": "jw.stu.edu.cn", "secure": False},
        {"name": "secure_session", "value": "SYNTHETIC_SECURE", "domain": "jw.stu.edu.cn", "secure": True},
        {"name": "central_sso", "value": "SYNTHETIC_SSO", "domain": ".stu.edu.cn", "secure": False},
    ], "origins": []}
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, text="synthetic")
    with CampusHTTP("jw", state, allow_legacy_http=True, transport=httpx.MockTransport(handler)) as http:
        http.text("http://jw.stu.edu.cn/jsxsd/kscj/cjcx_list", data={"kksj": ""})
        assert sent[0].headers["cookie"] == "JSESSIONID=SYNTHETIC_JW"
        with pytest.raises(AppError) as error:
            http.text("http://jw.stu.edu.cn/", data={"password": "SYNTHETIC_NEVER_SENT"})
        assert error.value.code == "insecure_password_form"
        assert len(sent) == 1


@pytest.mark.parametrize("url,data,enabled,expected", [
    ("http://jw.stu.edu.cn/jsxsd/?ticket=SYNTHETIC_CAS_TICKET", None, True, True),
    ("http://jw.stu.edu.cn/jsxsd/", None, False, False),
    ("http://jw.stu.edu.cn/jsxsd/?password=SYNTHETIC", None, True, False),
    ("http://jw.stu.edu.cn/jsxsd/", "pwd=SYNTHETIC", True, False),
    ("http://jw.stu.edu.cn/jsxsd/", '{"password":"SYNTHETIC"}', True, False),
    ("http://sso.stu.edu.cn/login", "username=SYNTHETIC", True, False),
    ("http://evil.example/", None, True, False),
])
def test_browser_compat_rejects_http_passwords_and_other_hosts(url, data, enabled, expected):
    assert browser_http_allowed(url, data, legacy_jw=enabled) is expected


def test_jw_collector_uses_selected_transport(app, grades_html, monkeypatch):
    settings = []
    requests = []
    class SyntheticHTTP:
        used_legacy_http = False
        def __init__(self, source, state, **kwargs):
            settings.append((source, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def request(self, url, **_):
            requests.append(url)
            if "kscj" in url:
                return httpx.Response(200, text=grades_html, request=httpx.Request("POST", url))
            raise AppError("synthetic_exam_unavailable", "合成考试接口", "jw")
    monkeypatch.setattr(collectors, "CampusHTTP", SyntheticHTTP)
    synthetic_vault = SimpleNamespace(runtime=app.runtime, load=lambda _: {})
    for enabled in (False, True):
        app.runtime.save_preferences({"jw_http_compat": enabled})
        result = collectors.jw(synthetic_vault, 20, "2026-2027-1")
        assert result.items and result.private
        assert settings[-1] == ("jw", {"allow_legacy_http": enabled})
        assert requests[-1].startswith("https://jw.stu.edu.cn/")
        assert result.coverage["transport"] == "https"


def test_private_setup_does_not_offer_transport_preferences(app):
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            assert app.runtime.preferences() == {"jw_http_compat": False}
            for invalid in ({}, {"jw_http_compat": True}, {"jw_http_compat": "true"}, {"jw_http_compat": 1},
                            {"jw_http_compat": True, "password": "SYNTHETIC"}):
                assert client.post("/api/transport", headers=headers, json=invalid).status_code == 400
                assert not app.runtime.preferences()["jw_http_compat"]
            assert client.get("/api/status", headers=headers).json()["transport"]["jw_http_compat"] is False
            assert client.post("/api/transport", json={"jw_http_compat": False}).status_code == 403
            assert not app.runtime.preferences()["jw_http_compat"]
    finally:
        ui.close()


@pytest.mark.parametrize("marker,allowed", [(True, True), (False, False), ("true", False), (1, False), (None, False)])
def test_jw_session_transport_marker_requires_exact_boolean(app, marker, allowed):
    from stu_mcp.features.jw.adapter import JwAdapter
    state = {"cookies": [], "jw_http_compat": marker}
    app.vault.save("jw", state)
    received = []
    JwAdapter(app.vault, http_factory=lambda source, session, **options: received.append((source, session, options)))
    assert received == [("jw", state, {"allow_legacy_http": allowed})]
    assert not app.runtime.preferences()["jw_http_compat"]


@pytest.mark.parametrize("service,permit,proof_flag,expected", [
    ("jw", True, True, True), ("jw", True, "true", False), ("jw", True, False, False),
    ("jw", False, True, False), ("mystu", True, True, False),
])
def test_only_proven_allowed_jw_callback_attaches_session_route(app, monkeypatch, service, permit, proof_flag, expected):
    from stu_mcp.auth_http import Candidate, Credentials, login_http
    state = {"cookies": [], "origins": [], "jw_http_compat": True}
    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", lambda *_, **__: Candidate(
        state, {"authenticated": True, "http_callback_used": proof_flag}))
    assert login_http(app.vault, service, credentials=Credentials("synthetic", "SYNTHETIC_PASSWORD"),
                      allow_http_callback=permit)["ok"]
    assert (app.vault.load(service).get("jw_http_compat") is True) is expected
    assert not app.runtime.preferences()["jw_http_compat"]


def test_official_cas_login_session_continues_into_http_grade_read_without_global_preference(app, grades_html):
    from stu_mcp.auth_http import Credentials, login_http
    from stu_mcp.features.jw.adapter import JwAdapter
    from stu_mcp.features.jw.schema import JW_GRADE_URL
    from stu_mcp.sources import JW_HOME, JW_LOGIN_URL
    callback = JW_LOGIN_URL.replace("https:", "http:", 1)
    calls = []
    form = ('<form method="post"><input name="username"><input name="password" type="password">'
            '<input name="lt" type="hidden" value="synthetic-lt">'
            '<input name="execution" type="hidden" value="synthetic-execution">'
            '<input name="_eventId" type="hidden" value="submit"></form>')

    def handler(request):
        calls.append(request)
        cookies = request.headers.get("cookie", "")
        if request.url.host == "sso.stu.edu.cn":
            assert request.url.scheme == "https" and "jw_session=" not in cookies
            if request.method == "POST":
                return httpx.Response(302, headers={"location": callback + "?ticket=synthetic-ticket"})
            return httpx.Response(200, text=form, headers={
                "set-cookie": "central=SYNTHETIC_SSO; Domain=.stu.edu.cn; Path=/"})
        assert request.url.host == "jw.stu.edu.cn" and "central=" not in cookies
        if str(request.url) == JW_HOME:
            return httpx.Response(200, text='<a id="NEW_XSD_XJCJ_WDCJ_KCCJCX"></a>'
                                 '<a id="NEW_XSD_KSBM_WDKS_KSAPCX"></a>')
        if request.url.path == httpx.URL(JW_GRADE_URL).path:
            if request.url.scheme == "https":
                return httpx.Response(303, headers={"location": JW_GRADE_URL.replace("https:", "http:", 1)})
            assert cookies == "jw_session=SYNTHETIC_JW" and request.method == "GET"
            return httpx.Response(200, text=grades_html)
        return httpx.Response(200, text="synthetic official callback", headers=[
            ("set-cookie", "jw_session=SYNTHETIC_JW; Path=/"),
            ("set-cookie", "secure_jw=SYNTHETIC_SECURE; Path=/; Secure")])

    transport = httpx.MockTransport(handler)
    result = login_http(app.vault, "jw", credentials=Credentials("synthetic", "SYNTHETIC_PASSWORD"),
                        allow_http_callback=True, transport=transport)
    assert result["ok"] and result["proof"]["http_callback_used"] is True
    assert app.vault.load("jw")["jw_http_compat"] is True
    assert not app.runtime.preferences()["jw_http_compat"]
    def factory(source, state, **options):
        return CampusHTTP(source, state, transport=transport, **options)
    with JwAdapter(app.vault, http_factory=factory) as adapter:
        assert adapter.grades("2026-2027-1")
        assert adapter.transport == "school_legacy_http"
    assert all(request.url.scheme == "https" for request in calls if request.method == "POST")
    assert all("SYNTHETIC_PASSWORD" not in request.content.decode() for request in calls
               if request.url.host != "sso.stu.edu.cn")
    app.logout("jw")
    with pytest.raises(AppError) as error:
        app.vault.load("jw")
    assert error.value.code == "needs_login" and not app.runtime.preferences()["jw_http_compat"]
