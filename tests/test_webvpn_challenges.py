"""Real headless Chromium against synthetic login DOM; all requests are fulfilled."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from stu_mcp import webvpn
from stu_mcp.runtime import AppError
from stu_mcp.sources import OA_SECURE_PROXY
from stu_mcp.webvpn import WebVPNConfig, protected_access
from stu_mcp.webvpn import _browser_automatic_login as automatic_login

FIELDS = {"enabled": True, "username": "SYNTHETIC_USER", "password": "SYNTHETIC_PASSWORD",
          "totp": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"}  # RFC 6238 test vector.
CHALLENGES = {
    "randcode_component": '<div class="auto-input-randCode"><input id="random-code"></div>',
    "randcode_input": '<input data-input-ctr-value="randCode" id="random-code">',
    "randcode_image": '<img class="password__code__image" src="/offline-code-image" width="80" height="24">',
    "legacy_name": '<input name="captcha" id="random-code">',
    "legacy_id": '<input id="captcha-input">',
    "legacy_image": '<img src="/captcha-image" width="80" height="24">',
    "legacy_frame": '<iframe src="/recaptcha" width="80" height="24"></iframe>',
}


def login_document(challenge="", *, reveal_on_username=False, totp_challenge=False):
    reveal = "document.getElementById('challenge').hidden=false" if reveal_on_username else ""
    next_step = (
        "document.getElementById('password-form').remove();"
        "document.getElementById('totp-form').hidden=false;"
        "document.getElementById('challenge').hidden=false;"
        if totp_challenge else
        "document.getElementById('password-form').remove();"
        "document.cookie='offline_session=SYNTHETIC;path=/;Secure';location.hash='!/service';"
    )
    hidden = " hidden" if reveal_on_username or totp_challenge else ""
    return (
        '<!doctype html><meta charset="utf-8"><div id="password-form">'
        '<div id="sangfor_main_auth_container_password">'
        f'<input class="input-txt" type="text" id="offline-user" oninput="{reveal}">'
        '<input type="password" id="loginPwd"></div>'
        '<button class="button--normal" onclick="passwordLogin()">登录</button></div>'
        f'<div id="challenge"{hidden}>{challenge}</div>'
        '<div id="totp-form" data-dialog-ctr="totp_signature" hidden>'
        '<input class="input-txt" id="offline-totp">'
        '<button class="button--normal" onclick="fetch(\'/offline-totp\',{method:\'POST\'})">确定</button></div>'
        '<script>async function passwordLogin(){'
        "await fetch('/offline-password',{method:'POST',body:'synthetic=1'});"
        f'{next_step}'
        '}</script>'
    )


@pytest.fixture
def offline_browser(monkeypatch):
    evidence = SimpleNamespace(document="", requests=[], snapshots=[], launches=[])
    with sync_playwright() as real:
        if not Path(real.chromium.executable_path).is_file():
            pytest.skip("offline WebVPN challenge contract requires installed Chromium")

        def launch(**kwargs):
            evidence.launches.append(kwargs)
            browser = real.chromium.launch(**kwargs)
            pages = []

            def install(page):
                pages.append(page)
                page.add_init_script(
                    "window.offlineInputEvents=[];addEventListener('input',"
                    "e=>window.offlineInputEvents.push(e.target.id));"
                )

                def fulfill(route):
                    request = route.request
                    path = urlsplit(request.url).path
                    evidence.requests.append((request.method, path))
                    if request.method == "GET" and path == "/portal/":
                        route.fulfill(status=200, content_type="text/html", body=evidence.document)
                    elif request.method == "POST":
                        route.fulfill(status=200, content_type="application/json", body="{}")
                    else:
                        route.fulfill(status=200, content_type="text/html", body="<p>Synthetic resource</p>")

                # Page routes take precedence over the product's context guard.
                # This test checks DOM/challenge behavior; no request reaches STU.
                page.route("**/*", fulfill)

            def new_context(**settings):
                context = browser.new_context(**settings)
                context.on("page", install)
                return context

            def close():
                for page in pages:
                    if not page.is_closed():
                        evidence.snapshots.append(page.evaluate(
                            "({inputs:window.offlineInputEvents||[],filled:[...document.querySelectorAll('input')]"
                            ".filter(e=>e.value).map(e=>e.id)})"
                        ))
                browser.close()

            return SimpleNamespace(new_context=new_context, close=close)

        @contextmanager
        def playwright():
            yield SimpleNamespace(chromium=SimpleNamespace(
                executable_path=real.chromium.executable_path, launch=launch))

        monkeypatch.setattr(webvpn, "sync_playwright", playwright)
        # These DOM tests explicitly exercise the optional legacy backend. The
        # production default remains HTTP; accidental dispatch must not contact STU.
        monkeypatch.setattr(webvpn, "automatic_login", automatic_login)
        monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state",
                            lambda **_: pytest.fail("offline DOM test cannot start HTTP authentication"))
        yield evidence


@pytest.mark.parametrize("challenge", CHALLENGES.values(), ids=CHALLENGES)
def test_visible_challenge_pauses_before_any_credential_or_login_post(app, offline_browser, challenge):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    offline_browser.document = login_document(challenge)

    with pytest.raises(AppError) as error:
        protected_access(app.vault, OA_SECURE_PROXY + "/offline-protected", lambda _: pytest.fail("not authenticated"))

    assert error.value.code == "auto_login_interaction_required"
    assert config.status()["status"] == "paused"
    assert config.status()["reason"] == "auto_login_interaction_required"
    assert offline_browser.snapshots == [{"inputs": [], "filled": []}]
    assert not any(method == "POST" for method, _ in offline_browser.requests)
    assert offline_browser.launches[0]["headless"] is True
    assert not app.runtime.session_file("webvpn").exists()


@pytest.mark.parametrize("hidden", ['style="display:none"', 'style="visibility:hidden"', "hidden"])
def test_challenges_inside_hidden_ancestor_do_not_block_normal_login(app, offline_browser, hidden):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    challenge = f'<section {hidden}>' + "".join(CHALLENGES.values()) + "</section>"
    offline_browser.document = login_document(challenge)

    state = automatic_login(config.credentials(config.marker()), lambda: None)

    assert any(cookie["name"] == "offline_session" for cookie in state["cookies"])
    assert [(method, path) for method, path in offline_browser.requests if method == "POST"] == [
        ("POST", "/offline-password")]
    assert offline_browser.snapshots[0]["inputs"] == ["offline-user", "loginPwd"]


def test_challenge_appearing_after_username_stops_before_password(app, offline_browser):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    offline_browser.document = login_document(CHALLENGES["randcode_component"], reveal_on_username=True)

    with pytest.raises(AppError) as error:
        automatic_login(config.credentials(config.marker()), lambda: None)

    assert error.value.code == "auto_login_interaction_required"
    assert offline_browser.snapshots == [{"inputs": ["offline-user"], "filled": ["offline-user"]}]
    assert not any(method == "POST" for method, _ in offline_browser.requests)


def test_challenge_at_totp_stage_stops_before_dynamic_code(app, offline_browser):
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    offline_browser.document = login_document(CHALLENGES["randcode_input"], totp_challenge=True)

    with pytest.raises(AppError) as error:
        automatic_login(config.credentials(config.marker()), lambda: None)

    assert error.value.code == "auto_login_interaction_required"
    assert offline_browser.snapshots[0]["inputs"] == ["offline-user", "loginPwd"]
    assert not offline_browser.snapshots[0]["filled"]
    assert [(method, path) for method, path in offline_browser.requests if method == "POST"] == [
        ("POST", "/offline-password")]
