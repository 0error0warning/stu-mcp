"""Private-page login orchestration using only synthetic interactions and proofs."""
import base64
import json
import time
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stu_mcp.auth_http import Candidate
from stu_mcp.runtime import AppError
from stu_mcp.setup_auth import SetupAuthJobs

PRIVATE = "SYNTHETIC_PRIVATE_VALUE"


def wait_for(jobs, predicate, *, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshots = jobs.snapshot()
        for snapshot in reversed(snapshots):
            if predicate(snapshot):
                return snapshot
        time.sleep(.005)
    raise AssertionError("Synthetic login did not reach expected state")


def challenge(jobs, kind):
    return wait_for(jobs, lambda job: job.get("challenge", {}).get("kind") == kind)


def finished(jobs):
    return wait_for(jobs, lambda job: job["status"] == "finished")


def answer(jobs, snapshot, **values):
    return jobs.submit_input(snapshot["id"], snapshot["challenge"]["id"], **values)


def test_page_credentials_only_enter_memory_then_existing_http_core(app, monkeypatch):
    observed = []

    def core(vault, service, *, interaction, check_cancelled, use_saved_credentials, **_):
        assert use_saved_credentials is False
        value = interaction.credentials()
        observed.append((service, value.username, value.password))
        check_cancelled()
        return {"ok": True, "status": "session_saved", "service": service, "verified_live": True,
                "proof": {"private": PRIVATE}, "message": PRIVATE, "cookies": PRIVATE}

    monkeypatch.setattr("stu_mcp.auth_http.login_http", core)
    jobs = SetupAuthJobs(app.vault)
    try:
        started = jobs.start("yuketang")
        prompt = challenge(jobs, "credentials")
        assert prompt["id"] == started["id"]
        assert PRIVATE not in json.dumps(jobs.snapshot())
        assert answer(jobs, prompt, username="synthetic-student", password=PRIVATE)["ok"]
        result = finished(jobs)
        assert observed == [("yuketang", "synthetic-student", PRIVATE)]
        assert result["result"]["status"] == "session_saved"
        assert "challenge" not in result and PRIVATE not in json.dumps(result)
        assert "challenge" not in json.dumps(app.status())
        assert jobs.tasks[0].input is None
    finally:
        jobs.close()


def test_secure_storage_failure_precedes_prompt_and_school_requests(app, monkeypatch):
    monkeypatch.setattr(app.vault, "_key", Mock(side_effect=AppError("secure_storage_unavailable", PRIVATE)))
    protocol = Mock(side_effect=AssertionError("no network before secure storage"))
    monkeypatch.setattr("stu_mcp.auth_http.yuketang.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("yuketang")
        view = finished(jobs)
        assert view["result"]["status"] == "secure_storage_unavailable"
        assert "challenge" not in view and PRIVATE not in json.dumps(view)
        protocol.assert_not_called()
    finally:
        jobs.close()


def test_cancel_during_protocol_prevents_actual_vault_save(app, monkeypatch, session):
    entered, release = Event(), Event()

    def protocol(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        return Candidate(session, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("school")
        prompt = challenge(jobs, "credentials")
        answer(jobs, prompt, username="synthetic-student", password=PRIVATE)
        assert entered.wait(3)
        jobs.cancel(prompt["id"])
        with pytest.raises(AppError, match="已有认证"):
            jobs.start("school")
        assert "challenge" not in jobs.snapshot()[0]
        release.set()
        assert finished(jobs)["result"]["status"] == "operation_cancelled"
        assert app.vault.fingerprint("mystu") is None
    finally:
        release.set()
        jobs.close()


def test_close_is_bounded_and_cancels_inflight_save(app, monkeypatch, session):
    entered, release = Event(), Event()

    def protocol(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        return Candidate(session, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    jobs.start("school")
    prompt = challenge(jobs, "credentials")
    answer(jobs, prompt, username="synthetic-student", password=PRIVATE)
    assert entered.wait(3)
    before = time.monotonic()
    jobs.close()
    assert time.monotonic() - before < .5
    with pytest.raises(AppError) as error:
        jobs.start("school")
    assert error.value.code == "setup_closed"
    release.set()
    assert finished(jobs)["result"]["status"] == "operation_cancelled"
    assert app.vault.fingerprint("mystu") is None


def test_school_page_uses_one_challenge_and_independent_real_core_saves(app, monkeypatch):
    calls = []
    monkeypatch.setattr("stu_mcp.auth_http.school.require_terminal", Mock(side_effect=AssertionError("web needs no TTY")))

    def protocol(source, username, password, **kwargs):
        kwargs["check"]()
        calls.append((source, username, password))
        host = {"jw": "jw.stu.edu.cn", "mystu": "my.stu.edu.cn", "repair": "repair.stu.edu.cn"}[source]
        state = {"cookies": [{"name": "session", "value": "SYNTHETIC_" + source,
                               "domain": host, "path": "/", "expires": -1}], "origins": []}
        return Candidate(state, {"authenticated": True})

    monkeypatch.setattr("stu_mcp.auth_http.cas.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("school")
        answer(jobs, challenge(jobs, "credentials"), username="synthetic-student", password=PRIVATE)
        view = finished(jobs)
        assert view["result"]["status"] == "school_login_complete"
        assert [item[0] for item in calls] == ["jw", "mystu", "repair"]
        assert len(view["results"]) == 3
        for source in ("jw", "mystu", "repair"):
            assert app.vault.status(source)["status"] == "session_saved"
        assert PRIVATE not in json.dumps(view)
    finally:
        jobs.close()


def test_old_or_duplicate_challenges_cannot_be_consumed(app, monkeypatch):
    def core(_vault, _service, *, interaction, **_):
        assert _.get("credentials").password == PRIVATE
        assert interaction.code() == "123456"
        return {"ok": True, "status": "session_saved"}

    monkeypatch.setattr("stu_mcp.auth_http.login_http", core)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        first = challenge(jobs, "webvpn_credentials")
        with pytest.raises(AppError) as wrong_kind:
            answer(jobs, first, code="123456")
        assert wrong_kind.value.code == "invalid_request"
        answer(jobs, first, username="synthetic-student", password=PRIVATE, totp="")
        second = challenge(jobs, "code")
        with pytest.raises(AppError) as duplicate:
            answer(jobs, first, username="synthetic-student", password=PRIVATE, totp="")
        assert duplicate.value.code == "invalid_challenge"
        with pytest.raises(AppError):
            answer(jobs, second, code="not-a-code")
        answer(jobs, second, code="123456")
        assert finished(jobs)["result"]["ok"]
    finally:
        jobs.close()


def test_qr_is_private_svg_cleared_on_finish_and_not_an_input_prompt(app, monkeypatch):
    release = Event()

    def core(_vault, _service, *, interaction, check_cancelled, **_):
        interaction.show_qr("SYNTHETIC_OFFICIAL_QR_CONTENT")
        assert release.wait(3)
        check_cancelled()
        return {"ok": True, "status": "session_saved"}

    monkeypatch.setattr("stu_mcp.auth_http.login_http", core)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("yuketang")
        prompt = challenge(jobs, "qr")
        image = prompt["challenge"]["image"]
        assert image.startswith("data:image/svg+xml;base64,")
        assert b"<svg" in base64.b64decode(image.split(",", 1)[1])
        with pytest.raises(AppError):
            answer(jobs, prompt, code="123456")
        assert "challenge" not in json.dumps(app.status())
        release.set()
        assert "challenge" not in finished(jobs)
        assert "data:image/" not in json.dumps(jobs.snapshot())
    finally:
        release.set()
        jobs.close()


def test_timeout_clears_pending_input_and_qr_then_keeps_bounded_history(app, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("stu_mcp.auth_http.login_http", lambda _v, _s, *, interaction, **_: interaction.credentials())
    jobs = SetupAuthJobs(app.vault, clock=lambda: clock[0], ttl=1)
    try:
        jobs.start("yuketang")
        prompt = challenge(jobs, "credentials")
        clock[0] = 2
        assert "challenge" not in jobs.snapshot()[0]
        assert finished(jobs)["result"]["status"] == "login_timeout"
        with pytest.raises(AppError):
            answer(jobs, prompt, username="synthetic-student", password=PRIVATE)
        clock[0] = 4
        assert jobs.snapshot() == []
    finally:
        jobs.close()


def test_duifene_preserves_original_callback_and_never_selects_or_starts_monitoring(app):
    callbacks = []
    control = SimpleNamespace(connect_callback=lambda link: callbacks.append(link) or {
        "ok": True, "status": "paused", "logged_in": True, "monitoring": False,
        "login_outcome": "confirmed", "courses": [{"private": PRIVATE}]})
    factory = Mock(return_value=control)
    jobs = SetupAuthJobs(app.vault, checkin_factory=factory, checkin_preflight=lambda: None)
    try:
        jobs.start("duifene")
        prompt = challenge(jobs, "callback")
        assert prompt["challenge"]["authorization_url"].startswith("https://open.weixin.qq.com/")
        factory.assert_not_called()
        answer(jobs, prompt, callback="https://www.duifene.com/?code=" + "A" * 32)
        view = finished(jobs)
        assert len(callbacks) == 1 and view["result"]["login_outcome"] == "confirmed"
        assert view["result"]["monitoring"] is False
        assert PRIVATE not in json.dumps(view) and "A" * 32 not in json.dumps(view)
    finally:
        jobs.close()


@pytest.mark.parametrize("existing", [False, True])
def test_duifene_preflight_uses_worker_storage_scope_without_mcp_key_or_worker(app, monkeypatch, tmp_path, existing):
    home = tmp_path / "synthetic-checkin"
    home.mkdir()
    state = home / "state.enc"
    if existing:
        state.write_bytes(b"SYNTHETIC_ENCRYPTED_STATE")
    store = SimpleNamespace(path=state, _cipher=Mock())
    factory = Mock(return_value=store)
    monkeypatch.setattr("stu_checkin.storage.default_home", lambda: home)
    monkeypatch.setattr("stu_checkin.storage.SecureStore", factory)
    monkeypatch.setattr(app.vault, "_key", Mock(side_effect=AssertionError("not the worker credential scope")))
    worker = Mock(side_effect=AssertionError("no worker before valid callback"))
    jobs = SetupAuthJobs(app.vault, checkin_factory=worker)
    try:
        jobs.start("duifene")
        prompt = challenge(jobs, "callback")
        factory.assert_called_once_with(home)
        store._cipher.assert_called_once_with(create=not existing)
        worker.assert_not_called()
        jobs.cancel(prompt["id"])
        assert finished(jobs)["result"]["status"] == "operation_cancelled"
    finally:
        jobs.close()


def test_duifene_storage_failure_precedes_callback_prompt(app, monkeypatch, tmp_path):
    from stu_checkin.storage import StorageError
    store = SimpleNamespace(path=tmp_path / "state.enc", _cipher=Mock(side_effect=StorageError(PRIVATE)))
    monkeypatch.setattr("stu_checkin.storage.SecureStore", lambda _home: store)
    worker = Mock(side_effect=AssertionError("no worker on storage failure"))
    jobs = SetupAuthJobs(app.vault, checkin_factory=worker)
    try:
        jobs.start("duifene")
        result = finished(jobs)
        assert result["result"]["status"] == "secure_storage_unavailable"
        assert "challenge" not in result and PRIVATE not in json.dumps(result)
        worker.assert_not_called()
    finally:
        jobs.close()


def test_cancel_after_callback_send_does_not_claim_retraction_or_retry(app):
    entered, release = Event(), Event()
    calls = []

    def connect(link):
        calls.append(link)
        entered.set()
        assert release.wait(3)
        return {"ok": False, "status": "query_error", "login_outcome": "unknown"}

    jobs = SetupAuthJobs(app.vault, checkin_factory=lambda: SimpleNamespace(connect_callback=connect),
                         checkin_preflight=lambda: None)
    try:
        jobs.start("duifene")
        prompt = challenge(jobs, "callback")
        answer(jobs, prompt, callback="https://www.duifene.com/?code=" + "B" * 32)
        assert entered.wait(3)
        jobs.cancel(prompt["id"])
        release.set()
        result = finished(jobs)["result"]
        assert result["status"] == "authentication_outcome_unknown" and len(calls) == 1
        assert result["cancellation_requested"] and "不能撤回" in result["message"]
    finally:
        release.set()
        jobs.close()


def test_invalid_callback_does_not_start_worker_or_repeat(app):
    factory = Mock(side_effect=AssertionError("invalid callback must not create worker"))
    jobs = SetupAuthJobs(app.vault, checkin_factory=factory, checkin_preflight=lambda: None)
    try:
        jobs.start("duifene")
        answer(jobs, challenge(jobs, "callback"), callback="https://untrusted.example/?code=" + "A" * 32)
        assert finished(jobs)["result"]["status"] == "invalid_callback"
        factory.assert_not_called()
    finally:
        jobs.close()


@pytest.mark.parametrize("service,options", [("mystu", {}), ("jw", {}), ("repair", {}), ("oa", {}),
    ("school", {"services": ["jw"]}), ("school", {"allow_http_callback": True}),
    ("webvpn", {"backend": "browser"}), ("yuketang", {"reauthenticate": True}),
    ("school", {"reauthenticate": "true"})])
def test_private_setup_exposes_only_profile_http_flows(app, monkeypatch, service, options):
    protocol = Mock(side_effect=AssertionError("invalid options must not authenticate"))
    monkeypatch.setattr("stu_mcp.auth_http.login_http", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        with pytest.raises((AppError, TypeError)):
            jobs.start(service, **options)
        assert jobs.snapshot() == []
        protocol.assert_not_called()
    finally:
        jobs.close()


def test_finished_history_is_bounded_and_opaque_exception_is_sanitized(app, monkeypatch):
    monkeypatch.setattr("stu_mcp.auth_http.login_http", Mock(side_effect=ValueError(PRIVATE)))
    jobs = SetupAuthJobs(app.vault)
    try:
        for _ in range(4):
            task = jobs.start("yuketang")
            wait_for(jobs, lambda row, task_id=task["id"]: row["id"] == task_id and row["status"] == "finished")
        assert len(jobs.snapshot()) == 2
        assert PRIVATE not in json.dumps(jobs.snapshot())
    finally:
        jobs.close()


VPN_SEED = base64.b32encode(b"12345678901234567890").decode()  # RFC 6238 synthetic vector.


def test_webvpn_primary_form_saves_token_and_logs_in_without_manual_code(app, monkeypatch, session, keys):
    from stu_mcp.webvpn import KEYRING_SERVICE, WebVPNConfig
    monkeypatch.setattr("time.time", lambda: 1700000000.0)  # Keep this fixture away from the rotation boundary.
    session["cookies"][0]["domain"] = "webvpn.stu.edu.cn"
    calls = []

    def protocol(*, username, password, totp_code, check, **_):
        check()
        assert username == "synthetic-student" and password == PRIVATE
        code = totp_code()
        assert len(code) == 6 and code.isdigit()
        calls.append(code)
        return session, {"authentication_verified": True}

    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        prompt = challenge(jobs, "webvpn_credentials")
        answer(jobs, prompt, username="synthetic-student", password=PRIVATE, totp=VPN_SEED)
        view = finished(jobs)
        assert view["result"]["status"] == "session_saved" and len(calls) == 1
        assert WebVPNConfig(app.vault).status()["enabled"]
        assert app.vault.status("webvpn")["status"] == "session_saved"
        assert (KEYRING_SERVICE, app.vault.account) in keys.values
        public = json.dumps([view, app.status()])
        files = b"".join(path.read_bytes() for path in app.runtime.home.rglob("*") if path.is_file())
        for secret in (PRIVATE, VPN_SEED, "synthetic-student"):
            assert secret not in public and secret.encode() not in files
        jobs.start("webvpn")
        wait_for(jobs, lambda item: item["id"] != prompt["id"] and item["status"] == "finished")
        assert len(calls) == 2  # Explicit retry uses saved credentials, without new input.
        assert all("challenge" not in item for item in jobs.snapshot())
    finally:
        jobs.close()


@pytest.mark.parametrize("previous_auto_config", [False, True])
def test_webvpn_blank_token_retains_manual_code_and_does_not_save_password(
        app, monkeypatch, session, keys, previous_auto_config):
    from stu_mcp.webvpn import KEYRING_SERVICE, WebVPNConfig
    session["cookies"][0]["domain"] = "webvpn.stu.edu.cn"
    if previous_auto_config:
        WebVPNConfig(app.vault).configure({"enabled": True, "username": "previous",
                                          "password": "PREVIOUS_SYNTHETIC_PASSWORD", "totp": VPN_SEED})

    def protocol(*, totp_code, **_):
        assert totp_code() == "123456"
        return session, {"authentication_verified": True}

    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn", reauthenticate=previous_auto_config)
        answer(jobs, challenge(jobs, "webvpn_credentials"), username="synthetic", password=PRIVATE, totp="")
        answer(jobs, challenge(jobs, "code"), code="123456")
        assert finished(jobs)["result"]["ok"]
        assert not WebVPNConfig(app.vault).status()["configured"]
        assert (KEYRING_SERVICE, app.vault.account) not in keys.values
    finally:
        jobs.close()


def test_webvpn_reconfiguration_prompts_and_invalid_token_is_not_consumed(app, monkeypatch):
    from stu_mcp.webvpn import WebVPNConfig
    config = WebVPNConfig(app.vault)
    config.configure({"enabled": True, "username": "previous", "password": PRIVATE, "totp": VPN_SEED})
    previous = config.marker()["id"]
    protocol = Mock(side_effect=AssertionError("no authentication before valid input"))
    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn", reauthenticate=True)
        prompt = challenge(jobs, "webvpn_credentials")
        with pytest.raises(AppError) as invalid:
            answer(jobs, prompt, username="synthetic", password=PRIVATE, totp="123456")
        assert invalid.value.code == "invalid_totp"
        assert jobs.snapshot()[0]["challenge"]["id"] == prompt["challenge"]["id"]
        jobs.cancel(prompt["id"])
        assert finished(jobs)["result"]["status"] == "operation_cancelled"
        assert config.marker()["id"] == previous
        protocol.assert_not_called()
    finally:
        jobs.close()


@pytest.mark.parametrize("failure", [None, "auto_login_failed"])
def test_webvpn_disabled_or_paused_configuration_prompts_without_reading_saved_secrets(app, monkeypatch, failure):
    from stu_mcp.webvpn import WebVPNConfig
    config = WebVPNConfig(app.vault)
    config.configure({"enabled": True, "username": "synthetic", "password": PRIVATE, "totp": VPN_SEED})
    config._write({**config.marker(), "enabled": False, "failure": failure})
    saved = Mock(side_effect=AssertionError("disabled credential record must not be loaded"))
    protocol = Mock(side_effect=AssertionError("disabled config requires fresh human input"))
    monkeypatch.setattr(WebVPNConfig, "credentials", saved)
    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        prompt = challenge(jobs, "webvpn_credentials")
        assert "username" not in prompt["challenge"] and "totp" not in prompt["challenge"]
        jobs.cancel(prompt["id"])
        assert finished(jobs)["result"]["status"] == "operation_cancelled"
        saved.assert_not_called()
        protocol.assert_not_called()
    finally:
        jobs.close()


def test_webvpn_logout_during_prompt_prevents_configuration_resurrection(app, monkeypatch, keys):
    from stu_mcp.webvpn import KEYRING_SERVICE, WebVPNConfig
    protocol = Mock(side_effect=AssertionError("logout fences new credentials"))
    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        prompt = challenge(jobs, "webvpn_credentials")
        app.logout("webvpn")
        answer(jobs, prompt, username="synthetic", password=PRIVATE, totp=VPN_SEED)
        assert finished(jobs)["result"]["status"] == "session_changed"
        assert not WebVPNConfig(app.vault).status()["configured"]
        assert (KEYRING_SERVICE, app.vault.account) not in keys.values
        protocol.assert_not_called()
    finally:
        jobs.close()


@pytest.mark.parametrize("mutation", ["cancel", "logout", "replace", "remove"])
def test_webvpn_inflight_changes_fence_session_save(app, monkeypatch, session, mutation):
    from stu_mcp.webvpn import WebVPNConfig
    entered, release = Event(), Event()
    session["cookies"][0]["domain"] = "webvpn.stu.edu.cn"

    def protocol(**_):
        entered.set()
        assert release.wait(3)
        return session, {"authentication_verified": True}

    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", protocol)
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        prompt = challenge(jobs, "webvpn_credentials")
        answer(jobs, prompt, username="synthetic", password=PRIVATE, totp=VPN_SEED)
        assert entered.wait(3)
        if mutation == "cancel":
            jobs.cancel(prompt["id"])
        elif mutation == "logout":
            app.logout("webvpn")
        elif mutation == "remove":
            WebVPNConfig(app.vault).remove()
        else:
            WebVPNConfig(app.vault).configure({"enabled": True, "username": "changed",
                                              "password": PRIVATE, "totp": VPN_SEED})
        release.set()
        expected = "operation_cancelled" if mutation == "cancel" else "session_changed"
        assert finished(jobs)["result"]["status"] == expected
        assert app.vault.fingerprint("webvpn") is None
    finally:
        release.set()
        jobs.close()


@pytest.mark.parametrize("code", ["auto_login_failed", "auto_login_interaction_required",
                                 "authentication_outcome_unknown"])
def test_webvpn_rejected_or_unknown_outcome_pauses_future_automatic_attempts(app, monkeypatch, code):
    from stu_mcp.webvpn import WebVPNConfig
    monkeypatch.setattr("stu_mcp.auth_http.webvpn.acquire_state", Mock(
        side_effect=AppError(code, PRIVATE, "oa")))
    jobs = SetupAuthJobs(app.vault)
    try:
        jobs.start("webvpn")
        answer(jobs, challenge(jobs, "webvpn_credentials"), username="synthetic", password=PRIVATE, totp=VPN_SEED)
        result = finished(jobs)["result"]
        assert result["status"] == code and PRIVATE not in json.dumps(result)
        assert WebVPNConfig(app.vault).status()["status"] == "paused"
        assert app.vault.fingerprint("webvpn") is None
    finally:
        jobs.close()
