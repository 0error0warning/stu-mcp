"""CLI selects HTTP explicitly without accepting authentication arguments."""
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stu_mcp import auth, auth_http, cli, terminal
from stu_mcp.runtime import AppError


def test_default_login_requires_tty_before_constructing_app(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO()))
    create = Mock(side_effect=AssertionError("no runtime before a human terminal"))
    monkeypatch.setattr(cli, "App", create)
    assert cli.main(["login", "mystu"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "terminal_required"
    create.assert_not_called()


def test_default_login_dispatches_http_and_per_attempt_jw_compat(app, monkeypatch, capsys):
    monkeypatch.setattr(terminal, "require_terminal", lambda: None)
    monkeypatch.setattr(cli, "App", lambda: app)
    protocol = Mock(return_value={"ok": True, "status": "session_saved", "method": "http"})
    browser = Mock(side_effect=AssertionError("no automatic browser fallback"))
    monkeypatch.setattr(auth_http, "login_http", protocol)
    monkeypatch.setattr(cli, "interactive_login", browser)
    assert cli.main(["login", "jw", "--allow-http-callback"]) == 0
    assert json.loads(capsys.readouterr().out)["method"] == "http"
    protocol.assert_called_once_with(app.vault, "jw", allow_http_callback=True)
    assert app.runtime.preferences()["jw_http_compat"] is False
    browser.assert_not_called()


def test_browser_login_is_an_explicit_compatibility_choice(app, monkeypatch, capsys):
    monkeypatch.setattr(cli, "App", lambda: app)
    browser = Mock(return_value={"ok": True, "status": "session_saved"})
    monkeypatch.setattr(cli, "interactive_login", browser)
    monkeypatch.setattr(auth_http, "login_http", Mock(side_effect=AssertionError("explicit browser only")))
    assert cli.main(["login", "mystu", "--browser"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "session_saved"
    browser.assert_called_once_with(app.vault, "mystu")


def test_default_setup_job_guides_host_cli_without_thread_or_browser(app, monkeypatch):
    monkeypatch.setattr(auth, "interactive_login", Mock(side_effect=AssertionError("no background TTY prompt")))
    result = auth.LoginJobs(app.vault).start("mystu")
    assert result["status"] == "host_cli_required"
    assert result["command"] == "stu-mcp login mystu"
    assert auth.LoginJobs(app.vault).snapshot() == []
    with pytest.raises(AppError):
        auth.LoginJobs(app.vault).start("mystu", backend="unknown")


def test_transport_preferences_are_local_explicit_and_separate(app, monkeypatch, capsys):
    monkeypatch.setattr(cli.Runtime, "default", lambda: app.runtime)
    assert cli.main(["transport", "--oa-http", "on"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["transport"]["oa_http_compat"] is True
    assert result["transport"]["jw_http_compat"] is False


def test_no_password_or_token_arguments_exist():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["login", "mystu", "--password", "SYNTHETIC_PRIVATE"])


def test_source_specific_unsafe_option_rejected_before_app(monkeypatch, capsys):
    create = Mock(side_effect=AssertionError("invalid options must not construct App"))
    monkeypatch.setattr(cli, "App", create)
    assert cli.main(["login", "yuketang", "--allow-http-callback"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_login_options"
    create.assert_not_called()


@pytest.mark.parametrize(("code", "action"), [
    ("authentication_network_error", "check_dns_and_route"),
    ("authentication_outcome_unknown", "verify_source_login"),
    ("authentication_schema_changed", "report_source_change"),
    ("interaction_required", "complete_source_challenge"),
    ("repair_login_required", "run_host_cli"),
    ("oa_http_compat_required", "choose_transport_compatibility"),
])
def test_http_failure_guidance_does_not_suggest_repeating_authentication(code, action):
    result = AppError(code, "合成错误", "repair").result()
    assert result["next_action"] == action
    assert result["retryable"] is False
