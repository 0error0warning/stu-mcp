"""Synthetic first-login proof and exact card HTTP exceptions; no school traffic."""
import io
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PIL import Image

from stu_mcp.auth_http import Credentials, login_http
from stu_mcp.auth_http.smartcard import CAPTCHA, HOME, LOGIN, PROFILE, acquire_state
from stu_mcp.auth_http.transport import HTTPFlow
from stu_mcp.network import CampusHTTP, checked_url
from stu_mcp.runtime import AppError

ACCOUNT, PASSWORD, CODE = "2099123456", "SYN123", "0246"
FORM = ('<form name="FormPost" method="post"><input name="name"><input name="passwd" type="password">'
        '<input name="loginType" value="2"><input name="userType" value="1"><input name="rand"></form>'
        '<script>function doSummit(){document.FormPost.action="loginstudent.action";}</script>')


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 4), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def profile(account=ACCOUNT):
    return ('<table><tr><td>学工号：</td><td>' + account + '</td></tr>'
            '<tr><td>余额</td><td>12.34元(卡余额)-5.60元(当前过渡余额)7.89元(上次过渡余额)</td></tr>'
            '<tr><td>卡状态</td><td>正常</td></tr></table>')


def protocol(*, form=FORM, image=None, media_type="image/png", login_html="<frameset></frameset>",
             identity=None, cookie=True, fail_post=False, after_post=None, after_profile=None):
    calls = []
    raw_image = image_bytes() if image is None else image

    def handle(request):
        calls.append(request)
        assert request.url.host == "smartcard.stu.edu.cn" and request.url.scheme == "http"
        if str(request.url) == HOME:
            headers = {"set-cookie": "JSESSIONID=SYNTHETIC_CARD_SESSION; Path=/; HttpOnly"} if cookie else {}
            return httpx.Response(200, text=form, headers=headers)
        if str(request.url) == CAPTCHA:
            return httpx.Response(200, content=raw_image, headers={"content-type": media_type})
        if str(request.url) == LOGIN:
            assert request.method == "POST"
            values = parse_qs(request.content.decode(), keep_blank_values=True)
            assert values == {"name": [ACCOUNT], "passwd": [PASSWORD], "rand": [CODE],
                              "loginType": ["2"], "userType": ["1"], "imageField.x": ["0"], "imageField.y": ["0"]}
            if after_post:
                after_post()
            if fail_post:
                raise httpx.ReadTimeout("SYNTHETIC_PRIVATE_TIMEOUT " + PASSWORD, request=request)
            return httpx.Response(200, text=login_html)
        if str(request.url) == PROFILE:
            if after_profile:
                after_profile()
            return httpx.Response(200, text=profile() if identity is None else identity)
        raise AssertionError("unexpected fixed card endpoint")

    return httpx.MockTransport(handle), calls


def interaction(captcha=None):
    return SimpleNamespace(credentials=lambda: Credentials(ACCOUNT, PASSWORD),
                           captcha=captcha or (lambda _image, **_: CODE))


def test_normal_js_action_login_requires_four_requests_image_and_own_profile():
    transport, calls = protocol()
    shown = []
    result = acquire_state(ACCOUNT, PASSWORD, captcha=lambda image, **kw: shown.append((image, kw)) or CODE,
                           check=lambda: None, transport=transport)
    assert [(r.method, str(r.url)) for r in calls] == [("GET", HOME), ("GET", CAPTCHA), ("POST", LOGIN), ("GET", PROFILE)]
    assert shown == [(image_bytes(), {"media_type": "image/png"})]
    assert result.proof == {"authenticated": True, "identity_matched": True, "transport": "http", "captcha_required": True}
    assert result.state["smartcard_account"] == ACCOUNT
    assert {c["name"] for c in result.state["cookies"]} == {"JSESSIONID"}
    assert PASSWORD not in repr(result)


def test_explicit_action_remains_supported_without_executing_script():
    transport, calls = protocol(form=FORM.replace('name="FormPost"', 'action="/loginstudent.action"').split("<script>")[0])
    assert acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport).proof["authenticated"]
    assert len(calls) == 4


