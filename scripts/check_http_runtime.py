"""Bounded loopback CLI smoke check, executed by an isolated installed interpreter.

The caller supplies only paths inside its disposable installation directory.
Child output and exceptions are never printed: a dependency error can contain
authentication headers. No school endpoint, browser or OS keyring is used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from stu_mcp import __version__, credentials, execution, hosting
from stu_mcp.transports import http as http_transport


def _stop_child(process: subprocess.Popen) -> None:
    """Stop only the HTTP process created by this smoke check, with bounded waits."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def _handshake(url: str, token: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 15
    async with httpx2.AsyncClient(trust_env=False, timeout=.75) as anonymous:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("HTTP child exited before readiness")
            try:
                response = await anonymous.get(url)
                if response.status_code == 401:
                    break
            except httpx2.HTTPError:
                pass
            await asyncio.sleep(.1)
        else:
            raise TimeoutError("HTTP startup deadline exceeded")
    async with (
        httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}, trust_env=False,
                           timeout=10, follow_redirects=False) as http,
        streamable_http_client(url, http_client=http) as (read, write),
        ClientSession(read, write, read_timeout_seconds=10) as session,
    ):
        initialized = await session.initialize()
        assert initialized.server_info.name == "stu-mcp"
        assert initialized.server_info.version == __version__
        tools = (await session.list_tools()).tools
        assert len(tools) == 38
        assert {"get_capabilities", "open_setup", "prepare_repair_draft",
                "diagnose_campus_network", "audit_campus_network"} <= {tool.name for tool in tools}
        response = await session.call_tool("get_capabilities", {})
        capabilities = response.model_dump(by_alias=True)["structuredContent"]
        assert capabilities["version"] == __version__
        assert capabilities["execution"]["scope"] == "mcp_host"
        assert capabilities["execution"]["instance_name"] == "installed-http"
        assert capabilities["execution"]["client_network_checked"] is False
        assert capabilities["execution"]["school_route_automatic"] is False
        assert capabilities["hosting"]["transport"] == "streamable-http"
        assert capabilities["hosting"]["identity_scope"] == "single_user_instance"
        assert capabilities["hosting"]["multi_user"] is False
        assert capabilities["hosting"]["credential_backend"] == "encrypted_file"
        assert capabilities["hosting"]["interaction"]["available"] is False
        assert capabilities["checkin"]["status"] == "service_not_started"
        # Invalid inputs exercise the installed tools without sending school requests.
        invalid = await session.call_tool("diagnose_campus_network", {"service_id": "synthetic-invalid"})
        assert invalid.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_service"


def main() -> None:
    interpreter, root, token_file = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    for module in (credentials, execution, hosting, http_transport):
        assert Path(module.__file__).is_relative_to(root / "tools")
    master_file = Path(os.environ["STU_MCP_KEY_FILE"]).resolve()
    assert master_file.is_relative_to(root) and token_file.is_relative_to(root)
    assert master_file != token_file
    token = token_file.read_text(encoding="ascii").strip()
    env = {**os.environ, "STU_MCP_HOME": str(root / "http-data"),
           "STU_CHECKIN_HOME": str(root / "http-checkin"), "STU_MCP_INTERACTION": "disabled"}
    env.pop("PYTHONPATH", None)
    env.pop("STU_CHECKIN_PYTHON", None)
    status = subprocess.run([interpreter, "-m", "stu_mcp", "status"], env=env, cwd=root,
                            capture_output=True, timeout=20, check=False)
    assert status.returncode == 0
    assert json.loads(status.stdout)["version"] == __version__
    assert token.encode() not in status.stdout + status.stderr
    # The child binds only loopback. A rare bind race fails this bounded check;
    # it never searches for or terminates another process using the port.
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    command = [interpreter, "-m", "stu_mcp", "serve", "--transport", "streamable-http",
               "--host", "127.0.0.1", "--port", str(port), "--auth-token-file", str(token_file),
               "--name", "installed-http"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, env=env, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            asyncio.run(asyncio.wait_for(_handshake(f"http://127.0.0.1:{port}/mcp", token, process), timeout=45))
            assert process.poll() is None
        finally:
            _stop_child(process)
        for stream in (stdout, stderr):
            assert stream.tell() <= 128 * 1024
            stream.seek(0)
            assert token.encode() not in stream.read()
    assert not (root / "http-checkin").exists()
    print("HTTP: installed CLI served 38 tools; SDK handshake, execution scope and isolated status verified", flush=True)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        main()
    except BaseException:
        print("HTTP installed-runtime check failed; child output withheld", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
