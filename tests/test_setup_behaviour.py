"""Real local-page regressions with synthetic sessions; never contact school endpoints."""
from pathlib import Path
from threading import Event
from time import monotonic
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect, sync_playwright

from stu_mcp.setup_web import SetupServer


@pytest.fixture
def setup_page(app, monkeypatch):
    monkeypatch.setattr("stu_mcp.app.detected_clients", lambda: [])
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Chromium not installed; Linux Python 3.13 CI runs these browser regressions")
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
        ui = SetupServer(app)
        ui.start(open_browser=False)
        page = context.new_page()
        try:
            yield page, ui
            assert not external
        finally:
            context.close()
            browser.close()
            ui.close()


@pytest.mark.parametrize("close_action", ["cancel", "other_account"])
def test_cancel_or_switch_clears_unsaved_webvpn_fields(setup_page, keys, close_action):
    page, ui = setup_page
    page.goto(ui.url)
    page.locator("#advanced-login > summary").click()
    page.locator('[data-service="oa"] .act').click()
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        page.locator("#" + field).fill("SYNTHETIC_UNSAVED_ONLY")
    page.locator(f'[data-service="{"oa" if close_action == "cancel" else "jw"}"] .act').click()
    expect(page.locator("#panel-oa")).to_be_hidden()
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        expect(page.locator("#" + field)).to_have_value("")
    assert keys.writes == 0


def test_rejected_webvpn_save_clears_every_input(setup_page, keys):
    page, ui = setup_page
    page.goto(ui.url)
    page.locator("#advanced-login > summary").click()
    page.locator('[data-service="oa"] .act').click()
    page.locator("#vpn-user").fill("SYNTHETIC_STUDENT")
    page.locator("#vpn-pass").fill("SYNTHETIC_PASSWORD")
    page.locator("#vpn-totp").fill("123456")
    page.locator("#vpn-save").click()
    expect(page.locator("#toast")).to_have_attribute("role", "alert")
    for field in ("vpn-user", "vpn-pass", "vpn-totp"):
        expect(page.locator("#" + field)).to_have_value("")
    assert keys.writes == 0


def synthetic_login(monkeypatch, app, session):
    complete, calls = Event(), []

    def login(vault, service, on_phase, **_):
        calls.append(service)
        on_phase("waiting_for_login")
        if not complete.wait(20):
            return {"ok": False, "message": "Synthetic test did not finish"}
        state = {"cookies": [{**cookie, "domain": "webvpn.stu.edu.cn"} for cookie in session["cookies"]],
                 "origins": []}
        vault.save("webvpn", state, on_relogin=lambda: app.store.forget("oa"))
        return {"ok": True, "status": "session_saved"}

    monkeypatch.setattr("stu_mcp.auth.interactive_login", login)
    return complete, calls


def start_explicit_browser_login(page):
    page.locator('[data-service="oa"] .act').click()
    page.locator("#vpn-alt").click()


def wait_for_requests(page, requests, count):
    deadline = monotonic() + 8
    while len(requests) < count and monotonic() < deadline:
        page.wait_for_timeout(50)
    assert len(requests) >= count


@pytest.mark.parametrize("failed_request", [2, 3])
def test_login_finishes_after_one_status_read_failure(setup_page, app, session, monkeypatch, failed_request):
    page, ui = setup_page
    complete, calls = synthetic_login(monkeypatch, app, session)
    requests = []

    def status(route):
        requests.append(route.request.url)
        if len(requests) == failed_request:
            route.fulfill(status=503, json={"ok": False, "message": "Synthetic temporary failure"})
        else:
            route.continue_()

    page.route("**/api/status", status)
    try:
        page.goto(ui.url)
        page.locator("#advanced-login > summary").click()
        start_explicit_browser_login(page)
        wait_for_requests(page, requests, failed_request)
        complete.set()
        expect(page.locator('[data-service="oa"] .meta')).to_have_text("会话已保存，访问待核验", timeout=10000)
        expect(page.locator('[data-service="oa"] .act')).to_be_enabled()
        assert calls == ["oa"]
    finally:
        complete.set()


