"""CLI/MCP updater integration with synthetic releases and no installer or network."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from unittest.mock import Mock

import httpx
import pytest

from stu_mcp import __version__
from stu_mcp.cli import main
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server
from stu_mcp.update_guard import register_instance
from stu_mcp.update_install import Installation
from stu_mcp.updates import RELEASES, UpdateService


class InactiveCheckin:
    def status(self):
        return {"ok": True, "service_running": False}


@pytest.mark.parametrize("verified", [True, False])
def test_closing_repair_allows_only_a_verified_completed_submission(app, verified):
    host = HostRuntime(app, checkin=InactiveCheckin())
    identity = host.repairs.prepare(title="合成故障")["draft_id"]
    raw = host.repairs.drafts[identity]
    raw.update(status="submitted" if verified else "submission_unknown", request_sent=True,
               submitted_by_mcp=verified, receipt={"order_id": "SYNTHETIC_ORDER"} if verified else None)
    host.repairs.close(identity)
    try:
        if verified:
            host._before_update()
        else:
            with pytest.raises(AppError) as error:
                host._before_update()
            assert error.value.code == "update_repair_active"
    finally:
        host.close()


@pytest.fixture
def updater(monkeypatch, tmp_path):
    monkeypatch.setattr("stu_mcp.update_guard.user_cache_path", lambda *a, **k: tmp_path / "cache")
    monkeypatch.setattr("stu_mcp.updates.installed_version", lambda: __version__)
    package = io.BytesIO()
    name = "stu_mcp-99.0.0-py3-none-any.whl"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("stu_mcp-99.0.0.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: stu-mcp\nVersion: 99.0.0\nRequires-Python: >=3.11\n")
    wheel = package.getvalue()
    base = "https://github.com/0error0warning/stu-mcp/releases/download/v99.0.0/"
    releases = [{"tag_name": "v99.0.0", "draft": False, "prerelease": False,
                 "published_at": "2099-01-01T00:00:00Z", "assets": [
                     {"name": value, "browser_download_url": base + value}
                     for value in (name, "SHA256SUMS.txt")]}]
    requests = []

    def respond(request):
        requests.append(str(request.url))
        if str(request.url) == RELEASES:
            return httpx.Response(200, json=releases)
        if str(request.url) == base + "SHA256SUMS.txt":
            return httpx.Response(200, content=f"{hashlib.sha256(wheel).hexdigest()}  {name}\n".encode())
        if str(request.url) == base + name:
            return httpx.Response(200, content=wheel)
        pytest.fail("Unexpected update request: " + str(request.url))

    installed = Mock(return_value={"installed_version": "99.0.0", "restart_required": True})
    service = UpdateService(transport=httpx.MockTransport(respond),
                            probe=lambda: Installation("uv_tool", __version__), install=installed)
    return service, installed, requests


def host_for(app, updater, *, transport="stdio", checkin=None):
    host = HostRuntime(app, checkin=checkin or InactiveCheckin(), transport=transport)
    host.updates = updater
    return host


async def call(server, name):
    result = await server.call_tool(name, {})
    return result.model_dump(by_alias=True)["structuredContent"]


@pytest.mark.asyncio
async def test_cli_and_mcp_share_on_demand_checks_without_installing(app, updater, monkeypatch, capsys):
    service, installed, requests = updater
    monkeypatch.setattr("stu_mcp.updates.UpdateService", lambda: service)
    assert main(["update", "--check"]) == 0
    cli = json.loads(capsys.readouterr().out)
    host = host_for(app, service)
    try:
        mcp = await call(build_server(host=host), "check_updates")
        assert cli["checked_at"] <= mcp["checked_at"]
        assert {k: v for k, v in cli.items() if k != "checked_at"} == {
            k: v for k, v in mcp.items() if k != "checked_at"}
        assert cli["status"] == "update_available"
        assert requests == [RELEASES, RELEASES]
        assert not service.capabilities()["automatic_checks"]
        installed.assert_not_called()
    finally:
        host.close()


def test_one_cli_call_downloads_checks_and_installs(app, updater, monkeypatch, capsys):
    service, installed, requests = updater
    worker_check = Mock()
    monkeypatch.setattr("stu_mcp.updates.UpdateService", lambda: service)
    monkeypatch.setattr("stu_mcp.hosting.check_worker_before_update", worker_check)
    assert main(["update"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "updated" and result["restart_required"]
    assert result["running_version"] == __version__
    assert result["installed_version"] == "99.0.0"
    installed.assert_called_once()
    worker_check.assert_called_once()
    assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_one_mcp_call_updates_then_fences_old_process_business(app, updater, transport):
    service, installed, _requests = updater
    host = host_for(app, service, transport=transport)
    server = build_server(host=host)
    try:
        result = await call(server, "update_self")
        assert result["status"] == "updated" and result["restart_required"]
        installed.assert_called_once()
        assert (await call(server, "get_tasks"))["status"] == "update_restart_required"
        app.status = Mock(side_effect=AssertionError("Old process must not re-enter business services"))
        capabilities = await call(server, "get_capabilities")
        assert capabilities["updates"]["restart_required"]
        assert capabilities["version"] == __version__
        app.status.assert_not_called()
        assert (await call(server, "check_updates"))["restart_required"]
    finally:
        host.close()


@pytest.mark.asyncio
async def test_active_request_and_update_mutually_exclude_other_tools(app, updater):
    service, installed, requests = updater
    host = host_for(app, service)
    server = build_server(host=host)
    try:
        with host.tool_operation("get_tasks"):
            assert (await call(server, "update_self"))["status"] == "update_busy"
        with host.tool_operation("update_self"):
            assert (await call(server, "get_tasks"))["status"] == "update_busy"
        assert not requests
        installed.assert_not_called()
        assert host._active_operations == 0 and not host._updating
    finally:
        host.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["needs_information", "awaiting_confirmation", "submitting", "submission_unknown"])
async def test_unfinished_repair_blocks_install_without_destroying_draft(app, updater, state):
    service, installed, _requests = updater
    host = host_for(app, service)
    host.repairs.drafts["synthetic"] = {"status": state}
    try:
        result = await call(build_server(host=host), "update_self")
        assert result["status"] == "update_repair_active"
        installed.assert_not_called()
        assert not service.restart_required
        assert host.repairs.drafts["synthetic"]["status"] == state
    finally:
        host.repairs.drafts.clear()
        host.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("running", [True, None])
async def test_existing_or_unverified_worker_blocks_install(app, updater, running):
    service, installed, _requests = updater
    worker = Mock()
    worker.status.return_value = {"service_running": running}
    host = host_for(app, service, checkin=worker)
    try:
        result = await call(build_server(host=host), "update_self")
        assert result["status"] == "update_worker_active"
        installed.assert_not_called()
        assert not service.restart_required
    finally:
        host.close()


@pytest.mark.asyncio
async def test_open_settings_server_blocks_install_without_closing_login_session(app, updater):
    service, installed, _requests = updater
    host = host_for(app, service)
    settings = Mock()
    host._setup = settings
    try:
        result = await call(build_server(host=host), "update_self")
        assert not result["ok"] and result["status"] == "update_setup_active"
        installed.assert_not_called()
        settings.close.assert_not_called()
        assert not service.restart_required
    finally:
        host.close()
    settings.close.assert_called_once()


def test_cli_does_not_exclude_a_running_instance_in_the_same_install(updater, monkeypatch, capsys):
    service, installed, _requests = updater
    monkeypatch.setattr("stu_mcp.updates.UpdateService", lambda: service)
    with register_instance("mcp"):
        assert main(["update"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "update_busy"
    installed.assert_not_called()


@pytest.mark.asyncio
async def test_install_failure_is_not_success_and_fences_uncertain_old_process(app, updater):
    service, installed, _requests = updater
    installed.side_effect = AppError("update_install_failed", "Synthetic install failure")
    host = host_for(app, service)
    server = build_server(host=host)
    try:
        result = await call(server, "update_self")
        assert not result["ok"] and result["status"] == "update_install_failed"
        assert result["installed_version"] == __version__
        assert result["restart_required"]
        assert (await call(server, "get_tasks"))["status"] == "update_restart_required"
    finally:
        host.close()


@pytest.mark.asyncio
async def test_update_tool_contract_matches_both_transports_and_takes_no_credentials(app, updater):
    service, _installed, _requests = updater
    local, remote = host_for(app, service), host_for(app, service, transport="streamable-http")
    try:
        contracts = []
        for host in (local, remote):
            tools = await build_server(host=host).list_tools()
            selected = {tool.name: tool.model_dump(by_alias=True) for tool in tools
                        if tool.name in {"check_updates", "update_self"}}
            assert set(selected) == {"check_updates", "update_self"}
            for tool in selected.values():
                assert tool["inputSchema"].get("properties", {}) == {}
                assert tool["inputSchema"].get("required", []) == []
            check, update = selected["check_updates"], selected["update_self"]
            assert check["annotations"]["readOnlyHint"]
            assert check["annotations"]["idempotentHint"]
            assert not update["annotations"]["readOnlyHint"]
            assert update["annotations"]["destructiveHint"]
            assert not update["annotations"]["idempotentHint"]
            contracts.append(selected)
        assert contracts[0] == contracts[1]
    finally:
        local.close()
        remote.close()
