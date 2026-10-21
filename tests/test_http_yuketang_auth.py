"""Offline protocol tests. Every account value and request is synthetic."""
from __future__ import annotations

import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from stu_mcp.auth_http import yuketang
from stu_mcp.auth_http.types import Candidate
from stu_mcp.runtime import AppError

QR = "SYNTHETIC_PRIVATE_QR_CONTENT"
TOKEN = "SYNTHETIC_PRIVATE_QR_TOKEN"
AUTH = "SYNTHETIC_PRIVATE_AUTH"
USER = "synthetic-user"
COOKIE = "SYNTHETIC_PRIVATE_COOKIE"
CSRF = "SYNTHETIC_PRIVATE_CSRF"
BEARER = "SYNTHETIC_PRIVATE_BEARER"
SECRETS = (QR, TOKEN, AUTH, USER, COOKIE, CSRF, BEARER, "SYNTHETIC_PRIVATE_METADATA")
URLS = (yuketang.ISSUE_URL, yuketang.WAIT_URL, yuketang.EXCHANGE_URL,
        yuketang.BINDING_URL, yuketang.COURSES_URL)


def row(identity=7, term=202601):
    return {"classroom_id": identity, "term": term, "course": {"name": "合成课程"}}


class Protocol:
    def __init__(self):
        self.sent = []
        self.responses = {
            "issue": {"code": 0, "msg": "SYNTHETIC_PRIVATE_METADATA", "data": {
                "qrContent": QR, "qrImage": "", "token": TOKEN}},
            "wait": {"code": 0, "data": {"UserID": USER, "Auth": AUTH,
                "Name": "SYNTHETIC_PRIVATE_METADATA", "Nickname": "SYNTHETIC_PRIVATE_METADATA",
                "Avatar": "SYNTHETIC_PRIVATE_METADATA"}},
            "exchange": {"success": True, "data": {}, "user_id": 123, "user_role": 2},
            "binding": {"success": True, "bind": True},
            "proof": {"errcode": 0, "errmsg": "SYNTHETIC_PRIVATE_METADATA", "data": {"list": [row()]}},
        }
        self.status = {}
        self.errors = {}
        self.headers = {
            "issue": {"set-auth": BEARER},
            "wait": [("set-cookie", f"sessionid={COOKIE}; Secure; HttpOnly; Path=/"),
                     ("set-cookie", f"csrftoken={CSRF}; Secure; Path=/")],
        }
        self.observer = lambda _phase: None

    def handle(self, request):
        # An added/redirected endpoint is a test failure, even on the same host.
        phase = dict(zip(URLS, self.responses, strict=True))[str(request.url)]
        self.sent.append((phase, request))
        self.observer(phase)
        if phase in self.errors:
            raise self.errors[phase]
        return httpx.Response(self.status.get(phase, 200),
                              headers=self.headers.get(phase, {}), json=self.responses[phase])

    @property
    def phases(self):
        return [phase for phase, _request in self.sent]

    def acquire(self, **kwargs):
        return yuketang.acquire_state(show_qr=kwargs.pop("show_qr", lambda _content: None),
                                      transport=httpx.MockTransport(self.handle), **kwargs)


@pytest.fixture
def protocol():
    return Protocol()


def assert_private(value):
    serialized = str(value)
    assert all(secret not in serialized for secret in SECRETS)


