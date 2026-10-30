"""Synthetic medical local-password protocol; no live school credentials or I/O."""
import base64
import io
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from PIL import Image

from stu_mcp.auth_http import Credentials, login_http
from stu_mcp.auth_http.med_jw import acquire_state, rsa_password
from stu_mcp.features.med_jw.schema import (
    MED_JW_CAPTCHA_URL,
    MED_JW_INFO_URL,
    MED_JW_LOGIN_URL,
    MED_JW_TIMETABLE_BODY,
    MED_JW_TIMETABLE_URL,
)
from stu_mcp.runtime import AppError

ACCOUNT, PASSWORD, CODE, TOKEN = "2099123456", "SYNTHETIC_PASSWORD", "aB2c", "SYNTHETIC_MED_TOKEN"


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 40), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


def identity(account=ACCOUNT, *, student="0", token=TOKEN):
    return {"code": 200, "user": {"usertype": student, "userbh": account,
                                  "userAccount": account, "token": token}}


def timetable():
    return {"code": 200, "kbList": json.dumps([{} for _ in range(7)])}


def protocol(*, login=None, info=None, timetable_payload=None, image=None, media_type="image/jpeg",
             fail_post=False, redirect_stage=None, after_stage=None, verify_code=CODE):
    calls = []
    raw_image = image_bytes() if image is None else image
    captcha_stamp = None

    def handle(request):
        nonlocal captcha_stamp
        calls.append(request)
        assert request.url.host == "jwgl.med.stu.edu.cn" and request.url.scheme == "https"
        if str(request.url).startswith(MED_JW_CAPTCHA_URL + "?"):
            stage = "captcha"
            assert request.method == "GET" and "token" not in request.headers
            captcha_stamp = int(parse_qs(request.url.query.decode())["yzmcode"][0])
            response = httpx.Response(200, content=raw_image, headers={"content-type": media_type})
        elif str(request.url) == MED_JW_LOGIN_URL:
            stage = "login"
            assert request.method == "POST" and "token" not in request.headers
            body = json.loads(request.content)
            assert body.keys() == {"username", "password", "code", "appid", "yzmCode", "verifyCode"}
            assert body["username"] == ACCOUNT and body["yzmCode"] == captcha_stamp
            assert body["code"] == "" and body["appid"] is None and body["verifyCode"] == verify_code
            assert len(base64.b64decode(body["password"])) == 64 and PASSWORD not in request.content.decode()
            if fail_post:
                raise httpx.ReadTimeout("PRIVATE_TIMEOUT_" + PASSWORD, request=request)
            response = httpx.Response(200, json=identity() if login is None else login,
                                      headers={"set-cookie": "incidental=private; Secure; Path=/"})
        elif str(request.url) == MED_JW_INFO_URL:
            stage = "info"
            assert request.method == "GET" and request.headers["token"] == TOKEN
            assert "cookie" not in request.headers
            response = httpx.Response(200, json=identity() if info is None else info,
                                      headers={"set-cookie": "incidental=private; Secure; Path=/"})
        elif str(request.url) == MED_JW_TIMETABLE_URL:
            stage = "timetable"
            assert request.method == "POST" and request.headers["token"] == TOKEN
            assert "cookie" not in request.headers and json.loads(request.content) == MED_JW_TIMETABLE_BODY
            response = httpx.Response(200, json=timetable() if timetable_payload is None else timetable_payload)
        else:
            raise AssertionError("unexpected medical endpoint")
        if after_stage:
            after_stage(stage)
        if redirect_stage == stage:
            return httpx.Response(307, headers={"location": "https://external.invalid/credential-collector"})
        return response

    return httpx.MockTransport(handle), calls


def interaction(captcha=None):
    return SimpleNamespace(credentials=lambda: Credentials(ACCOUNT, PASSWORD),
                           captcha=captcha or (lambda _image, **_: CODE))


def test_new_token_requires_student_identity_and_actual_business_read():
    transport, calls = protocol()
    shown = []
    candidate = acquire_state(ACCOUNT, PASSWORD,
                              captcha=lambda image, **kw: shown.append((image, kw)) or CODE,
                              check=lambda: None, transport=transport)
    assert [r.method for r in calls] == ["GET", "POST", "GET", "POST"]
    assert shown == [(image_bytes(), {"media_type": "image/jpeg"})]
    assert candidate.state == {"cookies": [], "origins": [], "med_jw_token": TOKEN}
    assert candidate.proof == {"authenticated": True, "identity_matched": True, "student_identity": True,
                               "timetable_read": True, "transport": "https", "captcha_required": True}
    assert not any(value in json.dumps(candidate.proof) for value in (ACCOUNT, PASSWORD, CODE, TOKEN))


def test_rsa_wire_format_uses_randomized_padding_and_observed_byte_limit():
    first, second = rsa_password(PASSWORD), rsa_password(PASSWORD)
    assert len(base64.b64decode(first)) == len(base64.b64decode(second)) == 64
    assert first != second
    assert len(base64.b64decode(rsa_password("中" * 17))) == 64
    with pytest.raises(AppError) as error:
        rsa_password("中" * 18)
    assert error.value.code == "invalid_authentication_input"


