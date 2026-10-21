"""Synthetic path failures: no school calls or user credentials."""
import json
import socket
import socketserver
import ssl
import threading

import httpx
import pytest

from stu_mcp import connectivity as net
from stu_mcp import network
from stu_mcp.access_policy import POLICIES, policy_for_url
from stu_mcp.cli import parser
from stu_mcp.runtime import AppError
from stu_mcp.services import describe_service


@pytest.mark.parametrize("service_id", ["campus_repair", "school_service_portal", "school_homepage"])
def test_public_entry_does_not_probe_sso_or_proxy_unless_requested(monkeypatch, service_id):
    proxy = net.Proxy("environment", "http://127.0.0.1:7890")
    monkeypatch.setattr(net, "proxy_snapshot", lambda: ([proxy], {"configured": True}))
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "resolved"})
    calls = []
    def probe(url, proxy=None):
        calls.append((url, proxy))
        return {"reachable": "sso.stu" not in url, "status": "synthetic"}
    monkeypatch.setattr(net, "_http", probe)
    diagnostic = net.NetworkDiagnostics()
    result = diagnostic.diagnose(service_id)
    assert result["status"] == "direct_ready"
    assert result["decision"]["can_attempt_anonymous_read"] is True
    assert result["decision"]["can_attempt_login"] is None
    assert calls == [(POLICIES[service_id].url, None)]
    assert result["checks"][0]["local_proxies"] == []
    assert result["proxy_comparison_requested"] is False
    if POLICIES[service_id].sso_dependency:
        login = diagnostic.diagnose(service_id, check_login=True)
        assert login["status"] == "direct_blocked"
        assert login["decision"]["can_attempt_anonymous_read"] is True
        assert login["decision"]["can_attempt_login"] is False


def test_dorm_preflight_stays_fresh_and_always_checks_its_sso(monkeypatch):
    calls = []
    monkeypatch.setattr(net, "_http", lambda url: calls.append(url) or {"reachable": True})
    for _ in range(2):
        assert set(net.direct_checks("sangpushan_repair")) == {"sangpushan_repair", "school_sso"}
    assert len(calls) == 4
    assert set(net._targets("sangpushan_repair", False)) == {"sangpushan_repair"}


def test_its_protocols_stay_separate_and_never_invent_an_sso_dependency():
    assert net._targets("network_repair_http") == {"network_repair_http": "http://its.stu.edu.cn/"}
    assert net._targets("network_repair", True) == {"network_repair": "https://its.stu.edu.cn/"}
    assert policy_for_url("https://its.stu.edu.cn:443/a").endpoint_id == "network_repair"
    assert policy_for_url("http://its.stu.edu.cn:80/a").endpoint_id == "network_repair_http"
    assert policy_for_url("https://its.stu.edu.cn.evil.invalid/") is None


def test_catalog_exposes_service_policy_without_turning_research_into_live_health():
    repair = describe_service({"url": "https://repair.stu.edu.cn/"})
    portal = describe_service({"url": "https://service.stu.edu.cn/"})
    assert repair["access_policy"]["preferred_access"] == "campus_access_if_needed"
    assert portal["access_policy"]["preferred_access"] == "direct_first"
    for record in (repair, portal):
        assert record["availability"] == record["access_policy"]["availability"] == "not_checked"
        assert record["access_policy"]["automatic_proxy_fallback"] is False


def test_cli_keeps_service_default_and_explicit_diagnostic_scope():
    default = parser().parse_args(["network"])
    assert default.check_login is None and default.compare_proxy is False
    expanded = parser().parse_args(["network", "--check-login", "--compare-proxy"])
    assert expanded.check_login is True and expanded.compare_proxy is True
    assert parser().parse_args(["network", "--anonymous-only"]).check_login is False


