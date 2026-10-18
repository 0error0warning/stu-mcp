import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from stu_mcp import charging
from stu_mcp.charging import ChargingClient, ChargingService, PublicConfig, parse_ports, sign_params
from stu_mcp.charging_cache import ChargingCache
from stu_mcp.charging_devices import Device
from stu_mcp.cli import main
from stu_mcp.runtime import AppError

FIRST = Device("4GR90000001", "合成书院 DEMO-1", "合成书院", 4, ("合成", "DEMO"))
SECOND = Device("4GR90000002", "合成图书馆 DEMO-2", "合成图书馆", 4, ("图书馆",))
PORTS = [{"num": 1, "state": 1}, {"num": 2, "state": 2},
         {"num": 3, "state": 1}, {"num": 4, "state": 2}]
SECRET = "SYNTHETIC_PUBLIC_SECRET_NEVER_REAL"


@pytest.fixture(autouse=True)
def synthetic_catalog(monkeypatch):
    monkeypatch.setattr(charging, "DEVICES", (FIRST, SECOND))
    monkeypatch.setattr(charging, "_CONFIG", None)


def install_client(monkeypatch, handler=None, *, kind=6, html=None):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.scheme == "https" and request.url.host == "wx.isfdz.com"
        assert "cookie" not in request.headers and "authorization" not in request.headers
        path = request.url.path
        if path == "/":
            return httpx.Response(200, text=html if html is not None else
                                  '<script src="/static/js/index.abcdef12.js"></script>')
        if path == "/static/js/index.abcdef12.js":
            # A cookie supplied by the public site must not follow subsequent API requests.
            return httpx.Response(200, text=f'var c={{app_id:"SYNTHETIC_ID",app_secret:"{SECRET}"}};',
                                  headers={"Set-Cookie": "synthetic_session=MUST_NOT_FORWARD; Path=/"})
        if handler is not None:
            result = handler(request)
            if result is not None:
                return result
        if path.endswith("getEquipType"):
            assert request.method == "GET"
            return httpx.Response(200, json={"code": 200, "data": kind})
        assert request.method == "POST"
        assert request.headers["Content-Type"].startswith("application/json")
        body = json.loads(request.content)
        assert body["parentCode"] == "" and body["code"] in {FIRST.code, SECOND.code}
        assert set(body) == {"code", "parentCode", "app_id", "timestamp", "sign"}
        expected = sign_params({"code": body["code"], "parentCode": ""},
                               PublicConfig("SYNTHETIC_ID", SECRET, 0), body["timestamp"])
        assert body == expected
        return httpx.Response(200, json={"code": 200, "data": PORTS})

    monkeypatch.setattr(charging, "ChargingClient", lambda: ChargingClient(transport=httpx.MockTransport(respond)))
    return requests


def service(app, tick=None):
    return ChargingService(app.store, clock=(lambda: tick[0]) if tick else None)


def test_signature_known_vector_and_empty_parent():
    config = PublicConfig("SYNTHETIC_ID", "SYNTHETIC_SECRET", 0)
    result = sign_params({"parentCode": "", "code": FIRST.code}, config, 1791158400)
    assert result["sign"] == "41e479eaaed847e4b8e7e21a2c4b35bb"
    assert result["parentCode"] == "" and type(result["timestamp"]) is int
    assert "SYNTHETIC_SECRET" not in repr(config)


@pytest.mark.parametrize("kind,protocol", [(6, "afterProtocol"), (1, "beforeProtocol")])
def test_public_protocol_branches_and_json_post(app, monkeypatch, kind, protocol):
    requests = install_client(monkeypatch, kind=kind)
    result = service(app).detail(FIRST.code)
    device = result["device"]
    assert result["ok"] and result["status"] == "ok"
    assert requests[-1].url.path == f"/api/equi/{protocol}/getLineInfo"
    assert device["counts"] == {"total": 4, "observed": 4, "free": 2, "occupied": 2, "fault": 0, "unknown": 0}
    assert device["ports"][0] == {"num": 1, "state": 1, "label": "空闲"}
    assert device["online"] is None and not device["cached"] and not device["stale"]
    assert result["official"] is False and SECRET not in json.dumps(result)


def test_fault_labels_unknown_states_and_incomplete_observations():
    result = parse_ports([{"num": 4, "state": 255}, {"num": 2, "state": 3}, {"num": 1, "state": 6}], 4)
    assert [p["label"] for p in result["ports"]] == ["烟感报警", "开路故障", "未知状态"]
    assert result["counts"] == {"total": 4, "observed": 3, "free": 0, "occupied": 0, "fault": 2, "unknown": 2}
    assert not result["ports_complete"] and result["ports"][-1]["state"] == 255
    future = parse_ports([{"num": 1, "state": 1024}], 4)
    assert future["ports"][0]["state"] == 1024 and future["counts"]["unknown"] == 4


