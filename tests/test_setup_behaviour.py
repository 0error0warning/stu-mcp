"""User-browser setup over private loopback HTTP; all school responses are synthetic."""
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from stu_mcp.auth_http import Candidate
from stu_mcp.runtime import AppError
from stu_mcp.setup_web import SetupServer


@pytest.fixture
def setup_page(app, monkeypatch):
    monkeypatch.setattr("stu_mcp.app.detected_clients", lambda: [])
    monkeypatch.setattr("stu_mcp.auth.interactive_login", lambda *_a, **_kw: pytest.fail("implicit server browser"))
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Chromium not installed; browser is a development-only test extra")
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        external = []

        def guard(route):
            if urlparse(route.request.url).hostname != "127.0.0.1":
                external.append(route.request.url)
                route.abort()
            else:
                route.continue_()

        context.route("**/*", guard)
        context.add_init_script("""const originalTimeout = window.setTimeout;
          window.setTimeout = (fn, delay, ...args) => originalTimeout(fn,
            [1500, 3000, 6000, 12000].includes(delay) ? 50 : delay, ...args);""")
        control = SimpleNamespace(home=app.runtime.home / "synthetic-checkin", status=lambda: {
            "ok": True, "status": "service_not_started", "logged_in": False,
            "service_running": False, "monitoring": False})
        ui = SetupServer(app, checkin=control)
        ui.jobs.checkin_preflight = lambda: None
        ui.start(open_browser=False)
        page = context.new_page()
        try:
            yield page, ui
            assert not external
        finally:
            context.close()
            browser.close()
            ui.close()


def fill_credentials(page):
    expect(page.locator("#credentials-form")).to_be_visible()
    page.locator("#login-user").fill("synthetic-student")
    page.locator("#login-pass").fill("SYNTHETIC_PRIVATE_PASSWORD")
    page.locator("#credentials-form button").click()


def begin_school(page, ui):
    page.goto(ui.url)
    page.locator('[data-login="school"]').click()
    page.locator('input[name="services"][value="jw"]').uncheck()
    page.locator("#school-options button").click()


def test_school_browser_setup_reuses_http_core_and_saves_each_session(setup_page, app, monkeypatch):
    page, ui = setup_page
    calls, inputs = [], []

    def protocol(source, username, password, **_):
        calls.append((source, username, password))
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    page.on("request", lambda req: inputs.append(req.post_data_json) if req.url.endswith("/api/login/input") else None)
    begin_school(page, ui)
    fill_credentials(page)
    expect(page.locator("#login-status")).to_contain_text("配置完成", timeout=12000)
    expect(page.locator("#login-results li")).to_have_count(2)
    assert [call[0] for call in calls] == ["mystu", "repair"]
    assert len(inputs) == 1 and inputs[0]["password"] == "SYNTHETIC_PRIVATE_PASSWORD"
    expect(page.locator("#login-pass")).to_have_value("")
    assert app.vault.status("mystu")["status"] == app.vault.status("repair")["status"] == "session_saved"
    page.reload()
    expect(page.locator("#school-state")).to_contain_text("MySTU：会话已保存")
    expect(page.locator("#school-state")).to_contain_text("宿舍报修：会话已保存")
    page.locator("#integration-gaps > summary").click()
    expect(page.locator('[data-service-id="campus_repair"]')).to_contain_text("仅入口导航")


def test_school_http_consent_is_explicit_and_does_not_change_preferences(setup_page, app, monkeypatch):
    page, ui = setup_page
    flags = []

    def protocol(source, *_args, legacy_jw=False, **_):
        flags.append((source, legacy_jw))
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    page.goto(ui.url)
    page.locator('[data-login="school"]').click()
    page.locator("#school-options button").click()
    expect(page.locator("#login-error")).to_contain_text("允许本次")
    assert not ui.jobs.snapshot() and not flags
    page.locator("#school-http").check()
    page.locator("#school-options button").click()
    fill_credentials(page)
    expect(page.locator("#login-status")).to_contain_text("配置完成", timeout=12000)
    assert flags == [("jw", True), ("mystu", False), ("repair", False)]
    assert not app.runtime.preferences()["jw_http_compat"]


def test_partial_school_failure_is_shown_per_business(setup_page, app, monkeypatch):
    page, ui = setup_page

    def protocol(source, *_args, **_):
        if source == "mystu":
            raise AppError("authentication_network_error", "synthetic private prose")
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    begin_school(page, ui)
    fill_credentials(page)
    expect(page.locator("#login-status")).to_contain_text("部分业务未完成")
    expect(page.locator("#login-results")).to_contain_text("MySTU：未完成")
    expect(page.locator("#login-results")).to_contain_text("宿舍报修：会话已保存")
    assert app.vault.status("repair")["status"] == "session_saved"
    assert "synthetic private prose" not in page.locator("#login-panel").inner_text()


def test_qr_stays_in_private_page_and_disappears_after_authorization(setup_page, app, monkeypatch):
    page, ui = setup_page
    complete = Event()

    def qr(*, show_qr, check, **_):
        show_qr("https://synthetic.invalid/PRIVATE_QR")
        assert complete.wait(5)
        check()
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.yuketang.acquire_state", qr)
    try:
        page.goto(ui.url)
        page.locator('[data-login="yuketang"]').click()
        expect(page.locator("#login-qr")).to_be_visible()
        assert page.locator("#login-qr").evaluate("image => image.complete && image.naturalWidth > 0")
        assert "qr" not in app.status()
        complete.set()
        expect(page.locator("#login-status")).to_contain_text("配置完成")
        assert page.locator("#login-qr").get_attribute("src") is None
    finally:
        complete.set()


