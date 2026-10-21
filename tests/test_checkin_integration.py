"""Real stdio + loopback + detached worker, with synthetic platform responses only."""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stu_mcp.checkin import CheckinClient

FIXTURE = Path(__file__).resolve().parent / "checkin_worker" / "worker_fixture.py"


def wait_for(condition, seconds=15):
    until = time.monotonic() + seconds
    while not condition():
        if time.monotonic() >= until:
            raise AssertionError("Integration condition not reached")
        time.sleep(.05)


def data(result):
    return result.model_dump(by_alias=True)["structuredContent"]


@contextmanager
def windows_handle(handle):
    try:
        yield handle
    finally:
        handle.Close()


def test_real_detached_concurrent_launch_and_stale_runtime_recovery(tmp_path):
    # Empty private home: no credentials, platform calls, browser windows or keyring writes.
    clients = [CheckinClient(tmp_path, startup_timeout=15) for _ in range(3)]
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            views = list(pool.map(lambda client: client._ensure()[0], clients))
        assert all(view["status"] == "not_logged_in" for view in views)
        assert len({view["process_id"] for view in views}) == 1
        assert len({view["service_instance"] for view in views}) == 1
        old = json.loads((tmp_path / "runtime.json").read_text())
        assert clients[0].stop_service()["status"] == "service_not_started"
        # Simulate a crash's stale discovery file, without sending signals to any PID.
        (tmp_path / "runtime.json").write_text(json.dumps(old))
        assert clients[0].status()["status_reason"] == "stale_runtime"
        new, _ = clients[0]._ensure()
        assert new["status"] == "not_logged_in", new
        assert new["service_instance"] != old["instance_id"]
        assert not (tmp_path / "state.enc").exists()
    finally:
        assert clients[0].stop_service()["status"] == "service_not_started"


@pytest.mark.asyncio
async def test_mcp_started_worker_survives_client_job_cleanup(tmp_path):
    home = tmp_path / "worker"
    observer = CheckinClient(home)
    code = ("import webbrowser; webbrowser.open=lambda *a,**k: True; "
            "from stu_mcp.server import build_server; build_server().run(transport='stdio')")
    # Exercise the desktop branch with a synthetic display hint. The opener is
    # stubbed above, so this needs neither a real display server nor a browser.
    env = dict(os.environ, STU_MCP_HOME=str(tmp_path / "mcp"), STU_CHECKIN_HOME=str(home),
               STU_MCP_INTERACTION="desktop", DISPLAY=":99")
    params = StdioServerParameters(command=sys.executable, args=["-c", code],
                                  env=env)
    try:
        async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=40) as mcp:
            await mcp.initialize()
            initial = data(await mcp.call_tool("get_checkin_status", {}))
            assert initial["status"] == "service_not_started"
            opened = data(await mcp.call_tool("list_checkin_courses", {}))
            assert opened["status"] == "not_logged_in" and opened["browser_opened"]
        # The MCP SDK closes a kill-on-close Job Object on Windows, including a graceful exit.
        after = observer.status()
        assert after["status"] == "not_logged_in", after
        assert after["service_instance"] == opened["service_instance"]
        if os.name == "nt":
            import win32api
            import win32con
            import win32security

            with (windows_handle(win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                                                      False, after["process_id"])) as process,
                  windows_handle(win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)) as token):
                worker_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            with windows_handle(win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)) as token:
                user_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            assert worker_sid == user_sid  # OS keyring remains the current user's, without elevation.
    finally:
        assert observer.stop_service()["status"] == "service_not_started"


@pytest.mark.asyncio
async def test_web_and_reconnected_mcp_share_worker_and_truthful_states(tmp_path):
    home = tmp_path / "worker"
    env = dict(os.environ, STU_CHECKIN_HOME=str(home))
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen([sys.executable, str(FIXTURE)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **flags)
    observer = CheckinClient(home)
    params = StdioServerParameters(command=sys.executable, args=["-m", "stu_mcp", "serve"],
                                  env=dict(os.environ, STU_MCP_HOME=str(tmp_path / "mcp"), STU_CHECKIN_HOME=str(home)))
    try:
        wait_for(lambda: observer.status()["status"] == "paused")
        info = json.loads((home / "runtime.json").read_text())
        with httpx.Client(base_url=info["url"], trust_env=False) as browser:
            browser.get("/")
            browser.headers.update({"Origin": info["url"].rstrip("/"), "X-STU-Client": "local-ui"})
            async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=30) as mcp:
                await mcp.initialize()
                selected = data(await mcp.call_tool("select_checkin_courses", {"all_courses": True}))
                assert selected["selected_courses"] == ["course-a", "course-b"]
                web = browser.get("api/state").json()
                assert web["selected_courses"] == selected["selected_courses"]
                started = data(await mcp.call_tool("start_checkin_monitor", {"minutes": 0}))
                # Windows venv's launcher can parent the actual interpreter process.
                assert started["process_id"] == info["pid"] and started["monitoring"]
            # MCP closed; worker still alive and continuous monitoring continues.
            assert process.poll() is None and observer.status()["monitoring"]
            async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=30) as mcp:
                await mcp.initialize()
                reused = data(await mcp.call_tool("get_checkin_status", {}))
                assert reused["service_instance"] == started["service_instance"]
                wait_for(lambda: observer.results().get("total") == 2)
                results = data(await mcp.call_tool("get_checkin_results", {}))
                assert all(r["status"] == "already_signed" for r in results["items"])
                assert results["last_confirmed_at"] == 0
                (home / "fixture-controls.json").write_text('{"fail":true}')
                wait_for(lambda: observer.status()["status"] == "query_error")
                broken = data(await mcp.call_tool("get_checkin_status", {}))
                assert broken["monitoring"] and broken["failed_courses"] == ["course-b"]
                assert broken["course_statuses"]["course-a"]["last_read_at"] > 0
                (home / "fixture-controls.json").write_text('{"fail":false}')
                wait_for(lambda: observer.status()["status"] == "monitoring")
                # Web pause is immediately authoritative for MCP too.
                assert browser.post("api/pause", json={}).json()["ok"]
                paused = data(await mcp.call_tool("get_checkin_status", {}))
                assert paused["status"] == "paused" and not paused["resume_enabled"]
                stopped = data(await mcp.call_tool("stop_checkin_service", {}))
                assert stopped["status"] == "service_not_started"
            process.wait(timeout=10)
            assert process.returncode == 0
            assert not (home / "runtime.json").exists()
    finally:
        if process.poll() is None:
            observer.stop_service()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()  # Exact synthetic child handle only, never a discovery PID.
                process.wait(timeout=5)
        if process.returncode:
            pytest.fail("Synthetic worker failed: " + process.stderr.read().decode(errors="replace")[-3000:])
