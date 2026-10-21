"""All network environments are synthetic. Real transports only use loopback."""
import json
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import httpx
import pytest

from stu_checkin.http_server import LoopbackHTTPServer
from stu_mcp import connectivity as net
from stu_mcp.repair import direct_preflight
from stu_mcp.runtime import AppError


def fixture_proxy(monkeypatch, proxy=None):
    proxies = [proxy] if proxy else []
    monkeypatch.setattr(net, "proxy_snapshot", lambda: (proxies, {
        "configured": bool(proxy), "system": {"configured": bool(proxy)},
        "settings": [p.public() for p in proxies], "tun_status": "unknown"}))


@pytest.mark.parametrize("location,proxy_enabled", [
    ("campus", False), ("off_campus", False), ("campus", True), ("off_campus", True)])
def test_four_environments_distinguish_location_hint_configuration_and_reachability(monkeypatch, location, proxy_enabled):
    fixture_proxy(monkeypatch, net.Proxy("environment", "http://127.0.0.1:7890") if proxy_enabled else None)
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "resolved", "address_scopes": ["private"]})
    calls = []
    def probe(url, proxy=None):
        calls.append((url, proxy))
        # A generic proxy cannot supply a campus route when off campus.
        return {"reachable": location == "campus" and proxy is None,
                "status": "reachable" if location == "campus" and proxy is None else "connect_error"}
    monkeypatch.setattr(net, "_http", probe)
    result = net.NetworkDiagnostics().diagnose(location_hint=location, compare_proxy=True)
    suffix = "proxy_configured" if proxy_enabled else "no_proxy_configured"
    assert result["network_context"] == {"location_hint": location, "location_verified": False,
                                          "scenario": location + "_" + suffix}
    assert result["decision"]["can_attempt_direct"] == (location == "campus")
    assert result["decision"]["automatic_proxy_fallback"] is False
    assert result["proxy_configuration"]["tun_status"] == "unknown"
    assert len(calls) == (4 if proxy_enabled else 2)
    if proxy_enabled and location == "campus":
        assert any("直连成功、显式本机代理失败" in s for s in result["decision"]["observations"])


def test_off_campus_public_access_is_not_refused_and_private_dns_does_not_infer_location(monkeypatch):
    fixture_proxy(monkeypatch)
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "resolved", "address_scopes": ["private"]})
    monkeypatch.setattr(net, "_http", lambda *_: {"status": "reachable", "reachable": True})
    diagnostic = net.NetworkDiagnostics()
    result = diagnostic.diagnose("school_service_portal", "off_campus")
    assert result["status"] == "direct_ready"
    unknown = diagnostic.diagnose("sangpushan_repair")
    assert unknown["network_context"]["location_hint"] == "unknown"
    assert unknown["network_context"]["location_verified"] is False
    assert unknown["checks"][0]["service_id"] == "sangpushan_repair"


def test_proxy_only_success_does_not_enable_proxy_login_and_sso_failure_is_separate(monkeypatch):
    fixture_proxy(monkeypatch, net.Proxy("windows_system", "http://127.0.0.1:7890"))
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "dns_error"})
    monkeypatch.setattr(net, "_http", lambda _, proxy=None: {"reachable": bool(proxy), "status": "test"})
    result = net.NetworkDiagnostics().diagnose(compare_proxy=True)
    assert result["status"] == "direct_blocked"
    assert result["decision"]["automatic_proxy_fallback"] is False
    assert any("仅本机代理探测成功" in s for s in result["decision"]["observations"])
    monkeypatch.setattr(net, "_http", lambda url, proxy=None: {
        "reachable": "repair.stu" in url, "status": "test"})
    result = net.NetworkDiagnostics().diagnose()
    assert result["checks"][0]["direct"]["reachable"] is True
    assert result["checks"][1]["direct"]["reachable"] is False
    with pytest.raises(AppError, match="统一认证"):
        direct_preflight()