def test_one_connect_retry_per_anonymous_read_and_origin_backoff_preserves_other_sources(monkeypatch):
    calls, sleeps, now = [], [], [1000.0]
    monkeypatch.setattr(network.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(network.time, "sleep", sleeps.append)
    def handler(request):
        calls.append(request.url.host)
        assert request.extensions["timeout"]["connect"] == 3
        if request.url.host == "www.stu.edu.cn" and now[0] < 1015:
            request.extensions["trace"]("connection.connect_tcp.started", {"host": "SYNTHETIC_SECRET"})
            raise httpx.ConnectTimeout("SYNTHETIC_SECRET", request=request)
        return httpx.Response(200, text="synthetic page")
    with network.CampusHTTP("public", transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(AppError) as first:
            http.text("https://www.stu.edu.cn/a")
        assert calls == ["www.stu.edu.cn"] * 2 and sleeps == [.15]
        for path in ("b", "c", "kstd.htm"):
            with pytest.raises(AppError) as cached:
                http.text("https://www.stu.edu.cn/" + path)
            assert cached.value.result()["network"]["cached_failure"] is True
            assert cached.value.result()["retry_after_seconds"] == 15
        assert http.text("https://xsc.stu.edu.cn/") == "synthetic page"
        assert calls == ["www.stu.edu.cn", "www.stu.edu.cn", "xsc.stu.edu.cn"]
        now[0] += 16
        assert http.text("https://www.stu.edu.cn/a") == "synthetic page"
        assert http.requests == 4
        assert "SYNTHETIC_SECRET" not in json.dumps(first.value.result())


@pytest.mark.parametrize("kind", ["authenticated_get", "post"])
def test_no_connection_retry_for_authentication_or_form_posts(monkeypatch, session, kind):
    calls = []
    def fail(request):
        calls.append(request)
        assert request.extensions["timeout"]["connect"] == 8
        request.extensions["trace"]("connection.connect_tcp.started", {})
        raise httpx.ConnectTimeout("SYNTHETIC_SECRET", request=request)
    with (network.CampusHTTP("mystu", session if kind == "authenticated_get" else None,
                             transport=httpx.MockTransport(fail)) as http, pytest.raises(AppError)):
        http.text("https://my.stu.edu.cn/page", data={"synthetic": "data"} if kind == "post" else None)
    assert len(calls) == 1


@pytest.mark.parametrize("cause,layer", [(socket.gaierror(-2, "PRIVATE"), "dns"),
                                         (ssl.SSLCertVerificationError("PRIVATE"), "tls_verification")])
def test_dns_and_certificate_errors_are_not_retried_or_suggested_as_retryable(cause, layer):
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ConnectError("PRIVATE", request=request) from cause
    with network.CampusHTTP("public", transport=httpx.MockTransport(fail)) as http, pytest.raises(AppError) as exc:
        http.text("https://www.stu.edu.cn/")
    result = exc.value.result()
    assert len(calls) == 1 and result["retryable"] is False
    assert result["network"]["failure_layer"] == layer
    assert "PRIVATE" not in json.dumps(result)


def test_path_backoff_does_not_mix_http_https_or_cache_individual_http_errors():
    calls = []
    def respond(request):
        calls.append((request.url.scheme, request.url.path))
        if request.url.scheme == "https":
            raise httpx.ConnectError("synthetic", request=request)
        return httpx.Response(404 if request.url.path == "/missing" else 200, text="ok")
    with network.CampusHTTP("oa", transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(AppError):
            http.text("https://oa.stu.edu.cn/")
        with pytest.raises(AppError):
            http.text("http://oa.stu.edu.cn/missing")
        assert http.text("http://oa.stu.edu.cn/board") == "ok"
    assert len(calls) == 3


def test_read_timeout_does_not_replay_a_partially_received_page():
    class Partial(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadTimeout("PRIVATE")
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=Partial())
    with network.CampusHTTP("public", transport=httpx.MockTransport(respond)) as http, pytest.raises(AppError):
        http.text("https://www.stu.edu.cn/a")
    assert len(calls) == 1


def test_proxy_timeout_does_not_claim_which_tcp_hop_failed(monkeypatch):
    def fail(**_):
        raise httpx.ConnectTimeout("PRIVATE")
    monkeypatch.setattr(net.httpx, "Client", fail)
    result = net._http("https://its.stu.edu.cn/", "http://127.0.0.1:7890")
    assert result["failure_layer"] == "proxy_or_upstream_unknown"
    assert result["proxy_outbound"] == "unknown" and "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("phase,layer", [(None, "connect_or_tls"), ("connection.start_tls.started", "tls")])
def test_tls_and_unclassified_connect_timeout_do_not_trigger_automatic_retry(phase, layer):
    calls = []
    def fail(request):
        calls.append(request)
        if phase:
            request.extensions["trace"](phase, {"server_hostname": "PRIVATE"})
        raise httpx.ConnectTimeout("PRIVATE", request=request)
    with network.CampusHTTP("public", transport=httpx.MockTransport(fail)) as http, pytest.raises(AppError) as exc:
        http.text("https://www.stu.edu.cn/")
    result = exc.value.result()
    assert len(calls) == 1
    assert result["network"]["failure_layer"] == layer and result["retryable"] is False
    assert "PRIVATE" not in json.dumps(result)


def test_default_port_and_explicit_default_port_share_origin_cooldown():
    calls = []
    def fail(request):
        calls.append(request)
        raise httpx.ConnectError("synthetic", request=request)
    with network.CampusHTTP("public", transport=httpx.MockTransport(fail)) as http:
        with pytest.raises(AppError):
            http.text("https://www.stu.edu.cn/")
        with pytest.raises(AppError) as cached:
            http.text("https://www.stu.edu.cn:443/kstd.htm")
    assert len(calls) == 1
    assert cached.value.result()["network"]["cached_failure"] is True


def test_transport_trace_stages_do_not_retain_raw_trace_details():
    evidence = network.TransportEvidence()
    for event, stage in [("connection.connect_tcp.started", "connect_before_tls"),
                         ("connection.start_tls.started", "tls"),
                         ("http11.receive_response_headers.started", "http_response"),
                         ("http11.receive_response_body.started", "body_read")]:
        evidence.trace(event, {"headers": "PRIVATE", "return_value": "PRIVATE"})
        assert evidence.phase == stage and "PRIVATE" not in repr(vars(evidence))


def test_real_tls_timeout_trace_is_not_claimed_as_tcp_failure(monkeypatch):
    # Real HTTP core trace events, TCP to a loopback listener that never speaks TLS.
    release = threading.Event()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            release.wait(1)
    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    real_client = httpx.Client
    def client(**kwargs):
        kwargs["timeout"] = .1
        return real_client(**kwargs)
    monkeypatch.setattr(net.httpx, "Client", client)
    try:
        result = net._http(f"https://127.0.0.1:{server.server_address[1]}/")
        assert result["reachable"] is False and result["failure_layer"] == "tls"
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)


def test_sso_only_diagnostic_has_login_evidence_without_a_second_request(monkeypatch):
    monkeypatch.setattr(net, "proxy_snapshot", lambda: ([], {"configured": False}))
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "resolved"})
    calls = []
    monkeypatch.setattr(net, "_http", lambda url: calls.append(url) or {"reachable": True})
    result = net.NetworkDiagnostics().diagnose("school_sso")
    assert calls == [POLICIES["school_sso"].url]
    assert result["decision"]["login_checked"] is True
    assert result["decision"]["can_attempt_login"] is True