@pytest.mark.parametrize("data", [None, [], {}, [{"num": 1, "state": 1}, {"num": 1, "state": 2}],
                                 [{"num": 0, "state": 1}], [{"num": 5, "state": 1}],
                                 [{"num": True, "state": 1}], [{"num": 1, "state": True}],
                                 [{"num": 1, "state": "1"}], [{"num": 1, "state": -1}]])
def test_invalid_ports_are_errors_instead_of_zero_availability(data):
    with pytest.raises(AppError) as error:
        parse_ports(data, 4)
    assert error.value.code == "schema_changed"


def test_persistent_cache_ttl_and_age_survive_new_service(app, monkeypatch):
    tick = [1800000000.0]
    requests = install_client(monkeypatch)
    first = service(app, tick).detail(FIRST.code)["device"]
    status_before = app.store.freshness()
    tick[0] += 20
    second = service(app, tick).detail(FIRST.code)["device"]
    assert len(requests) == 4 and second["cached"] and second["cache_age_seconds"] == 20
    assert second["collected_at"] == first["collected_at"] and app.store.freshness() == status_before
    tick[0] += 101
    stale = service(app, tick).detail(FIRST.code, refresh=False)["device"]
    assert stale["status"] == "stale" and stale["stale"] and stale["cache_age_seconds"] == 121
    assert len(requests) == 4 and stale["collected_at"] == first["collected_at"]
    refreshed = service(app, tick).detail(FIRST.code)["device"]
    assert len(requests) == 6 and not refreshed["cached"] and not refreshed["stale"]
    assert refreshed["collected_at"] != first["collected_at"]
    reusable = service(app, tick)
    reusable.detail(SECOND.code)
    last_status = app.store.freshness()
    tick[0] += 1
    reusable.detail(SECOND.code)
    assert app.store.freshness() == last_status


def test_offline_retains_original_success_and_throttles_failed_attempts(app, monkeypatch):
    tick, offline = [1800000000.0], [False]

    def handler(request):
        if offline[0] and request.url.path.endswith("getLineInfo"):
            return httpx.Response(200, json={"code": 500, "msg": "设备不在线 " + SECRET})

    requests = install_client(monkeypatch, handler)
    first = service(app, tick).detail(FIRST.code)["device"]
    successful_at = app.store.freshness()[0]["success_at"]
    tick[0] += 61
    offline[0] = True
    result = service(app, tick).detail(FIRST.code)
    retained = result["device"]
    assert result["status"] == "partial" and retained["status"] == "device_offline"
    assert retained["counts"] == first["counts"] and retained["ports"] == first["ports"]
    assert retained["collected_at"] == first["collected_at"] and retained["last_attempt_at"] != first["last_attempt_at"]
    assert retained["stale"] and retained["cached"] and retained["retained_from_cache"]
    assert retained["online"] is False and SECRET not in json.dumps(result)
    assert app.store.freshness()[0]["success_at"] == successful_at
    tick[0] += 1
    assert service(app, tick).detail(FIRST.code)["device"]["status"] == "device_offline"
    assert len(requests) == 6


def test_offline_without_history_has_null_ports_and_counts(app, monkeypatch):
    install_client(monkeypatch, lambda _: httpx.Response(200, json={"code": 500, "msg": "设备不在线"}))
    result = service(app).detail(FIRST.code)
    assert not result["ok"] and result["status"] == "unavailable"
    assert result["device"]["ports"] is None and result["device"]["counts"] is None
    assert result["device"]["collected_at"] is None and result["device"]["stale"]


def test_overview_does_not_count_retained_old_free_ports_as_current_availability(app, monkeypatch):
    tick, offline = [1800000000.0], [False]

    def handler(request):
        if (offline[0] and request.url.path.endswith("getLineInfo")
                and json.loads(request.content)["code"] == FIRST.code):
            return httpx.Response(200, json={"code": 500, "msg": "设备不在线"})

    install_client(monkeypatch, handler)
    assert service(app, tick).overview(limit=2)["counts"]["free"] == 4
    tick[0] += 61
    offline[0] = True
    result = service(app, tick).overview(limit=2)
    assert result["items"][0]["counts"]["free"] == 2 and result["items"][0]["retained_from_cache"]
    assert result["counts"] == {"total": 8, "observed": 4, "free": 2, "occupied": 2, "fault": 0, "unknown": 4}
    assert result["coverage"]["fresh_device_count"] == 1 and result["stale"]
    tick[0] += 121
    assert service(app, tick).overview(limit=2, refresh=False)["counts"] is None