@pytest.mark.parametrize("code", ["abc", "aB2c34", "１２３４", "", "a\nb2"])
def test_invalid_captcha_never_sends_credentials(code):
    transport, calls = protocol()
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=lambda _image, **_: code, check=lambda: None, transport=transport)
    assert error.value.code == "invalid_authentication_input" and len(calls) == 1


@pytest.mark.parametrize("payload,code", [
    ({**identity(), "code": 500}, "login_rejected"),
    ({"code": 500, "msg": "验证码已过期 PRIVATE_PROSE", "user": {"token": TOKEN}}, "captcha_rejected"),
    ({**identity(), "weakPass": 1}, "interaction_required"),
    ({**identity(), "initPw": 1}, "interaction_required"),
    ({**identity(), "twofactorAuth": 1}, "interaction_required"),
    (identity(student="1"), "authentication_unconfirmed"),
    (identity(student=False), "authentication_unconfirmed"),
    (identity("2099000000"), "authentication_identity_mismatch"),
    (identity(token=""), "authentication_unconfirmed"),
    (identity(token="private\r\nX-Inject: value"), "authentication_unconfirmed"),
    ({"code": True, "user": identity()["user"]}, "login_rejected"),
])
def test_token_is_not_success_without_valid_status_identity_and_completed_challenge(payload, code):
    transport, calls = protocol(login=payload)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code == code and len(calls) == 2
    assert not any(value in str(error.value.result()) for value in (TOKEN, PASSWORD, "PRIVATE_PROSE"))


@pytest.mark.parametrize("payload,code", [
    (identity("2099000000"), "authentication_identity_mismatch"),
    (identity(student="1"), "authentication_unconfirmed"),
    ({"code": 401, "msg": "PRIVATE_PROSE"}, "login_rejected"),
    ({"code": 200, "user": {}}, "authentication_unconfirmed"),
])
def test_get_info_must_prove_current_token_belongs_to_input_student(payload, code):
    transport, calls = protocol(info=payload)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code == code and len(calls) == 3


@pytest.mark.parametrize("payload", [
    {"code": 200}, {"code": 200, "kbList": "not-json"}, {"code": 200, "kbList": {}},
    {"code": 200, "kbList": [{"01": [{"kcmc": "Incomplete course"}]}] + [{}] * 6},
])
def test_unconfirmed_timetable_does_not_complete_login(payload):
    transport, calls = protocol(timetable_payload=payload)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code in {"authentication_schema_changed", "authentication_unconfirmed"}
    assert len(calls) == 4


@pytest.mark.parametrize("stage,count", [("captcha", 1), ("login", 2), ("info", 3), ("timetable", 4)])
def test_redirects_never_forward_tokens_or_credentials(stage, count):
    transport, calls = protocol(redirect_stage=stage)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code == "authentication_unconfirmed" and len(calls) == count


@pytest.mark.parametrize("raw_image,media_type", [(b"", "image/jpeg"), (b"x" * 65537, "image/jpeg"),
                                                  (b"not an image", "image/jpeg"), (b"<svg/>", "image/svg+xml")],
                         ids=["empty", "oversized", "malformed", "svg"])
def test_invalid_image_never_prompts_or_sends_password(raw_image, media_type):
    transport, calls = protocol(image=raw_image, media_type=media_type)
    shown = []
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=lambda *_a, **_kw: shown.append(1),
                      check=lambda: None, transport=transport)
    assert error.value.code == "captcha_display_unavailable" and len(calls) == 1 and not shown


def test_unknown_credential_post_outcome_is_not_retried_and_error_is_sanitized():
    transport, calls = protocol(fail_post=True)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=lambda: None, transport=transport)
    assert error.value.code == "authentication_outcome_unknown" and len(calls) == 2
    assert PASSWORD not in str(error.value.result()) and "PRIVATE_TIMEOUT" not in str(error.value.result())


@pytest.mark.parametrize("stage,count", [("captcha", 1), ("login", 2), ("info", 3), ("timetable", 4)])
def test_cancel_check_after_each_network_checkpoint(stage, count):
    cancelled = False
    def after_stage(current):
        nonlocal cancelled
        cancelled = current == stage
    def check():
        if cancelled:
            raise AppError("operation_cancelled", "cancelled", "med_jw")
    transport, calls = protocol(after_stage=after_stage)
    with pytest.raises(AppError) as error:
        acquire_state(ACCOUNT, PASSWORD, captcha=interaction().captcha, check=check, transport=transport)
    assert error.value.code == "operation_cancelled" and len(calls) == count


