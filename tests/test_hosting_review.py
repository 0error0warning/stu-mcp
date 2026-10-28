"""Independent synthetic review of HTTP boundaries and shared host lifetime."""
from unittest.mock import Mock

import httpx
import pytest
from cryptography.fernet import Fernet
from starlette.responses import Response

from stu_mcp.checkin import CheckinClient
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server
from stu_mcp.setup_web import SetupServer
from stu_mcp.transports.http import HTTPSettings, PrivateHTTP, build_http_app, load_bearer

TOKEN = b"SYNTHETIC_PRIVATE_HTTP_TOKEN_0123456789"


async def _rpc(client, method, *, params=None, request_id=1, session=None):
    headers = {"Mcp-Session-Id": session} if session else {}
    body = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        body["id"] = request_id
    if params is not None:
        body["params"] = params
    return await client.post("/mcp", json=body, headers=headers)


@pytest.mark.asyncio
async def test_real_sdk_http_session_disconnect_keeps_peer_and_shared_repair_draft(app, tmp_path):
    token = tmp_path / "token"
    token.write_bytes(TOKEN)
    token.chmod(0o600)
    checkin = CheckinClient(home=tmp_path / "checkin")
    host = HostRuntime(app, checkin=checkin, transport="streamable-http")
    shutdown = Mock(wraps=host.repairs.shutdown)
    host.repairs.shutdown = shutdown
    server = build_server(host=host)
    wrapped = build_http_app(server, HTTPSettings(), token)
    async with (
        wrapped.app.router.lifespan_context(wrapped.app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://127.0.0.1:8765",
                          headers={"Authorization": "Bearer " + TOKEN.decode(),
                                   "Accept": "application/json, text/event-stream"}) as client,
    ):
        sessions = []
        for index in range(2):
            response = await _rpc(client, "initialize", params={
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": f"synthetic-{index}", "version": "1"}})
            assert response.status_code == 200
            sessions.append(response.headers["mcp-session-id"])
            ready = await _rpc(client, "notifications/initialized", request_id=None, session=sessions[-1])
            assert ready.status_code == 202
        prepared = await _rpc(client, "tools/call", params={"name": "prepare_repair_draft",
                              "arguments": {"title": "合成故障"}}, session=sessions[0])
        draft = prepared.json()["result"]["structuredContent"]
        assert draft["status"] == "needs_information"
        removed = await client.delete("/mcp", headers={"Mcp-Session-Id": sessions[0]})
        assert removed.status_code == 200
        assert not host._closed
        shutdown.assert_not_called()
        peer = await _rpc(client, "tools/call", params={"name": "get_repair_draft",
                          "arguments": {"draft_id": draft["draft_id"]}}, session=sessions[1])
        assert peer.json()["result"]["structuredContent"]["preview"]["title"] == "合成故障"
        tools = await _rpc(client, "tools/list", session=sessions[1])
        assert len(tools.json()["result"]["tools"]) == 52
        assert "report_feedback" in {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert host._closed
    shutdown.assert_called_once()
    host.close()
    shutdown.assert_called_once()
    assert not checkin.home.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,status", [
    ([], 401),
    ([(b"authorization", b"Bearer WRONG")], 401),
    ([(b"authorization", b"Bearer " + TOKEN), (b"authorization", b"Bearer " + TOKEN)], 401),
    ([(b"authorization", b"Bearer " + TOKEN), (b"host", b"private.invalid")], 421),
    ([(b"authorization", b"Bearer " + TOKEN), (b"origin", b"https://private.invalid")], 403),
])
async def test_http_boundary_rejects_without_forwarding_or_echoing_request_data(headers, status):
    called = []

    async def downstream(scope, receive, send):
        called.append(scope)

    settings = HTTPSettings().security()
    wrapped = PrivateHTTP(downstream, TOKEN, settings)
    # Preserve duplicate request headers; httpx's mapping form would collapse them.
    if not any(key == b"host" for key, _ in headers):
        headers = [(b"host", b"127.0.0.1:8765"), *headers]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "method": "POST", "path": "/mcp",
             "query_string": b"", "headers": headers, "http_version": "1.1"}
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"SYNTHETIC_PRIVATE_BODY"}

    await wrapped(scope, receive, send)
    assert sent[0]["status"] == status
    assert not called
    rendered = repr(sent)
    for value in (TOKEN.decode(), "private.invalid", "SYNTHETIC_PRIVATE_BODY"):
        assert value not in rendered


def test_unstarted_setup_cleanup_does_not_wait_for_a_server_thread(app, monkeypatch):
    ui = SetupServer(app)
    shutdown = Mock(side_effect=AssertionError("shutdown before serve_forever would wait forever"))
    monkeypatch.setattr(ui.httpd, "shutdown", shutdown)
    try:
        ui.close()
        shutdown.assert_not_called()
    finally:
        ui.httpd.server_close()


@pytest.mark.parametrize("copied", [False, True])
def test_http_bearer_cannot_reuse_the_session_master_key(tmp_path, monkeypatch, copied):
    master = tmp_path / "master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o600)
    monkeypatch.setenv("STU_MCP_KEY_FILE", str(master))
    token = tmp_path / "token" if copied else master
    if copied:
        token.write_bytes(master.read_bytes())
        token.chmod(0o600)
    with pytest.raises(AppError):
        load_bearer(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("public_url,origin", [
    ("https://SERVER.example:443/mcp", "https://server.example"),
    ("http://LOCALHOST:80/mcp", "http://localhost"),
])
async def test_reverse_proxy_allowlist_accepts_canonical_client_headers(public_url, origin):
    async def downstream(scope, receive, send):
        await Response(status_code=204)(scope, receive, send)

    wrapped = PrivateHTTP(downstream, TOKEN, HTTPSettings(public_url=public_url).security())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped)) as client:
        response = await client.post(public_url, headers={"Authorization": "Bearer " + TOKEN.decode(),
                                                       "Origin": origin})
    assert response.status_code == 204
