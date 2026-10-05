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
        def __init__(self, source, state, **kwargs):
            settings.append((source, kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def text(self, url, **_):
            requests.append(url)
            if "kscj" in url:
                return grades_html
            raise AppError("synthetic_exam_unavailable", "合成考试接口", "jw")
    monkeypatch.setattr(collectors, "CampusHTTP", SyntheticHTTP)
    synthetic_vault = SimpleNamespace(runtime=app.runtime, load=lambda _: {})
    for enabled, scheme in ((False, "https"), (True, "http")):
        app.runtime.save_preferences({"jw_http_compat": enabled})
        result = collectors.jw(synthetic_vault, 20, "2026-2027-1")
        assert result.items and result.private
        assert settings[-1] == ("jw", {"allow_legacy_http": enabled})
        assert requests[-1].startswith(scheme + "://jw.stu.edu.cn/")
        assert result.coverage["transport"] == ("school_legacy_http" if enabled else "https")


def test_setup_transport_option_is_explicit_boolean(app):
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            assert app.runtime.preferences() == {"jw_http_compat": False}
            for invalid in ({}, {"jw_http_compat": "true"}, {"jw_http_compat": 1},
                            {"jw_http_compat": True, "password": "SYNTHETIC"}):
                assert client.post("/api/transport", headers=headers, json=invalid).status_code == 400
                assert not app.runtime.preferences()["jw_http_compat"]
            assert client.post("/api/transport", headers=headers, json={"jw_http_compat": True}).status_code == 200
            assert client.get("/api/status", headers=headers).json()["transport"]["jw_http_compat"] is True
            assert client.post("/api/transport", json={"jw_http_compat": False}).status_code == 403
            assert app.runtime.preferences()["jw_http_compat"]
    finally:
        ui.close()
