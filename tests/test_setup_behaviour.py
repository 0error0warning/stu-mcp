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

    def login(vault, service, on_phase):
        calls.append(service)
        on_phase("waiting_for_login")
        if not complete.wait(20):
            return {"ok": False, "message": "Synthetic test did not finish"}
        vault.save("mystu", session, on_relogin=lambda: app.store.forget("mystu"))
        return {"ok": True, "status": "session_saved"}

    monkeypatch.setattr("stu_mcp.auth.interactive_login", login)
    return complete, calls


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
        page.locator('[data-service="mystu"] .act').click()
        wait_for_requests(page, requests, failed_request)
        complete.set()
        expect(page.locator('[data-service="mystu"] .meta')).to_have_text("已登录", timeout=10000)
        expect(page.locator('[data-service="mystu"] .act')).to_be_enabled()
        assert calls == ["mystu"]
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
        page.locator('[data-service="mystu"] .act').click()
        expected = 2 if http_status == 403 else 7
        wait_for_requests(page, requests, expected)
        page.wait_for_timeout(250)
        assert len(requests) == expected and calls == ["mystu"]
    finally:
        complete.set()
