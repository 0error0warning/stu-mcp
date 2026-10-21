"""Synthetic DNS/network observations only; no school traffic or user sessions."""
import json
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import dns.exception
import dns.resolver
import pytest

from stu_mcp import network_audit as net
from stu_mcp.runtime import AppError
from stu_mcp.services import SERVICE_DIRECTORY
from stu_mcp.sources import SOURCES


def test_catalog_covers_registered_school_hosts_without_third_party_or_callback_urls():
    expected = {host for source in SOURCES.values() for host in source.hosts if host.endswith(".stu.edu.cn")}
    expected |= {host for host in SERVICE_DIRECTORY if host.endswith(".stu.edu.cn")}
    assert expected <= set(net.HOSTS)
    assert len({e["endpoint_id"] for e in net.ENDPOINTS}) == len(net.ENDPOINTS)
    assert {e["url"] for e in net.ENDPOINTS if e["hostname"] == "its.stu.edu.cn"} == {
        "http://its.stu.edu.cn/", "https://its.stu.edu.cn/"}
    assert all(urlparse(e["url"]).hostname.endswith(".stu.edu.cn") for e in net.ENDPOINTS)
    assert all(not urlparse(e["url"]).query and not urlparse(e["url"]).fragment for e in net.ENDPOINTS)
    assert next(e["url"] for e in net.ENDPOINTS if e["hostname"] == "oa.stu.edu.cn").startswith("http:")
    assert next(e["url"] for e in net.ENDPOINTS if e["hostname"] == "info.stu.edu.cn").endswith("/its/")


def fake_resolver(monkeypatch, outcomes):
    calls = []
    class Resolver:
        def __init__(self, *, configure):
            assert configure is False
        def resolve(self, host, kind, *, search, lifetime):
            assert host == "repair.stu.edu.cn." and search is False
            assert 0 < lifetime <= net.DNS_SECONDS and self.cache is None and not self.retry_servfail
            assert self.nameservers == [net.PUBLIC_DNS["alidns"]]
            calls.append(kind)
            value = outcomes[kind]
            if isinstance(value, Exception):
                raise value
            return [SimpleNamespace(address=address) for address in value]
    monkeypatch.setattr(net.dns.resolver, "Resolver", Resolver)
    return calls


@pytest.mark.parametrize("error,expected,complete", [
    (dns.resolver.NXDOMAIN(), "nxdomain", True),
    (dns.resolver.NoAnswer(), "no_address_records", True),
    (dns.exception.Timeout(), "dns_inconclusive", False),
    (OSError("PRIVATE ticket=SECRET"), "dns_inconclusive", False),
])
def test_public_dns_does_not_call_timeout_or_missing_aaaa_a_nonexistent_site(monkeypatch, error, expected, complete):
    calls = fake_resolver(monkeypatch, {"A": error, "AAAA": error})
    result = net._public_dns("repair.stu.edu.cn", "alidns")
    assert result["status"] == expected and result["complete"] is complete
    assert calls == ["A", "AAAA"]
    assert result["resolver_identity_verified"] is False
    assert "PRIVATE" not in json.dumps(result) and "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("v4,v6,families,complete", [
    (["8.8.8.8"], dns.resolver.NoAnswer(), [4], True),
    (dns.resolver.NoAnswer(), ["2001:4860:4860::8888"], [6], True),
    (["8.8.8.8"], dns.exception.Timeout(), [4], False),
    (["198.18.0.1"], dns.resolver.NoAnswer(), [4], True),
])
def test_public_dns_keeps_both_families_and_partial_positive_answers(monkeypatch, v4, v6, families, complete):
    fake_resolver(monkeypatch, {"A": v4, "AAAA": v6})
    result = net._public_dns("repair.stu.edu.cn", "alidns")
    assert result["status"] == "resolved" and result["families"] == families
    assert result["complete"] is complete
    assert result["fake_ip_detected"] is (v4 == ["198.18.0.1"])
    assert "8.8.8.8" not in json.dumps(result) and "198.18.0.1" not in json.dumps(result)


def test_public_dns_shares_one_lifetime_across_record_types(monkeypatch):
    fake_resolver(monkeypatch, {"A": ["8.8.8.8"], "AAAA": []})
    clock = iter([0, 0, 3, 3])
    monkeypatch.setattr(net.time, "monotonic", lambda: next(clock))
    result = net._public_dns("repair.stu.edu.cn", "alidns")
    assert result["status"] == "resolved" and result["complete"] is False
    assert result["records"]["AAAA"]["status"] == "deadline_exceeded"


@pytest.mark.parametrize("code,status", [(socket.EAI_NONAME, "not_resolved"),
                                         (socket.EAI_AGAIN, "temporary_failure"), (9999, "os_resolution_error"),
                                         (None, "os_resolution_error")])
def test_os_dns_errno_is_not_presented_as_an_authoritative_nxdomain(monkeypatch, code, status):
    def fail(*args, **kwargs):
        raise socket.gaierror(code, "PRIVATE")
    monkeypatch.setattr(net.socket, "getaddrinfo", fail)
    result = net._os_dns("repair.stu.edu.cn")
    assert result["status"] == status and "PRIVATE" not in json.dumps(result)


