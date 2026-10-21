import json

import pytest

from stu_mcp.cli import main, parser
from stu_mcp.runtime import AppError
from stu_mcp.server_init import initialize_secrets
from stu_mcp.transports.http import load_bearer


def test_initialization_is_explicit_private_separate_and_no_overwrite(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    directory = tmp_path / "secrets"
    assert main(["server-init", str(directory)]) == 0
    result = json.loads(capsys.readouterr().out)
    key = (directory / "master.key").read_text().strip()
    token = (directory / "http-token").read_text().strip()
    assert key != token and len(key) == 44 and len(token) == 64
    assert key not in json.dumps(result) and token not in json.dumps(result)
    assert load_bearer(directory / "http-token") == token.encode()
    with pytest.raises(AppError) as error:
        initialize_secrets(directory)
    assert error.value.code == "secret_directory_exists"
    assert (directory / "master.key").read_text().strip() == key
    assert (directory / "http-token").read_text().strip() == token
    assert not (tmp_path / "data").exists()


def test_secret_directory_cannot_be_inside_either_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    for home in ("data", "checkin"):
        with pytest.raises(AppError) as error:
            initialize_secrets(tmp_path / home / "secrets")
        assert error.value.code == "unsafe_secret_directory"
        assert not (tmp_path / home).exists()


def test_serve_default_and_setup_parser_compatible():
    args = parser().parse_args(["serve"])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1" and args.port == 8765
    assert args.auth_token_file is None
    assert parser().parse_args(["setup"]).port == 0
    assert parser().parse_args(["setup", "--port", "8766", "--no-browser"]).port == 8766


def test_failed_serve_keeps_stdout_clean_and_never_prints_token_value(tmp_path, capsys):
    path = tmp_path / "token"
    path.write_text("deliberately_invalid_secret", encoding="ascii")
    path.chmod(0o600)
    assert main(["serve", "--transport", "streamable-http", "--auth-token-file", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "deliberately_invalid_secret" not in captured.err
    assert main(["serve", "--port", "8000"]) == 1
    assert capsys.readouterr().out == ""


def test_session_master_key_is_not_accepted_as_http_bearer(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    path = tmp_path / "mistaken-token"
    path.write_bytes(Fernet.generate_key())
    path.chmod(0o600)
    monkeypatch.delenv("STU_MCP_KEY_FILE", raising=False)
    with pytest.raises(AppError) as error:
        load_bearer(path)
    assert error.value.code == "invalid_http_token"
    path.write_text("same_non_fernet_value_copied_as_http_token")
    other = tmp_path / "session-key"
    other.write_bytes(path.read_bytes())
    other.chmod(0o600)
    monkeypatch.setenv("STU_MCP_KEY_FILE", str(other))
    with pytest.raises(AppError) as error:
        load_bearer(path)
    assert error.value.code == "invalid_http_token"


def test_failed_initialization_rolls_back_only_its_new_files(tmp_path, monkeypatch):
    import os
    original = os.open

    def fail_second(path, *args, **kwargs):
        if str(path).endswith("http-token"):
            raise PermissionError("synthetic denied")
        return original(path, *args, **kwargs)

    directory = tmp_path / "new-secrets"
    monkeypatch.setattr("stu_mcp.server_init.os.open", fail_second)
    with pytest.raises(AppError) as error:
        initialize_secrets(directory)
    assert error.value.code == "secret_initialization_failed"
    assert not directory.exists()
    monkeypatch.setattr("stu_mcp.server_init.os.open", original)
    assert initialize_secrets(directory)["ok"]