@pytest.mark.parametrize("http_status", [403, 503])
def test_status_retries_stop_on_forbidden_or_retry_budget(setup_page, app, session, monkeypatch, http_status):
    page, ui = setup_page
    complete, calls = synthetic_login(monkeypatch, app, session)
    requests = []
    # Accelerate only existing polling/backoff durations, keeping browser event ordering.
    page.add_init_script("""const originalTimeout = window.setTimeout;
      window.setTimeout = (fn, delay, ...args) => originalTimeout(fn,
        [1500, 3000, 6000, 12000].includes(delay) ? 30 : delay, ...args);""")

    def status(route):
        requests.append(route.request.url)
        if len(requests) > 1:
            route.fulfill(status=http_status, json={"ok": False, "message": "Synthetic unavailable status"})
        else:
            route.continue_()

    page.route("**/api/status", status)
    try:
        page.goto(ui.url)
        page.locator("#advanced-login > summary").click()
        start_explicit_browser_login(page)
        expected = 2 if http_status == 403 else 7
        wait_for_requests(page, requests, expected)
        page.wait_for_timeout(250)
        assert len(requests) == expected and calls == ["oa"]
    finally:
        complete.set()


def test_default_http_login_displays_host_command_without_browser_or_background_job(setup_page, monkeypatch):
    page, ui = setup_page
    monkeypatch.setattr("stu_mcp.auth.interactive_login", lambda *_args, **_kwargs: pytest.fail("implicit browser"))
    monkeypatch.setattr("stu_mcp.auth_http.login_http", lambda *_args, **_kwargs: pytest.fail("background credentials"))
    submitted = []

    def record(route):
        submitted.append(route.request.post_data_json)
        route.continue_()

    page.route("**/api/login", record)
    page.goto(ui.url)
    page.locator("#advanced-login > summary").click()
    page.locator('[data-service="mystu"] .act').click()
    expect(page.locator("#toast")).to_contain_text("stu-mcp login mystu")
    expect(page.locator("#toast")).to_have_attribute("role", "status")
    expect(page.locator('[data-service="mystu"] .act')).to_be_enabled()
    assert submitted == [{"service": "mystu", "backend": "http"}]
    assert ui.jobs.snapshot() == []


def test_configuration_view_has_one_school_entry_and_keeps_gaps_separate(setup_page, monkeypatch):
    page, ui = setup_page
    monkeypatch.setattr("stu_mcp.auth_http.login_school", lambda *_a, **_kw: pytest.fail("background credentials"))
    page.goto(ui.url)
    school = page.locator('[data-profile="school"]')
    expect(school).to_contain_text("成绩")
    expect(school).to_contain_text("作业")
    expect(school).to_contain_text("报修")
    expect(page.locator("#advanced-login")).not_to_have_attribute("open", "")
    school.locator("button").click()
    expect(page.locator("#login-command-text")).to_have_text("stu-mcp login school")
    expect(page.locator("#login-command-text")).to_be_visible()
    assert ui.jobs.snapshot() == []
    page.locator("#integration-gaps > summary").click()
    expect(page.locator('[data-service-id="campus_repair"]')).to_contain_text("业务未接入")
    expect(page.locator('[data-service-id="dorm_utilities"]')).to_contain_text("业务未接入")


def test_saved_school_sessions_are_not_shown_as_live_verified(setup_page, app, session):
    for source in ("jw", "mystu", "repair"):
        app.vault.save(source, session)
    page, ui = setup_page
    page.goto(ui.url)
    school = page.locator('[data-profile="school"]')
    expect(school.locator(".profile-sessions li")).to_have_count(3)
    expect(school.locator(".profile-sessions")).to_contain_text("会话已保存，访问待核验")
    page.locator("#integration-gaps > summary").click()
    expect(page.locator('[data-service-id="campus_repair"]')).to_contain_text("业务未接入")
