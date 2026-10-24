"""Thin campus-card interfaces keep independent authentication and no cache writes."""
import hashlib
import json

import pytest

from stu_mcp import cli
from stu_mcp.auth_http.school import SCHOOL_SERVICES
from stu_mcp.capability_catalog import build_capability_catalog
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server
from stu_mcp.sources import SOURCES


@pytest.mark.asyncio
@pytest.mark.parametrize("transactions", [False, True])
async def test_card_cli_mcp_share_service_without_cache(app, monkeypatch, capsys, transactions):
    from stu_mcp.features.smartcard import service

    calls = []
    expected = {"ok": True, "source": "smartcard", "status": "ok", "cached": False}

    def read(vault, *args):
        assert vault is app.vault
        calls.append(args)
        return expected

    def forbidden(*_args, **_kwargs):
        pytest.fail("Card reads must not refresh or persist student records")

    monkeypatch.setattr(service, "card_transactions" if transactions else "card_overview", read)
    monkeypatch.setattr(cli, "App", lambda: app)
    monkeypatch.setattr(app, "refresh", forbidden)
    monkeypatch.setattr(app.store, "save_batch", forbidden)
    args = {"start_date": "2026-10-17", "end_date": "2026-10-24", "transaction_type": "1A"} if transactions else {}
    command = ["card-transactions", "--start-date", "2026-10-17", "--end-date", "2026-10-24",
               "--transaction-type", "1A"] if transactions else ["card"]
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out) == expected
    host = HostRuntime(app)
    try:
        tool = "get_campus_card_transactions" if transactions else "get_campus_card"
        result = await build_server(host=host).call_tool(tool, args)
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
    finally:
        host.close()
    assert calls == ([("2026-10-17", "2026-10-24", "1A")] * 2 if transactions else [(), ()])


@pytest.mark.asyncio
async def test_card_tool_annotations_and_login_failure_are_actionable(app, monkeypatch, capsys):
    from stu_mcp.features.smartcard import service

    def missing(*_args, **_kwargs):
        raise AppError("needs_login", "请本人登录一卡通查询。", "smartcard")

    monkeypatch.setattr(service, "card_overview", missing)
    monkeypatch.setattr(cli, "App", lambda: app)
    assert cli.main(["card"]) == 1
    expected = json.loads(capsys.readouterr().out)
    assert expected["source"] == "smartcard" and expected["next_action"] == "open_setup"
    host = HostRuntime(app)
    try:
        server = build_server(host=host)
        result = await server.call_tool("get_campus_card", {})
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
        tools = {tool.name: tool for tool in await server.list_tools()}
        for name in ("get_campus_card", "get_campus_card_transactions"):
            tool = tools[name]
            assert tool.annotations.read_only_hint and tool.annotations.idempotent_hint
            assert tool.annotations.open_world_hint
            assert not {"username", "password", "captcha", "cookie", "token"}.intersection(
                tool.input_schema.get("properties", {}))
        assert tools["get_campus_card_transactions"].input_schema["required"] == ["start_date", "end_date"]
    finally:
        host.close()


def test_card_status_and_catalog_do_not_join_school_account_or_probe_network(app):
    catalog = build_capability_catalog({"smartcard": {"auth": {"status": "session_saved"}}})
    services = {row["service_id"]: row for row in catalog["services"]}
    card = services["campus_card"]
    assert card["integration"] == "implemented" and card["source_id"] == card["login_id"] == "smartcard"
    assert card["state"]["status"] == "session_saved" and card["state"]["business_read"] == "not_checked"
    profiles = {row["configuration_id"]: row for row in catalog["profiles"]}
    assert profiles["smartcard"]["service_ids"] == ["campus_card"]
    assert profiles["smartcard"]["setup_ui"]["available"] is True
    assert "campus_card" not in profiles["school"]["service_ids"]
    assert "smartcard" not in SCHOOL_SERVICES
    assert SOURCES["smartcard"].hosts == ("smartcard.stu.edu.cn",)
    source = next(row for row in app.status()["sources"] if row["source"] == "smartcard")
    assert source["login_required"] and source["refresh_requires_query"]
    with pytest.raises(AppError, match="一卡通") as error:
        app.refresh("smartcard")
    assert error.value.code == "query_required"


def test_card_login_cli_rejects_browser_without_launching_it(monkeypatch, capsys):
    monkeypatch.setattr(cli, "interactive_login", lambda *_: pytest.fail("No browser login for smartcard"))
    assert cli.main(["login", "smartcard", "--browser"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_login_options"
    assert cli.parser().parse_args(["logout", "smartcard"]).service == "smartcard"


def test_original_48_complete_tool_definitions_stay_identical():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    current = json.loads((root / "scripts/mcp-tool-contract.json").read_text(encoding="utf-8"))
    original = sorted((tool for tool in current["tools"] if tool["name"] not in {
        "get_campus_card", "get_campus_card_transactions"}), key=lambda tool: tool["name"])
    encoded = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    # Captured from the complete committed 48-tool contract before this additive change.
    assert len(original) == 48 and current["tool_count"] == len(current["tools"]) == 50
    assert hashlib.sha256(encoded).hexdigest() == "aa905835ed26078095b2c5f4e216b26fb1d3775dd0b1015e5a24e03569070dac"