def test_official_once_only_sequence_private_callback_and_positive_proof(protocol, capsys, caplog):
    shown = []
    caplog.set_level(logging.DEBUG)
    result = protocol.acquire(show_qr=shown.append)
    assert isinstance(result, Candidate)
    assert shown == [QR]
    assert protocol.phases == ["issue", "wait", "exchange", "binding", "proof"]
    assert [request.method for _, request in protocol.sent] == ["GET", "POST", "POST", "GET", "GET"]
    assert result.proof == {
        "authenticated": True, "endpoint": "student_courses", "response_course_count": 1,
        "response_list_empty": False,
        "inventory": {"complete": True, "empty": False, "course_count": 1, "semester": "202601"},
    }
    assert result.state["yuketang_authorization"] == "Bearer " + BEARER
    assert {cookie["name"] for cookie in result.state["cookies"]} == {"sessionid", "csrftoken"}
    assert all(cookie["domain"] == yuketang.HOST for cookie in result.state["cookies"])
    assert result.state["origins"] == []
    assert_private(repr(result))
    assert_private(result.proof)
    assert capsys.readouterr() == ("", "")
    assert_private(caplog.text)


def test_exchange_preserves_official_raw_json_form_content_type_and_csrf(protocol):
    protocol.acquire()
    requests = dict(protocol.sent)
    wait, exchange, proof = (requests[phase] for phase in ("wait", "exchange", "proof"))
    assert json.loads(wait.content) == {"token": TOKEN}
    assert wait.headers["content-type"] == "application/json"
    assert exchange.content == json.dumps({"UserID": USER, "Auth": AUTH}, separators=(",", ":")).encode()
    assert exchange.headers["content-type"] == "application/x-www-form-urlencoded"
    assert exchange.headers["X-Requested-With"] == "XMLHttpRequest"
    assert exchange.headers["X-CSRFToken"] == CSRF
    assert proof.headers["authorization"] == "Bearer " + BEARER
    assert all("authorization" not in request.headers for phase, request in protocol.sent if phase != "proof")
    assert all(request.url.scheme == "https" and request.url.host == yuketang.HOST
               for _, request in protocol.sent)


@pytest.mark.parametrize("data", [
    {"UserID": None, "Auth": None, "user_id": USER, "auth": AUTH},
    {"UserID": USER, "Auth": AUTH, "user_id": USER, "auth": AUTH},
])
def test_observed_aliases_fallback_or_agree(protocol, data):
    protocol.responses["wait"]["data"] = data
    assert protocol.acquire().proof["authenticated"]


@pytest.mark.parametrize("data", [
    {"UserID": USER, "Auth": AUTH, "user_id": "other"},
    {"UserID": USER, "Auth": AUTH, "auth": "other"},
    {"UserID": 1, "user_id": True, "Auth": AUTH},
    {"UserID": USER}, {"Auth": AUTH},
    {"UserID": True, "Auth": AUTH},
    {"UserID": [], "Auth": AUTH},
    {"UserID": USER, "Auth": {}},
    {"UserID": USER, "Auth": ""},
    {"UserID": "user/other", "Auth": AUTH},
    "SYNTHETIC_PRIVATE_METADATA",
])
def test_conflicting_incomplete_or_changed_credentials_stop_before_exchange(protocol, data):
    protocol.responses["wait"]["data"] = data
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "schema_changed"
    assert protocol.phases == ["issue", "wait"]
    assert_private(failure.value.result())


def test_official_no_credential_pair_branch_requires_binding_and_course_proof(protocol):
    protocol.responses["wait"]["data"] = {}
    result = protocol.acquire()
    assert protocol.phases == ["issue", "wait", "binding", "proof"]
    assert result.proof["authenticated"]


@pytest.mark.parametrize("phase, payload", [
    ("issue", {}), ("issue", {"code": True, "data": {}}),
    ("issue", {"code": "0", "data": {}}),
    ("wait", {"code": 0, "data": {}, "success": False}),
    ("wait", {"code": 0, "data": {}, "errcode": 9}),
    ("wait", {"code": 0, "data": {}, "success": 1}),
    ("exchange", {"data": {}}), ("exchange", {"success": 1}),
    ("exchange", {"success": True, "code": False}),
    ("exchange", {"success": True, "errcode": 12}),
    ("binding", {"bind": True}), ("binding", {"success": True, "bind": 1}),
    ("binding", {"success": True}), ("binding", {"success": False, "bind": True}),
])
def test_status_missing_conflicting_or_changed_never_proves_authentication(protocol, phase, payload):
    protocol.responses[phase] = payload
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert protocol.phases[-1] == phase
    assert "proof" not in protocol.phases
    assert_private(failure.value.result())


