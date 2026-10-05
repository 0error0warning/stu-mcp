import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest

from stu_mcp import collectors, webvpn
from stu_mcp.network import CampusHTTP
from stu_mcp.runtime import AppError
from stu_mcp.setup_web import SetupServer
from stu_mcp.sources import OA_SECURE_PROXY
from stu_mcp.webvpn import KEYRING_SERVICE, WebVPNConfig, automatic_login, parse_totp, protected_access

RAW_SEED = b"12345678901234567890"  # Published RFC 6238 test vector, never a user's secret.
SEED = base64.b32encode(RAW_SEED).decode()
FIELDS = {"enabled": True, "username": "SYNTHETIC_STUDENT_ACCOUNT",
          "password": "SYNTHETIC_STUDENT_PASSWORD", "totp": SEED}
LISTING = '<table><tr><td><a href="/newstemplateprotal.jsp?docid=DEMO">合成 OA 通知</a></td></tr></table>'
PROTECTED_URL = OA_SECURE_PROXY + "/login/Login.jsp?logintype=1"


@pytest.fixture
def vpn_session(session):
    session["cookies"][0].update(domain="webvpn.stu.edu.cn", value="SYNTHETIC_VPN_COOKIE")
    return session


def protected_http(monkeypatch, handler):
    monkeypatch.setattr(webvpn, "CampusHTTP", lambda source, state: CampusHTTP(
        source, state, transport=httpx.MockTransport(handler)))


def require_proxy(monkeypatch):
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source: CampusHTTP(
        source, transport=httpx.MockTransport(lambda _: httpx.Response(403))))


def test_config_is_opt_in_keyring_only_and_never_echoed(app, keys):
    config = WebVPNConfig(app.vault)
    assert config.status()["configured"] is False
    with pytest.raises(AppError):
        config.configure({**FIELDS, "enabled": False})
    result = config.configure(FIELDS)
    assert result["status"] == "auto_login_configured"
    assert config.status()["enabled"] is True
    stored = json.loads(keys.values[(KEYRING_SERVICE, app.vault.account)])
    assert stored["password"] == FIELDS["password"]
    assert stored["totp"]["secret"] == SEED
    output = json.dumps([result, app.status(), config.status()], ensure_ascii=False)
    files = b"".join(p.read_bytes() for p in app.runtime.home.rglob("*") if p.is_file())
    for secret in (FIELDS["username"], FIELDS["password"], SEED):
        assert secret not in output
        assert secret.encode() not in files


@pytest.mark.parametrize("value,encoding", [(SEED, "base32"), (RAW_SEED.hex(), "hex"),
                                          (base64.b64encode(RAW_SEED).decode(), "base64"),
                                          ("otpauth://totp/Test?secret=" + SEED + "&digits=8&period=30", "auto")])
def test_seed_encodings_and_standard_totp_vector(value, encoding):
    otp = parse_totp(value, encoding)
    otp.digits = 8
    assert otp.at(59) == "94287082"


@pytest.mark.parametrize("value", ["123456", "SYNTHETIC_BAD_SECRET!", "otpauth://hotp/Test?secret=" + SEED,
                                 "otpauth://totp/Test?secret=" + SEED + "&secret=other",
                                 "otpauth://totp/Test?secret=" + SEED + "&digits=10",
                                 "otpauth://totp/Test?secret=" + SEED + "&period=1"])
def test_bad_totp_does_not_store_or_echo_input(app, keys, value):
    with pytest.raises(AppError) as error:
        WebVPNConfig(app.vault).configure({**FIELDS, "totp": value})
    assert error.value.code == "invalid_totp"
    assert value not in str(error.value)
    assert not keys.values


