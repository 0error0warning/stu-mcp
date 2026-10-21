"""Provider-shape changes must retain old snapshots and their real collection time."""
import json

import httpx
import pytest

from stu_mcp import charging
from stu_mcp.charging_devices import Device
from stu_mcp.features.charging.adapter import ChargingClient, ConfigCache
from stu_mcp.features.charging.service import ChargingService

DEVICE = Device("4GR90000001", "合成设备", "合成地点", 2)
PORTS = [{"num": 1, "state": 1}, {"num": 2, "state": 2}]


@pytest.fixture
def provider(app, monkeypatch):
    state = {"entry": '<script src="/static/js/index.abcdef12.js"></script>',
             "config": '{app_id:"SYNTHETIC_ID",app_secret:"SYNTHETIC_SECRET"}',
             "kind": {"code": 200, "data": 6}, "ports": {"code": 200, "data": PORTS},
             "requests": [], "cache": ConfigCache(), "clock": [1800000000.0]}

    def handler(request):
        state["requests"].append(request.url.path)
        assert request.url.host == "wx.isfdz.com" and request.url.scheme == "https"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text=state["entry"])
        if path.endswith(".js"):
            return httpx.Response(200, text=state["config"], headers={"Set-Cookie": "synthetic=not-forwarded"})
        return httpx.Response(200, json=state["kind"] if path.endswith("getEquipType") else state["ports"])

    def factory():
        return ChargingClient(transport=httpx.MockTransport(handler), config_cache=state["cache"])

    state["factory"] = factory
    state["service"] = lambda: ChargingService(app.store, devices=(DEVICE,),
                                               clock=lambda: state["clock"][0], client_factory=factory)
    return state


@pytest.mark.parametrize("branch,value,status", [
    ("entry", '<script src="/static/js/index.abcdef12.js"></script>'
              '<script src="/static/js/index.123456ab.js"></script>', "schema_changed"),
    ("config", '{app_id:"SYNTHETIC_ID"};{app_secret:"SYNTHETIC_SECRET"}', "schema_changed"),
    ("kind", {"code": 200}, "schema_changed"),
    ("ports", {"code": 200, "data": {"token": "SYNTHETIC_SECRET"}}, "schema_changed"),
    ("ports", {"code": 200, "data": [{"num": 1, "state": True}]}, "schema_changed"),
    ("kind", {"code": 403, "msg": "设备不在线"}, "access_denied"),
    ("kind", {"code": 429, "msg": "设备不在线"}, "rate_limited"),
])
def test_provider_drift_keeps_previous_success_and_timestamp(app, provider, branch, value, status):
    old = provider["service"]().detail(DEVICE.code)["device"]
    assert old["counts"]["free"] == 1
    provider[branch] = value
    provider["cache"].current = None
    provider["clock"][0] += 61
    result = provider["service"]().detail(DEVICE.code)
    latest = result["device"]
    assert latest["error"]["status"] == status and latest["stale"]
    assert latest["retained_from_cache"]
    assert latest["counts"] == old["counts"] and latest["ports"] == old["ports"]
    assert latest["collected_at"] == old["collected_at"]
    assert "SYNTHETIC_SECRET" not in json.dumps(result)


def test_failed_discovery_does_not_cache_configuration_or_follow_a_second_candidate(provider):
    provider["entry"] += '<script src="/static/js/index.123456ab.js"></script>'
    result = provider["service"]().detail(DEVICE.code)
    assert result["device"]["error"]["status"] == "schema_changed"
    assert provider["requests"] == ["/"] and provider["cache"].current is None


def test_only_validated_configuration_can_be_cached(provider):
    provider["config"] += ';{app_id:"another",app_secret:"SYNTHETIC_SECRET"}'
    result = provider["service"]().detail(DEVICE.code)
    assert result["device"]["error"]["status"] == "schema_changed"
    assert len(provider["requests"]) == 2 and provider["cache"].current is None


def test_feature_service_and_old_injection_point_have_identical_output(app, provider, monkeypatch):
    monkeypatch.setattr(charging, "DEVICES", (DEVICE,))
    monkeypatch.setattr(charging, "ChargingClient", provider["factory"])
    feature = provider["service"]().detail(DEVICE.code)
    # Cache-only reads have intentionally different fetched/cached flags, so use another store.
    from stu_mcp.app import App
    from stu_mcp.runtime import Runtime
    from stu_mcp.vault import Vault
    runtime = Runtime(app.runtime.home.parent / "legacy-runtime")
    other = App(runtime, Vault(runtime, app.vault._store))
    legacy = charging.ChargingService(other.store, clock=lambda: provider["clock"][0]).detail(DEVICE.code)
    assert feature == legacy