def test_fake_ip_is_evidence_of_dns_interference_not_proof_of_client_or_physical_location(monkeypatch):
    fixture_proxy(monkeypatch)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("198.18.0.7", 443))])
    monkeypatch.setattr(net, "_http", lambda *_: {"status": "connect_error", "reachable": False})
    result = net.NetworkDiagnostics().diagnose()
    assert result["checks"][0]["dns"]["fake_ip_detected"] is True
    assert result["network_context"]["location_verified"] is False
    assert any("fake-IP" in s for s in result["decision"]["observations"])
    assert "198.18.0.7" not in json.dumps(result)


@pytest.mark.parametrize("value,status", [
    ("http://alice:PRIVATE@127.0.0.1:7890", "credentials_not_used"),
    ("https://proxy.private.invalid:443", "remote_not_probed"),
    ("file:///PRIVATE", "unsupported_scheme"),
    ("http://127.0.0.1:bad/PRIVATE", "invalid"),
    ("socks4://127.0.0.1:1080", "unsupported_scheme"),
])
def test_unsupported_proxies_are_not_probed_and_secrets_or_hostnames_not_exported(monkeypatch, value, status):
    fixture_proxy(monkeypatch, net.Proxy("environment", value))
    calls = []
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "dns_error"})
    def probe(_, proxy=None):
        calls.append(proxy)
        return {"status": "reachable", "reachable": True}
    monkeypatch.setattr(net, "_http", probe)
    result = net.NetworkDiagnostics().diagnose(compare_proxy=True)
    assert calls == [None, None]
    assert result["checks"][0]["local_proxies"][0]["status"] == status
    assert "PRIVATE" not in json.dumps(result)
    assert "proxy.private" not in json.dumps(result)


def test_cache_is_short_explicit_refresh_and_proxy_changes_invalidate_it(monkeypatch):
    fixture_proxy(monkeypatch)
    calls = []
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "dns_error"})
    monkeypatch.setattr(net, "_http", lambda *args: calls.append(args) or {"reachable": True})
    now = [1000]
    monkeypatch.setattr(net.time, "monotonic", lambda: now[0])
    diagnostic = net.NetworkDiagnostics()
    original = diagnostic.diagnose()
    assert len(calls) == 2 and original["cached"] is False
    now[0] += 1
    cached = diagnostic.diagnose()
    assert cached["cached"] is True and cached["age_seconds"] == 1
    cached["checks"].clear()
    assert len(diagnostic.diagnose()["checks"]) == 2  # Caller cannot alter cached evidence.
    diagnostic.diagnose(refresh=True)
    assert len(calls) == 4
    now[0] += 16
    diagnostic.diagnose()
    assert len(calls) == 6
    fixture_proxy(monkeypatch, net.Proxy("environment", "http://127.0.0.1:7890"))
    diagnostic.diagnose()
    assert len(calls) == 8  # Configuration changed; comparisons are still opt-in.
    diagnostic.diagnose(compare_proxy=True)
    assert len(calls) == 12  # A different requested scope must not reuse the old result.


