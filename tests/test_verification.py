import json

import pytest

from stu_mcp import __version__
from stu_mcp.cli import parser
from stu_mcp.verification import verify_server


@pytest.mark.asyncio
async def test_verify_real_installed_server_excludes_personal_status(app, monkeypatch, tmp_path):
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    app.runtime.save_profile({"major": "private-synthetic-major"})
    result = await verify_server(app.runtime)
    assert result["ok"] is True
    assert result["version"] == __version__
    assert result["tool_count"] >= 52
    assert result["agent_connection_verified"] is False
    assert result["verification"] == "installed_mcp_only"
    assert "private-synthetic-major" not in json.dumps(result)


@pytest.mark.asyncio
async def test_verify_spawn_failure_is_sanitized(app, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-synthetic-secret")
    monkeypatch.setattr("stu_mcp.verification.stdio_client", fail)
    result = await verify_server(app.runtime)
    assert result["ok"] is False
    assert "private-synthetic-secret" not in json.dumps(result)


def test_cli_dsh_profile_and_verification_entrypoints():
    args = parser().parse_args(["connect", "dsh", "--profile", "web"])
    assert args.profile == "web" and not args.apply
    assert parser().parse_args(["verify"]).command == "verify"
