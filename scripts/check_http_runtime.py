"""Bounded loopback CLI smoke check, executed by an isolated installed interpreter.

The caller supplies only paths inside its disposable installation directory.
Child output and exceptions are never printed: a dependency error can contain
authentication headers. No school endpoint, browser or OS keyring is used.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from stu_checkin import auth as checkin_auth
from stu_mcp import __version__, checkin_login, credentials, execution, hosting, terminal, webvpn_cli
from stu_mcp.transports import http as http_transport

CONTRACT = Path(__file__).with_name("mcp-tool-contract.json")
CONTRACT_FIELDS = ("name", "inputSchema", "outputSchema", "annotations")


def assert_tool_contract(tools) -> list[str]:
    """Compare all public tool fields against the committed v0.5.0 contract.

    Descriptions may clarify behavior; they are reported separately. Everything
    used by existing clients to discover or invoke the 38 tools stays exact.
    """
    baseline = json.loads(CONTRACT.read_text(encoding="utf-8"))
    previous = {tool["name"]: tool for tool in baseline["tools"]}
    current = {tool.name: tool.model_dump(by_alias=True, exclude_none=True) for tool in tools}
    assert len(tools) == len(current) == len(previous) == baseline["tool_count"] == 38, "tool count changed"
    assert current.keys() == previous.keys(), "tool names changed"
    for name in previous:
        assert all(current[name].get(field) == previous[name].get(field) for field in CONTRACT_FIELDS), (
            "tool schema/annotations changed: " + name)
    return sorted(name for name in previous
                  if current[name].get("description") != previous[name].get("description"))


class OwnedHTTPProcess:
    """Own precisely this child's process tree, including Windows venv launchers.

    A process-name or port search could kill someone else's MCP. A fresh Windows
    Job Object or POSIX session instead confines cleanup to this spawned tree.
    """
    def __init__(self, command, *, env, cwd, stdout, stderr):
        self.job = None
        self.process = None
        self.closed = False
        if os.name == "nt":
            import win32api
            import win32job

            self.win32api, self.win32job = win32api, win32job
            self.job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, limits)
        try:
            self.process = subprocess.Popen(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if self.job is not None:
                self.win32job.AssignProcessToJobObject(self.job, self.process._handle)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.job is not None:
            try:
                self.win32job.TerminateJobObject(self.job, 1)
            finally:
                self.win32api.CloseHandle(self.job)
                self.job = None
        if self.process is None:
            return
        if os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
        elif self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)


def assert_listener_closed(port: int) -> None:
    deadline = time.monotonic() + 5
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                if time.monotonic() >= deadline:
                    raise RuntimeError("owned HTTP listener remained open after cleanup")
        except OSError:
            return
        time.sleep(.05)


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
        descriptions = assert_tool_contract(tools)
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
        assert capabilities["hosting"]["interaction"]["scope"] == "manual_browser"
        flows = capabilities["hosting"]["login_flows"]
        assert flows["duifene"]["method"] == "wechat_callback"
        assert flows["duifene"]["requires_display"] is False
        assert capabilities["hosting"]["default_authentication"] == "http"
        assert capabilities["hosting"]["browser_backend"] == "optional_explicit"
        assert flows["webvpn"]["automatic_renewal"] == "http_totp"
        assert flows["webvpn"]["manual_login"] == "http_cli"
        for source in ("jw", "mystu", "yuketang"):
            assert flows[source]["input"] == "host_tty"
            assert flows[source]["new_login_requires_display"] is False
        assert flows["repair"]["method"] == "isolated_cas_http"
        assert capabilities["repair"]["default_backend"] == "http"
        assert capabilities["privacy"]["credential_backend"] == "encrypted_file"
        assert capabilities["checkin"]["status"] == "service_not_started"
        # A passive status read must not launch the worker or require a display.
        status = await session.call_tool("get_checkin_status", {})
        assert status.model_dump(by_alias=True)["structuredContent"]["status"] == "service_not_started"
        # Invalid inputs exercise the installed tools without sending school requests.
        invalid = await session.call_tool("diagnose_campus_network", {"service_id": "synthetic-invalid"})
        assert invalid.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_service"
    print("HTTP: 38 tool names, input/output schemas and annotations match v0.5.0; description updates: "
          + (", ".join(descriptions) or "none"), flush=True)


def main() -> None:
    interpreter, root, token_file = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    assert importlib.util.find_spec("playwright") is None, "core wheel unexpectedly installed Playwright"
    for module in (credentials, execution, hosting, http_transport, checkin_login, terminal, webvpn_cli, checkin_auth):
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
                            capture_output=True, timeout=20, check=False,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert status.returncode == 0
    assert json.loads(status.stdout)["version"] == __version__
    assert token.encode() not in status.stdout + status.stderr
    # Actual installed CLI dispatch must fail before input or App side effects.
    for arguments in (*(("login", source) for source in ("jw", "mystu", "yuketang", "webvpn", "repair", "duifene")),
                      ("webvpn-auto", "configure")):
        denied = subprocess.run([interpreter, "-m", "stu_mcp", *arguments], env=env, cwd=root,
                                input=b"", capture_output=True, timeout=15, check=False,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert denied.returncode == 1
        assert json.loads(denied.stdout)["status"] == "terminal_required"
        assert token.encode() not in denied.stdout + denied.stderr
    browser = subprocess.run([interpreter, "-m", "stu_mcp", "browser", "install"], env=env, cwd=root,
                             input=b"", capture_output=True, timeout=15, check=False,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert browser.returncode == 1
    assert json.loads(browser.stdout)["status"] == "browser_unavailable"
    assert not browser.stderr, "core must explain the optional extra without invoking a downloader"
    assert token.encode() not in browser.stdout
    assert not Path(env["STU_CHECKIN_HOME"]).exists()
    # The child binds only loopback. A rare bind race fails this bounded check;
    # it never searches for or terminates another process using the port.
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    command = [interpreter, "-m", "stu_mcp", "serve", "--transport", "streamable-http",
               "--host", "127.0.0.1", "--port", str(port), "--auth-token-file", str(token_file),
               "--name", "installed-http"]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        child = OwnedHTTPProcess(command, env=env, cwd=root, stdout=stdout, stderr=stderr)
        process = child.process
        try:
            asyncio.run(asyncio.wait_for(_handshake(f"http://127.0.0.1:{port}/mcp", token, process), timeout=45))
            assert process.poll() is None
        finally:
            child.close()
        assert process.poll() is not None
        assert_listener_closed(port)
        for stream in (stdout, stderr):
            assert stream.tell() <= 128 * 1024
            stream.seek(0)
            assert token.encode() not in stream.read()
    assert not (root / "http-checkin").exists()
    print("core: Playwright absent; CLI login defaults to HTTP/host TTY; SDK transport and owned-tree cleanup verified",
          flush=True)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        main()
    except BaseException:
        print("HTTP installed-runtime check failed; child output withheld", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