def test_saved_card_state_is_encrypted_independent_and_contains_no_query_password(app):
    transport, _ = protocol()
    result = login_http(app.vault, "smartcard", interaction=interaction(), transport=transport)
    assert result["ok"] and result["service"] == "smartcard" and result["verified_live"]
    saved = app.vault.load("smartcard")
    assert saved["smartcard_account"] == ACCOUNT and PASSWORD not in json.dumps(saved)
    ciphertext = app.runtime.session_file("smartcard").read_bytes()
    assert ACCOUNT.encode() not in ciphertext and b"SYNTHETIC_CARD_SESSION" not in ciphertext
    assert PASSWORD.encode() not in ciphertext and PASSWORD not in json.dumps(result)
    assert app.vault.fingerprint("mystu") is None and app.vault.fingerprint("jw") is None


@pytest.mark.parametrize("code", ["123456", "abcd", "１２３４", ""], ids=["totp", "letters", "fullwidth", "empty"])
def test_invalid_captcha_answer_stops_before_password_post(code):
    transport, calls = protocol()
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=lambda _image, **_: code, check=lambda: None, transport=transport)
    assert error.value.code == "invalid_authentication_input"
    assert [r.method for r in calls] == ["GET", "GET"]


@pytest.mark.parametrize("image,media_type", [(b"", "image/png"), (b"x" * 65537, "image/png"),
                                             (b"private invalid image", "image/png"), (b"<svg/>", "image/svg+xml")],
                         ids=["empty", "oversized", "malformed", "svg"])
def test_changed_image_never_prompts_or_sends_password(image, media_type):
    transport, calls = protocol(image=image, media_type=media_type)
    shown = []
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=lambda *_a, **_kw: shown.append(1), check=lambda: None, transport=transport)
    assert error.value.code == "captcha_display_unavailable" and not shown
    assert len(calls) == 2 and not any(r.method == "POST" for r in calls)


@pytest.mark.parametrize("html,code", [("验证码错误：SYNTHETIC_PRIVATE_PROSE", "captcha_rejected"),
                                      ('<input type="password" name="passwd">', "login_rejected")])
def test_expired_challenge_or_rejected_password_is_one_post_only(app, html, code):
    transport, calls = protocol(login_html=html)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "smartcard", interaction=interaction(), transport=transport)
    assert error.value.code == code and "SYNTHETIC_PRIVATE_PROSE" not in error.value.message
    assert len([r for r in calls if r.method == "POST"]) == 1 and len(calls) == 3
    assert app.vault.fingerprint("smartcard") is None


def test_unknown_post_outcome_never_retries_or_saves_and_hides_provider_prose(app):
    transport, calls = protocol(fail_post=True)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "smartcard", interaction=interaction(), transport=transport)
    assert error.value.code == "authentication_outcome_unknown"
    assert PASSWORD not in str(error.value.result()) and "SYNTHETIC_PRIVATE_TIMEOUT" not in error.value.message
    assert len([r for r in calls if r.method == "POST"]) == 1 and app.vault.fingerprint("smartcard") is None


def test_human_cancelling_captcha_sends_no_password(app):
    transport, calls = protocol()
    def cancel(*_args, **_kwargs):
        raise AppError("operation_cancelled", "cancelled", "smartcard")
    with pytest.raises(AppError) as error:
        login_http(app.vault, "smartcard", interaction=interaction(cancel), transport=transport)
    assert error.value.code == "operation_cancelled" and len(calls) == 2
    assert app.vault.fingerprint("smartcard") is None


@pytest.mark.parametrize("stage,expected_requests", [("captcha", 2), ("post", 3), ("profile", 4), ("save", 4)])
def test_logout_generation_fence_prevents_inflight_login_from_restoring_session(app, monkeypatch, stage, expected_requests):
    def logout():
        app.vault.logout("smartcard")
    transport, calls = protocol(after_post=logout if stage == "post" else None,
                                after_profile=logout if stage == "profile" else None)
    def answer(_image, **_):
        if stage == "captcha":
            logout()
        return CODE
    if stage == "save":
        save = app.vault.save
        def guarded_save(*args, **kwargs):
            logout()
            return save(*args, **kwargs)
        monkeypatch.setattr(app.vault, "save", guarded_save)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "smartcard", interaction=interaction(answer), transport=transport)
    assert error.value.code == "session_changed" and len(calls) == expected_requests
    assert app.vault.fingerprint("smartcard") is None