def test_location_aliases_pagination_and_counts_cover_only_returned_devices(app, monkeypatch):
    install_client(monkeypatch)
    result = app.charging_overview("", limit=1)
    assert result["total_count"] == 2 and result["has_more"] and result["next_offset"] == 1
    assert "ports" not in result["items"][0] and result["counts"]["total"] == 4
    assert result["coverage"]["inventory_complete"] is None
    assert result["coverage"]["counts_scope"] == "returned_devices_only"
    assert app.charging_overview("DEMO-1", refresh=False)["items"][0]["device_code"] == FIRST.code
    assert app.charging_overview("图书馆", refresh=False)["items"][0]["device_code"] == SECOND.code
    missing = app.charging_overview("不存在的合成地点", refresh=False)
    assert missing["items"] == [] and missing["counts"] is None and missing["message"]


@pytest.mark.parametrize("status,code", [(302, "source_rejected"), (401, "access_denied"),
                                        (403, "access_denied"), (500, "source_unavailable")])
def test_http_failures_stop_batch_without_following_or_leaking(app, monkeypatch, status, code):
    requests = install_client(monkeypatch, lambda _: httpx.Response(status, text=SECRET,
                              headers={"Location": "https://evil.example/" + SECRET}))
    result = app.charging_overview(limit=2)
    assert len(requests) == 3 and all(i["error"]["status"] == code for i in result["items"])
    assert all(i["counts"] is None for i in result["items"]) and SECRET not in json.dumps(result)


def test_retry_after_blocks_other_devices_and_later_processes(app, monkeypatch):
    tick = [1800000000.0]
    requests = install_client(monkeypatch, lambda _: httpx.Response(429, headers={"Retry-After": "180"}))
    result = service(app, tick).overview(limit=2)
    assert len(requests) == 3 and result["items"][0]["error"]["status"] == "rate_limited"
    assert result["items"][0]["retry_after_seconds"] >= 180
    tick[0] += 61
    later = service(app, tick).detail(SECOND.code)
    assert len(requests) == 3 and later["device"]["error"]["status"] == "rate_limited"
    assert later["device"]["error"]["retry_after_seconds"] >= 119


def test_signature_config_refresh_is_bounded_and_not_a_user_login(app, monkeypatch):
    requests = install_client(monkeypatch, lambda _: httpx.Response(200, json={"code": 500, "msg": "签名错误"}))
    result = app.charging_overview(limit=2)
    assert len(requests) == 6
    assert sum(r.url.path == "/" for r in requests) == 2
    assert all(i["error"]["status"] == "source_rejected" for i in result["items"])
    assert SECRET not in json.dumps(result) and "needs_login" not in json.dumps(result)


def test_configuration_rotates_once_then_query_succeeds(app, monkeypatch):
    rejected = [False]

    def handler(request):
        if request.url.path.endswith("getEquipType") and not rejected[0]:
            rejected[0] = True
            return httpx.Response(200, json={"code": 500, "msg": "时间戳已过期"})

    requests = install_client(monkeypatch, handler)
    assert service(app).detail(FIRST.code)["ok"]
    assert len(requests) == 7 and sum(r.url.path == "/" for r in requests) == 2


@pytest.mark.parametrize("html", ['<script src="https://evil.example/static/js/index.abcdef12.js"></script>',
                                 '<script src="http://wx.isfdz.com/static/js/index.abcdef12.js"></script>',
                                 '<script src="/static/js/index.abcdef12.js?token=synthetic"></script>'])
def test_public_script_discovery_restricts_origin_scheme_and_query(app, monkeypatch, html):
    requests = install_client(monkeypatch, html=html)
    result = service(app).detail(FIRST.code)
    assert len(requests) == 1 and result["device"]["error"]["status"] == "schema_changed"


def test_public_entry_accepts_unquoted_relative_script_sources(app, monkeypatch):
    requests = install_client(monkeypatch, html='<script src=https://cdn.example/unrelated.js></script>'
                              '<script defer src=./static/js/index.abcdef12.js></script>')
    result = service(app).detail(FIRST.code)
    assert result["ok"] and len(requests) == 4