def test_bounded_workers_do_not_wait_for_stuck_dns_or_spawn_without_limit(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(net, "_SLOTS", threading.BoundedSemaphore(1))
    start = time.monotonic()
    try:
        result = net._bounded({"dns": lambda: release.wait(2), "other": lambda: True}, timeout=.05)
        assert time.monotonic() - start < .6
        assert result["dns"]["status"] == "deadline_exceeded"
        assert result["other"]["status"] == "probe_busy"
        second = net._bounded({"dns": lambda: True}, timeout=.05)
        assert second["dns"]["status"] == "probe_busy"
    finally:
        release.set()


def test_inconclusive_and_concurrent_diagnoses_are_not_reported_as_site_down(monkeypatch):
    fixture_proxy(monkeypatch)
    monkeypatch.setattr(net, "_bounded", lambda jobs: {key: {"status": "deadline_exceeded", "reachable": None}
                                                     for key in jobs})
    diagnostic = net.NetworkDiagnostics()
    assert diagnostic.diagnose()["status"] == "direct_inconclusive"
    with diagnostic._lock, pytest.raises(AppError) as exc:
        diagnostic.diagnose()
    assert exc.value.code == "network_diagnosis_running"


def test_invalid_targets_and_locations_cannot_trigger_requests(monkeypatch):
    monkeypatch.setattr(net, "_bounded", lambda _: pytest.fail("unexpected request"))
    for target in ("https://evil.invalid", "repair.stu.edu.cn?ticket=PRIVATE", "unknown"):
        with pytest.raises(AppError):
            net.NetworkDiagnostics().diagnose(target)
    with pytest.raises(AppError):
        net.NetworkDiagnostics().diagnose(location_hint="guess_from_ip")


@pytest.mark.parametrize("status,location,expected", [
    (302, "https://sso.stu.edu.cn/login?ticket=PRIVATE", True),
    (307, "/login?ticket=PRIVATE", True),
    (302, "https://sso.stu.edu.cn.evil.invalid/login", False),
    (302, "https://alice:PRIVATE@sso.stu.edu.cn/", False),
    (302, "http://sso.stu.edu.cn/login", False),
    (302, "https://sso.stu.edu.cn:444/", False),
    (302, "", False), (503, "", False), (403, "", False), (200, "", True)])
def test_http_probe_does_not_follow_redirects_read_bodies_or_leak_tickets(monkeypatch, status, location, expected):
    real_client = httpx.Client
    seen = []
    def respond(request):
        seen.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        return httpx.Response(status, headers={"Location": location}, content=b"PRIVATE body")
    def client(**kw):
        assert kw["trust_env"] is False and kw["follow_redirects"] is False
        return real_client(**kw, transport=httpx.MockTransport(respond))
    monkeypatch.setattr(net.httpx, "Client", client)
    result = net._http("https://repair.stu.edu.cn/")
    assert result["reachable"] is expected
    assert len(seen) == 1 and "PRIVATE" not in json.dumps(result)


def test_real_explicit_loopback_http_proxy_is_comparison_only_and_ignores_bypass(monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            self.send_response(302)
            self.send_header("Location", "https://sso.stu.edu.cn/login?ticket=SYNTHETIC")
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *_):
            pass
    server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
        monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "*")
        proxy = net.Proxy("environment", f"http://127.0.0.1:{server.server_port}", ("*",))
        result = net._http("http://fixture.invalid/", proxy.probe_url())
        assert result["reachable"] is True
        assert len(requests) == 1 and requests[0][0] == "http://fixture.invalid/"
        assert "Cookie" not in requests[0][1] and "Authorization" not in requests[0][1]
        assert proxy.bypasses("repair.stu.edu.cn") is True
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