def test_keyring_failure_never_saves_plaintext(app):
    class BrokenKeys:
        def set_password(self, *_):
            raise RuntimeError(FIELDS["password"])
    app.vault._store = BrokenKeys()
    with pytest.raises(AppError) as error:
        WebVPNConfig(app.vault).configure(FIELDS)
    assert error.value.code == "secure_storage_unavailable"
    assert FIELDS["password"] not in str(error.value)
    assert WebVPNConfig(app.vault).status()["enabled"] is False
    assert FIELDS["password"] not in (app.runtime.home / "webvpn-auto.json").read_text()


def test_interrupted_configuration_remains_disabled_and_credentials_can_be_removed(app, keys, monkeypatch):
    config = WebVPNConfig(app.vault)
    write = webvpn.private_write
    def fail_activation(path, data):
        if json.loads(data)["enabled"]:
            raise OSError("synthetic disk failure")
        write(path, data)
    monkeypatch.setattr(webvpn, "private_write", fail_activation)
    with pytest.raises(AppError) as error:
        config.configure(FIELDS)
    assert error.value.code == "local_state_unavailable"
    assert config.status()["configured"] and not config.status()["enabled"]
    assert (KEYRING_SERVICE, app.vault.account) in keys.values
    config.remove()
    assert (KEYRING_SERVICE, app.vault.account) not in keys.values


def test_logout_erases_webvpn_credentials_session_and_cache_only(app, keys, vpn_session, session):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    app.vault.save("webvpn", vpn_session)
    app.vault.save("mystu", session)
    app.store.save_batch("oa", [{"id": "oa:notice:private", "kind": "notice", "title": "合成私有通知"}], private=True)
    app.store.save_batch("public", [{"id": "public:notice:keep", "kind": "notice", "title": "保留公开通知"}])
    app.logout("webvpn")
    assert (KEYRING_SERVICE, app.vault.account) not in keys.values
    assert config.status()["configured"] is False
    assert app.vault.status("webvpn")["status"] == "needs_login"
    assert app.store.list(sources=("oa",))["items"] == []
    assert app.vault.status("mystu")["status"] == "session_saved"
    assert app.store.get("public:notice:keep")["title"] == "保留公开通知"


def test_config_update_clears_old_oa_account_but_disable_retains_current_session(app, vpn_session):
    config = WebVPNConfig(app.vault)
    app.vault.save("webvpn", vpn_session)
    app.store.save_batch("oa", [{"id": "oa:notice:old", "kind": "notice", "title": "旧账号合成通知"}], private=True)
    config.configure(FIELDS)
    assert app.vault.status("webvpn")["status"] == "needs_login"
    assert app.store.list(sources=("oa",))["items"] == []
    app.vault.save("webvpn", vpn_session)
    config.remove()
    assert config.status()["configured"] is False
    assert app.vault.status("webvpn")["status"] == "session_saved"


def test_missing_session_requires_manual_login_without_optional_credentials(app, monkeypatch):
    monkeypatch.setattr(webvpn, "automatic_login", lambda *_: pytest.fail("must not log in without opt-in"))
    with pytest.raises(AppError) as error:
        protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
    assert error.value.code == "needs_login"


def test_valid_session_is_reused_without_reading_saved_password(app, vpn_session, monkeypatch):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    app.vault.save("webvpn", vpn_session)
    protected_http(monkeypatch, lambda _: httpx.Response(200, text=LISTING))
    monkeypatch.setattr(config.__class__, "credentials", lambda *_: pytest.fail("valid cookie must be reused"))
    result = protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
    assert result.value == LISTING
    assert result.session_version == app.vault.fingerprint("webvpn")