def test_webvpn_prompts_for_credentials_then_current_code(setup_page, monkeypatch):
    page, ui = setup_page
    observed = []

    def protocol(*, username, password, totp_code, **_):
        observed.append((username, password, totp_code()))
        return {"cookies": [], "origins": []}, {"authenticated": True}

    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    page.goto(ui.url)
    page.locator('[data-login="webvpn"]').click()
    fill_credentials(page)
    expect(page.locator("#code-form")).to_be_visible()
    page.locator("#login-code").fill("123456")
    page.locator("#code-form button").click()
    expect(page.locator("#login-status")).to_contain_text("配置完成")
    assert observed == [("synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD", "123456")]
    expect(page.locator("#login-code")).to_have_value("")


def test_callback_is_private_and_uses_existing_worker_path_once(setup_page, monkeypatch):
    page, ui = setup_page
    callback = "https://www.duifene.com/?code=" + "a" * 32
    received = []
    def connected(value):
        received.append(value)
        ui.checkin.status = lambda: {"ok": True, "status": "paused", "logged_in": True,
                                    "service_running": True, "monitoring": False}
        return {"ok": True, "status": "paused", "logged_in": True, "login_outcome": "confirmed"}

    ui.checkin.connect_callback = connected
    page.goto(ui.url)
    page.locator('[data-login="duifene"]').click()
    expect(page.locator("#callback-form")).to_be_visible()
    assert page.locator("#callback-link").get_attribute("href").startswith("https://open.weixin.qq.com/")
    page.locator("#login-callback").fill(callback)
    page.locator("#callback-form button").click()
    expect(page.locator("#login-status")).to_contain_text("配置完成")
    expect(page.locator("#duifene-state")).to_have_text("会话已保存")
    assert received == [callback]
    expect(page.locator("#login-callback")).to_have_value("")
    assert callback not in str(ui.jobs.snapshot())


def test_cancel_clears_private_inputs_and_does_not_save_session(setup_page, app):
    page, ui = setup_page
    page.goto(ui.url)
    page.locator('[data-login="webvpn"]').click()
    expect(page.locator("#credentials-form")).to_be_visible()
    page.locator("#login-pass").fill("SYNTHETIC_UNSENT")
    page.locator("#login-cancel").click()
    expect(page.locator("#login-status")).to_contain_text("已停止后续认证")
    expect(page.locator("#login-pass")).to_have_value("")
    assert app.vault.status("webvpn")["status"] == "needs_login"
    page.locator('[data-login="yuketang"]').is_enabled()


@pytest.mark.parametrize("http_status", [403, 503])
def test_polling_is_bounded_when_private_status_becomes_unavailable(setup_page, monkeypatch, http_status):
    page, ui = setup_page
    complete, entered = Event(), Event()
    requests = []

    def qr(*, show_qr, **_):
        show_qr("SYNTHETIC_QR")
        entered.set()
        assert complete.wait(5)
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.yuketang.acquire_state", qr)
    page.goto(ui.url)
    page.locator('[data-login="yuketang"]').click()
    expect(page.locator("#login-qr")).to_be_visible()

    def status(route):
        requests.append(route.request.url)
        route.fulfill(status=http_status, json={"ok": False, "message": "Synthetic unavailable status"})

    page.route("**/api/status", status)
    try:
        deadline = monotonic() + 3
        expected = 1 if http_status == 403 else 6
        while len(requests) < expected and monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_timeout(180)
        assert len(requests) == expected
        assert page.locator("#login-qr").get_attribute("src") is None
    finally:
        complete.set()


def test_optional_webvpn_configuration_clears_inputs_after_rejected_save(setup_page, keys):
    page, ui = setup_page
    page.goto(ui.url)
    page.locator("#advanced-login > summary").click()
    page.locator("#vpn-auto-open").click()
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        page.locator("#" + field).fill("SYNTHETIC_UNSAVED_ONLY")
    page.locator("#vpn-totp").fill("123456")
    page.locator("#vpn-save").click()
    expect(page.locator("#toast")).to_have_attribute("role", "alert")
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        expect(page.locator("#" + field)).to_have_value("")
    assert keys.writes == 0


def test_cli_is_an_optional_choice_and_saved_sessions_are_not_live_claims(setup_page, app, session):
    page, ui = setup_page
    for source in ("jw", "mystu", "repair"):
        app.vault.save(source, session)
    page.goto(ui.url)
    expect(page.locator("#school-state")).to_contain_text("会话已保存")
    assert "当前可用" not in page.locator("#school-state").inner_text()
    page.locator("#advanced-login > summary").click()
    page.locator("#cli-open").click()
    expect(page.locator("#cli-panel")).to_contain_text("stu-mcp login school")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.parametrize("lost_path", ["/api/login", "/api/login/input"])
def test_lost_reply_recovers_by_reading_status_without_repeating_auth_input(setup_page, monkeypatch, lost_path):
    page, ui = setup_page
    posts, calls = [], []

    def protocol(source, *_args, **_):
        calls.append(source)
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    def lose_reply(route):
        posts.append(route.request.url)
        upstream = route.fetch()
        assert upstream.ok
        route.fulfill(status=503, json={"ok": False, "message": "Synthetic lost reply"})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    page.route("**" + lost_path, lose_reply)
    page.goto(ui.url)
    page.locator("#advanced-login > summary").click()
    page.locator("#school-sessions button").filter(has_text="重新登录").nth(1).click()
    fill_credentials(page)
    expect(page.locator("#login-status")).to_contain_text("配置完成", timeout=12000)
    assert len(posts) == 1 and calls == ["mystu"]
