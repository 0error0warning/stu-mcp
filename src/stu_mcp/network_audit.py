"""Batch checks of registered STU entries; DNS and HTTP are separate evidence."""
from __future__ import annotations

import copy
import ipaddress
import socket
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from queue import Empty, Queue
from urllib.parse import urlparse

import dns.exception
import dns.resolver

from .access_policy import POLICIES
from .connectivity import _http
from .execution import execution_context
from .runtime import AppError
from .services import SERVICE_DIRECTORY
from .sources import OA_DIRECT, SOURCES

PUBLIC_DNS = {"alidns": "223.5.5.5", "dnspod": "119.29.29.29"}
DEADLINE_SECONDS = 15
DNS_SECONDS = 2.5
WORKERS = 12
_SLOTS = threading.BoundedSemaphore(WORKERS)
_FAKE_IP = ipaddress.ip_network("198.18.0.0/15")
_UNKNOWN = {"deadline_exceeded", "probe_busy", "probe_error"}


def _catalog() -> tuple[dict, ...]:
    entries, origins = [], set()

    def add(key, title, url):
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.hostname.endswith(".stu.edu.cn"):
            return
        origin = (parsed.scheme, parsed.hostname)
        if origin not in origins:
            entries.append({"endpoint_id": key, "title": title, "url": url,
                            "hostname": parsed.hostname})
            origins.add(origin)

    for key, policy in POLICIES.items():
        host = urlparse(policy.url).hostname
        add(key, SERVICE_DIRECTORY.get(host, {}).get("title", key), policy.url)
    for entry in SERVICE_DIRECTORY.values():
        add(entry["service_id"], entry["title"], entry["url"])
    for source in SOURCES.values():
        for host in source.hosts:
            if any(origin[1] == host for origin in origins):
                continue
            login = urlparse(source.login_url or "")
            url = (source.login_url.split("#", 1)[0] if login.hostname == host else
                   OA_DIRECT + "/" if host == "oa.stu.edu.cn" else f"https://{host}/")
            add(source.id + ":" + host, source.label + " · 匿名入口", url)
    # The path, not the entire info host, has the network-center business role.
    add("network_center_info", "网络中心公开说明", "https://info.stu.edu.cn/its/")
    return tuple(entries)


ENDPOINTS = _catalog()
HOSTS = tuple(dict.fromkeys(entry["hostname"] for entry in ENDPOINTS))
CAPABILITY = {"tool": "audit_campus_network", "endpoint_count": len(ENDPOINTS),
              "host_count": len(HOSTS), "catalog_scope": "registered_first_party_STU_entries",
              "public_dns_comparison_default": False, "public_dns_resolvers": dict(PUBLIC_DNS),
              "deadline_seconds": DEADLINE_SECONDS, "worker_limit": WORKERS, "cache_seconds": 15,
              "changes_system_settings": False, "automatic_proxy_fallback": False,
              "business_workflow_verified": False, "physical_location_detection": False}


def _addresses(values) -> dict:
    addresses = {ipaddress.ip_address(value) for value in values}
    scopes = {"fake_ip" if value.version == 4 and value in _FAKE_IP else
              "private" if value.is_private else "public" if value.is_global else "special"
              for value in addresses}
    return {"address_count": len(addresses), "address_scopes": sorted(scopes),
            "families": sorted({value.version for value in addresses}),
            "fake_ip_detected": "fake_ip" in scopes}


