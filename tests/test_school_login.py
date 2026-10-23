"""Synthetic group orchestration; no real school credentials or requests."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stu_mcp import auth_http, cli, terminal
from stu_mcp.auth_http import Candidate, Credentials, cas, school
from stu_mcp.runtime import AppError

USERNAME, PASSWORD = "synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD"
HOSTS = {"jw": "jw.stu.edu.cn", "mystu": "my.stu.edu.cn", "repair": "repair.stu.edu.cn"}


@pytest.fixture
def human(monkeypatch):
    monkeypatch.setattr(school, "require_terminal", lambda: None)
    interaction = SimpleNamespace(credentials=Mock(return_value=Credentials(USERNAME, PASSWORD)))
    return interaction


def state(source, username=USERNAME):
    return {"cookies": [{"name": "business", "value": "SYNTHETIC_" + source.upper(),
                         "domain": HOSTS[source], "path": "/", "expires": -1,
                         "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": [],
            "school_account_fingerprint": school.school_account_fingerprint(username)}


def successful_protocol(monkeypatch, *, before=None, fail=None):
    calls = []

    def acquire(source, username, password, *, check, **kwargs):
        check()
        calls.append((source, username, password, kwargs["legacy_jw"]))
        if before:
            before(source)
        check()
        if fail and source in fail:
            raise AppError(fail[source], "合成认证错误", source)
        candidate = state(source)
        candidate.pop("school_account_fingerprint")
        if source == "repair":
            candidate["repair_sso_state"] = {"cookies": [], "origins": []}
        return Candidate(candidate, {"authenticated": True, "synthetic_proof": source})

    monkeypatch.setattr(cas, "acquire_state", acquire)
    return calls


def test_once_input_separate_sessions_proofs_cache_and_no_password_persistence(app, human, monkeypatch):
    for source in school.SCHOOL_SERVICES:
        app.vault.save(source, state(source, "old-student"))
        if source != "repair":
            app.store.save_batch(source, [{"id": source, "kind": "course", "title": "old"}], private=True)
    app.store.save_batch("public", [{"id": "public", "kind": "notice", "title": "public"}])
    calls = successful_protocol(monkeypatch)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["ok"] and result["status"] == "school_login_complete"
    assert human.credentials.call_count == 1
    assert [call[0] for call in calls] == list(school.SCHOOL_SERVICES)
    assert [call[3] for call in calls] == [True, False, False]
    assert all(call[1:3] == (USERNAME, PASSWORD) for call in calls)
    assert all(item["verified_live"] and item["proof"]["synthetic_proof"] == item["service"]
               for item in result["results"])
    for source in school.SCHOOL_SERVICES:
        saved = app.vault.load(source)
        assert {cookie["domain"] for cookie in saved["cookies"]} == {HOSTS[source]}
        assert saved["school_account_fingerprint"] == school.school_account_fingerprint(USERNAME)
        assert PASSWORD not in json.dumps(saved)
        assert USERNAME.encode() not in app.runtime.session_file(source).read_bytes()
        if source != "repair":
            assert not app.store.list(sources=(source,))["items"]
    assert "repair_sso_state" in app.vault.load("repair")
    assert "repair_sso_state" not in app.vault.load("mystu")
    assert app.store.list(sources=("public",))["items"]
    assert USERNAME not in json.dumps(result) and PASSWORD not in json.dumps(result)
    assert "school_account_fingerprint" not in json.dumps(result)


def test_same_account_saved_sessions_skip_only_local_check(app, human, monkeypatch):
    for source in school.SCHOOL_SERVICES:
        app.vault.save(source, state(source))
    calls = successful_protocol(monkeypatch)
    result = auth_http.login_school(app.vault, interaction=human)
    assert result["ok"] and not calls
    assert human.credentials.call_count == 1
    assert all(item["skipped"] and item["verified_live"] is False for item in result["results"])


def test_server_expired_session_can_be_explicitly_reauthenticated(app, human, monkeypatch):
    app.vault.save("mystu", state("mystu"))
    previous = app.vault.fingerprint("mystu")
    calls = successful_protocol(monkeypatch)
    result = auth_http.login_school(app.vault, services=["mystu"], interaction=human, reauthenticate=True)
    assert result["ok"] and len(calls) == 1
    assert result["results"][0]["verified_live"] is True
    assert app.vault.fingerprint("mystu") != previous


def test_legacy_unknown_account_session_is_reauthenticated_without_forced_logout(app, human, monkeypatch):
    old = state("mystu")
    old.pop("school_account_fingerprint")
    app.vault.save("mystu", old)
    calls = successful_protocol(monkeypatch)
    result = auth_http.login_school(app.vault, services=["mystu"], interaction=human)
    assert result["ok"] and len(calls) == 1
    assert result["results"][0]["verified_live"] is True
    assert result["untouched_services"] == ["jw", "repair"]


@pytest.mark.parametrize("error", ["authentication_network_error", "authentication_schema_changed",
                                 "authentication_unconfirmed", "insecure_transport"])
def test_source_failure_preserves_old_session_cache_and_other_success(app, human, monkeypatch, error):
    old = state("mystu", "old-student")
    app.vault.save("mystu", old)
    app.store.save_batch("mystu", [{"id": "old", "kind": "course", "title": "old"}], private=True)
    calls = successful_protocol(monkeypatch, fail={"mystu": error})
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["ok"] is False and result["status"] == "school_login_partial"
    assert len(calls) == 3
    assert result["results"][0]["ok"] and result["results"][2]["ok"]
    failure = result["results"][1]
    assert failure["kept_previous"] and failure["previous_identity_verified"] is False
    assert app.vault.load("mystu") == old
    assert app.store.list(sources=("mystu",))["items"][0]["id"] == "old"


@pytest.mark.parametrize("error", ["login_rejected", "interaction_required", "authentication_outcome_unknown",
                                 "authentication_identity_mismatch", "operation_cancelled", "authentication_response_limit"])
def test_rejection_challenge_unknown_or_cancel_stops_shared_password_attempts(app, human, monkeypatch, error):
    calls = successful_protocol(monkeypatch, fail={"jw": error})
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["status"] == "school_login_stopped" and not result["ok"]
    assert len(calls) == 1
    assert [item["status"] for item in result["results"]] == [error, "not_attempted", "not_attempted"]
    assert all(item["verified_live"] is False for item in result["results"])


def test_jw_http_is_not_implicitly_enabled_and_does_not_block_other_sources(app, human, monkeypatch):
    calls = []

    def acquire(source, *args, **kwargs):
        if source == "jw":
            assert kwargs["legacy_jw"] is False
            raise AppError("insecure_transport", "需要本人明确兼容", "jw")
        calls.append(source)
        return Candidate(state(source), {"authenticated": True})

    monkeypatch.setattr(cas, "acquire_state", acquire)
    result = auth_http.login_school(app.vault, interaction=human)
    assert result["status"] == "school_login_partial"
    assert result["results"][0]["status"] == "insecure_transport"
    assert calls == ["mystu", "repair"]
    assert app.runtime.preferences()["jw_http_compat"] is False


def test_logout_of_later_source_during_input_cannot_be_revived(app, human, monkeypatch):
    human.credentials.side_effect = lambda: (app.logout("repair"), Credentials(USERNAME, PASSWORD))[1]
    calls = successful_protocol(monkeypatch)
    result = auth_http.login_school(app.vault, interaction=human)
    assert result["status"] == "school_login_stopped" and not calls
    assert not app.runtime.session_file("repair").exists()


def test_logout_of_later_source_during_first_auth_stops_before_save_and_later_posts(app, human, monkeypatch):
    def before(source):
        if source == "jw":
            app.logout("repair")
    calls = successful_protocol(monkeypatch, before=before)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["status"] == "school_login_stopped" and len(calls) == 1
    assert not app.runtime.session_file("jw").exists()
    assert not app.runtime.session_file("repair").exists()


def test_logout_immediately_after_save_is_reported_as_changed_without_losing_rows(app, human, monkeypatch):
    calls = successful_protocol(monkeypatch)
    save = app.vault.save

    def logout_after_save(source, *args, **kwargs):
        result = save(source, *args, **kwargs)
        if source == "jw":
            app.logout(source)
        return result

    monkeypatch.setattr(app.vault, "save", logout_after_save)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["status"] == "school_login_stopped"
    assert [item["status"] for item in result["results"]] == ["session_changed", "not_attempted", "not_attempted"]
    assert len(calls) == 1 and not app.runtime.session_file("jw").exists()


def test_final_fence_keeps_other_successes_and_marks_changed_source(app, human, monkeypatch):
    successful_protocol(monkeypatch)
    save, revision = app.vault.save, app.vault.login_revision
    last_saved = False

    def mark_last_saved(source, *args, **kwargs):
        nonlocal last_saved
        result = save(source, *args, **kwargs)
        last_saved = source == "repair"
        return result

    def change_earlier_after_final_baseline(source):
        nonlocal last_saved
        result = revision(source)
        if source == "repair" and last_saved:
            last_saved = False
            app.logout("jw")
        return result

    monkeypatch.setattr(app.vault, "save", mark_last_saved)
    monkeypatch.setattr(app.vault, "login_revision", change_earlier_after_final_baseline)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["status"] == "school_login_stopped"
    assert [item["ok"] for item in result["results"]] == [False, True, True]
    assert result["results"][0]["status"] == "session_changed"
    assert result["results"][0]["verified_live"] is False


def test_same_account_concurrent_relogin_cannot_be_adopted_as_our_save(app, human, monkeypatch):
    calls = successful_protocol(monkeypatch)
    save = app.vault.save

    def replace_after_save(source, *args, **kwargs):
        receipt = save(source, *args, **kwargs)
        if source == "jw":
            app.logout(source)
            save(source, state(source))  # Another login with the same account is still a new generation.
        return receipt

    monkeypatch.setattr(app.vault, "save", replace_after_save)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert result["status"] == "school_login_stopped" and len(calls) == 1
    assert [item["status"] for item in result["results"]] == ["session_changed", "not_attempted", "not_attempted"]


def test_final_group_check_without_source_error_cannot_report_complete(app, human, monkeypatch):
    successful_protocol(monkeypatch)
    save, revision = app.vault.save, app.vault.login_revision
    final_baseline, final_check = False, False

    def saved(source, *args, **kwargs):
        nonlocal final_baseline
        result = save(source, *args, **kwargs)
        final_baseline = source == "repair"
        return result

    def busy_during_final_check(source):
        nonlocal final_check
        if final_check:
            raise AppError("local_state_busy", "合成本地状态繁忙")
        result = revision(source)
        if source == "repair" and final_baseline:
            final_check = True
        return result

    monkeypatch.setattr(app.vault, "save", saved)
    monkeypatch.setattr(app.vault, "login_revision", busy_during_final_check)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert not result["ok"] and result["status"] == "school_login_stopped"
    assert all(item["ok"] for item in result["results"])
    assert result["group_error"]["status"] == "local_state_busy"


def test_unexpected_adapter_failure_preserves_completed_source_without_exposing_exception(app, human, monkeypatch):
    def fail_second(source, *_args, **_kwargs):
        if source == "mystu":
            raise ValueError("SYNTHETIC_PRIVATE_EXCEPTION")
        return Candidate(state(source), {"authenticated": True})

    monkeypatch.setattr(cas, "acquire_state", fail_second)
    result = auth_http.login_school(app.vault, interaction=human, allow_http_callback=True)
    assert [item["status"] for item in result["results"]] == ["session_saved", "operation_failed", "not_attempted"]
    assert "SYNTHETIC_PRIVATE_EXCEPTION" not in json.dumps(result)
    assert app.vault.load("jw")


def test_storage_failure_precedes_input_and_network(app, human, monkeypatch):
    monkeypatch.setattr(app.vault, "_key", Mock(side_effect=AppError("secure_storage_unavailable", "不可用")))
    calls = successful_protocol(monkeypatch)
    with pytest.raises(AppError) as error:
        auth_http.login_school(app.vault, interaction=human)
    assert error.value.code == "secure_storage_unavailable"
    assert not calls
    human.credentials.assert_not_called()


@pytest.mark.parametrize("services", [[], ["jw", "jw"], ["oa"], ["yuketang"]])
def test_invalid_scope_rejected_before_input(app, human, services):
    with pytest.raises(AppError) as error:
        auth_http.login_school(app.vault, services=services, interaction=human)
    assert error.value.code == "invalid_school_services"
    human.credentials.assert_not_called()


@pytest.mark.parametrize("args", [["login", "school", "--browser"], ["login", "mystu", "--services", "mystu"],
                                ["login", "mystu", "--reauthenticate"],
                                ["login", "school", "--services", "mystu", "--allow-http-callback"],
                                ["login", "school", "--services", "jw", "jw"]])
def test_cli_rejects_incompatible_group_options_before_app(monkeypatch, capsys, args):
    create = Mock(side_effect=AssertionError("invalid options must not construct App"))
    monkeypatch.setattr(cli, "App", create)
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_login_options"
    create.assert_not_called()


def test_cli_school_dispatch_preserves_existing_single_source_contract(app, monkeypatch, capsys):
    monkeypatch.setattr(terminal, "require_terminal", lambda: None)
    monkeypatch.setattr(cli, "App", lambda: app)
    protocol = Mock(return_value={"ok": True, "service": "school", "status": "school_login_complete"})
    monkeypatch.setattr(auth_http, "login_school", protocol)
    assert cli.main(["login", "school", "--services", "jw", "mystu", "--allow-http-callback"]) == 0
    assert json.loads(capsys.readouterr().out)["service"] == "school"
    protocol.assert_called_once_with(app.vault, services=["jw", "mystu"], allow_http_callback=True)


def test_cli_passes_explicit_reauthentication_only_to_school(app, monkeypatch, capsys):
    monkeypatch.setattr(terminal, "require_terminal", lambda: None)
    monkeypatch.setattr(cli, "App", lambda: app)
    protocol = Mock(return_value={"ok": True, "service": "school", "status": "school_login_complete"})
    monkeypatch.setattr(auth_http, "login_school", protocol)
    assert cli.main(["login", "school", "--services", "repair", "--reauthenticate"]) == 0
    protocol.assert_called_once_with(app.vault, services=["repair"], allow_http_callback=False, reauthenticate=True)
