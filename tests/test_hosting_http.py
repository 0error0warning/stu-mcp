"""Real loopback transport tests; no school accounts, requests or system changes."""
import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_takeout import Catalog

from stu_mcp.features.takeout.client import BASE
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server
from stu_mcp.transports.http import HTTPSettings, build_http_app, load_bearer

TOKEN = "synthetic_http_token_not_a_real_credential_12345"


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / "http-token"
    path.write_text(TOKEN, encoding="ascii")
    path.chmod(0o600)
    return path


@pytest.fixture
def http_server(app, tmp_path, monkeypatch, token_file):
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    monkeypatch.setenv("STU_MCP_INTERACTION", "disabled")
    host = HostRuntime(app, transport="streamable-http")
    closed = []
    shutdown = host.repairs.shutdown

    def observed_shutdown():
        closed.append(True)
        shutdown()

    monkeypatch.setattr(host.repairs, "shutdown", observed_shutdown)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(
            build_http_app(build_server(host=host), HTTPSettings(port=port), token_file),
            log_level="critical", access_log=False, proxy_headers=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started, "loopback server startup failed"
        try:
            yield f"http://127.0.0.1:{port}/mcp", host, closed
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), "loopback server did not stop"
            assert closed == [True]
            host.close()
            assert closed == [True]


@asynccontextmanager
async def client_for(url):
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False) as http,
        streamable_http_client(url, http_client=http) as (read, write),
        ClientSession(read, write, read_timeout_seconds=10) as client,
    ):
        await client.initialize()
        yield client


def structured(result):
    return result.model_dump(by_alias=True)["structuredContent"]


async def test_real_http_two_clients_share_state_and_disconnect_does_not_close_host(http_server):
    url, host, closed = http_server
    async with client_for(url) as first:
        tools = await first.list_tools()
        assert len(tools.tools) == 48
        capabilities = structured(await first.call_tool("get_capabilities", {}))
        assert capabilities["hosting"]["transport"] == "streamable-http"
        assert capabilities["hosting"]["identity_scope"] == "single_user_instance"
        assert not capabilities["hosting"]["interaction"]["available"]
        assert capabilities["execution"]["scope"] == "mcp_host"
        draft = structured(await first.call_tool("prepare_repair_draft", {"title": "合成故障"}))
        async with client_for(url) as second:
            record = structured(await second.call_tool("get_repair_draft", {"draft_id": draft["draft_id"]}))
            assert record["preview"]["title"] == "合成故障"
        assert closed == []
        record = structured(await first.call_tool("get_repair_draft", {"draft_id": draft["draft_id"]}))
        assert record["draft_id"] == draft["draft_id"]
        denied = structured(await first.call_tool("submit_repair_draft", {
            "draft_id": draft["draft_id"], "review_id": "not-reviewed"}))
        assert denied["status"] == "repair_confirmation_required"
        setup = structured(await first.call_tool("open_setup", {}))
        assert setup["status"] == "host_setup_required"
        assert "url" not in setup and TOKEN not in json.dumps(setup)
        # Exercise the new planner over the actual transport using synthetic API
        # data, independently of the third party's current network availability.
        class Scheduled(Catalog):
            def settings(self, shop_id):
                return {"shopId": shop_id, "isOpenTakeoutBook": "T", "customTakeoutBookDay": "2",
                        "customTakeoutOrderBookTimeNew": '[{"time":690,"advanceOrderMinutes":"50"}]'}
        host.app.vault.save("takeout", {"cookies": [], "takeout_config": {
            "server": BASE, "userId": "123", "appletId": "456", "default_area": "700",
            "apiToken": "SYNTHETIC_API", "signToken": "SYNTHETIC_SIGN",
            "salt": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"}})
        host.app.takeout.client_factory = Scheduled
        host.app.takeout.clock = lambda: 0  # 1970-01-01 08:00+08:00, before the synthetic cutoff
        meal = structured(await first.call_tool("find_takeout_meal_shops", {
            "area_id": "700", "meal_period": "午餐", "scan_limit": 1}))
        assert meal["ok"] and meal["matched_in_page"] == 1
        assert meal["has_more"] and meal["next_offset"] == 1
        assert meal["items"][0]["slots"][0]["delivery_end"] is None
        assert meal["ordering_supported"] is False and "SYNTHETIC_API" not in json.dumps(meal)
    assert closed == [] and host._setup is None


def test_http_auth_host_origin_query_and_size_limits(http_server):
    url, _, _ = http_server
    with httpx.Client(trust_env=False, timeout=10) as client:
        assert client.post(url).status_code == 401
        assert client.post(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.post(url, headers=[("Authorization", f"Bearer {TOKEN}"),
                                         ("Authorization", f"Bearer {TOKEN}")]).status_code == 401
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(url, headers=headers | {"Host": "attacker.invalid"})
        assert response.status_code == 421 and "attacker" not in response.text
        response = client.post(url, headers=headers | {"Origin": "https://attacker.invalid"})
        assert response.status_code == 403 and "attacker" not in response.text
        assert client.post(url + "?token=never", headers=headers).status_code == 400
        assert client.post(url.replace("/mcp", "/setup"), headers=headers).status_code == 404
        response = client.post(url, headers=headers | {"Content-Type": "application/json",
                                                      "Accept": "application/json, text/event-stream"},
                               content=b" " * (1024 * 1024 + 1))
        assert response.status_code == 413
        # Even error responses do not reflect bearer secrets or request bodies.
        assert TOKEN not in response.text


@pytest.mark.parametrize("settings", [HTTPSettings(host="hostname.invalid"), HTTPSettings(port=0),
    HTTPSettings(public_url="http://public.invalid/mcp"),
    HTTPSettings(public_url="https://user:pass@example.test/mcp"),
    HTTPSettings(public_url="https://example.test/mcp?token=bad"),
    HTTPSettings(public_url="https://*.example.test/mcp"),
    HTTPSettings(public_url="https://example.test/other")])
def test_invalid_http_configuration_fails_closed(settings):
    with pytest.raises(AppError, match="HTTP"):
        settings.security()


def test_private_proxy_has_explicit_host_origin_and_no_wildcards():
    security = HTTPSettings(host="0.0.0.0", public_url="https://my-node.example.test/mcp").security()
    assert security.enable_dns_rebinding_protection
    assert "my-node.example.test" in security.allowed_hosts
    assert "https://my-node.example.test" in security.allowed_origins
    assert not any("*" in entry for entry in security.allowed_hosts + security.allowed_origins)


def test_auth_file_required_and_invalid_token_safe(tmp_path):
    with pytest.raises(AppError) as error:
        load_bearer(None)
    assert error.value.code == "http_auth_required"
    path = tmp_path / "token"
    path.write_bytes(b"short\n")
    path.chmod(0o600)
    with pytest.raises(AppError) as error:
        load_bearer(path)
    assert "short" not in str(error.value)


async def test_stdio_and_http_advertise_identical_tool_definitions(app):
    # Transport only changes instance instructions/capabilities, not tool APIs.
    local = HostRuntime(app)
    remote = HostRuntime(app, transport="streamable-http")
    try:
        first, second = await asyncio.gather(build_server(host=local).list_tools(),
                                            build_server(host=remote).list_tools())
        assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    finally:
        local.close()
        remote.close()
