"""Independent, on-demand public charging reads. No website service or user session."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from .charging_cache import STALE_AFTER, TTL, ChargingCache
from .charging_devices import DEVICES, VERIFIED_ON, Device, select_devices
from .network import retry_after
from .runtime import AppError

BASE = "https://wx.isfdz.com"
STATE_LABELS = {0: "粘连故障", 1: "空闲", 2: "占用", 3: "开路故障", 4: "设备急停",
                5: "过温保护", 6: "烟感报警", 7: "过压故障", 8: "欠压故障"}
AFTER_TYPES = frozenset({2, 6, 8, 10, 11, 12, 13, 14})
BEFORE_TYPES = frozenset({1, 3, 4, 5, 7, 9})
API_PATHS = frozenset({("GET", "charge/mobile/getEquipType"),
                       ("POST", "equi/afterProtocol/getLineInfo"),
                       ("POST", "equi/beforeProtocol/getLineInfo")})
STOP_CODES = frozenset({"rate_limited", "access_denied", "source_rejected", "source_unavailable",
                        "network_error", "request_timeout", "request_limit", "request_deadline",
                        "schema_changed", "response_too_large"})
_CONFIG_LOCK = threading.Lock()


@dataclass(repr=False)
class PublicConfig:
    app_id: str = field(repr=False)
    secret: str = field(repr=False)
    loaded_at: float = field(repr=False)


_CONFIG: PublicConfig | None = None


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            source = dict(attrs).get("src")
            if isinstance(source, str):
                self.sources.append(source)


def timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


def sign_params(params: dict, config: PublicConfig, unix_seconds: int) -> dict:
    values = {**params, "timestamp": unix_seconds, "app_id": config.app_id}
    basis = "".join(f"{key}={values[key]}" for key in sorted(values)) + config.secret
    return {**values, "sign": hashlib.md5(basis.encode("utf-8")).hexdigest()}


def parse_ports(data, capacity: int) -> dict:
    if not isinstance(data, list) or not data or len(data) > capacity:
        raise AppError("schema_changed", "充电平台未返回有效的插座列表，未将其当作零空闲。", "charging")
    seen, ports = set(), []
    for port in data:
        if (not isinstance(port, dict) or type(port.get("num")) is not int
                or not 1 <= port["num"] <= capacity or port["num"] in seen
                or type(port.get("state")) is not int or port["state"] < 0):
            raise AppError("schema_changed", "插座编号或状态结构变化，未覆盖上次成功数据。", "charging")
        seen.add(port["num"])
        ports.append({"num": port["num"], "state": port["state"],
                      "label": STATE_LABELS.get(port["state"], "未知状态")})
    free = sum(p["state"] == 1 for p in ports)
    occupied = sum(p["state"] == 2 for p in ports)
    fault = sum(p["state"] in STATE_LABELS and p["state"] not in (1, 2) for p in ports)
    return {"ports": sorted(ports, key=lambda p: p["num"]), "ports_complete": len(seen) == capacity,
            "counts": {"total": capacity, "observed": len(ports), "free": free, "occupied": occupied,
                       "fault": fault, "unknown": capacity - free - occupied - fault}}


class ChargingClient:
    def __init__(self, *, transport=None):
        self.client = httpx.Client(verify=True, trust_env=False, follow_redirects=False, transport=transport,
                                   timeout=httpx.Timeout(12, connect=6),
                                   headers={"User-Agent": "STU-MCP/charging", "Accept": "application/json,text/html"})
        self.requests = 0
        self.deadline = time.monotonic() + 40
        self.renewed_config = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def _read(self, path: str, *, method: str = "GET", params: dict | None = None,
              body: dict | None = None, max_bytes: int = 1_000_000) -> httpx.Response:
        valid = method == "GET" and (path == "/" or re.fullmatch(r"/static/js/index\.[a-f0-9]{6,64}\.js", path))
        valid = valid or (method, path.removeprefix("/api/")) in API_PATHS and path.startswith("/api/")
        if not valid or method not in {"GET", "POST"}:
            raise AppError("unsafe_url", "该路径不在充电只读接口范围内。", "charging")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AppError("request_deadline", "本轮充电查询已达到时间上限，请缩小范围。", "charging")
        if self.requests >= 18:
            raise AppError("request_limit", "本轮充电查询已达到请求上限。", "charging")
        self.requests += 1
        self.client.cookies.clear()
        try:
            with self.client.stream(method, BASE + path, params=params, json=body,
                                    timeout=httpx.Timeout(min(12, remaining), connect=min(6, remaining))) as response:
                status = response.status_code
                if status in (401, 403):
                    raise AppError("access_denied", "充电平台拒绝此次公开读取；未请求用户登录。", "charging",
                                   http_status=status)
                if status == 429:
                    raise AppError("rate_limited", "充电平台限制了读取频率，请等待后重试。", "charging",
                                   http_status=status, retry_after_seconds=retry_after(response.headers.get("retry-after")))
                if status >= 500:
                    raise AppError("source_unavailable", "充电平台暂时不可用，请稍后重试。", "charging", http_status=status)
                if status != 200:
                    raise AppError("source_rejected", "充电平台未接受此次读取；未跟随跳转。", "charging", http_status=status)
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise AppError("response_too_large", "充电平台响应超过读取上限。", "charging")
                    if time.monotonic() > self.deadline:
                        raise AppError("request_deadline", "本轮充电读取已超时。", "charging")
                return httpx.Response(status, content=bytes(content))
        except httpx.TimeoutException:
            raise AppError("request_timeout", "充电平台读取超时。", "charging") from None
        except httpx.HTTPError:
            raise AppError("network_error", "无法连接充电平台。", "charging") from None

    def configuration(self, *, renew: bool = False) -> PublicConfig:
        global _CONFIG
        with _CONFIG_LOCK:
            if not renew and _CONFIG and time.monotonic() - _CONFIG.loaded_at < 21600:
                return _CONFIG
            html = self._read("/", max_bytes=256_000).text
            parser = ScriptSources()
            parser.feed(html)
            script = None
            for value in parser.sources:
                url = urlsplit(urljoin(BASE + "/", value))
                if (url.scheme == "https" and url.netloc == "wx.isfdz.com" and not url.query and not url.fragment
                        and re.fullmatch(r"/static/js/index\.[a-f0-9]{6,64}\.js", url.path)):
                    script = url.path
                    break
            if script is None:
                raise AppError("schema_changed", "充电平台公开客户端入口变化。", "charging")
            source = self._read(script, max_bytes=2_000_000).text
            app_id = re.search(r'\bapp_id\s*:\s*["\']([^"\'\r\n]{1,128})["\']', source)
            secret = re.search(r'\bapp_secret\s*:\s*["\']([^"\'\r\n]{1,256})["\']', source)
            if not app_id or not secret:
                raise AppError("schema_changed", "充电平台公开请求配置变化。", "charging")
            _CONFIG = PublicConfig(app_id.group(1), secret.group(1), time.monotonic())
            return _CONFIG

    def query(self, method: str, path: str, params: dict):
        if (method, path) not in API_PATHS:
            raise AppError("unsafe_url", "该路径不在充电只读接口范围内。", "charging")
        for attempt in range(2):
            signed = sign_params(params, self.configuration(), int(time.time()))
            response = self._read("/api/" + path, method=method,
                                  params=signed if method == "GET" else None,
                                  body=signed if method == "POST" else None)
            try:
                payload = response.json()
            except ValueError:
                raise AppError("schema_changed", "充电平台返回了非 JSON 数据。", "charging") from None
            if not isinstance(payload, dict) or type(payload.get("code")) is not int:
                raise AppError("schema_changed", "充电平台响应结构变化。", "charging")
            if payload["code"] == 200:
                return payload.get("data")
            message = payload.get("msg")
            if isinstance(message, str) and "设备不在线" in message:
                raise AppError("device_offline", "充电平台报告设备不在线，当前插座状态未知。", "charging", http_status=200)
            if message in ("签名错误", "时间戳已过期"):
                if attempt == 0 and not self.renewed_config:
                    self.renewed_config = True
                    self.configuration(renew=True)
                    continue
                raise AppError("source_rejected", "充电平台请求签名或时间戳未通过验证。", "charging", http_status=200)
            if payload["code"] in (401, 403, 429):
                code = "rate_limited" if payload["code"] == 429 else "access_denied"
                raise AppError(code, "充电平台限制或拒绝此次公开读取。", "charging", http_status=200)
            raise AppError("source_error", "充电平台返回业务失败，未将其当作零空闲。", "charging", http_status=200)
        raise AppError("source_rejected", "充电平台请求未通过验证。", "charging")

    def device(self, device: Device) -> dict:
        kind = self.query("GET", "charge/mobile/getEquipType", {"code": device.code})
        if type(kind) is not int or kind not in AFTER_TYPES | BEFORE_TYPES:
            raise AppError("unsupported_device", "充电平台返回了未支持的设备类型。", "charging")
        protocol = "afterProtocol" if kind in AFTER_TYPES else "beforeProtocol"
        ports = self.query("POST", f"equi/{protocol}/getLineInfo", {"code": device.code, "parentCode": ""})
        return {"device_type": kind, **parse_ports(ports, device.capacity)}


class ChargingService:
    def __init__(self, store, *, devices: tuple[Device, ...] | None = None, clock=None):
        self.devices = DEVICES if devices is None else devices
        self.store = store
        self.clock = clock or time.time
        self.cache = ChargingCache(store, self.clock)
        self.attempted = False
        self.fresh_reads = 0

    def _view(self, device: Device, row: dict, *, fetched: bool = False, error: dict | None = None) -> dict:
        data = json.loads(row["payload"]) if row.get("payload") else None
        error = error or (json.loads(row["error"]) if row.get("error") else None)
        age = max(0, int(self.clock() - datetime.fromisoformat(data["collected_at"]).timestamp())) if data else None
        stale = data is None or error is not None or age > STALE_AFTER
        status = error["status"] if error else ("not_cached" if data is None else
                                              "partial" if data["counts"]["unknown"] else "ok")
        if data and stale and not error:
            status = "stale"
        result = {**device.metadata(), "device_type": None, "ports": None, "counts": None,
                  "ports_complete": False, "collected_at": None, **(data or {}),
                  "status": status, "online": False if error and error["status"] == "device_offline" else None,
                  "last_attempt_at": timestamp(row["attempted_at"]) if row.get("attempted_at") else None,
                  "cached": bool(data) and not fetched, "stale": stale, "cache_age_seconds": age,
                  "retained_from_cache": bool(data) and error is not None, "error": error}
        if row.get("retry_at", 0) > self.clock():
            result["retry_after_seconds"] = max(1, int(row["retry_at"] - self.clock() + 0.999))
        return result

    def _collect(self, devices: list[Device], refresh: bool) -> list[dict]:
        if type(refresh) is not bool:
            raise AppError("invalid_refresh", "刷新选项必须为 true 或 false。", "charging")
        self.attempted, self.fresh_reads = False, 0
        items, client, stopped = [], None, None
        with ExitStack() as stack:
            for device in devices:
                row, fetched, failure = self.cache.read(device.code), False, None
                if refresh and stopped is not None:
                    failure = stopped
                elif refresh:
                    token, row, failure = self.cache.claim(device.code)
                    if token:
                        self.attempted = True
                        try:
                            if client is None:
                                client = stack.enter_context(ChargingClient())
                            data = {**client.device(device), "collected_at": timestamp(self.clock())}
                            row = self.cache.finish(device.code, token, data, None)
                            fetched = True
                            self.fresh_reads += 1
                        except Exception as exc:
                            safe = exc if isinstance(exc, AppError) else AppError(
                                "source_error", "充电查询未能处理此次响应，已保留旧数据。", "charging")
                            failure = safe.result()
                            row = self.cache.finish(device.code, token, None, failure)
                            if safe.code in STOP_CODES:
                                stopped = failure
                                self.cache.cooldown(failure)
                items.append(self._view(device, row, fetched=fetched, error=failure))
        return items

    def _envelope(self, items: list[dict]) -> dict:
        has_data = any(i["counts"] is not None for i in items)
        status = "ok" if all(i["status"] == "ok" for i in items) else "partial" if has_data else "unavailable"
        if self.attempted:
            recorded = status if self.fresh_reads else next((i["error"]["status"] for i in items if i["error"]), "source_error")
            self.store.record_status("charging", recorded, self.fresh_reads)
        return {"ok": has_data or not items, "status": status, "source": "charging", "official": False,
                "provider": "isfdz", "content_trust": "untrusted_source_data", "queried_at": timestamp(self.clock()),
                "stale": any(i["stale"] for i in items), "cached": bool(items) and all(i["cached"] for i in items),
                "cache_ttl_seconds": TTL, "stale_after_seconds": STALE_AFTER,
                "errors": [{"device_code": i["device_code"], **i["error"]} for i in items if i["error"]]}

    def overview(self, location: str = "", limit: int = 4, offset: int = 0, refresh: bool = True) -> dict:
        if type(limit) is not int or not 1 <= limit <= 4 or type(offset) is not int or not 0 <= offset <= 10000:
            raise AppError("invalid_limit", "充电总览每页 1–4 台设备，偏移量为 0–10000。", "charging")
        selected = select_devices(location, self.devices)
        items = self._collect(selected[offset:offset + limit], refresh)
        result = self._envelope(items)
        counts = None
        current = [i for i in items if i["counts"] is not None and not i["stale"]]
        if current:
            counts = {k: sum(i["counts"][k] for i in current)
                      for k in ("observed", "free", "occupied", "fault", "unknown")}
            missing = sum(i["expected_port_count"] for i in items if i["counts"] is None or i["stale"])
            counts.update(total=sum(i["expected_port_count"] for i in items), unknown=counts["unknown"] + missing)
        summaries = [{k: v for k, v in i.items() if k != "ports"} for i in items]
        return {**result, "items": summaries, "counts": counts, "location": location,
                "total_count": len(selected), "offset": offset, "has_more": offset + limit < len(selected),
                "next_offset": offset + limit if offset + limit < len(selected) else None,
                "coverage": {"catalog_device_count": len(self.devices), "catalog_verified_on": VERIFIED_ON,
                             "inventory_complete": None, "returned_device_count": len(items),
                             "devices_with_data": sum(i["counts"] is not None for i in items),
                             "fresh_device_count": sum(not i["stale"] for i in items),
                             "counts_scope": "returned_devices_only",
                             "counts_fresh_only": True,
                             "scope": "已核验设备清单，不代表全校完整清单；插座空闲不保证现场停车空间。"},
                "message": "" if items else "已核验清单中没有匹配的设备；这不能证明现场没有设备。"}

    def detail(self, device_code: str, refresh: bool = True) -> dict:
        device = next((d for d in self.devices if d.code == device_code), None)
        if device is None:
            raise AppError("unknown_device", "设备不在已核验清单内，请先按位置查询总览取得编号。", "charging")
        items = self._collect([device], refresh)
        return {**self._envelope(items), "device": items[0]}
