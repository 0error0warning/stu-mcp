import json
from pathlib import Path

import pytest
import tomlkit
from ruamel.yaml import YAML

from stu_mcp.clients import CLIENTS, connect, server_config, target
from stu_mcp.runtime import AppError


@pytest.mark.parametrize("client", ["codex", "claude-code", "cursor", "workbuddy", "zcode", "grok-build"])
def test_connection_preserves_config_and_is_idempotent(app, tmp_path, client):
    home = tmp_path / "client-home"
    path = target(client, home)
    path.parent.mkdir(parents=True)
    if CLIENTS[client].format == "toml":
        raw = b'# keep this comment\nmodel = "synthetic-model"\n[mcp_servers.other]\ncommand = "other-command"\n'
    else:
        servers = {"other": {"command": "other-command", "env": {"OTHER_TOKEN": "synthetic-secret"}}}
        raw = json.dumps({"preferences": {"theme": "dark"},
                          **({"mcp": {"servers": servers}} if client == "zcode" else {"mcpServers": servers})}).encode()
    path.write_bytes(raw)
    preview = connect(client, app.runtime, home=home)
    assert preview["status"] == "preview"
    assert path.read_bytes() == raw
    result = connect(client, app.runtime, home=home, apply=True)
    assert result["status"] == "connected"
    assert Path(result["backup"]).read_bytes() == raw
    assert "synthetic-secret" not in json.dumps(result)
    changed = path.read_bytes()
    doc = tomlkit.parse(changed.decode()) if CLIENTS[client].format == "toml" else json.loads(changed)
    servers = doc
    for key in CLIENTS[client].keys:
        servers = servers[key]
    assert servers["other"]["command"] == "other-command"
    assert servers["stu-mcp"] == server_config(client)
    if CLIENTS[client].format == "toml":
        assert "# keep this comment" in changed.decode()
        assert doc["model"] == "synthetic-model"
    else:
        assert doc["preferences"]["theme"] == "dark"
    assert connect(client, app.runtime, home=home, apply=True)["status"] == "already_connected"
    assert path.read_bytes() == changed
    assert "env" not in servers["stu-mcp"]


@pytest.mark.parametrize("client", ["codex", "claude-code", "cursor", "workbuddy", "zcode", "grok-build"])
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


def test_zcode_preserves_active_fallback_without_modifying_it(app, tmp_path):
    fallback = tmp_path / ".agents" / "mcp.json"
    fallback.parent.mkdir()
    other = {"command": "original", "enable": False, "env": {"API_TOKEN": "synthetic-secret"}}
    raw = json.dumps({"mcpServers": {"other": other}}).encode()
    fallback.write_bytes(raw)
    native = target("zcode", tmp_path)
    native.parent.mkdir(parents=True)
    native.write_text('{"mcp":{"servers":{},"timeout":100},"model":"keep-model"}')
    preview = connect("zcode", app.runtime, home=tmp_path)
    assert preview["preserved_fallback_servers"] == 1
    assert "synthetic-secret" not in json.dumps(preview)
    result = connect("zcode", app.runtime, home=tmp_path, apply=True)
    assert result["preserved_fallback_servers"] == 1
    saved = json.loads(native.read_bytes())
    assert saved["model"] == "keep-model"
    assert saved["mcp"]["timeout"] == 100
    assert saved["mcp"]["servers"]["other"] == other
    assert fallback.read_bytes() == raw
    assert connect("zcode", app.runtime, home=tmp_path, apply=True)["status"] == "already_connected"


def test_zcode_ignores_inactive_fallback_and_does_not_enable_it(app, tmp_path):
    native = target("zcode", tmp_path)
    native.parent.mkdir(parents=True)
    native.write_text('{"mcp":{"servers":{"existing":{"command":"keep"}}}}')
    fallback = tmp_path / ".agents" / "mcp.json"
    fallback.parent.mkdir()
    fallback.write_text("invalid and inactive")
    result = connect("zcode", app.runtime, home=tmp_path, apply=True)
    assert result["preserved_fallback_servers"] == 0
    assert set(json.loads(native.read_bytes())["mcp"]["servers"]) == {"existing", "stu-mcp"}


@pytest.mark.parametrize("raw", ['{"mcpServers":null}', '{"mcpServers":{"x":1,"x":2}}', '[{}]'])
def test_json_wrong_shape_or_duplicates_are_not_overwritten(app, tmp_path, raw):
    path = target("workbuddy", tmp_path)
    path.parent.mkdir()
    path.write_text(raw)
    with pytest.raises(AppError, match="安全解析"):
        connect("workbuddy", app.runtime, home=tmp_path, apply=True)
    assert path.read_text() == raw


