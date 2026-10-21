"""Bounded meal scans and whole-operation credential generation fences."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from test_takeout import Catalog

from stu_mcp.features.takeout.client import BASE
from stu_mcp.runtime import AppError


@pytest.fixture
def takeout(app):
    config = {"server": BASE, "userId": "123", "appletId": "456", "default_area": "700",
              "apiToken": "SYNTHETIC_TAKEOUT_API", "signToken": "SYNTHETIC_TAKEOUT_SIGN",
              "salt": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"}
    app.vault.save("takeout", {"cookies": [], "takeout_config": config})
    app.takeout.client_factory = Catalog
    app.takeout.clock = lambda: datetime.fromisoformat("2026-10-21T10:00:00+08:00").timestamp()
    Catalog.calls = []
    return app.takeout


class Meals(Catalog):
    def shops(self, *args):
        self.calls.append(("shops", args))
        return {"shopList": [{"shopId": str(n), "shopName": f"合成店{n}"} for n in range(10, 15)],
                "categoryList": [], "area": [{"id": 700, "areaName": "合成区域"}]}

    def settings(self, shop_id):
        self.calls.append(("settings", shop_id))
        if shop_id == "13":
            raise AppError("source_rejected", "单店读取被拒绝。", "takeout")
        slots = {"10": [{"time": 690, "time1": 715, "advanceOrderMinutes": "50"}],
                 "11": [{"time": 1080, "time1": 1100}],
                 "12": [], "14": [{"time": 610, "advanceOrderMinutes": "60"}]}[shop_id]
        return {"shopId": shop_id, "isOpenTakeoutBook": "T", "customTakeoutBookDay": "2",
                "customTakeoutOrderBookTimeNew": json.dumps(slots)}


def test_meal_scan_uses_actual_batches_and_catalog_offsets_not_global_match_count(takeout):
    takeout.client_factory = Meals
    first = takeout.meal_shops("700", "午餐", scan_limit=2)
    assert first["candidate_total_count"] == 5 and first["scanned_count"] == 2
    assert first["matched_in_page"] == 1 and first["excluded_count"] == 1
    assert first["items"][0]["shop_id"] == "10"
    assert first["items"][0]["slots"][0]["cutoff_at"] == "2026-10-21T10:40:00+08:00"
    assert first["items"][0]["time_constraint_scope"] == "cutoff_and_booking_window"
    assert first["next_offset"] == 2 and first["has_more"]
    assert Catalog.calls[0] == ("shops", ("", "-1", "700"))
    assert [name for name, _ in Catalog.calls] == ["shops", "settings", "settings"]
    second = takeout.meal_shops("700", "lunch", offset=2, scan_limit=2)
    assert second["matched_in_page"] == 0 and second["scanned_count"] == 2
    assert second["status"] == "partial" and second["read_error_count"] == 1
    assert [item["shop_id"] for item in second["unknown_items"]] == ["12", "13"]
    assert second["unknown_items"][1]["error_code"] == "source_rejected"
    assert second["next_offset"] == 4 and second["has_more"]
    last = takeout.meal_shops("700", "午餐", offset=4)
    assert last["matched_in_page"] == 0 and last["excluded_count"] == 1
    assert last["next_offset"] is None and not last["has_more"]
    closed = takeout.meal_shops("700", "午餐", offset=4, include_closed=True)
    assert closed["items"][0]["slots"][0]["time_status"] == "cutoff_passed"
    assert closed["items"][0]["passing_slot_count"] == 0
    assert closed["ordering_supported"] is False


@pytest.mark.parametrize("include_closed", [False, True])
def test_unknown_constraints_are_not_presented_as_confirmed_meal_shops(takeout, include_closed):
    class Unknown(Meals):
        def settings(self, shop_id):
            result = super().settings(shop_id)
            result["isOpenTakeoutBook"] = "new-mode"
            return result
    takeout.client_factory = Unknown
    result = takeout.meal_shops("700", "午餐", scan_limit=1, include_closed=include_closed)
    assert result["items"] == []
    assert result["unknown_items"][0]["slots"][0]["passes_time_constraints"] is None


@pytest.mark.parametrize("updates", [{"scan_limit": 0}, {"scan_limit": 11}, {"scan_limit": True},
    {"offset": -1}, {"date": "invalid"}, {"meal_period": ""}, {"meal_period": "other"},
    {"area_id": ""}, {"include_closed": "yes"}])
def test_meal_scan_rejects_unbounded_or_ambiguous_queries_without_http(takeout, updates):
    kwargs = {"area_id": "700", "meal_period": "午餐", **updates}
    with pytest.raises(AppError):
        takeout.meal_shops(**kwargs)
    assert Catalog.calls == []


@pytest.mark.parametrize("operation,trigger", [("detail", "detail"), ("menu", "menu"),
    ("product", "product"), ("selection", "settings"), ("meal_shops", "shops")])
def test_configuration_change_between_reads_discards_entire_result(takeout, app, monkeypatch, operation, trigger):
    takeout.client_factory = Meals if operation == "meal_shops" else Catalog
    original = takeout._read

    def switching(name, *args, **kwargs):
        result = original(name, *args, **kwargs)
        if name == trigger:
            state = app.vault.load("takeout")
            state["takeout_config"]["default_area"] = "800"
            app.vault.save("takeout", state)
        return result
    monkeypatch.setattr(takeout, "_read", switching)
    arguments = {"detail": ("10",), "menu": ("10",), "product": ("10", "100"),
                 "selection": ("10", [{"product_id": "100", "quantity": 1}]),
                 "meal_shops": ("700", "午餐")}
    with pytest.raises(AppError) as error:
        getattr(takeout, operation)(*arguments[operation])
    assert error.value.code == "session_changed"


def test_logout_during_cache_hit_cannot_return_previous_rules(takeout, app):
    takeout.delivery_slots("10")
    original = takeout.clock
    calls = 0

    def logout_on_cache_age():
        nonlocal calls
        calls += 1
        if calls == 2:  # first is query-date validation; second is the cache age
            app.vault.logout("takeout")
        return original()
    takeout.clock = logout_on_cache_age
    with pytest.raises(AppError) as error:
        takeout.delivery_slots("10")
    assert error.value.code == "session_changed"
    assert len(Catalog.calls) == 1


def test_lru_evicts_one_entry_and_keeps_recent_results(takeout):
    for i in range(32):
        takeout.shops(str(i))
    takeout.shops("0")
    takeout.shops("20", refresh=True)
    assert len(takeout.cache) == 32
    takeout.shops("32")
    assert len(takeout.cache) == 32
    assert takeout.shops("0")["cached"]
    assert not takeout.shops("1")["cached"]