def test_shared_login_saves_only_independent_encrypted_medical_token(app):
    transport, _ = protocol()
    result = login_http(app.vault, "med_jw", interaction=interaction(), transport=transport)
    assert result["ok"] and result["service"] == "med_jw" and result["verified_live"]
    saved = app.vault.load("med_jw")
    assert saved["med_jw_token"] == TOKEN and not saved["cookies"]
    serialized = json.dumps(saved)
    assert PASSWORD not in serialized and ACCOUNT not in serialized
    encrypted = app.runtime.session_file("med_jw").read_bytes()
    assert TOKEN.encode() not in encrypted
    assert not any(value in json.dumps(result) for value in (TOKEN, PASSWORD, ACCOUNT))
    assert app.vault.fingerprint("jw") is None and app.vault.fingerprint("mystu") is None


@pytest.mark.parametrize("stage,count", [("captcha", 1), ("login", 2), ("info", 3), ("timetable", 4), ("save", 4)])
def test_shared_logout_fence_prevents_inflight_medical_login_restoring_token(app, monkeypatch, stage, count):
    transport, calls = protocol(after_stage=lambda current: app.vault.logout("med_jw") if current == stage else None)
    if stage == "save":
        save = app.vault.save
        def guarded_save(*args, **kwargs):
            app.vault.logout("med_jw")
            return save(*args, **kwargs)
        monkeypatch.setattr(app.vault, "save", guarded_save)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "med_jw", interaction=interaction(), transport=transport)
    assert error.value.code == "session_changed" and len(calls) == count
    assert app.vault.fingerprint("med_jw") is None


def wait_setup(jobs, *, kind=None):
    if kind is None:
        task = jobs.tasks[0]
        task.thread.join(timeout=10)
        snapshot = jobs.snapshot()[0]
        assert snapshot["status"] == "finished", "Synthetic medical login did not finish"
        return snapshot
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        snapshot = jobs.snapshot()[0]
        if snapshot.get("challenge", {}).get("kind") == kind:
            return snapshot
        assert snapshot["status"] != "finished", "Synthetic medical login ended before the expected challenge"
        time.sleep(.005)
    raise AssertionError("Synthetic medical login did not reach the expected state")


@pytest.mark.parametrize("answer", ["aB2c", "aB2c3"])
def test_private_setup_drives_real_medical_protocol_and_clears_completed_challenge(app, monkeypatch, answer):
    from stu_mcp.auth_http import med_jw
    from stu_mcp.setup_auth import SetupAuthJobs

    transport, calls = protocol(verify_code=answer)
    flow_class = med_jw.HTTPFlow
    monkeypatch.setattr(med_jw, "HTTPFlow", lambda *args, **kw: flow_class(*args, **(kw | {"transport": transport})))
    jobs = SetupAuthJobs(app.vault)
    try:
        started = jobs.start("med_jw")
        credentials = wait_setup(jobs, kind="credentials")
        assert credentials["id"] == started["id"] and calls == []
        jobs.submit_input(credentials["id"], credentials["challenge"]["id"], username=ACCOUNT, password=PASSWORD)
        captcha = wait_setup(jobs, kind="captcha")
        assert captcha["challenge"]["image"].startswith("data:image/jpeg;base64,")
        assert len(calls) == 1
        assert not any(secret in json.dumps(captcha) for secret in (ACCOUNT, PASSWORD, TOKEN))
        jobs.submit_input(captcha["id"], captcha["challenge"]["id"], code=answer)
        finished = wait_setup(jobs)
        assert finished["result"]["status"] == "session_saved" and len(calls) == 4
        assert "challenge" not in finished and jobs.tasks[0].input is None
        assert jobs.tasks[0].challenge is None
        assert not any(secret in json.dumps(finished) for secret in (ACCOUNT, PASSWORD, TOKEN, answer))
        assert app.vault.load("med_jw")["med_jw_token"] == TOKEN
    finally:
        jobs.close()


def test_private_setup_cancel_clears_medical_inputs_and_challenge_before_password_send(app, monkeypatch):
    from stu_mcp.auth_http import med_jw
    from stu_mcp.setup_auth import SetupAuthJobs

    transport, calls = protocol()
    flow_class = med_jw.HTTPFlow
    monkeypatch.setattr(med_jw, "HTTPFlow", lambda *args, **kw: flow_class(*args, **(kw | {"transport": transport})))
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("med_jw")
        credentials = wait_setup(jobs, kind="credentials")
        jobs.submit_input(credentials["id"], credentials["challenge"]["id"], username=ACCOUNT, password=PASSWORD)
        captcha = wait_setup(jobs, kind="captcha")
        jobs.cancel(captcha["id"])
        finished = wait_setup(jobs)
        assert finished["result"]["status"] == "operation_cancelled" and len(calls) == 1
        assert jobs.tasks[0].input is None and jobs.tasks[0].challenge is None
        assert "challenge" not in finished
        assert not any(secret in json.dumps(finished) for secret in (ACCOUNT, PASSWORD, TOKEN))
        assert app.vault.fingerprint("med_jw") is None
        with pytest.raises(AppError):
            jobs.submit_input(captcha["id"], captcha["challenge"]["id"], code=CODE)
    finally:
        jobs.close()