def test_explicit_client_homes_and_environment_homes(tmp_path, monkeypatch):
    for client, variable, suffix in (
        ("codex", "CODEX_HOME", ("config.toml",)),
        ("grok-build", "GROK_HOME", ("config.toml",)),
        ("deepseek-harness", "DSH_HOME", ("profiles", "desktop", "cordis.patch.yml")),
    ):
        alternate = tmp_path / ("alternate-" + client)
        monkeypatch.setenv(variable, str(alternate))
        assert target(client) == alternate.joinpath(*suffix)
        assert target(client, tmp_path) == tmp_path.joinpath(*CLIENTS[client].parts)


def desktop_profile(home):
    path = target("deepseek-harness", home)
    path.parent.mkdir(parents=True)
    (path.parent / "package.json").write_text('{"name":"synthetic-desktop-profile"}')
    return path


def test_deepseek_desktop_requires_its_own_initialized_profile(app, tmp_path):
    cli = tmp_path / ".dsh" / "profiles" / "web"
    cli.mkdir(parents=True)
    (cli / "package.json").write_text("{}")
    result = connect("deepseek-harness", app.runtime, home=tmp_path, apply=True)
    assert result["ok"] is False
    assert result["status"] == "client_initialization_required"
    assert not target("deepseek-harness", tmp_path).exists()


def test_cordis_preserves_comments_custom_tags_and_other_plugins(app, tmp_path, capsys):
    path = desktop_profile(tmp_path)
    raw = b"# keep\n- id: other\n  config:\n    value: !!js process.env.OTHER_TOKEN\n    data: !!python/object/apply:builtins.print [DO_NOT_EXECUTE]\n"
    path.write_bytes(raw)
    preview = connect("deepseek-harness", app.runtime, home=tmp_path)
    assert preview["status"] == "preview"
    assert path.read_bytes() == raw
    result = connect("deepseek-harness", app.runtime, home=tmp_path, apply=True)
    assert Path(result["backup"]).read_bytes() == raw
    changed = path.read_bytes()
    assert b"# keep" in changed and b"!!js" in changed
    assert capsys.readouterr().out == ""
    doc = YAML(typ="rt").load(changed.decode())
    entry = doc[-1]["insert"][0]
    assert entry["name"] == "@deepseek-ai/dsh-mcp-client"
    assert entry["config"] == {"serverName": "stu-mcp", "transport": "stdio", **server_config()}
    assert connect("deepseek-harness", app.runtime, home=tmp_path, apply=True)["status"] == "already_connected"
    assert path.read_bytes() == changed


@pytest.mark.parametrize("raw", [b"# only comments\n", b"{}", b"- insert: {}", b"- id: x\n  id: y\n"])
def test_bad_cordis_is_not_repaired_or_overwritten(app, tmp_path, raw):
    path = desktop_profile(tmp_path)
    path.write_bytes(raw)
    with pytest.raises(AppError) as error:
        connect("deepseek-harness", app.runtime, home=tmp_path, apply=True)
    assert error.value.code == "invalid_client_config"
    assert path.read_bytes() == raw


def test_cordis_global_override_or_duplicate_is_not_silently_shadowed(app, tmp_path):
    path = desktop_profile(tmp_path)
    raw = b"- id: mcp-stu-mcp\n  disabled: true\n"
    global_patch = tmp_path / ".dsh" / "cordis.patch.yml"
    global_patch.write_bytes(raw)
    with pytest.raises(AppError) as error:
        connect("deepseek-harness", app.runtime, home=tmp_path, apply=True, replace=True)
    assert error.value.code == "client_config_conflict"
    assert global_patch.read_bytes() == raw
    assert not path.exists()


def test_connect_upgrade_keeps_user_settings_on_owned_server(app, tmp_path):
    path = target("workbuddy", tmp_path)
    path.parent.mkdir()
    existing = {"command": "old-python", "args": ["-m", "stu_mcp", "serve"],
                "disabled": True, "env": {"STU_MCP_HOME": "custom-path"}}
    path.write_text(json.dumps({"mcpServers": {"stu-mcp": existing}}))
    connect("workbuddy", app.runtime, home=tmp_path, apply=True)
    saved = json.loads(path.read_bytes())["mcpServers"]["stu-mcp"]
    assert saved["disabled"] is True
    assert saved["env"] == {"STU_MCP_HOME": "custom-path"}
    assert saved["command"] == server_config()["command"]