@pytest.mark.parametrize("url", ["https://r.stu.edu.cn:wrong/", "https://user:PRIVATE@r.stu.edu.cn/",
                                  "https://[invalid/", "file://r.stu.edu.cn/"])
def test_malformed_urls_and_credentials_do_not_pick_a_policy(url):
    assert policy_for_url(url) is None


@pytest.mark.parametrize("url,location,expected", [
    ("http://its.stu.edu.cn/", "/login", True),
    ("http://its.stu.edu.cn/", "https://its.stu.edu.cn/login", True),
    ("https://its.stu.edu.cn/", "http://its.stu.edu.cn/login", False),
    ("http://its.stu.edu.cn/", "http://sso.stu.edu.cn/login", False)])
def test_legacy_http_diagnostic_can_observe_same_origin_redirect_without_https_downgrade(monkeypatch, url, location, expected):
    real_client = httpx.Client
    calls = []
    def response(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": location})
    monkeypatch.setattr(net.httpx, "Client", lambda **kw: real_client(**kw, transport=httpx.MockTransport(response)))
    result = net._http(url)
    assert result["reachable"] is expected and len(calls) == 1
    assert "Location" not in json.dumps(result)  # Diagnostic never follows it.


def test_its_http_diagnostic_reads_http_proxy_configuration_not_https(monkeypatch):
    monkeypatch.setattr(net, "getproxies_environment", lambda: {
        "http": "http://127.0.0.1:7891", "https": "http://127.0.0.1:7892", "all": "socks5://127.0.0.1:1080"})
    monkeypatch.setattr(net, "_windows_proxy", lambda scheme="https": ([], {"configured": False}))
    monkeypatch.setattr(net, "_dns", lambda _: {"status": "resolved"})
    calls = []
    monkeypatch.setattr(net, "_http", lambda url, proxy=None: calls.append(proxy) or {"reachable": True})
    result = net.NetworkDiagnostics().diagnose("network_repair_http", compare_proxy=True)
    assert set(calls) == {None, "http://127.0.0.1:7891"}
    assert result["proxy_configuration"]["scope"].startswith("HTTP_")
