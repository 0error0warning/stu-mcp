"""Human CLI and capability contracts, with temporary encrypted credentials only."""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet

from stu_mcp import checkin_login, cli, interaction, terminal, webvpn
from stu_mcp.app import App
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import Runtime
from stu_mcp.webvpn import KEYRING_SERVICE, WebVPNConfig

USERNAME = "SYNTHETIC_CLI_STUDENT_ACCOUNT"
PASSWORD = "SYNTHETIC_CLI_PRIVATE_PASSWORD"
RAW_SEED = b"12345678901234567890"  # Public RFC 6238 vector.
SEED = base64.b32encode(RAW_SEED).decode()
FIELDS = {"enabled": True, "username": USERNAME, "password": PASSWORD, "totp": SEED}


class HiddenTerminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def private_app(tmp_path, monkeypatch):
    home = tmp_path / "mcp"
    master = tmp_path / "external-master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o600)
    monkeypatch.setenv("STU_MCP_HOME", str(home))
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    monkeypatch.setenv("STU_MCP_KEY_FILE", str(master))
    monkeypatch.setenv("STU_MCP_INSTANCE_NAME", "synthetic-cli")
    monkeypatch.setattr("stu_mcp.app.detected_clients", lambda: [])
    monkeypatch.setattr(webvpn, "automatic_login", Mock(side_effect=AssertionError("no school login")))
    app = App(Runtime(home))
    monkeypatch.setattr(cli, "App", lambda: app)
    return app, master


@pytest.fixture
def human_input(monkeypatch):
    errors = HiddenTerminal()
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=HiddenTerminal(), stderr=errors))
    calls = []

    def values(items):
        remaining = iter(items)

        def getpass(prompt, *, stream):
            assert stream is errors
            calls.append(prompt)
            value = next(remaining)
            if isinstance(value, BaseException):
                raise value
            return value

        monkeypatch.setattr(terminal.getpass, "getpass", getpass)

    return values, calls, errors


def invoke(arguments, capsys):
    code = cli.main(arguments)
    output = capsys.readouterr()
    return code, json.loads(output.out), output.out + output.err


def assert_private_output(output, master=None):
    for private in (USERNAME, PASSWORD, SEED, RAW_SEED.hex(), base64.b64encode(RAW_SEED).decode()):
        assert private not in output
    if master is not None:
        assert str(master) not in output and master.read_text() not in output


def seed_session_and_cache(app):
    state = {"cookies": [{"name": "session", "value": "SYNTHETIC_OLD_VPN_COOKIE",
                          "domain": "webvpn.stu.edu.cn"}], "origins": []}
    app.vault.save("webvpn", state)
    app.store.save_batch("oa", [{"id": "old-private-oa", "kind": "notice", "title": "旧合成通知"}], private=True)
    app.store.save_batch("public", [{"id": "public-one", "kind": "notice", "title": "公开合成通知"}])
    return state


def test_duifene_dispatches_without_constructing_campus_app(monkeypatch, capsys):
    create = Mock(side_effect=AssertionError("Duifene owns its independent worker"))
    login = Mock(return_value={"ok": True, "login_outcome": "confirmed", "monitoring": False,
                               "resume_enabled": False})
    monkeypatch.setattr(cli, "App", create)
    monkeypatch.setattr(checkin_login, "login_via_callback", login)
    code, result, output = invoke(["login", "duifene"], capsys)
    assert code == 0 and result["login_outcome"] == "confirmed"
    login.assert_called_once_with()
    create.assert_not_called()
    assert_private_output(output)


