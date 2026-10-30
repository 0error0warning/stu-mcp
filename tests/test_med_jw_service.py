"""Synthetic medical timetable transport and session-lifecycle regressions."""
import json

import httpx
import pytest

from stu_mcp.features.med_jw.adapter import MedJwAdapter
from stu_mcp.features.med_jw.schema import MED_JW_TIMETABLE_BODY, MED_JW_TIMETABLE_URL
from stu_mcp.features.med_jw.service import academic_timetable
from stu_mcp.runtime import AppError, key_lock

TOKEN = "SYNTHETIC_MED_TOKEN_NEVER_REAL"


def state(token=TOKEN):
    return {"cookies": [], "origins": [], "med_jw_token": token}


def timetable(*, invalid_row=False):
    rows = [{"kcmc": "合成医学院课程", "teaxms": "合成教师", "jxcdmc": "101", "jzwmc": "合成楼",
             "szxqmc": "合成校区", "kcbh": "SYN-MED-1", "jxbmc": "合成班", "xq": 1, "zc": 2,
             "jcdm": "0102", "jcdm2": "01,02", "qssj": "08:00:00", "jssj": "09:40:00"}]
    if invalid_row:
        rows.append(rows[0] | {"kcbh": "SYN-MED-2", "zc": "unknown"})
    return {"code": 200, "xnxqdm": "SYN-MED-TERM", "xnxqmc": "学校原生学期", "zc": 2,
            "kbList": json.dumps([{"01": rows}, {}, {}, {}, {}, {}, {}])}


def test_read_uses_one_fixed_https_json_request_and_returns_no_token(app):
    app.vault.save("med_jw", state())
    seen = []

    def handle(request):
        seen.append(request)
        assert str(request.url) == MED_JW_TIMETABLE_URL
        assert request.method == "POST"
        assert json.loads(request.content) == MED_JW_TIMETABLE_BODY
        assert request.headers["token"] == TOKEN
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200, json=timetable())

    result = academic_timetable(app.vault, transport=httpx.MockTransport(handle))
    assert len(seen) == 1
    assert result["ok"] and result["status"] == "ok"
    assert result["source"] == "med_jw" and result["source_url"] == MED_JW_TIMETABLE_URL
    assert result["semester"] == "SYN-MED-TERM"
    assert result["cached"] is False and result["transport"] == "https"
    assert result["coverage"]["complete"] is True
    assert TOKEN not in json.dumps(result)
    assert result["courses"][0]["title"] == "合成医学院课程"


def test_partial_snapshot_keeps_valid_rows_and_declares_coverage(app):
    app.vault.save("med_jw", state())
    result = academic_timetable(app.vault, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=timetable(invalid_row=True))))
    assert result["ok"] and result["status"] == "partial"
    assert result["pending"] and result["coverage"]["complete"] is False
    assert len(result["courses"]) == 1


def test_explicit_empty_current_snapshot_is_a_success(app):
    app.vault.save("med_jw", state())
    result = academic_timetable(app.vault, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"code": 200, "kbList": [{}, {}, {}, {}, {}, {}, {}]})))
    assert result["ok"] and result["courses"] == []
    assert result["coverage"]["complete"] is True


@pytest.mark.parametrize("semester", ["2026-2027-1", "SYN-MED-TERM", " ", None, 42])
def test_cannot_claim_to_query_an_arbitrary_term_before_accessing_session(app, semester):
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, semester, transport=httpx.MockTransport(
            lambda _: pytest.fail("unsupported semester must not reach the network")))
    assert error.value.code == "unsupported_semester"


def test_main_campus_session_cannot_substitute_for_medical_session(app):
    app.vault.save("jw", {"cookies": [], "origins": []})
    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, transport=httpx.MockTransport(
            lambda _: pytest.fail("no medical session must not reach the network")))
    assert error.value.code == "needs_login" and error.value.source == "med_jw"