def test_oversized_payload_is_safe(app, monkeypatch):
    requests = install_client(monkeypatch, lambda _: httpx.Response(200, content=SECRET.encode() * 40000))
    result = service(app).detail(FIRST.code)
    assert len(requests) == 3 and result["device"]["error"]["status"] == "response_too_large"
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("body,code", [(b'not JSON SYNTHETIC_SECRET', "schema_changed"),
                                      (b'[]', "schema_changed"), (b'{"data":null}', "schema_changed"),
                                      (b'{"code":500,"msg":"SYNTHETIC_SECRET"}', "source_error"),
                                      (b'{"code":403,"msg":"SYNTHETIC_SECRET"}', "access_denied"),
                                      (b'{"code":429,"msg":"SYNTHETIC_SECRET"}', "rate_limited")])
def test_http_200_business_errors_and_invalid_json_are_not_empty_success(app, monkeypatch, body, code):
    install_client(monkeypatch, lambda _: httpx.Response(200, content=body))
    result = service(app).detail(FIRST.code)
    assert not result["ok"] and result["device"]["error"]["status"] == code
    assert result["device"]["counts"] is None and "SYNTHETIC_SECRET" not in json.dumps(result)


def test_network_errors_stop_batch_and_do_not_expose_request_values(app, monkeypatch):
    def handler(request):
        raise httpx.ConnectError(SECRET, request=request)
    requests = install_client(monkeypatch, handler)
    result = app.charging_overview(limit=2)
    assert len(requests) == 3 and all(i["error"]["status"] == "network_error" for i in result["items"])
    assert SECRET not in json.dumps(result)


def test_concurrent_queries_share_a_device_lease(app, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def handler(request):
        if request.url.path.endswith("getLineInfo"):
            started.set()
            assert release.wait(5)

    requests = install_client(monkeypatch, handler)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(lambda: service(app).detail(FIRST.code))
        try:
            assert started.wait(5)
            concurrent = service(app).detail(FIRST.code)
            assert concurrent["device"]["status"] == "refresh_running" and len(requests) == 4
        finally:
            release.set()
        first = pending.result(timeout=5)
    cached = service(app).detail(FIRST.code)
    assert cached["device"]["counts"] == first["device"]["counts"] and len(requests) == 4


def test_expired_worker_cannot_overwrite_a_newer_lease(app):
    tick = [1800000000.0]
    cache = ChargingCache(app.store, lambda: tick[0])
    old, _, _ = cache.claim(FIRST.code)
    tick[0] += 61
    new, _, _ = cache.claim(FIRST.code)
    assert old and new and old != new
    cache.finish(FIRST.code, new, {"version": "new"}, None)
    cache.finish(FIRST.code, old, {"version": "old"}, None)
    assert json.loads(cache.read(FIRST.code)["payload"]) == {"version": "new"}


def test_no_login_local_queries_and_cli_work_without_network(app, monkeypatch, capsys):
    class Unavailable:
        def get_password(self, *_):
            pytest.fail("public charging must not read a keyring")
    app.vault._store = Unavailable()
    monkeypatch.setattr(charging, "ChargingClient", lambda: pytest.fail("local cache query must not use HTTP"))
    overview = app.charging_overview(refresh=False)
    assert overview["counts"] is None and len(overview["items"]) == 2
    capability = next(s for s in app.status()["sources"] if s["source"] == "charging")
    assert capability["auth"]["status"] == "not_required" and not capability["login_available"]
    assert capability["access"] == "third_party_public"
    with pytest.raises(AppError) as error:
        app.refresh("charging")
    assert error.value.code == "query_required"
    monkeypatch.setattr("stu_mcp.cli.App", lambda: app)
    assert main(["charging", "overview", "合成书院", "--local"]) == 1
    assert json.loads(capsys.readouterr().out)["total_count"] == 1
    assert main(["charging", "device", FIRST.code, "--local"]) == 1
    assert json.loads(capsys.readouterr().out)["device"]["device_code"] == FIRST.code


@pytest.mark.parametrize("kwargs", [{"limit": 5}, {"limit": True}, {"offset": -1},
                                    {"location": "bad\nlocation"}, {"refresh": "yes"}])
def test_invalid_queries_do_not_construct_http(app, monkeypatch, kwargs):
    monkeypatch.setattr(charging, "ChargingClient", lambda: pytest.fail("invalid queries must not use HTTP"))
    with pytest.raises(AppError):
        app.charging_overview(**kwargs)


def test_unknown_devices_and_non_read_api_paths_are_rejected(app):
    with pytest.raises(AppError) as error:
        app.charging_device("https://evil.example/?code=" + FIRST.code)
    assert error.value.code == "unknown_device"
    with ChargingClient(transport=httpx.MockTransport(lambda _: pytest.fail("not a reviewed path"))) as client:
        with pytest.raises(AppError):
            client.query("GET", "charge/mobile/bindCard", {})
        with pytest.raises(AppError):
            client._read("/", method="POST")