@pytest.mark.parametrize("rejection", [401, 403, "redirect", "html", "spa"])
def test_server_expiry_renews_once_and_refresh_can_save_private_oa(app, vpn_session, monkeypatch, rejection):
    WebVPNConfig(app.vault).configure(FIELDS)
    old = {"cookies": [{**vpn_session["cookies"][0], "value": "OLD_SYNTHETIC_COOKIE"}], "origins": []}
    app.vault.save("webvpn", old)
    calls = []
    def renew(credentials, check):
        check()
        calls.append(credentials)
        return vpn_session
    def handler(request):
        if "OLD_SYNTHETIC_COOKIE" in request.headers.get("Cookie", ""):
            if rejection == "redirect":
                return httpx.Response(302, headers={"location": "https://webvpn.stu.edu.cn/portal/#!/login"})
            if rejection == "html":
                return httpx.Response(200, text='<input type="password">')
            if rejection == "spa":
                return httpx.Response(200, text='<title>Loading...</title><script src="./jssdk/common/errcode.js"></script>')
            return httpx.Response(rejection)
        return httpx.Response(200, text=LISTING)
    require_proxy(monkeypatch)
    protected_http(monkeypatch, handler)
    monkeypatch.setattr(webvpn, "automatic_login", renew)
    assert app.refresh("oa")["saved"] == 1
    assert app.refresh("oa")["saved"] == 1
    assert len(calls) == 1
    assert calls[0].username == FIELDS["username"]
    assert FIELDS["password"] not in repr(calls[0])
    assert app.vault.load("webvpn") == vpn_session
    assert app.store.list(sources=("oa",))["items"][0]["title"] == "合成 OA 通知"