@pytest.fixture
def matrix(monkeypatch):
    entries = tuple(e for e in net.ENDPOINTS if e["endpoint_id"] in {
        "sangpushan_repair", "campus_repair", "network_repair", "network_repair_http"})
    hosts = tuple(dict.fromkeys(e["hostname"] for e in entries))
    monkeypatch.setattr(net, "ENDPOINTS", entries)
    monkeypatch.setattr(net, "HOSTS", hosts)
    calls = []
    def os_dns(host):
        return {"status": "not_resolved" if host == "repair.stu.edu.cn" else "resolved"}
    def public(host, provider):
        calls.append((host, provider))
        return {"status": "resolved", "address_scopes": ["private"], "complete": True}
    def http(url):
        calls.append(url)
        if "//r.stu." in url:
            return {"status": "reachable", "reachable": True, "http_status": 302}
        if url.startswith("https://its."):
            return {"status": "connect_error", "reachable": False, "failure_layer": "tls_verification"}
        return {"status": "timeout", "reachable": False}
    monkeypatch.setattr(net, "_os_dns", os_dns)
    monkeypatch.setattr(net, "_public_dns", public)
    monkeypatch.setattr(net, "_http", http)
    return calls


def test_batch_keeps_service_identity_and_does_not_route_http_via_positive_public_dns(matrix):
    result = net.NetworkAudit().audit("off_campus", compare_public_dns=True)
    checks = {c["endpoint_id"]: c for c in result["checks"]}
    assert checks["sangpushan_repair"]["status"] == "os_dns_unresolved"
    assert checks["campus_repair"]["status"] == "entry_responding"
    assert checks["network_repair"]["status"] == "tls_failed"
    assert checks["network_repair_http"]["status"] == "direct_probe_failed"
    assert result["network_context"]["location_verified"] is False
    assert result["changes_system_settings"] is result["automatic_proxy_fallback"] is False
    assert len(matrix) == len(net.ENDPOINTS) + len(net.HOSTS) * 2
    assert result["summary"]["os_dns_unresolved_hosts"] == ["repair.stu.edu.cn"]
    assert result["status"] == "complete"  # Complete observations include observed probe failures.


def test_batch_cache_is_detached_keyed_and_explicitly_refreshed(matrix):
    audit = net.NetworkAudit()
    original = audit.audit()
    count = len(matrix)
    original["checks"].clear()
    cached = audit.audit()
    assert cached["cached"] is True and len(cached["checks"]) == 4 and len(matrix) == count
    audit.audit(refresh=True)
    assert len(matrix) == count * 2
    audit.audit("campus")
    assert len(matrix) == count * 3
    audit.audit("campus", compare_public_dns=True)
    assert len(matrix) > count * 4
    assert not any(isinstance(call, tuple) for call in matrix[:count * 3])


def test_worker_queue_drains_more_jobs_than_worker_count(monkeypatch):
    monkeypatch.setattr(net, "_SLOTS", threading.BoundedSemaphore(2))
    monkeypatch.setattr(net, "WORKERS", 2)
    assert net._run({str(i): lambda i=i: {"status": "done", "n": i} for i in range(9)}) == {
        str(i): {"status": "done", "n": i} for i in range(9)}


def test_stuck_os_dns_limits_wait_and_retains_slot_until_release(monkeypatch):
    release, exited = threading.Event(), threading.Event()
    monkeypatch.setattr(net, "_SLOTS", threading.BoundedSemaphore(1))
    def slow():
        try:
            release.wait(2)
            return {"status": "late"}
        finally:
            exited.set()
    try:
        start = time.monotonic()
        first = net._run({"slow": slow, "queued": lambda: pytest.fail("must not start after deadline")}, timeout=.04)
        assert time.monotonic() - start < .3
        assert first["slow"]["status"] == first["queued"]["status"] == "deadline_exceeded"
        assert net._run({"next": lambda: True}, timeout=.04)["next"]["status"] == "probe_busy"
    finally:
        release.set()
        exited.wait(1)


def test_incomplete_probes_and_concurrent_runs_are_explicit(monkeypatch, matrix):
    monkeypatch.setattr(net, "_run", lambda jobs: {key: {"status": "deadline_exceeded"} for key in jobs})
    audit = net.NetworkAudit()
    result = audit.audit()
    assert result["status"] == "partial"
    assert all(c["status"] == "inconclusive" for c in result["checks"])
    assert not result["summary"]["os_dns_unresolved_hosts"]
    assert len(result["summary"]["incomplete_dns_checks"]) == len(net.HOSTS)
    with audit._lock, pytest.raises(AppError, match="已有批量"):
        audit.audit()


def test_positive_a_with_unknown_aaaa_is_explicit_in_summary(monkeypatch, matrix):
    monkeypatch.setattr(net, "_public_dns", lambda host, provider: {
        "status": "resolved", "complete": False, "records": {"A": {"status": "resolved"},
                                                               "AAAA": {"status": "timeout"}}})
    result = net.NetworkAudit().audit(compare_public_dns=True)
    assert result["status"] == "partial"
    assert len(result["summary"]["incomplete_dns_checks"]) == len(net.HOSTS) * 2
    assert all(value == [] for value in result["summary"]["public_dns_no_address_hosts"].values())


@pytest.mark.parametrize("dns_status,http,expected", [
    ("not_resolved", {"http_status": 403, "status": "access_denied", "reachable": False}, "entry_rejected"),
    ("resolved", {"http_status": 503, "status": "service_error", "reachable": False}, "http_error_or_unexpected"),
    ("resolved", {"status": "probe_busy"}, "inconclusive"),
])
def test_http_response_and_unknown_are_not_falsely_reported_as_dns_failure(dns_status, http, expected):
    assert net._classify({"status": dns_status}, http) == expected


@pytest.mark.parametrize("kwargs", [{"location_hint": "guess"}, {"location_hint": []},
                                   {"compare_public_dns": 1}, {"refresh": "yes"}])
def test_invalid_arguments_rejected_before_any_probe(kwargs):
    with pytest.raises(AppError):
        net.NetworkAudit().audit(**kwargs)
