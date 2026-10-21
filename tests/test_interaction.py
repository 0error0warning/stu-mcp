"""Synthetic host environments: never launch school login or expose a desktop."""
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from stu_mcp import auth, interaction
from stu_mcp.features.repair import adapter
from stu_mcp.runtime import AppError
from stu_mcp.setup_web import SetupServer


@pytest.fixture
def host(monkeypatch):
    monkeypatch.delenv("STU_MCP_INTERACTION", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    return monkeypatch


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_desktop_default_preserves_native_hosts(host, platform):
    host.setattr(interaction.sys, "platform", platform)
    assert interaction.require_interaction() == "desktop"


@pytest.mark.parametrize("display", ["DISPLAY", "WAYLAND_DISPLAY"])
def test_linux_desktop_requires_display(host, display):
    host.setattr(interaction.sys, "platform", "linux")
    with pytest.raises(AppError, match="显示环境") as exc:
        interaction.require_interaction("jw")
    assert exc.value.code == "interaction_unavailable"
    assert exc.value.source == "jw"
    host.setenv(display, ":99")
    assert interaction.require_interaction() == "desktop"


def test_virtual_display_requires_explicit_linux_display(host):
    host.setenv("STU_MCP_INTERACTION", "virtual-display")
    host.setattr(interaction.sys, "platform", "linux")
    with pytest.raises(AppError) as exc:
        interaction.require_interaction()
    assert exc.value.code == "interaction_unavailable"
    host.setenv("DISPLAY", ":99")
    assert interaction.require_interaction() == "virtual-display"
    host.setattr(interaction.sys, "platform", "win32")
    with pytest.raises(AppError):
        interaction.require_interaction()


def test_interaction_disabled_cannot_launch_or_start_repair_preflight(app, host):
    host.setenv("STU_MCP_INTERACTION", "disabled")
    started = Mock(side_effect=AssertionError("browser/network must not start"))
    host.setattr(auth, "sync_playwright", started)
    host.setattr(adapter, "direct_preflight", started)
    with pytest.raises(AppError) as login:
        auth.interactive_login(app.vault, "mystu")
    assert login.value.code == "interaction_unavailable"
    with pytest.raises(AppError) as repair, adapter.open_browser(Event(), started):
        pytest.fail("disabled interaction entered a browser context")
    assert repair.value.code == "interaction_unavailable"
    started.assert_not_called()


def test_unknown_mode_is_explicit_configuration_error(host):
    host.setenv("STU_MCP_INTERACTION", "headless")
    with pytest.raises(AppError) as exc:
        interaction.require_interaction()
    assert exc.value.code == "invalid_interaction_mode"


def test_virtual_display_repair_remains_headed_and_preserves_tls_and_direct_route(host):
    host.setattr(interaction.sys, "platform", "linux")
    host.setenv("STU_MCP_INTERACTION", "virtual-display")
    host.setenv("DISPLAY", ":99")
    page = SimpleNamespace(set_default_timeout=Mock())
    context = SimpleNamespace(route=Mock(), new_page=lambda: page)
    browser = SimpleNamespace(new_context=Mock(return_value=context), close=Mock())
    launch = Mock(return_value=browser)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    host.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(playwright))
    host.setattr(auth, "prepare_browser", lambda *_: None)
    host.setattr(adapter, "direct_preflight", lambda: {"transport": "direct"})
    with adapter.open_browser(Event(), Mock()) as session:
        assert session.page is page
    launch.assert_called_once_with(headless=False, args=adapter.DIRECT_BROWSER_ARGS)
    browser.new_context.assert_called_once_with(ignore_https_errors=False, service_workers="block")
    browser.close.assert_called_once()
    assert context.route.call_args.args[0] == "**/*"


def test_local_admin_opener_never_claims_remote_device_was_opened(host):
    host.setenv("STU_MCP_INTERACTION", "virtual-display")
    host.setattr(interaction.sys, "platform", "linux")
    host.setenv("DISPLAY", ":99")
    opened = Mock(return_value=True)
    host.setattr(interaction.webbrowser, "open", opened)
    assert not interaction.open_local_page("http://127.0.0.1:8766/#synthetic")
    opened.assert_not_called()
    host.setenv("STU_MCP_INTERACTION", "desktop")
    assert interaction.open_local_page("http://127.0.0.1:8766/#synthetic")
    opened.assert_called_once()


def test_setup_injected_opener_and_loopback_security_are_preserved(app):
    opened = Mock(return_value=True)
    ui = SetupServer(app, opener=opened)
    try:
        assert ui.start()
        opened.assert_called_once_with(ui.url)
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            assert client.get("/api/status", headers=headers).status_code == 200
            assert client.get("/api/status", headers={**headers, "Host": "example.org"}).status_code == 403
    finally:
        ui.close()


def test_setup_honors_requested_port(app):
    original = SetupServer(app)
    port = original.httpd.server_port
    original.httpd.server_close()
    requested = SetupServer(app, port=port)
    try:
        assert requested.httpd.server_port == port
        assert requested.host == f"127.0.0.1:{port}"
    finally:
        requested.httpd.server_close()


def test_setup_fixed_port_is_exclusive_without_disrupting_first_server(app):
    first = SetupServer(app)
    port = first.httpd.server_port
    first.start(open_browser=False)
    try:
        with pytest.raises(OSError):
            SetupServer(app, port=port)
        with httpx.Client(base_url=first.origin, trust_env=False) as client:
            assert client.get("/").status_code == 200
            assert client.get("/api/status", headers={"X-STU-Setup": first.secret}).status_code == 200
    finally:
        first.close()
    rebound = SetupServer(app, port=port)
    try:
        assert rebound.httpd.server_port == port
    finally:
        rebound.close()


def test_setup_thread_start_failure_can_close_without_waiting_for_server(app, monkeypatch):
    ui = SetupServer(app)
    monkeypatch.setattr(ui.thread, "start", Mock(side_effect=RuntimeError("synthetic start failure")))
    shutdown = Mock(side_effect=AssertionError("shutdown would deadlock before serve_forever"))
    monkeypatch.setattr(ui.httpd, "shutdown", shutdown)
    with pytest.raises(RuntimeError, match="synthetic"):
        ui.start(open_browser=False)
    ui.close()
    shutdown.assert_not_called()
    assert ui.httpd.socket.fileno() == -1


def test_setup_failed_bind_closes_socket(app, monkeypatch):
    from stu_checkin.http_server import LoopbackHTTPServer
    closed = []
    original = LoopbackHTTPServer.server_close
    def close(server):
        original(server)
        closed.append(server.socket.fileno())
    monkeypatch.setattr(LoopbackHTTPServer, "server_close", close)
    monkeypatch.setattr(LoopbackHTTPServer, "server_bind", Mock(side_effect=OSError("synthetic bind failure")))
    with pytest.raises(OSError, match="synthetic bind failure"):
        SetupServer(app, port=8766)
    assert closed == [-1]


@pytest.mark.parametrize("port", [-1, 65536, "8766", True])
def test_setup_rejects_invalid_port_before_binding(app, port):
    with pytest.raises(AppError) as exc:
        SetupServer(app, port=port)
    assert exc.value.code == "invalid_setup_port"