def test_webvpn_configure_rejects_non_tty_before_app_or_input(monkeypatch, capsys):
    monkeypatch.setattr(terminal, "sys", SimpleNamespace(stdin=io.StringIO(), stderr=io.StringIO()))
    create = Mock(side_effect=AssertionError("TTY must be checked before App"))
    hidden = Mock(side_effect=AssertionError("never read a piped secret"))
    monkeypatch.setattr(cli, "App", create)
    monkeypatch.setattr(terminal.getpass, "getpass", hidden)
    code, result, output = invoke(["webvpn-auto", "configure"], capsys)
    assert code == 1 and result["status"] == "terminal_required"
    create.assert_not_called()
    hidden.assert_not_called()
    assert_private_output(output)


def test_webvpn_hidden_configure_reuses_file_backend_and_invalidates_old_session(
        private_app, human_input, capsys):
    app, master = private_app
    values, prompts, errors = human_input
    seed_session_and_cache(app)
    old_revision = app.vault.login_revision("webvpn")
    values([USERNAME, PASSWORD, RAW_SEED.hex()])
    code, result, output = invoke(["webvpn-auto", "configure", "--encoding", "hex"], capsys)
    assert code == 0 and result["status"] == "auto_login_configured"
    assert len(prompts) == 3 and not errors.getvalue()
    config = WebVPNConfig(app.vault)
    credentials = config.credentials(config.marker())
    assert (credentials.username, credentials.password, credentials.totp.secret) == (USERNAME, PASSWORD, SEED)
    assert config.status()["enabled"] and config.status()["configured"]
    assert not app.runtime.session_file("webvpn").exists()
    assert app.vault.login_revision("webvpn") != old_revision
    assert app.store.list(sources=("oa",))["items"] == []
    assert app.store.get("public-one")["title"] == "公开合成通知"
    disk = b"".join(path.read_bytes() for path in app.runtime.home.rglob("*") if path.is_file())
    for value in (USERNAME, PASSWORD, SEED):
        assert value.encode() not in disk
    assert master.read_bytes() not in disk
    assert_private_output(output, master)
    webvpn.automatic_login.assert_not_called()


@pytest.mark.parametrize("cancel", [KeyboardInterrupt(), EOFError()])
def test_cancelled_webvpn_input_preserves_existing_configuration_and_session(
        private_app, human_input, capsys, cancel):
    app, master = private_app
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    state = seed_session_and_cache(app)
    marker = config.marker()
    before = {str(path.relative_to(app.runtime.home)): path.read_bytes()
              for path in app.runtime.home.rglob("*") if path.is_file()}
    values, prompts, _ = human_input
    values([USERNAME, PASSWORD, cancel])
    code, result, output = invoke(["webvpn-auto", "configure"], capsys)
    assert code == 1 and result["status"] == "operation_cancelled" and len(prompts) == 3
    assert config.marker() == marker and app.vault.load("webvpn") == state
    after = {str(path.relative_to(app.runtime.home)): path.read_bytes()
             for path in app.runtime.home.rglob("*") if path.is_file()}
    assert after == before
    assert app.store.get("old-private-oa")["title"] == "旧合成通知"
    assert_private_output(output, master)
    webvpn.automatic_login.assert_not_called()


def test_bad_server_key_fails_before_asking_for_credentials(private_app, human_input, capsys):
    app, master = private_app
    master.write_bytes(b"SYNTHETIC_INVALID_MASTER")
    values, prompts, _ = human_input
    values([USERNAME, PASSWORD, SEED])
    code, result, output = invoke(["webvpn-auto", "configure"], capsys)
    assert code == 1 and result["status"] == "secure_storage_unavailable" and not prompts
    assert not WebVPNConfig(app.vault).status()["configured"]
    assert_private_output(output, master)


