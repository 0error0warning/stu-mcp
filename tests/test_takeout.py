"""Synthetic catalog responses only; never create an order or use a real account."""
from __future__ import annotations

import json
import logging

import pytest

from stu_mcp.features.takeout.client import BASE, CATEGORIES, DETAIL, MENU, SHOPS, TakeoutClient, signed
from stu_mcp.features.takeout.configuration import import_config, validate_config
from stu_mcp.runtime import AppError


@pytest.fixture
def takeout_config():
    return {"server": BASE, "userId": "123", "appletId": "456", "default_area": "700",
            "apiToken": "SYNTHETIC_TAKEOUT_API", "signToken": "SYNTHETIC_TAKEOUT_SIGN",
            "salt": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"}


class Catalog:
    calls = []

    def __init__(self, config):
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def shops(self, *args):
        self.calls.append(("shops", args))
        return {"shopList": [{"shopId": "10", "shopName": "合成店", "cacheMinBookMoney": 12,
                              "apiToken": self.config["apiToken"], "wxShopMenuUrl": "https://invalid/?token=SECRET"},
                             {"shopId": "11", "shopName": "合成茶店"}],
                "categoryList": [{"id": 20, "categoryName": "饮料"}]}

    def detail(self, shop_id):
        self.calls.append(("detail", shop_id))
        return {"shopVo": {"shop": {"id": float(shop_id), "shopName": "合成店", "minBookPrice": 12,
                                    "user": {"customerToken": "SYNTHETIC_PRIVATE"}}}}

    def menu(self, shop_id):
        self.calls.append(("menu", shop_id))
        return {"100": {"id": 100, "n": "合成汉堡", "p": "15.90", "dp1": 10, "c": [20], "u": "份"},
                "101": {"id": 101, "n": "合成茶", "p": "0.10", "c": [21], "u": "杯"}}

    def categories(self, shop_id):
        self.calls.append(("categories", shop_id))
        return {"menuCategoryList": [{"id": 20, "categoryName": "主餐"}, {"id": 21, "categoryName": "饮料"}]}

    def settings(self, shop_id):
        self.calls.append(("settings", shop_id))
        return {"shopId": shop_id, "minBookPrice": 12, "isOpenTakeoutOrder": "Y",
                "customerToken": "SYNTHETIC_PRIVATE"}

    def product(self, shop_id, product_id):
        self.calls.append(("product", (shop_id, product_id)))
        return {"shopId": shop_id, "feeName": "打包费", "feeAmount": 1, "thisMenuPrice": 12}

    def properties(self, product_id):
        self.calls.append(("properties", product_id))
        return {"items": [{"id": product_id, "sid": "10", "n": "合成汉堡", "p": "15.90", "c": [20],
            "pts": [{"pid": 1, "pn": "小吃", "pnn": "Y", "pc": 1, "pt": 0,
                     "pvs": [{"vid": 2, "vn": "薯条", "vp": 0}, {"vid": 3, "vn": "鸡块", "vp": 2}]}]}]}


@pytest.fixture
def takeout(app, takeout_config):
    app.vault.save("takeout", {"cookies": [], "takeout_config": takeout_config})
    app.takeout.client_factory = Catalog
    Catalog.calls = []
    return app.takeout


def test_missing_configuration_is_isolated_and_status_does_not_call_keyring(app, monkeypatch):
    monkeypatch.setattr(app.vault, "load", lambda _: pytest.fail("passive status must not decrypt"))
    assert app.takeout.status()["configured"] is False
    monkeypatch.undo()
    with pytest.raises(AppError, match="宿主") as error:
        app.takeout.shops()
    assert error.value.code == "takeout_not_configured"
    assert app.query("notice", source="public")["total_count"] == 0


def test_config_import_is_encrypted_and_does_not_save_a_plaintext_fallback(app, tmp_path, takeout_config):
    source = tmp_path / "config.json"
    source.write_text(json.dumps(takeout_config), encoding="utf-8")
    source.chmod(0o600)
    result = import_config(app.vault, source)
    stored = app.runtime.session_file("takeout").read_bytes()
    assert result["encrypted"] and result["verified_live"] is False
    for key in ("apiToken", "signToken", "salt"):
        assert takeout_config[key].encode() not in stored
        assert takeout_config[key] not in json.dumps(result)
    assert app.vault.load("takeout")["cookies"] == []


@pytest.mark.parametrize("updates", [
    {"server": "https://evil.invalid"}, {"salt": "short"},
    {"proxy": "http://external.invalid:80"}, {"proxy": "http://user:secret@127.0.0.1:7897"},
    {"proxy": "http://127.0.0.1:7897/?key=secret"}, {"headers": {"Cookie": "secret"}},
    {"headers": {"Referer": "https://evil.invalid/"}},
    {"proxy": 7897}, {"proxy": []}, {"headers": {1: "synthetic"}},
    {"headers": {"User-Agent": "中文"}}, {"headers": {"Accept": " leading-space"}},
    {"headers": {"User-Agent": "synthetic\x00value"}},
])
def test_config_rejects_other_origins_credential_headers_and_proxy_credentials(takeout_config, updates):
    with pytest.raises(AppError):
        validate_config({**takeout_config, **updates})


def test_catalog_pagination_cache_and_allowlisted_output(takeout, takeout_config):
    result = takeout.shops("奶茶", limit=1)
    assert result["total_count"] == 2 and result["has_more"]
    assert result["items"][0]["shop_id"] == "10"
    assert result["categories"][0]["category_id"] == "20"
    assert not result["cached"] and result["ordering_supported"] is False
    again = takeout.shops("奶茶", limit=1, offset=1)
    assert again["cached"] and len(Catalog.calls) == 1
    serialized = json.dumps(result)
    assert takeout_config["apiToken"] not in serialized and "wxShopMenuUrl" not in serialized
    with pytest.raises(AppError):
        takeout.shops(offset=-1)


def test_menu_filters_are_local_and_do_not_claim_checkout_price(takeout):
    result = takeout.menu("10", query="汉堡", category_id="20")
    assert result["total_count"] == 1 and result["items"][0]["base_price"] == "15.90"
    assert result["items"][0]["promotion_present"] is True
    assert result["items"][0]["checkout_price_verified"] is False
    takeout.menu("10", category_id="21")
    assert [name for name, _ in Catalog.calls] == ["menu", "categories"]


def test_selection_is_a_decimal_estimate_and_only_reads_detail_and_menu(takeout):
    result = takeout.selection("10", [{"product_id": "100", "quantity": 2},
                                     {"product_id": "101", "quantity": 3}])
    assert result["base_price_total"] == "32.10"
    assert result["submitted"] is False and result["order_id"] is None
    assert result["status"] == "selection_only" and not result["payment_supported"]
    assert [name for name, _ in Catalog.calls] == ["detail", "settings", "menu"]
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result)