def test_anonymous_oa_works_without_auto_login_or_keyring(app, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    class NoKeys:
        def get_password(self, *_):
            pytest.fail("anonymous OA must not read saved credentials")
    app.vault._store = NoKeys()
    monkeypatch.setattr(collectors, "CampusHTTP", lambda source: CampusHTTP(
        source, transport=httpx.MockTransport(lambda _: httpx.Response(200, text=LISTING))))
    assert app.refresh("oa")["coverage"]["access"] == "anonymous_http"


@pytest.mark.parametrize("code", ["auto_login_failed", "auto_login_interaction_required"])
def test_rejected_credentials_or_human_challenge_pause_future_attempts(app, monkeypatch, code):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    calls = []
    def rejected(*_):
        calls.append(1)
        raise AppError(code, "合成认证失败", "oa")
    monkeypatch.setattr(webvpn, "automatic_login", rejected)
    for expected in (code, "auto_login_paused"):
        with pytest.raises(AppError) as error:
            protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
        assert error.value.code == expected
    assert config.status()["status"] == "paused" and len(calls) == 1
    config.configure(FIELDS)
    assert config.status()["enabled"] is True


def test_temporary_failure_is_throttled_across_new_app_instances(app, monkeypatch):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    calls = []
    def offline(*_):
        calls.append(1)
        raise AppError("network_error", "合成网络失败", "oa")
    monkeypatch.setattr(webvpn, "automatic_login", offline)
    with pytest.raises(AppError, match="合成网络"):
        protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
    assert WebVPNConfig(app.vault).status()["retry_after_seconds"] > 0
    with pytest.raises(AppError) as error:
        protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
    assert error.value.code == "auto_login_cooldown" and len(calls) == 1
    assert config.status()["enabled"] is True


def test_network_or_parser_failure_does_not_resubmit_credentials(app, vpn_session, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    app.vault.save("webvpn", vpn_session)
    protected_http(monkeypatch, lambda _: httpx.Response(500))
    monkeypatch.setattr(webvpn, "automatic_login", lambda *_: pytest.fail("network failure is not proof of expiry"))
    with pytest.raises(AppError) as error:
        protected_access(app.vault, PROTECTED_URL, lambda r: r.text)
    assert error.value.code == "network_error"


@pytest.mark.parametrize("url", ["http://oa.stu.edu.cn/private", "https://evil.example/",
                               "https://oa-stu-edu-cn.webvpn.stu.edu.cn/?access_token=synthetic"])
def test_unsafe_destination_is_rejected_before_credentials_are_loaded(app, monkeypatch, url):
    monkeypatch.setattr(WebVPNConfig, "snapshot", lambda *_: pytest.fail("must validate URL first"))
    with pytest.raises(AppError):
        protected_access(app.vault, url, lambda r: r.text)


@pytest.mark.parametrize("change", ["logout", "replace", "disable"])
def test_state_changes_during_auto_login_cannot_restore_old_session_or_cache(app, vpn_session, monkeypatch, change):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    started, finish = threading.Event(), threading.Event()
    def delayed(_, check):
        check()
        started.set()
        assert finish.wait(timeout=5)
        check()
        return vpn_session
    monkeypatch.setattr(webvpn, "automatic_login", delayed)
    require_proxy(monkeypatch)
    protected_http(monkeypatch, lambda _: httpx.Response(200, text=LISTING))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(app.refresh, "oa")
        assert started.wait(timeout=5)
        if change == "logout":
            app.logout("webvpn")
        elif change == "replace":
            config.configure({**FIELDS, "username": "SECOND_SYNTHETIC_ACCOUNT"})
        else:
            config.remove()
        finish.set()
        with pytest.raises(AppError) as error:
            pending.result(timeout=5)
        assert error.value.code == "session_changed"
    assert not app.runtime.session_file("webvpn").exists()
    assert app.store.list(sources=("oa",))["items"] == []


def test_simultaneous_readers_perform_only_one_auto_login(app, vpn_session, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    barrier, local, calls = threading.Barrier(2), threading.local(), []
    original_snapshot = WebVPNConfig.snapshot
    def synchronized(config):
        result = original_snapshot(config)
        if not getattr(local, "initialized", False):
            local.initialized = True
            barrier.wait(timeout=5)
        return result
    def renew(_, check):
        check()
        calls.append(1)
        return vpn_session
    monkeypatch.setattr(WebVPNConfig, "snapshot", synchronized)
    monkeypatch.setattr(webvpn, "automatic_login", renew)
    protected_http(monkeypatch, lambda _: httpx.Response(200, text=LISTING))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: protected_access(app.vault, PROTECTED_URL, lambda r: r.text), [1, 2]))
    assert len(calls) == 1
    assert all(r.value == LISTING for r in results)
    assert results[0].session_version == results[1].session_version


def test_notice_and_attachment_resume_with_renewed_session(app, vpn_session, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    notice = {"id": "oa:notice:DEMO", "kind": "notice", "title": "合成通知", "url": OA_SECURE_PROXY + "/newstemplateprotal.jsp?docid=DEMO"}
    app.store.save_batch("oa", [notice], private=True)
    calls = []
    monkeypatch.setattr(webvpn, "automatic_login", lambda *_: calls.append(1) or vpn_session)
    def handler(request):
        if "FileDownload" in request.url.path:
            return httpx.Response(200, text="合成附件正文", headers={"content-type": "text/plain"})
        return httpx.Response(200, text='<div id="docContent">合成通知正文</div><table><tr id="accessory_dsp_tr1"><td><input name="accessory" value="42">合成附件</td></tr></table>')
    protected_http(monkeypatch, handler)
    result = app.notice(notice["id"], refresh=True)
    assert "合成通知正文" in result["item"]["body"]
    assert "session_version" not in result["item"]
    assert app.attachment(notice["id"])["text"] == "合成附件正文"
    assert len(calls) == 1


def test_setup_is_the_only_credential_input_and_status_never_reads_secrets(app, capsys):
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            assert client.post("/api/webvpn-auto", json=FIELDS).status_code == 403
            assert client.post("/api/webvpn-auto", headers={"X-STU-Setup": ui.secret}, json=FIELDS).status_code == 403
            invalid = client.post("/api/webvpn-auto", headers=headers, json={**FIELDS, "totp": "123456"})
            assert invalid.status_code == 400 and "123456" not in invalid.text
            saved = client.post("/api/webvpn-auto", headers=headers, json=FIELDS)
            assert saved.status_code == 200
            status = client.get("/api/status", headers=headers)
            assert status.json()["webvpn_auto_login"]["enabled"] is True
            for value in (FIELDS["username"], FIELDS["password"], SEED):
                assert value not in status.text + saved.text + capsys.readouterr().out
            assert client.get("/api/webvpn-auto", headers=headers).status_code == 404
            assert client.post("/api/webvpn-auto/remove", headers=headers, json={}).status_code == 200
            assert client.get("/api/status", headers=headers).json()["webvpn_auto_login"]["configured"] is False
    finally:
        ui.close()


def test_failed_keyring_deletion_disables_login_and_can_be_retried(app, keys, vpn_session, monkeypatch):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    app.vault.save("webvpn", vpn_session)
    original = keys.delete_password
    def blocked(*_):
        raise RuntimeError(FIELDS["password"])
    monkeypatch.setattr(keys, "delete_password", blocked)
    with pytest.raises(AppError) as error:
        app.logout("webvpn")
    assert error.value.code == "secure_storage_unavailable"
    assert FIELDS["password"] not in str(error.value)
    assert not config.status()["enabled"] and config.status()["configured"]
    assert not app.runtime.session_file("webvpn").exists()
    monkeypatch.setattr(keys, "delete_password", original)
    config.remove()
    assert not config.status()["configured"]
    assert (KEYRING_SERVICE, app.vault.account) not in keys.values


@pytest.mark.parametrize("logout_during_login", [False, True])
def test_manual_login_erases_auto_credentials_and_obeys_logout_fence(app, keys, vpn_session, tmp_path, monkeypatch, logout_during_login):
    from test_auth import fake_playwright

    import stu_mcp.auth as auth
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    fake, _ = fake_playwright(tmp_path, vpn_session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth, "prepare_browser", lambda *_: None)
    def proof(*_, **__):
        if logout_during_login:
            app.logout("webvpn")
        return True
    monkeypatch.setattr(auth, "proof", proof)
    if logout_during_login:
        with pytest.raises(AppError) as error:
            auth.interactive_login(app.vault, "webvpn")
        assert error.value.code == "session_changed"
        assert not app.runtime.session_file("webvpn").exists()
    else:
        assert auth.interactive_login(app.vault, "webvpn")["status"] == "session_saved"
        assert app.vault.load("webvpn") == vpn_session
    assert not config.status()["configured"]
    assert (KEYRING_SERVICE, app.vault.account) not in keys.values


def test_logout_after_portal_success_before_session_commit_is_fenced(app, vpn_session, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    started, finish = threading.Event(), threading.Event()
    monkeypatch.setattr(webvpn, "automatic_login", lambda *_: vpn_session)
    def delayed(_):
        started.set()
        assert finish.wait(timeout=5)
        return httpx.Response(200, text=LISTING)
    protected_http(monkeypatch, delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(protected_access, app.vault, PROTECTED_URL, lambda r: r.text)
        assert started.wait(timeout=5)
        app.logout("webvpn")
        finish.set()
        with pytest.raises(AppError) as error:
            pending.result(timeout=5)
        assert error.value.code == "session_changed"
    assert not app.runtime.session_file("webvpn").exists()


def test_logout_after_session_commit_before_cache_commit_is_fenced(app, vpn_session, monkeypatch):
    WebVPNConfig(app.vault).configure(FIELDS)
    monkeypatch.setattr(webvpn, "automatic_login", lambda *_: vpn_session)
    require_proxy(monkeypatch)
    protected_http(monkeypatch, lambda _: httpx.Response(200, text=LISTING))
    original = app.vault.save
    def save_then_logout(*args, **kwargs):
        version = original(*args, **kwargs)
        app.logout("webvpn")
        return version
    monkeypatch.setattr(app.vault, "save", save_then_logout)
    with pytest.raises(AppError) as error:
        app.refresh("oa")
    assert error.value.code == "session_changed"
    assert app.store.list(sources=("oa",))["items"] == []


def fake_browser(tmp_path, vpn_session, *, captcha=False, binding=False):
    actions, settings = [], {}
    class Locator:
        def __init__(self, page, selector):
            self.page, self.selector, self.first = page, selector, self
        def count(self):
            if "error-content" in self.selector:
                return 0
            if "captcha" in self.selector:
                return int(captcha)
            if "totp_loading" in self.selector:
                return int(binding)
            if "loginPwd" in self.selector or "auto-input-usr" in self.selector or "checkbox" in self.selector:
                return int(self.page.phase == "password")
            if "totp_signature" in self.selector:
                return int(self.page.phase == "totp")
            if "button.button--normal" in self.selector:
                return int(self.page.phase == "password")
            raise AssertionError(self.selector)
        def all_inner_texts(self):
            return []  # The page's help text mentions login errors, but is not an error widget.
        def fill(self, value, **_):
            actions.append(("fill", value))
        def is_checked(self):
            return self.page.accepted
        def click(self, **_):
            if "checkbox" in self.selector:
                self.page.accepted = True
            elif self.page.phase == "password":
                self.page.phase = "totp"
                actions.append(("password_submit", None))
            else:
                self.page.phase = "service"
                self.page.url = "https://webvpn.stu.edu.cn/portal/#!/service"
                actions.append(("totp_submit", None))
        def filter(self, **_):
            return self
    class Page:
        phase, accepted = "password", False
        def goto(self, *_args, **_kwargs):
            self.url = "https://webvpn.stu.edu.cn/portal/#!/login"
        def locator(self, selector):
            return Locator(self, selector)
        def wait_for_timeout(self, _):
            pass
    class Context:
        def route(self, _, guard):
            settings["guard"] = guard
        def new_page(self):
            return Page()
        def storage_state(self):
            return vpn_session
    class Browser:
        def new_context(self, **kwargs):
            settings.update(kwargs)
            return Context()
        def close(self):
            settings["closed"] = True
    def launch(**kwargs):
        settings.update(kwargs)
        return Browser()
    executable = tmp_path / "synthetic-browser"
    executable.touch()
    return SimpleNamespace(chromium=SimpleNamespace(executable_path=str(executable), launch=launch)), actions, settings


def test_browser_generates_fresh_code_submits_once_and_blocks_other_origins(app, vpn_session, tmp_path, monkeypatch):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    credentials = config.credentials(config.marker())
    fake, actions, settings = fake_browser(tmp_path, vpn_session)
    monkeypatch.setattr(webvpn, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(webvpn.time, "time", lambda: 59.0)
    state = automatic_login(credentials, lambda: None)
    assert state == vpn_session
    assert [a[0] for a in actions].count("password_submit") == 1
    assert [a[0] for a in actions].count("totp_submit") == 1
    assert ("fill", credentials.totp.at(59)) in actions
    assert settings["headless"] is True and settings["ignore_https_errors"] is False and settings["closed"]
    for url in ("http://webvpn.stu.edu.cn/login", "https://evil.example/steal", "https://webvpn.stu.edu.cn.evil.example/"):
        outcome = []
        route = SimpleNamespace(request=SimpleNamespace(url=url, method="POST", is_navigation_request=lambda: False),
                                abort=lambda result=outcome: result.append("blocked"),
                                continue_=lambda result=outcome: result.append("sent"))
        settings["guard"](route)
        assert outcome == ["blocked"]


@pytest.mark.parametrize("challenge", ["captcha", "binding"])
def test_browser_does_not_automate_captcha_or_totp_binding(app, vpn_session, tmp_path, monkeypatch, challenge):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    fake, actions, settings = fake_browser(tmp_path, vpn_session, **{challenge: True})
    monkeypatch.setattr(webvpn, "sync_playwright", lambda: nullcontext(fake))
    with pytest.raises(AppError) as error:
        automatic_login(config.credentials(config.marker()), lambda: None)
    assert error.value.code == "auto_login_interaction_required"
    assert not actions and settings["closed"]
