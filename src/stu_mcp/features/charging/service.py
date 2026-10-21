"""Device query budgets and cache policy, independent of provider HTML and JSON."""
from __future__ import annotations

import json
import time
from contextlib import ExitStack
from datetime import datetime

from ...charging_cache import STALE_AFTER, TTL, ChargingCache
from ...charging_devices import DEVICES, VERIFIED_ON, Device, select_devices
from ...runtime import AppError
from .adapter import ChargingClient
from .parser import timestamp
from .schema import STOP_CODES


class ChargingService:
    def __init__(self, store, *, devices: tuple[Device, ...] | None = None, clock=None, client_factory=ChargingClient):
        self.devices = DEVICES if devices is None else devices
        self.client_factory = client_factory
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
                                client = stack.enter_context(self.client_factory())
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