@pytest.mark.parametrize("token", [None, "", "has space", "line\r\nbreak", "汉字", "x" * 8193, 123])
def test_unusable_token_fails_before_constructing_request(token):
    with pytest.raises(AppError) as error:
        MedJwAdapter(state(token), transport=httpx.MockTransport(
            lambda _: pytest.fail("invalid token must not reach the network")))
    assert error.value.code == "session_invalid"
    if token:
        assert str(token) not in error.value.message


@pytest.mark.parametrize("status,body,expected", [
    (401, b"not-json", "login_expired"),
    (403, b"not-json", "login_expired"),
    (500, b"not-json", "source_error"),
    (200, b"not-json", "schema_changed"),
    (200, b'{"code":401}', "login_expired"),
    (200, b'{"code":501}', "login_expired"),
    (200, b'{"code":500}', "source_error"),
    (200, b'{"code":200}', "schema_changed"),
])
def test_errors_never_become_empty_success_or_echo_server_text(status, body, expected):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(status, content=body)

    with (MedJwAdapter(state(), transport=httpx.MockTransport(handle)) as adapter,
          pytest.raises(AppError) as error):
        adapter.timetable()
    assert error.value.code == expected and error.value.source == "med_jw"
    assert len(seen) == 1
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("target", [
    "https://external.example.invalid/steal",
    "https://jwgl.med.stu.edu.cn/dev-api/appapi/Studentxk/addxk",
    "http://jwgl.med.stu.edu.cn/dev-api/appapi/Studentkb/index",
    "https://sso.med.stu.edu.cn/cas/login",
])
def test_redirect_never_receives_token(target):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": target})

    with (MedJwAdapter(state(), transport=httpx.MockTransport(handle)) as adapter,
          pytest.raises(AppError) as error):
        adapter.timetable()
    assert error.value.code == "unexpected_redirect"
    assert seen == [MED_JW_TIMETABLE_URL]
    assert target not in error.value.message


def test_network_failure_is_not_retried_and_does_not_echo_request():
    seen = []

    def handle(request):
        seen.append(request)
        raise httpx.ReadTimeout("private server response " + TOKEN, request=request)

    with (MedJwAdapter(state(), transport=httpx.MockTransport(handle)) as adapter,
          pytest.raises(AppError) as error):
        adapter.timetable()
    assert error.value.code == "network_error"
    assert len(seen) == 1 and TOKEN not in str(error.value)


def test_body_budget_is_enforced():
    with (MedJwAdapter(state(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * 2_000_001))) as adapter,
          pytest.raises(AppError) as error):
        adapter.timetable()
    assert error.value.code == "response_limit"


@pytest.mark.parametrize("change", ["logout", "replace"])
def test_inflight_snapshot_is_discarded_after_session_change(app, change):
    app.vault.save("med_jw", state())

    def handle(_):
        if change == "logout":
            with key_lock(app.runtime.home, "med_jw"):
                app.vault.logout("med_jw")
        else:
            app.vault.save("med_jw", state("SYNTHETIC_OTHER_TOKEN"))
        return httpx.Response(200, json=timetable())

    with pytest.raises(AppError) as error:
        academic_timetable(app.vault, transport=httpx.MockTransport(handle))
    assert error.value.code == "session_changed"
    if change == "logout":
        assert app.vault.status("med_jw")["status"] == "needs_login"
    else:
        assert app.vault.load("med_jw")["med_jw_token"] == "SYNTHETIC_OTHER_TOKEN"


def test_medical_read_does_not_change_other_source_or_cache(app):
    app.vault.save("med_jw", state())
    app.vault.save("jw", {"cookies": [], "origins": []})
    main_fingerprint = app.vault.fingerprint("jw")
    medical_fingerprint = app.vault.fingerprint("med_jw")
    academic_timetable(app.vault, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=timetable())))
    assert app.vault.fingerprint("jw") == main_fingerprint
    assert app.vault.fingerprint("med_jw") == medical_fingerprint