def test_webvpn_status_does_not_read_credentials_and_remove_preserves_current_session(
        private_app, monkeypatch, capsys):
    app, master = private_app
    config = WebVPNConfig(app.vault)
    config.configure(FIELDS)
    state = seed_session_and_cache(app)
    backend = app.vault.key_store
    blocked = Mock(side_effect=AssertionError("status must not read saved credentials"))
    monkeypatch.setattr(app.vault, "key_store", blocked)
    code, result, output = invoke(["webvpn-auto", "status"], capsys)
    assert code == 0 and result["configured"] and result["enabled"]
    blocked.assert_not_called()
    assert_private_output(output, master)
    monkeypatch.setattr(app.vault, "key_store", backend)
    code, result, output = invoke(["webvpn-auto", "remove"], capsys)
    assert code == 0 and result["status"] == "auto_login_removed"
    assert not config.status()["configured"] and not config.status()["enabled"]
    assert app.vault.key_store().get_password(KEYRING_SERVICE, app.vault.account) is None
    assert app.vault.load("webvpn") == state
    assert app.store.get("old-private-oa")["title"] == "旧合成通知"
    assert_private_output(output, master)
    webvpn.automatic_login.assert_not_called()


@pytest.mark.parametrize("mode", ["desktop", "disabled"])
def test_no_display_limits_manual_browser_without_disabling_callback_or_auto_renewal(
        private_app, monkeypatch, mode):
    app, master = private_app
    WebVPNConfig(app.vault).configure(FIELDS)
    monkeypatch.setenv("STU_MCP_INTERACTION", mode)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(interaction, "sys", SimpleNamespace(platform="linux"))
    blocked = Mock(side_effect=AssertionError("capability reporting must not read saved credentials"))
    monkeypatch.setattr(app.vault, "key_store", blocked)
    checkin = SimpleNamespace(status=lambda: {"status": "service_not_started"})
    host = HostRuntime(app, checkin=checkin, transport="streamable-http")
    try:
        result = host.capabilities()
    finally:
        host.close()
    hosting = result["hosting"]
    assert not hosting["interaction"]["available"] and hosting["interaction"]["scope"] == "manual_browser"
    flows = hosting["login_flows"]
    assert flows["duifene"]["requires_display"] is False
    assert flows["duifene"]["method"] == "wechat_callback"
    assert flows["duifene"]["existing_authorized_plan_may_resume"] is True
    assert flows["webvpn"]["automatic_renewal"] == "http_totp"
    assert flows["webvpn"]["human_challenges"] == "pause"
    assert flows["webvpn"]["real_account_renewal_verified"] is False
    assert result["webvpn_auto_login"]["enabled"]
    for source in ("jw", "mystu", "yuketang"):
        assert flows[source]["new_login_requires_display"] is False
        assert flows[source]["method"] == ("http_qr" if source == "yuketang" else "cas_http")
        assert flows[source]["saved_session_reads_require_display"] is False
    assert hosting["default_authentication"] == "http"
    assert hosting["browser_backend"] == "optional_explicit"
    assert hosting["credential_backend"] == "encrypted_file" and not hosting["credential_backend_verified"]
    assert result["privacy"]["credential_backend"] == "encrypted_file"
    assert result["privacy"]["storage"] == "external_key_and_encrypted_sessions"
    assert not result["privacy"]["credential_backend_verified"]
    assert_private_output(json.dumps(result), master)
    blocked.assert_not_called()
    webvpn.automatic_login.assert_not_called()


def test_os_backend_metadata_does_not_probe_user_keyring(private_app, monkeypatch):
    app, _ = private_app
    monkeypatch.delenv("STU_MCP_KEY_FILE")
    monkeypatch.setenv("STU_MCP_INTERACTION", "disabled")
    blocked = Mock(side_effect=AssertionError("must not probe the real keyring"))
    monkeypatch.setattr(app.vault, "key_store", blocked)
    host = HostRuntime(app, checkin=SimpleNamespace(status=lambda: {}))
    try:
        result = host.capabilities()
    finally:
        host.close()
    assert result["hosting"]["credential_backend"] == "os_keyring"
    assert result["privacy"]["credential_backend"] == "os_keyring"
    assert result["privacy"]["storage"] == "os_keyring_and_encrypted_sessions"
    assert not result["hosting"]["credential_backend_verified"]
    blocked.assert_not_called()