@pytest.mark.parametrize("change", [lambda html: html.split("<script>")[0],
                                     lambda html: html.replace('method="post"', 'method="get"'),
                                     lambda html: html.replace('name="rand"', 'name="changed"'),
                                     lambda html: html.replace('name="FormPost"', 'action="http://evil.example/login"')])
def test_unknown_form_stops_before_challenge_or_credential_send(change):
    transport, calls = protocol(form=change(FORM))
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code == "authentication_schema_changed" and len(calls) == 1


@pytest.mark.parametrize("identity,cookie,code", [(profile("2099000000"), True, "session_invalid"),
                                                ("<frameset></frameset>", True, "schema_changed"),
                                                (profile(), False, "authentication_unconfirmed")],
                         ids=["other-account", "frameset-only", "no-cookie"])
def test_success_page_without_identity_and_reusable_session_is_not_authentication(app, identity, cookie, code):
    transport, calls = protocol(identity=identity, cookie=cookie)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "smartcard", interaction=interaction(), transport=transport)
    assert error.value.code == code and len(calls) == 4
    assert app.vault.fingerprint("smartcard") is None


@pytest.mark.parametrize("source,url,data", [
    ("mystu", "http://my.stu.edu.cn/login", {"username": ACCOUNT, "password": PASSWORD}),
    ("smartcard", "http://evil.example/login", {"name": ACCOUNT, "passwd": PASSWORD, "rand": CODE,
        "loginType": "2", "userType": "1", "imageField.x": "0", "imageField.y": "0"}),
    ("smartcard", HOME, {"name": ACCOUNT, "passwd": PASSWORD, "rand": CODE,
        "loginType": "2", "userType": "1", "imageField.x": "0", "imageField.y": "0"}),
    ("smartcard", LOGIN, {"username": ACCOUNT, "password": PASSWORD}),
    ("smartcard", LOGIN + "?next=x", {"name": ACCOUNT, "passwd": PASSWORD}),
])
def test_http_credential_exception_does_not_expand_to_other_services_or_payloads(source, url, data):
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))
    with HTTPFlow(source, (urlsplit(url).hostname,), allow_http=lambda _: True, transport=transport) as flow, pytest.raises(AppError) as error:
        flow.post(url, data=data, credential=True)
    assert error.value.code == "unsafe_authentication_request" and not calls


@pytest.mark.parametrize("suffix", ["/loginstudent.action", "/accounttodayTrjn.action", "/accountlostUser.action",
                                  "/accountcardUser.action?unknown=", "/accountcardUser.action?__continue=",
                                  "/accounthisTrjn.action?__continue=a&__continue=b",
                                  "/accounthisTrjn.action?ticket=private", "/accounthisTrjn.action;changed"])
def test_card_read_route_rejects_write_other_and_empty_unknown_query(suffix):
    with pytest.raises(AppError):
        checked_url("smartcard", "http://smartcard.stu.edu.cn" + suffix, authenticated=True)


def test_card_reads_only_send_own_host_cookie_and_never_post_credentials():
    def cookie(name, domain):
        return {"name": name, "value": "SYNTHETIC_" + name, "domain": domain, "path": "/", "expires": -1}
    state = {"cookies": [cookie("card", "smartcard.stu.edu.cn"), cookie("parent", ".stu.edu.cn"),
                         cookie("sso", "sso.stu.edu.cn")], "origins": [], "smartcard_account": ACCOUNT}
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, text="ok"))
    with CampusHTTP("smartcard", state, transport=transport) as client:
        client.request(PROFILE)
        client.request("http://smartcard.stu.edu.cn/accounthisTrjn.action?__continue=synthetic")
        with pytest.raises(AppError) as error:
            client.request(PROFILE, data={"passwd": PASSWORD})
    assert error.value.code == "insecure_password_form"
    assert len(calls) == 2 and all("card=SYNTHETIC_card" in r.headers["cookie"] for r in calls)
    assert all("parent" not in r.headers["cookie"] and "sso" not in r.headers["cookie"] for r in calls)
