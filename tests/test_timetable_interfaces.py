"""On-demand timetable entry points reuse JW core without changing cached queries."""
import json

import pytest

from stu_mcp import cli
from stu_mcp.capability_catalog import build_capability_catalog
from stu_mcp.features.jw import service
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server


@pytest.mark.asyncio
@pytest.mark.parametrize("semester", ["", "2026-2027-1"])
async def test_cli_and_mcp_share_timetable_service_without_refresh_or_cache(app, monkeypatch, capsys, semester):
    calls = []
    expected = {"ok": True, "source": "jw", "semester": "2026-2027-1", "courses": [],
                "available_semesters": [{"semester": "2026-2027-1", "label": "合成学期"}],
                "coverage": {"kind": "theory"}, "pending": [], "unarranged": []}

    def read(vault, requested):
        assert vault is app.vault
        calls.append(requested)
        return expected

    def forbidden(*_args, **_kwargs):
        pytest.fail("Live timetable must not refresh or read/write the course/event cache")

    monkeypatch.setattr(service, "academic_timetable", read)
    monkeypatch.setattr(cli, "App", lambda: app)
    monkeypatch.setattr(app, "refresh", forbidden)
    monkeypatch.setattr(app.store, "list", forbidden)
    monkeypatch.setattr(app.store, "save_batch", forbidden)
    assert cli.main(["timetable", "--semester", semester]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    host = HostRuntime(app)
    try:
        result = await build_server(host=host).call_tool("get_academic_timetable", {"semester": semester})
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
    finally:
        host.close()
    assert calls == [semester, semester]


@pytest.mark.asyncio
async def test_timetable_entry_points_preserve_actionable_failures(app, monkeypatch, capsys):
    def missing(*_args, **_kwargs):
        raise AppError("needs_login", "请先登录学校账号。", "jw")

    monkeypatch.setattr(service, "academic_timetable", missing)
    monkeypatch.setattr(cli, "App", lambda: app)
    assert cli.main(["timetable"]) == 1
    expected = json.loads(capsys.readouterr().out)
    assert expected["status"] == "needs_login" and expected["next_action"] == "open_setup"
    host = HostRuntime(app)
    try:
        result = await build_server(host=host).call_tool("get_academic_timetable", {})
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
    finally:
        host.close()


def test_timetable_catalog_extends_existing_school_business_and_keeps_one_converter():
    catalog = build_capability_catalog()
    services = {row["service_id"]: row for row in catalog["services"]}
    academic = services["jw_academics"]
    assert academic["configuration_id"] == "school" and academic["login_id"] == "jw"
    assert next(feature for feature in academic["features"] if feature["id"] == "academic_timetable")["tools"] == [
        "get_academic_timetable"]
    conversion = [feature for row in services.values() for feature in row["features"]
                  if feature["id"] == "timetable_conversion"]
    assert len(conversion) == 1 and conversion[0]["tools"] == []
    school = next(profile for profile in catalog["profiles"] if profile["configuration_id"] == "school")
    assert {services[key]["login_id"] for key in school["service_ids"]} == {"jw", "mystu", "repair"}


@pytest.mark.asyncio
async def test_timetable_tool_is_read_only_and_existing_learning_tools_stay_cached(app, monkeypatch):
    calls = []

    def query(*args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setattr(app, "query", query)
    host = HostRuntime(app)
    try:
        server = build_server(host=host)
        tools = {tool.name: tool for tool in await server.list_tools()}
        timetable = tools["get_academic_timetable"]
        assert timetable.annotations.read_only_hint is True
        assert timetable.annotations.idempotent_hint is True
        assert timetable.annotations.open_world_hint is True
        assert timetable.input_schema["properties"]["semester"]["default"] == ""
        await server.call_tool("get_schedule", {})
        await server.call_tool("get_courses", {})
    finally:
        host.close()
    assert calls == [("event", "", 20, 0, "mystu"), ("course", "", 20, 0, "all")]