def _os_dns(host: str) -> dict:
    start = time.monotonic()
    try:
        values = [row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
        result = {"status": "resolved" if values else "not_resolved", **_addresses(values)}
    except socket.gaierror as exc:
        result = {"status": "not_resolved" if exc.errno is not None and exc.errno in {
                      socket.EAI_NONAME, getattr(socket, "EAI_NODATA", None)} else
                  "temporary_failure" if exc.errno == socket.EAI_AGAIN else "os_resolution_error"}
    return result | {"scope": "OS_getaddrinfo_including_local_cache_and_hosts",
                     "elapsed_ms": round((time.monotonic() - start) * 1000)}


def _public_dns(host: str, provider: str) -> dict:
    start = time.monotonic()
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [PUBLIC_DNS[provider]]
    resolver.cache = None
    resolver.retry_servfail = False
    records, addresses = {}, []
    for kind in ("A", "AAAA"):
        remaining = DNS_SECONDS - (time.monotonic() - start)
        if remaining <= 0:
            records[kind] = {"status": "deadline_exceeded"}
            continue
        resolver.timeout = min(.8, remaining)
        try:
            answer = resolver.resolve(host + ".", kind, search=False, lifetime=remaining)
            values = [str(value.address) for value in answer]
            addresses.extend(values)
            records[kind] = {"status": "resolved", **_addresses(values)}
        except dns.resolver.NXDOMAIN:
            records[kind] = {"status": "nxdomain"}
        except dns.resolver.NoAnswer:
            records[kind] = {"status": "no_answer"}
        except dns.exception.Timeout:
            records[kind] = {"status": "timeout"}
        except (dns.exception.DNSException, OSError, ValueError):
            records[kind] = {"status": "resolver_error"}
    statuses = {record["status"] for record in records.values()}
    complete = statuses <= {"resolved", "nxdomain", "no_answer"}
    status = ("resolved" if addresses else "nxdomain" if statuses == {"nxdomain"} else
              "no_address_records" if complete else "dns_inconclusive")
    return {"status": status, **_addresses(addresses), "records": records, "complete": complete,
            "resolver_id": provider, "resolver_address": PUBLIC_DNS[provider],
            "resolver_identity_verified": False,
            "scope": "explicit_public_DNS_query_not_the_HTTP_resolver",
            "elapsed_ms": round((time.monotonic() - start) * 1000)}


def _run(jobs: dict, *, timeout: float = DEADLINE_SECONDS) -> dict:
    """Bound both the queue and global worker count; stuck OS DNS retains a slot.

    Daemons do not delay shutdown. Queued jobs do not start after the deadline,
    and late results cannot change a report already returned to the caller.
    """
    deadline, slots = time.monotonic() + timeout, _SLOTS
    work, done = Queue(), Queue()
    for item in jobs.items():
        work.put(item)

    def worker():
        try:
            while time.monotonic() < deadline:
                try:
                    key, fn = work.get_nowait()
                except Empty:
                    break
                try:
                    result = fn()
                except Exception:
                    result = {"status": "probe_error"}
                done.put((key, result))
        finally:
            slots.release()

    started = 0
    for _ in range(min(WORKERS, len(jobs))):
        if not slots.acquire(blocking=False):
            break
        threading.Thread(target=worker, daemon=True, name="stu-network-audit").start()
        started += 1
    results = {}
    while started and len(results) < len(jobs):
        try:
            key, value = done.get(timeout=max(0, deadline - time.monotonic()))
        except Empty:
            break
        results[key] = value
    fallback = "deadline_exceeded" if started else "probe_busy"
    return {key: results.get(key, {"status": fallback}) for key in jobs}


def _classify(dns_result: dict, http: dict) -> str:
    if "http_status" in http:
        return ("entry_responding" if http.get("reachable") is True else
                "entry_rejected" if http.get("status") == "access_denied" else "http_error_or_unexpected")
    if http.get("failure_layer") in {"tls", "tls_verification"}:
        return "tls_failed"
    if dns_result.get("status") == "not_resolved":
        return "os_dns_unresolved"
    if http.get("status") in _UNKNOWN:
        return "inconclusive"
    return "direct_probe_failed" if http.get("reachable") is False else "inconclusive"


class NetworkAudit:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache = None

    def audit(self, location_hint: str = "unknown", *, compare_public_dns: bool = False,
              refresh: bool = False) -> dict:
        if not isinstance(location_hint, str) or location_hint not in {"unknown", "campus", "off_campus"}:
            raise AppError("invalid_network_location", "接入网络只使用用户说明的 campus/off_campus，否则留 unknown。")
        if not isinstance(compare_public_dns, bool) or not isinstance(refresh, bool):
            raise AppError("invalid_network_options", "公共DNS对照和刷新只接受布尔开关。")
        if not self._lock.acquire(blocking=False):
            raise AppError("network_audit_running", "已有批量网络检查在进行，请稍后查询。")
        try:
            key = (location_hint, compare_public_dns)
            cached = self._cache
            if not refresh and cached and cached[0] == key and time.monotonic() - cached[1] < 15:
                return copy.deepcopy(cached[2]) | {"cached": True,
                    "age_seconds": round(time.monotonic() - cached[1], 2), "execution": execution_context()}
            start, jobs = time.monotonic(), {}
            for host in HOSTS:
                jobs[host + ":os"] = lambda host=host: _os_dns(host)
                for provider in PUBLIC_DNS if compare_public_dns else ():
                    jobs[host + ":" + provider] = lambda host=host, provider=provider: _public_dns(host, provider)
            for entry in ENDPOINTS:
                jobs[entry["endpoint_id"] + ":http"] = lambda url=entry["url"]: _http(url)
            results = _run(jobs)
            hosts = [{"hostname": host, "system_dns": results[host + ":os"],
                      "public_dns": {provider: results[host + ":" + provider]
                                     for provider in PUBLIC_DNS if compare_public_dns}} for host in HOSTS]
            checks = [{**entry, "direct": results[entry["endpoint_id"] + ":http"],
                       "status": _classify(results[entry["hostname"] + ":os"],
                                           results[entry["endpoint_id"] + ":http"])} for entry in ENDPOINTS]
            incomplete = (any(value.get("status") in _UNKNOWN or value.get("status") == "dns_inconclusive"
                              or value.get("complete") is False for value in results.values())
                          or any(host["system_dns"]["status"] not in {"resolved", "not_resolved"} for host in hosts))
            summary = {"endpoint_status_counts": dict(Counter(check["status"] for check in checks)),
                       "os_dns_unresolved_hosts": [h["hostname"] for h in hosts
                                                   if h["system_dns"]["status"] == "not_resolved"],
                       "public_dns_no_address_hosts": {provider: [h["hostname"] for h in hosts
                            if h["public_dns"][provider]["status"] in {"nxdomain", "no_address_records"}]
                            for provider in PUBLIC_DNS if compare_public_dns},
                       "inconclusive_endpoints": [c["endpoint_id"] for c in checks if c["status"] == "inconclusive"],
                       "incomplete_dns_checks": [
                           {"hostname": host["hostname"], "resolver": provider, "status": value["status"]}
                           for host in hosts
                           for provider, value in {"system": host["system_dns"], **host["public_dns"]}.items()
                           if value.get("status") in _UNKNOWN or value.get("status") in {
                               "temporary_failure", "os_resolution_error", "dns_inconclusive"}
                           or value.get("complete") is False]}
            result = {"ok": True, "status": "partial" if incomplete else "complete", "summary": summary,
                      "execution": execution_context(),
                      "checked_at": datetime.now(UTC).isoformat(), "cached": False, "age_seconds": 0,
                      "elapsed_ms": round((time.monotonic() - start) * 1000),
                      "network_context": {"location_hint": location_hint, "location_verified": False,
                                          "physical_location_detection": False, "tun_status": "unknown"},
                      "catalog_scope": "registered_first_party_STU_entries_not_all_school_sites",
                      "endpoint_count": len(ENDPOINTS), "host_count": len(HOSTS),
                      "hosts": hosts, "checks": checks, "public_dns_comparison_requested": compare_public_dns,
                      "changes_system_settings": False, "automatic_proxy_fallback": False,
                      "limitations": ["网络检查发生在 MCP 执行主机；不检查调用客户端的 DNS、代理、路由或物理位置。",
                                      "客户端到 MCP 的连接须由客户端传输握手验证；本报告只探测执行主机到学校的路径。",
                                      "每个结论仅覆盖本次运行主机的网络与检查时间，不代表所有校外Wi-Fi或学校停服。",
                                      "OS解析包含本机缓存和hosts；公共DNS显式查询不改变HTTP解析器或路由。",
                                      "显式DNS地址不排除网络劫持；未认证解析器身份，未强制验证每个解析IP的连通性。",
                                      "应用层直连不使用HTTP代理，仍可能受TUN、系统DNS及路由影响。",
                                      "只检查匿名响应头，不跟随跳转、读正文、登录或验证具体业务；HTTP/HTTPS分别报告。",
                                      "15秒进程内缓存，切网后refresh=true；超时或工作槽不足为证据不足。"]}
            self._cache = (key, time.monotonic(), copy.deepcopy(result))
            return result
        finally:
            self._lock.release()
