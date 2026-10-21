"""Anonymous fixed-path charging reads and bounded public configuration refresh."""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

import httpx

from ...charging_devices import Device
from ...network import retry_after
from ...runtime import AppError
from .models import PublicConfig
from .parser import (
    device_protocol,
    discover_script,
    parse_configuration,
    parse_envelope,
    parse_ports,
    sign_params,
)
from .schema import API_PATHS, BASE, CONFIG_TTL_SECONDS, SCRIPT_PATH_PATTERN


@dataclass
class ConfigCache:
    current: PublicConfig | None = field(default=None, repr=False)
    lock: object = field(default_factory=threading.Lock, repr=False)


_CONFIG_CACHE = ConfigCache()


class ChargingClient:
    def __init__(self, *, transport=None, config_cache=None):
        self.config_cache = _CONFIG_CACHE if config_cache is None else config_cache
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
        valid = method == "GET" and (path == "/" or re.fullmatch(SCRIPT_PATH_PATTERN, path))
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
        with self.config_cache.lock:
            config = self.config_cache.current
            if not renew and config and time.monotonic() - config.loaded_at < CONFIG_TTL_SECONDS:
                return config
            script = discover_script(self._read("/", max_bytes=256_000).text)
            source = self._read(script, max_bytes=2_000_000).text
            config = parse_configuration(source, time.monotonic())
            self.config_cache.current = config
            return config

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
            result = parse_envelope(payload)
            if not result.renew_config:
                return result.data
            if attempt == 0 and not self.renewed_config:
                self.renewed_config = True
                self.configuration(renew=True)
                continue
            raise AppError("source_rejected", "充电平台请求签名或时间戳未通过验证。", "charging", http_status=200)
        raise AppError("source_rejected", "充电平台请求未通过验证。", "charging")

    def device(self, device: Device) -> dict:
        kind = self.query("GET", "charge/mobile/getEquipType", {"code": device.code})
        protocol = device_protocol(kind)
        ports = self.query("POST", f"equi/{protocol}/getLineInfo", {"code": device.code, "parentCode": ""})
        return {"device_type": kind, **parse_ports(ports, device.capacity)}