@pytest.mark.parametrize("scheme", ["socks5", "socks5h"])
def test_real_loopback_socks_proxy_without_contacting_school(scheme):
    targets = []
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(3)
            version, size = self.rfile.read(2)
            assert version == 5
            self.rfile.read(size)
            self.wfile.write(b"\x05\x00")
            header = self.rfile.read(4)
            assert header == b"\x05\x01\x00\x03"
            size = self.rfile.read(1)[0]
            targets.append(self.rfile.read(size).decode())
            self.rfile.read(2)
            self.wfile.write(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50")
            while self.rfile.readline() != b"\r\n":
                pass
            self.wfile.write(b"HTTP/1.1 302 Found\r\nLocation: https://sso.stu.edu.cn/login\r\nContent-Length: 0\r\n\r\n")
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = net._http("http://fixture.invalid/", f"{scheme}://127.0.0.1:{server.server_address[1]}")
        assert result["reachable"] is True
        assert targets == ["fixture.invalid"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


def test_proxy_environment_precedence_redaction_and_no_global_changes(monkeypatch):
    monkeypatch.setattr(net, "getproxies_environment", lambda: {
        "https": "http://alice:PRIVATE@127.0.0.1:7890", "all": "socks5h://127.0.0.1:1080", "no": ".stu.edu.cn"})
    monkeypatch.setattr(net, "_windows_proxy", lambda: ([], {"configured": False}))
    proxies, meta = net.proxy_snapshot()
    assert len(proxies) == 1 and proxies[0].bypasses("repair.stu.edu.cn")
    assert meta["configured"] is True and meta["configuration_is_traffic_evidence"] is False
    assert "PRIVATE" not in repr(proxies) and "PRIVATE" not in json.dumps(meta)
    assert proxies[0].probe_url() is None


@pytest.mark.parametrize("server,expected", [
    ("127.0.0.1:7890", "http://127.0.0.1:7890"),
    ("http=127.0.0.1:8888;https=127.0.0.1:7890", "http://127.0.0.1:7890"),
    ("socks=127.0.0.1:1080", "socks5://127.0.0.1:1080"),
    ("http=127.0.0.1:8888", None),
])
def test_windows_protocol_mapping_and_domain_bypass_are_read_only(monkeypatch, server, expected):
    import sys
    from contextlib import nullcontext
    values = {"ProxyEnable": 1, "ProxyServer": server,
              "ProxyOverride": "repair.stu.edu.cn;*.stu.edu.cn;<local>"}
    def query(_, name):
        if name not in values:
            raise FileNotFoundError()
        return values[name], 1
    monkeypatch.setattr(net, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER=0,
        OpenKey=lambda *_: nullcontext(object()), QueryValueEx=query))
    proxies, meta = net._windows_proxy()
    assert meta["configured"] is True and meta["pac_evaluated"] is False
    assert (proxies[0].probe_url() if proxies else None) == expected
    if proxies:
        assert proxies[0].bypasses("repair.stu.edu.cn")
        assert not proxies[0].bypasses("repair.stu.edu.cn.evil.invalid")


def test_unknown_system_proxy_is_not_reported_disabled_and_pac_is_not_evaluated(monkeypatch):
    monkeypatch.setattr(net, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(net, "getproxies_environment", lambda: {})
    proxies, meta = net.proxy_snapshot()
    assert not proxies and meta["configured"] is None
    assert meta["system"]["status"] == "not_inspected"
    monkeypatch.setattr(net, "_windows_proxy", lambda: ([], {
        "configured": True, "pac_configured": True, "pac_evaluated": False}))
    proxies, meta = net.proxy_snapshot()
    assert not proxies and meta["configured"] is True
    assert meta["system"]["pac_evaluated"] is False


def test_network_service_identity_matches_directory_and_sso_is_not_duplicated():
    from urllib.parse import urlparse

    from stu_mcp.services import SERVICE_DIRECTORY
    for service_id, url in net.ENDPOINTS.items():
        assert SERVICE_DIRECTORY[urlparse(url).hostname]["service_id"] == net.POLICIES[service_id].service_id
    assert net._targets("school_sso") == {"school_sso": net.ENDPOINTS["school_sso"]}


def test_duplicate_proxy_addresses_share_probe_without_losing_source_bypass_evidence(monkeypatch):
    value = "http://127.0.0.1:7890"
    proxies = [net.Proxy("environment", value), net.Proxy("windows_system", value, ("*.stu.edu.cn",))]
    monkeypatch.setattr(net, "proxy_snapshot", lambda: (proxies, {"configured": True}))
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "dns_error"})
    calls = []
    monkeypatch.setattr(net, "_http", lambda url, proxy=None: calls.append((url, proxy)) or {"reachable": True})
    result = net.NetworkDiagnostics().diagnose(compare_proxy=True)
    assert len(calls) == 4
    compared = result["checks"][0]["local_proxies"]
    assert len(compared) == 2
    assert compared[0]["bypass_matches_target"] is False
    assert compared[1]["bypass_matches_target"] is True
