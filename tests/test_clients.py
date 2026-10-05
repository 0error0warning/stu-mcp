import json

import pytest
import tomlkit

from stu_mcp.clients import connect, server_config, target
from stu_mcp.runtime import AppError


@pytest.mark.parametrize("client", ["codex", "claude-code", "cursor"])
def test_connection_preserves_config_and_is_idempotent(app, tmp_path, client):
    home = tmp_path / "client-home"
    path = target(client, home)
    path.parent.mkdir(parents=True)
    if client == "codex":
        raw = b'# keep this comment\nmodel = "synthetic-model"\n[mcp_servers.other]\ncommand = "other-command"\n'
    else:
        raw = json.dumps({"preferences": {"theme": "dark"}, "mcpServers": {"other": {"command": "other-command"}}}).encode()
    path.write_bytes(raw)
    preview = connect(client, app.runtime, home=home)
    assert preview["status"] == "preview"
    assert path.read_bytes() == raw
    result = connect(client, app.runtime, home=home, apply=True)
    assert result["status"] == "connected"
    assert __import__("pathlib").Path(result["backup"]).read_bytes() == raw
    changed = path.read_bytes()
    doc = tomlkit.parse(changed.decode()) if client == "codex" else json.loads(changed)
    servers = doc["mcp_servers"] if client == "codex" else doc["mcpServers"]
    assert servers["other"]["command"] == "other-command"
    assert servers["stu-mcp"] == server_config()
    if client == "codex":
        assert "# keep this comment" in changed.decode()
        assert doc["model"] == "synthetic-model"
    else:
        assert doc["preferences"]["theme"] == "dark"
    assert connect(client, app.runtime, home=home, apply=True)["status"] == "already_connected"
    assert path.read_bytes() == changed
    assert "env" not in servers["stu-mcp"]


@pytest.mark.parametrize("client", ["codex", "claude-code", "cursor"])
def test_bad_existing_config_is_not_overwritten(app, tmp_path, client):
    path = target(client, tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{ not valid json or toml")
    with pytest.raises(AppError) as error:
        connect(client, app.runtime, home=tmp_path, apply=True)
    assert error.value.code == "invalid_client_config"
    assert path.read_bytes() == b"{ not valid json or toml"


def test_name_conflict_requires_explicit_replacement(app, tmp_path):
    path = target("claude-code", tmp_path)
    path.write_text(json.dumps({"mcpServers": {"stu-mcp": {"command": "another-implementation"}}}), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(AppError) as error:
        connect("claude-code", app.runtime, home=tmp_path, apply=True)
    assert error.value.code == "client_config_conflict"
    assert path.read_bytes() == before
    assert connect("claude-code", app.runtime, home=tmp_path, apply=True, replace=True)["status"] == "connected"
