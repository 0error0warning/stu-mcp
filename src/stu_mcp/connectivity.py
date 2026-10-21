"""Anonymous, bounded campus diagnostics; never change routing or forward login.

HTTP bypass is not a TUN/DNS bypass. A user's physical network is a hint, not
something that an RFC1918 answer, a proxy setting or a successful GET proves.
"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from queue import Empty, Queue
from urllib.parse import urljoin, urlparse
from urllib.request import getproxies_environment, proxy_bypass_environment

import httpx

from .access_policy import POLICIES
from .execution import execution_context
from .network import TransportEvidence, failure_layer
from .runtime import AppError

# Exact business identities, not arbitrary URLs or SSO callback tickets.
ENDPOINTS = {key: policy.url for key, policy in POLICIES.items()}
CAPABILITY = {"tool": "diagnose_campus_network", "service_ids": list(ENDPOINTS),
              "location_hints": ["unknown", "campus", "off_campus"],
              "transport": "direct", "local_proxy_comparison": True,
              "local_proxy_comparison_default": False, "service_specific_policy": True,
              "login_dependency_check": "service_default_or_explicit_check_login",
              "automatic_proxy_fallback": False, "changes_system_settings": False,
              "physical_location_detection": False, "tun_detection": "unknown",
              "deadline_seconds": 6, "cache_seconds": 15}
_SLOTS = threading.BoundedSemaphore(12)


def _bounded(jobs: dict[str, Callable], *, timeout: float = 6) -> dict:
    """DNS can ignore socket timeouts. Limit both caller wait and daemon workers.

    A stuck OS resolver must not hold up MCP shutdown or create unbounded threads.
    Timed-out work retains its slot until it actually exits; late results are ignored.
    """
    deadline = time.monotonic() + timeout
    slots = _SLOTS
    queue: Queue = Queue()
    pending, results = set(), {}

    def run(key, fn):
        try:
            value = fn()
        except Exception:
            value = {"status": "probe_error", "reachable": None}
        finally:
            slots.release()
        queue.put((key, value))

    for key, fn in jobs.items():
        if not slots.acquire(blocking=False):
            results[key] = {"status": "probe_busy", "reachable": None}
            continue
        pending.add(key)
        threading.Thread(target=run, args=(key, fn), daemon=True, name="stu-network-probe").start()
    while pending:
        try:
            key, value = queue.get(timeout=max(0, deadline - time.monotonic()))
        except Empty:
            break
        results[key] = value
        pending.remove(key)
    for key in pending:
        results[key] = {"status": "deadline_exceeded", "reachable": None}
    return results


def _dns(host: str) -> dict:
    try:
        addresses = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        scopes = set()
        for value in addresses:
            address = ipaddress.ip_address(value)
            scopes.add("fake_ip" if address.version == 4 and address in ipaddress.ip_network("198.18.0.0/15")
                       else "private" if address.is_private else "public" if address.is_global else "special")
        return {"status": "resolved", "address_scopes": sorted(scopes),
                "fake_ip_detected": "fake_ip" in scopes}
    except socket.gaierror:
        return {"status": "dns_error", "address_scopes": [], "fake_ip_detected": None}


def _http(url: str, proxy: str | None = None) -> dict:
    start = time.monotonic()
    evidence = TransportEvidence()
    result = {"status": "connect_error", "reachable": False}
    try:
        # Do not follow or expose a CAS query, read a response body, send cookies,
        # use env credentials, disable TLS verification or retry a failed GET.
        with (httpx.Client(trust_env=False, proxy=proxy, timeout=4, follow_redirects=False) as client,
              client.stream("GET", url, extensions={"trace": evidence.trace}) as response):
            status = response.status_code
            ready = 200 <= status < 300
            if status in {301, 302, 303, 307, 308}:
                target = urlparse(urljoin(url, response.headers.get("location", "")))
                origin = urlparse(url)
                secure = target.scheme == "https" and target.port in (None, 443)
                legacy_same_origin = (origin.scheme == target.scheme == "http"
                                      and target.hostname == origin.hostname and target.port in (None, 80))
                ready = (bool(response.headers.get("location")) and not target.username and not target.password
                         and (secure or legacy_same_origin)
                         and target.hostname in {origin.hostname, "sso.stu.edu.cn"})
            result = {"status": "reachable" if ready else "access_denied" if status in {401, 403}
                      else "service_error" if status >= 500 else "unexpected_response",
                      "reachable": ready, "http_status": status}
    except httpx.TimeoutException as exc:
        result["status"] = "timeout"
        result["failure_layer"] = "proxy_or_upstream_unknown" if proxy else failure_layer(exc, evidence)
    except httpx.HTTPError as exc:
        layer = failure_layer(exc, evidence)
        result["failure_layer"] = ("proxy_or_upstream_unknown" if proxy and layer != "tls_verification"
                                   else layer)
    except ValueError:
        pass
    except ImportError:
        result = {"status": "proxy_dependency_missing", "reachable": None}
    return result | {"elapsed_ms": round((time.monotonic() - start) * 1000),
                     "transport": "local_proxy_comparison" if proxy else "direct",
                     "proxy_outbound": "unknown" if proxy else "not_used",
                     "scope": "anonymous_response_headers_only"}


@dataclass(frozen=True)
class Proxy:
    source: str
    value: str = field(repr=False)
    bypass: tuple[str, ...] = field(default=(), repr=False)

    def public(self) -> dict:
        try:
            parsed = urlparse(self.value if "://" in self.value else "http://" + self.value)
            host, port = parsed.hostname, parsed.port
            loopback = host == "localhost" or bool(host and ipaddress.ip_address(host).is_loopback)
        except ValueError:
            # A domain is a remote proxy; do not resolve it or expose its name.
            loopback = False
            try:
                parsed = urlparse(self.value if "://" in self.value else "http://" + self.value)
                host, port = parsed.hostname, parsed.port
            except ValueError:
                return {"source": self.source, "status": "invalid", "local": False}
        auth = bool(parsed.username is not None or parsed.password is not None)
        supported = parsed.scheme in {"http", "https", "socks5", "socks5h"}
        status = ("credentials_not_used" if auth else "unsupported_scheme" if not supported
                  else "local_comparison_available" if loopback and host and port else "remote_not_probed")
        return {"source": self.source, "status": status, "scheme": parsed.scheme if supported else "other",
                "local": loopback, "bypass_configured": bool(self.bypass)}

    def probe_url(self) -> str | None:
        if self.public()["status"] != "local_comparison_available":
            return None
        # A hosts-file override must not send a localhost probe to another host.
        parsed = urlparse(self.value if "://" in self.value else "http://" + self.value)
        host = "[::1]" if ":" in parsed.hostname else "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
        return f"{parsed.scheme}://{host}:{parsed.port}"

    def bypasses(self, host: str) -> bool:
        if self.source == "environment":
            return proxy_bypass_environment(host, {"no": ",".join(self.bypass)})
        return any(fnmatchcase(host.lower(), pattern.lower()) for pattern in self.bypass)


def _windows_proxy(scheme: str = "https") -> tuple[list[Proxy], dict]:
    if os.name != "nt":
        return [], {"status": "not_inspected", "configured": None, "pac_configured": None}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            def get(name, default):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return default
            enabled, server = bool(get("ProxyEnable", 0)), str(get("ProxyServer", ""))
            bypass = tuple(part.strip() for part in str(get("ProxyOverride", "")).split(";") if part.strip())
            pac = bool(get("AutoConfigURL", ""))
        proxies = []
        if enabled and server:
            if "=" in server:
                settings = dict(part.strip().split("=", 1) for part in server.split(";") if "=" in part)
                value = settings.get(scheme) or settings.get("socks", "")
                if value and "://" not in value:
                    value = ("http://" if settings.get(scheme) else "socks5://") + value
            else:
                value = server
            if value:
                proxies.append(Proxy("windows_system", value, bypass))
        return proxies, {"status": "inspected", "configured": enabled or pac, "pac_configured": pac,
                         "pac_evaluated": False, "auto_detect_evaluated": False}
    except (OSError, ValueError):
        return [], {"status": "read_failed", "configured": None, "pac_configured": None}


def proxy_snapshot(scheme: str = "https") -> tuple[list[Proxy], dict]:
    env = getproxies_environment()
    value = env.get(scheme) or env.get("all")
    proxies = [Proxy("environment", value, tuple(env.get("no", "").split(",")))] if value else []
    system, meta = _windows_proxy() if scheme == "https" else _windows_proxy(scheme)
    proxies.extend(system)
    configured = True if proxies or meta["configured"] else False if meta["configured"] is False else None
    return proxies, {"configured": configured, "system": meta, "settings": [p.public() for p in proxies],
                     "scope": scheme.upper() + "_environment_and_Windows_user_proxy",
                     "configuration_is_traffic_evidence": False, "tun_status": "unknown"}


def _targets(service_id: str, check_login: bool | None = None) -> dict[str, str]:
    if service_id not in ENDPOINTS:
        raise AppError("invalid_network_service", "请选择已登记的校园服务，不能传入任意网址。")
    targets = {service_id: ENDPOINTS[service_id]}
    policy = POLICIES[service_id]
    if policy.sso_dependency and (policy.check_login_default if check_login is None else check_login):
        targets["school_sso"] = ENDPOINTS["school_sso"]
    return targets


def direct_checks(service_id: str) -> dict:
    """Fresh bounded preflight of the service and its separate login dependency."""
    jobs = {key: (lambda url=url: _http(url)) for key, url in _targets(service_id, check_login=True).items()}
    return _bounded(jobs)


def _decision(checks: list[dict], location: str) -> dict:
    values = [check["direct"]["reachable"] for check in checks]
    ready = all(value is True for value in values)
    blocked = any(value is False for value in values)
    code = "direct_ready" if ready else "direct_blocked" if blocked else "direct_inconclusive"
    steps, observations = [], []
    policy = POLICIES[checks[0]["service_id"]]
    login_checked = any(c["service_id"] == "school_sso" for c in checks)
    if ready:
        observations.append("MCP 执行主机直连已收到服务及统一认证的匿名响应；尚未验证登录、表单或受理。"
                            if login_checked and len(checks) > 1 else
                            "MCP 执行主机直连已收到该入口的匿名响应；未核验正文、登录或业务流程。")
    else:
        if location == "off_campus" and policy.preferred_access == "campus_access_if_needed":
            steps.append("校外直连可能没有校内路由；普通代理不等于校园 VPN。检查学校认可的接入方式及其覆盖范围。")
        else:
            steps.append(policy.hint)
            steps.append("核对当前 DNS、路由和 TUN；该端点单次失败不代表其他学校服务不可用。")
        steps.append("网络恢复后重新诊断；不要因连接中断重发已发出的报修请求。")
    for check in checks:
        if check["dns"].get("fake_ip_detected"):
            observations.append(f"{check['service_id']} 的系统 DNS 返回 fake-IP 段；应用层直连仍可能受代理 DNS/TUN 影响。")
        for comparison in check["local_proxies"]:
            direct, proxy = check["direct"].get("reachable"), comparison.get("reachable")
            if direct is True and proxy is False:
                observations.append(f"{check['service_id']} 直连成功、显式本机代理失败；MCP 继续直连，可核对浏览器的该站绕过配置。")
            elif direct is False and proxy is True:
                observations.append(f"{check['service_id']} 仅本机代理探测成功；不会自动把登录或报修切到代理，需先核对路由。")
    return {"status": code, "can_attempt_direct": True if ready else False if blocked else None,
            "can_attempt_anonymous_read": checks[0]["direct"].get("reachable"),
            "login_checked": login_checked,
            "can_attempt_login": (True if ready else False if blocked else None) if login_checked else None,
            "observations": observations, "next_steps": steps, "automatic_proxy_fallback": False}


class NetworkDiagnostics:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict = {}

    def diagnose(self, service_id: str = "sangpushan_repair", location_hint: str = "unknown",
                 refresh: bool = False, *, check_login: bool | None = None, compare_proxy: bool = False) -> dict:
        targets = _targets(service_id, check_login)
        if (check_login is not None and not isinstance(check_login, bool)) or not isinstance(compare_proxy, bool):
            raise AppError("invalid_network_options", "登录检查和代理比较只接受布尔开关。")
        if location_hint not in {"unknown", "campus", "off_campus"}:
            raise AppError("invalid_network_location", "网络位置只接受 unknown、campus 或 off_campus；不确定请留空。")
        scheme = urlparse(ENDPOINTS[service_id]).scheme
        proxies, configuration = proxy_snapshot() if scheme == "https" else proxy_snapshot(scheme)
        # Raw settings stay in memory and out of cache keys/results/logs.
        signature = hashlib.sha256(repr([(p.source, p.value, p.bypass) for p in proxies]).encode()).hexdigest()
        key = (service_id, location_hint, signature, repr(configuration), check_login, compare_proxy)
        if not self._lock.acquire(blocking=False):
            raise AppError("network_diagnosis_running", "已有网络诊断在进行，请稍后查询。")
        try:
            cached = self._cache.get(key)
            age = time.monotonic() - cached[0] if cached else 0
            if not refresh and cached and age < 15:
                return copy.deepcopy(cached[1]) | {"cached": True, "age_seconds": round(age, 2),
                                                 "execution": execution_context()}
            start, jobs = time.monotonic(), {}
            for name, url in targets.items():
                host = urlparse(url).hostname
                jobs[name + ":dns"] = lambda host=host: _dns(host)
                jobs[name + ":direct"] = lambda url=url: _http(url)
                # Equal env/system endpoints share one probe per target.
                for proxy_url in ({p.probe_url() for p in proxies} - {None} if compare_proxy else set()):
                    jobs[name + ":" + proxy_url] = lambda url=url, proxy=proxy_url: _http(url, proxy)
            results, checks = _bounded(jobs), []
            for name, url in targets.items():
                comparisons = []
                for proxy in proxies if compare_proxy else []:
                    probe_url = proxy.probe_url()
                    comparison = results[name + ":" + probe_url] if probe_url else {
                        "status": proxy.public()["status"], "reachable": None}
                    comparisons.append(comparison | {"source": proxy.source,
                        "bypass_matches_target": proxy.bypasses(urlparse(url).hostname),
                        "explicit_comparison_ignores_bypass": True})
                checks.append({"service_id": name, "url": url, "dns": results[name + ":dns"],
                               "direct": results[name + ":direct"], "local_proxies": comparisons})
            decision = _decision(checks, location_hint)
            configured = configuration["configured"]
            suffix = "proxy_configured" if configured else "no_proxy_configured" if configured is False else "proxy_unknown"
            result = {"ok": True, "status": decision["status"], "service_id": service_id,
                      "execution": execution_context(),
                      "access_policy": POLICIES[service_id].public(),
                      "proxy_comparison_requested": compare_proxy,
                      "checked_at": datetime.now(UTC).isoformat(), "cached": False, "age_seconds": 0,
                      "elapsed_ms": round((time.monotonic() - start) * 1000),
                      "network_context": {"location_hint": location_hint, "location_verified": False,
                                          "scenario": location_hint + "_" + suffix},
                      "proxy_configuration": configuration, "checks": checks, "decision": decision,
                      "scope": "anonymous_GET_response_headers_and_OS_DNS_only",
                      "limitations": ["网络检查发生在 MCP 执行主机；不检查调用客户端的 DNS、代理、路由或物理位置。",
                                      "客户端到 MCP 的连接须由客户端传输握手验证；本报告只探测执行主机到学校的路径。",
                                      "应用层直连忽略环境/系统 HTTP 代理，不能绕过 TUN、DNS 或系统路由。",
                                      "代理配置不证明流量路径；不识别实际客户端名称，不自动判断物理校内/校外。",
                                      "只比较无凭据的本机 HTTP(S)/SOCKS5 代理；远端、PAC 和需凭据代理不探测。",
                                      "各服务与统一认证分别报告；可达不代表登录、填表或报修已成功。"]}
            # At most one recent result; no persistent network/device inventory.
            self._cache = {key: (time.monotonic(), copy.deepcopy(result))}
            return result
        finally:
            self._lock.release()
