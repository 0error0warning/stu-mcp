"""Private UI interaction and cancellation share the HTTP authentication core."""
import io
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stu_mcp import terminal
from stu_mcp.auth_http import Candidate, Credentials, cas, login_http, login_school, webvpn
from stu_mcp.runtime import AppError

USERNAME, PASSWORD = "synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD"


def human_interaction():
    return SimpleNamespace(credentials=Mock(return_value=Credentials(USERNAME, PASSWORD)),
                           code=Mock(return_value="123456"), show_qr=Mock())


def install_cas(monkeypatch):
    calls = []

    def acquire(source, username, password, *, check, **_kwargs):
        check()
        calls.append(source)
        assert (username, password) == (USERNAME, PASSWORD)
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    monkeypatch.setattr(cas, "acquire_state", acquire)
    return calls


def cancellation(flag):
    def check():
        if flag["cancelled"]:
            raise AppError("operation_cancelled", "已取消本次认证。")
    return check


@pytest.mark.parametrize("group", [False, True])
def test_explicit_human_interaction_works_without_host_tty(app, monkeypatch, group):
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO()))
    calls = install_cas(monkeypatch)
    interaction = human_interaction()
    if group:
        result = login_school(app.vault, services=["mystu", "repair"], interaction=interaction)
        assert calls == ["mystu", "repair"]
    else:
        result = login_http(app.vault, "mystu", interaction=interaction)
        assert calls == ["mystu"]
    assert result["ok"] is True
    interaction.credentials.assert_called_once_with()


@pytest.mark.parametrize("group", [False, True])
def test_default_terminal_interaction_still_rejects_non_tty(app, monkeypatch, group):
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO()))
    calls = install_cas(monkeypatch)
    with pytest.raises(AppError) as error:
        if group:
            login_school(app.vault, services=["mystu"])
        else:
            login_http(app.vault, "mystu")
    assert error.value.code == "terminal_required" and not calls


@pytest.mark.parametrize("group", [False, True])
def test_cancelled_before_input_never_requests_credentials_or_protocol(app, monkeypatch, group):
    calls = install_cas(monkeypatch)
    interaction, flag = human_interaction(), {"cancelled": True}
    with pytest.raises(AppError) as error:
        if group:
            login_school(app.vault, services=["mystu"], interaction=interaction,
                         check_cancelled=cancellation(flag))
        else:
            login_http(app.vault, "mystu", interaction=interaction, check_cancelled=cancellation(flag))
    assert error.value.code == "operation_cancelled"
    interaction.credentials.assert_not_called()
    assert not calls


@pytest.mark.parametrize("group", [False, True])
def test_cancelled_during_input_never_enters_authentication(app, monkeypatch, group):
    calls = install_cas(monkeypatch)
    interaction, flag = human_interaction(), {"cancelled": False}

    def read():
        flag["cancelled"] = True
        return Credentials(USERNAME, PASSWORD)

    interaction.credentials.side_effect = read
    with pytest.raises(AppError) as error:
        if group:
            login_school(app.vault, services=["mystu"], interaction=interaction,
                         check_cancelled=cancellation(flag))
        else:
            login_http(app.vault, "mystu", interaction=interaction, check_cancelled=cancellation(flag))
    assert error.value.code == "operation_cancelled" and not calls
    assert not app.runtime.session_file("mystu").exists()


def test_cancel_at_final_save_guard_preserves_session_and_cache(app, monkeypatch, session):
    app.vault.save("mystu", session)
    app.store.save_batch("mystu", [{"id": "old", "kind": "course", "title": "old"}], private=True)
    before, flag = app.vault.fingerprint("mystu"), {"cancelled": False}
    calls = install_cas(monkeypatch)
    save = app.vault.save

    def cancelled_save(*args, **kwargs):
        flag["cancelled"] = True
        return save(*args, **kwargs)

    monkeypatch.setattr(app.vault, "save", cancelled_save)
    receipt = {}
    with pytest.raises(AppError) as error:
        login_http(app.vault, "mystu", interaction=human_interaction(),
                   check_cancelled=cancellation(flag), commit_receipt=receipt)
    assert error.value.code == "operation_cancelled" and calls == ["mystu"]
    assert app.vault.fingerprint("mystu") == before and not receipt
    assert app.store.list(sources=("mystu",))["items"][0]["id"] == "old"


def test_group_cancellation_preserves_success_and_stops_remaining_passwords(app, monkeypatch):
    calls = install_cas(monkeypatch)
    flag, progress = {"cancelled": False}, []

    def received(item):
        progress.append(item)
        if item["service"] == "jw" and item["ok"]:
            flag["cancelled"] = True

    result = login_school(app.vault, interaction=human_interaction(), allow_http_callback=True,
                          check_cancelled=cancellation(flag), on_result=received)
    assert result["status"] == "school_login_stopped" and calls == ["jw"]
    assert [item["status"] for item in result["results"]] == ["session_saved", "operation_cancelled", "not_attempted"]
    assert app.vault.load("jw")
    assert [item["service"] for item in progress] == ["jw", "mystu", "repair"]
    assert USERNAME not in str(progress) and PASSWORD not in str(progress)


def test_group_progress_is_a_copy_and_cannot_change_authentication_result(app, monkeypatch):
    install_cas(monkeypatch)

    def received(item):
        item["ok"] = False
        item["proof"]["authenticated"] = False

    result = login_school(app.vault, services=["mystu"], interaction=human_interaction(), on_result=received)
    assert result["ok"] and result["results"][0]["proof"]["authenticated"] is True


def test_webvpn_interaction_can_explicitly_avoid_saved_auto_credentials(app, monkeypatch):
    from stu_mcp import webvpn as configuration

    config = SimpleNamespace(snapshot=Mock(return_value={}), check=Mock(),
                             marker=Mock(return_value={"configured": True}),
                             credentials=Mock(side_effect=AssertionError("must ask this human")),
                             remove_locked=Mock())
    monkeypatch.setattr(configuration, "WebVPNConfig", lambda _vault: config)
    interaction = human_interaction()

    def acquire(*, username, password, totp_code, check, **_kwargs):
        check()
        assert (username, password) == (USERNAME, PASSWORD)
        assert totp_code() == "123456"
        return {"cookies": [], "origins": []}, {"authenticated": True}

    monkeypatch.setattr(webvpn, "acquire_state", acquire)
    result = login_http(app.vault, "webvpn", interaction=interaction, use_saved_credentials=False)
    assert result["ok"]
    interaction.credentials.assert_called_once_with()
    interaction.code.assert_called_once_with()
    config.credentials.assert_not_called()