@pytest.mark.parametrize("phase", ["issue", "wait"])
@pytest.mark.parametrize("code", [50000, 50080])
def test_additional_challenges_stop_without_following_another_login_branch(protocol, phase, code):
    protocol.responses[phase] = {"code": code, "data": {"url": "SYNTHETIC_PRIVATE_METADATA"}}
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "interaction_required"
    assert protocol.phases[-1] == phase
    assert "exchange" not in protocol.phases


def test_unbound_account_never_binds_or_fetches_courses(protocol):
    protocol.responses["binding"] = {"success": True, "bind": False}
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "account_not_bound"
    assert protocol.phases == ["issue", "wait", "exchange", "binding"]


@pytest.mark.parametrize("payload", [
    {"data": {"list": []}},
    {"errcode": 0, "data": {"list": [7]}},
    {"errcode": 0, "data": {"list": [row(), row()]}},
    {"errcode": 0, "success": False, "data": {"list": []}},
    {"errcode": True, "data": {"list": []}},
    {"errcode": 0, "data": {"list": [{"classroom_id": 7, "name": ""}]}},
    {"errcode": 0, "data": {"list": [{"classroom_id": 7, "name": {"Auth": AUTH}}]}},
    {"errcode": 0, "data": {"list": [row(term=True)]}},
    {"errcode": 0, "data": {"list": "SYNTHETIC_PRIVATE_METADATA"}},
])
def test_course_proof_requires_explicit_success_and_every_row_valid(protocol, payload):
    protocol.responses["proof"] = payload
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert protocol.phases.count("proof") == 1
    assert_private(failure.value.result())


@pytest.mark.parametrize("marker", [{"errcode": 0}, {"code": "0"}, {"success": True}])
def test_valid_empty_inventory_can_prove_a_session_without_claiming_courses(protocol, marker):
    protocol.responses["proof"] = {**marker, "data": {"list": []}}
    result = protocol.acquire()
    assert result.proof["authenticated"]
    assert result.proof["response_list_empty"]
    assert result.proof["inventory"] == {"complete": True, "empty": True, "course_count": 0, "semester": None}


def test_partial_inventory_proves_session_but_preserves_incomplete_scope(protocol):
    protocol.responses["proof"] = {"errcode": 0, "data": {
        "has_more": True, "list": [row(6, 202502), row(7, 202601)]}}
    result = protocol.acquire()
    assert result.proof["response_course_count"] == 2
    assert result.proof["inventory"] == {
        "complete": False, "empty": False, "course_count": 1, "semester": "202601"}


@pytest.mark.parametrize("phase", ["wait", "exchange"])
def test_timeout_after_credential_post_is_unknown_and_never_replayed(protocol, phase, caplog):
    protocol.errors[phase] = httpx.ReadTimeout("SYNTHETIC_PRIVATE_METADATA")
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "authentication_outcome_unknown"
    assert protocol.phases[-1] == phase
    assert protocol.phases.count(phase) == 1
    assert_private(failure.value.result())
    assert_private(caplog.text)


@pytest.mark.parametrize("status", [204, 302, 500])
def test_unexpected_credential_response_status_is_unknown_without_redirect_or_replay(protocol, status):
    protocol.status["exchange"] = status
    protocol.headers["exchange"] = {"location": "https://unrelated.invalid/login"}
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "authentication_outcome_unknown"
    assert failure.value.http_status == status
    assert protocol.phases == ["issue", "wait", "exchange"]