def test_product_option_groups_and_shop_binding(takeout):
    result = takeout.product("10", "100")
    item = result["product"]
    assert item["options_unverified"] is False
    assert item["option_groups"][0]["required"] is True
    assert item["option_groups"][0]["choices"][1]["price_delta"] == "2"
    assert item["packing_fee_amount"] == "1" and not item["checkout_price_verified"]
    with pytest.raises(AppError) as error:
        takeout.product("11", "100")
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("items", [[], [{"product_id": "100", "quantity": True}],
    [{"product_id": "100", "quantity": 10}], [{"product_id": "100", "quantity": 1, "address": "secret"}],
    [{"product_id": "100", "quantity": 1}, {"product_id": "100", "quantity": 1}]])
def test_invalid_selection_does_not_make_requests(takeout, items):
    with pytest.raises(AppError):
        takeout.selection("10", items)
    assert not Catalog.calls


def test_configuration_change_and_logout_invalidate_cached_results(takeout, app):
    takeout.shops()
    app.vault.logout("takeout")
    with pytest.raises(AppError) as error:
        takeout.shops()
    assert error.value.code == "takeout_not_configured"
    assert len(Catalog.calls) == 1


def test_configuration_change_during_read_discards_result(takeout, app):
    class Changing(Catalog):
        def shops(self, *args):
            app.vault.logout("takeout")
            return super().shops(*args)
    takeout.client_factory = Changing
    with pytest.raises(AppError) as error:
        takeout.shops()
    assert error.value.code == "session_changed"
    assert not takeout.cache


def test_unknown_http_operation_is_rejected_and_reads_keep_tls_and_proxy_policy(takeout_config, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="urllib3.connectionpool")
    with pytest.raises(AppError):
        signed("POST", "/applet/wechat/submit/order/api/json.jhtml", {}, takeout_config)
    with TakeoutClient(takeout_config) as client:
        assert client.http.trust_env is False and client.http.verify is True
        assert not client.http.proxies
        calls = []

        def respond(method, url, **kwargs):
            logging.getLogger("urllib3.connectionpool").debug("%s", kwargs["params"]["apiToken"])
            calls.append((method, url, kwargs))
            class Response:
                status_code = 200
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    pass
                def iter_content(self, _):
                    yield b'{"shopList": []}'
            return Response()
        monkeypatch.setattr(client.http, "request", respond)
        assert client.shops("茶", "-1", "")["shopList"] == []
        assert calls[0][0:2] == ("GET", BASE + SHOPS)
        assert calls[0][2]["allow_redirects"] is False
        assert "signature" in calls[0][2]["params"]
        assert takeout_config["apiToken"] not in caplog.text
        logging.getLogger("urllib3.connectionpool").debug("outside-private-context")
        assert "outside-private-context" in caplog.text
    assert {SHOPS, MENU, CATEGORIES, DETAIL}


def test_business_rejection_does_not_invalidate_shared_signing_config(takeout_config, monkeypatch):
    bodies = iter([b'{"ret":1,"msg":"SYNTHETIC_PRIVATE_MESSAGE"}', b'{"shopList":[]}'])
    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def iter_content(self, _):
            yield next(bodies)
    with TakeoutClient(takeout_config) as client:
        monkeypatch.setattr(client.http, "request", lambda *args, **kwargs: Response())
        with pytest.raises(AppError) as error:
            client.settings("10")
        assert error.value.code == "source_rejected"
        assert "SYNTHETIC_PRIVATE_MESSAGE" not in json.dumps(error.value.result())
        assert client.shops("", "-1", "0") == {"shopList": []}


@pytest.mark.parametrize(("body", "expected"), [
    (b" " * (2 * 1024 * 1024 + 1), "response_too_large"),
    (b"[" * 2000 + b"0" + b"]" * 2000, "schema_changed"),
], ids=["oversized-response", "deeply-nested-json"])
def test_http_response_size_and_json_depth_are_bounded(takeout_config, monkeypatch, body, expected):
    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def iter_content(self, chunk_size):
            for offset in range(0, len(body), chunk_size):
                yield body[offset:offset + chunk_size]
    with TakeoutClient(takeout_config) as client:
        monkeypatch.setattr(client.http, "request", lambda *args, **kwargs: Response())
        with pytest.raises(AppError) as error:
            client.shops("", "-1", "0")
        assert error.value.code == expected