@pytest.mark.parametrize("stop_at", ["before_issue", "display", "after_wait", "after_proof"])
def test_cancel_or_logout_fence_prevents_remaining_work_and_returned_candidate(protocol, stop_at):
    stopped = stop_at == "before_issue"

    def check():
        if stopped:
            raise AppError("session_changed", "合成退出栅栏。", "yuketang")

    def display(_content):
        nonlocal stopped
        stopped |= stop_at == "display"

    def observe(phase):
        nonlocal stopped
        stopped |= stop_at == "after_wait" and phase == "wait" or stop_at == "after_proof" and phase == "proof"

    protocol.observer = observe
    with pytest.raises(AppError) as failure:
        protocol.acquire(show_qr=display, check=check)
    assert failure.value.code == "session_changed"
    assert protocol.phases == {
        "before_issue": [], "display": ["issue"], "after_wait": ["issue", "wait"],
        "after_proof": ["issue", "wait", "exchange", "binding", "proof"],
    }[stop_at]


def test_keyboard_interrupt_in_private_display_does_not_start_wait(protocol):
    def display(_content):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        protocol.acquire(show_qr=display)
    assert protocol.phases == ["issue"]


@pytest.mark.parametrize("timeout", [True, 0, -1, float("inf"), float("nan"), "180"])
def test_invalid_budget_never_issues_qr(protocol, timeout):
    with pytest.raises(AppError) as failure:
        protocol.acquire(timeout=timeout)
    assert failure.value.code == "invalid_timeout"
    assert protocol.phases == []


def test_display_time_counts_towards_total_budget_without_new_qr(protocol, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(yuketang, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def display(_content):
        clock[0] += 2

    with pytest.raises(AppError) as failure:
        protocol.acquire(show_qr=display, timeout=1)
    assert failure.value.code == "authentication_budget"
    assert protocol.phases == ["issue"]


@pytest.mark.parametrize("key,value", [("qrContent", None), ("token", {}),
                                        ("qrContent", ""), ("token", "X" * 4097)])
def test_qr_contract_checked_before_display(protocol, key, value):
    protocol.responses["issue"]["data"][key] = value
    shown = []
    with pytest.raises(AppError) as failure:
        protocol.acquire(show_qr=shown.append)
    assert failure.value.code == "schema_changed"
    assert protocol.phases == ["issue"] and shown == []


def test_bearer_rotation_preserves_prefix_and_stays_out_of_public_proof(protocol):
    protocol.headers["wait"].append(("set-auth", "Bearer ROTATED_SYNTHETIC_TOKEN"))
    result = protocol.acquire()
    assert result.state["yuketang_authorization"] == "Bearer ROTATED_SYNTHETIC_TOKEN"
    assert dict(protocol.sent)["proof"].headers["authorization"] == "Bearer ROTATED_SYNTHETIC_TOKEN"
    assert "ROTATED_SYNTHETIC_TOKEN" not in str(result.proof)


@pytest.mark.parametrize("value", ["", "Bearer ", "a b", "X" * 8193, "合成令牌"])
def test_invalid_auth_header_stops_without_displaying_qr(protocol, value):
    # HTTPX itself rejects non-Latin header strings; raw bytes model actual wire data.
    protocol.headers["issue"] = [(b"set-auth", value.encode("utf-8"))]
    shown = []
    with pytest.raises(AppError) as failure:
        protocol.acquire(show_qr=shown.append)
    assert failure.value.code == "schema_changed"
    assert shown == [] and protocol.phases == ["issue"]


def test_conflicting_auth_headers_stop_before_display(protocol):
    protocol.headers["issue"] = [("set-auth", "first"), ("set-auth", "second")]
    with pytest.raises(AppError) as failure:
        protocol.acquire()
    assert failure.value.code == "schema_changed"
    assert protocol.phases == ["issue"]


def test_protocol_does_not_mutate_input_payloads(protocol):
    original = deepcopy(protocol.responses)
    protocol.acquire()
    assert protocol.responses == original
