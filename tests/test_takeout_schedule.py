"""Synthetic schedule boundaries and catalog filter semantics; no transactions."""
from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest
from test_takeout import Catalog

from stu_mcp.features.takeout.schedule import business_hours, delivery_schedule
from stu_mcp.runtime import AppError


@pytest.fixture
def takeout(app):
    from stu_mcp.features.takeout.client import BASE
    config = {"server": BASE, "userId": "123", "appletId": "456", "default_area": "700",
              "apiToken": "SYNTHETIC_TAKEOUT_API", "signToken": "SYNTHETIC_TAKEOUT_SIGN",
              "salt": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"}
    app.vault.save("takeout", {"cookies": [], "takeout_config": config})
    app.takeout.client_factory = Catalog
    Catalog.calls = []
    return app.takeout


def epoch(value="2026-10-21T12:00:00+08:00"):
    return datetime.fromisoformat(value).timestamp()


def settings():
    return {"shopId": "10", "isOpenTakeoutBook": "T", "customTakeoutBookDay": "2",
            "customTakeoutBookTime": "15", "cannotOrderWhenOutTimeReserve": "N",
            "shopSalesTime": [{"startSalesTime": 1110.0, "endSalesTime": 2190.0}],
            "customTakeoutOrderBookTimeNew": json.dumps([
                {"time": 690, "time1": 715, "advanceOrderMinutes": "50", "status": "Y"},
                {"time": 1050, "time1": 1075, "advanceOrderMinutes": "50", "status": "Y"},
                {"time": 1280, "time1": 1300, "advanceOrderMinutes": "60", "status": "Y"},
                {"time": 1430, "time1": 20, "advanceOrderMinutes": "0", "status": "N"},
                {"time": 1470, "time1": 1500, "status": "Y"}])}


def test_timezone_dates_cutoff_and_business_hours_are_distinct():
    result = delivery_schedule(settings(), epoch("2026-10-21T15:00:00-05:00"))
    assert result["business_today"] == "2026-10-22"
    assert result["booking_dates"] == ["2026-10-22", "2026-10-23"]
    assert result["utc_offset"] == "+08:00"
    assert result["items"][0]["cutoff_at"] == "2026-10-22T10:40:00+08:00"
    assert result["items"][0]["delivery_start"] == "2026-10-22T11:30:00+08:00"
    assert result["business_hours"]["intervals"][0]["end_day_offset"] == 1
    assert result["business_hours"]["intervals"][0]["end_time"] == "12:30"
    assert result["time_constraint_scope"] == "cutoff_and_booking_window"
    assert result["checkout_eligibility_verified"] is False


@pytest.mark.parametrize(("instant", "status"), [
    ("2026-10-21T20:19:59+08:00", "before_cutoff"),
    ("2026-10-21T20:20:00+08:00", "before_cutoff"),
    ("2026-10-21T20:20:01+08:00", "cutoff_passed")])
def test_cutoff_at_exact_second_and_after(instant, status):
    result = delivery_schedule(settings(), epoch(instant), meal_period="宵夜")
    slot = next(row for row in result["items"] if row["slot_index"] == 2)
    assert slot["time_status"] == status
    assert slot["cutoff_at"] == "2026-10-21T20:20:00+08:00"
    assert slot["advance_order_minutes"] == 60


def test_next_day_slots_and_cross_midnight_end_and_fallback():
    result = delivery_schedule(settings(), epoch(), date="2026-10-22")
    assert all(row["time_status"] == "before_cutoff" for row in result["items"][:3])
    crossing, shifted = result["items"][-2:]
    assert crossing["delivery_end"] == "2026-10-23T00:20:00+08:00"
    assert crossing["end_day_offset"] == 1 and crossing["time_status"] == "disabled"
    assert shifted["delivery_start"] == "2026-10-23T00:30:00+08:00"
    assert shifted["cutoff_at"] == "2026-10-23T00:15:00+08:00"
    assert shifted["cutoff_basis"] == "shop_advance_minutes"
    assert shifted["time_status"] == "outside_booking_window"
    assert shifted["delivery_date_in_booking_window"] is False
    assert shifted["passes_time_constraints"] is False
    result = delivery_schedule(settings(), epoch(), date="2026-10-22", include_closed=False)
    assert result["total_count"] == 3


@pytest.mark.parametrize("end", [None, ""])
def test_single_time_slot_preserves_unknown_end(end):
    data = settings()
    data["customTakeoutOrderBookTimeNew"] = json.dumps([{"time": 1050, "time1": end}])
    result = delivery_schedule(data, epoch())
    row, = result["items"]
    assert result["schedule_status"] == "reported" and result["invalid_slot_count"] == 0
    assert row["delivery_start"] == "2026-10-21T17:30:00+08:00"
    assert row["delivery_end"] is None and row["end_day_offset"] is None
    assert row["cutoff_at"] == "2026-10-21T17:15:00+08:00"
    assert row["time_status"] == "before_cutoff"
    data["customTakeoutOrderBookTimeNew"] = json.dumps([{"time": 1050}])
    assert delivery_schedule(data, epoch())["items"][0] == row


@pytest.mark.parametrize(("start", "end", "normalized_end"), [
    (1430, 20, 1460), (1470, 20, 2900), (1470, 1500, 1500), (2880, 0, 2880)])
def test_interval_end_never_precedes_start(start, end, normalized_end):
    data = settings()
    data["shopSalesTime"] = [{"startSalesTime": start, "endSalesTime": end}]
    interval, = business_hours(data)["intervals"]
    assert interval["end_minute"] == normalized_end >= interval["start_minute"]
    data["customTakeoutOrderBookTimeNew"] = json.dumps([{"time": start, "time1": end}])
    slot, = delivery_schedule(data, epoch())["items"]
    assert datetime.fromisoformat(slot["delivery_end"]) >= datetime.fromisoformat(slot["delivery_start"])
    assert slot["end_day_offset"] == normalized_end // 1440


def test_cross_day_delivery_must_fit_actual_booking_date():
    data = settings()
    data["customTakeoutBookDay"] = "-1"
    data["customTakeoutOrderBookTimeNew"] = json.dumps([{"time": 1470}])
    slot, = delivery_schedule(data, epoch(), date="2026-10-22")["items"]
    assert slot["delivery_date_in_booking_window"] is False
    assert slot["time_status"] == "outside_booking_window"
    data["customTakeoutBookDay"] = "2"
    slot, = delivery_schedule(data, epoch())["items"]
    assert slot["delivery_date_in_booking_window"] is True
    assert slot["time_status"] == "before_cutoff"
    result = delivery_schedule(data, epoch(), date="2026-10-20")
    assert result["date_in_booking_window"] is False
    assert result["items"][0]["time_status"] == "outside_booking_window"


@pytest.mark.parametrize(("day", "row"), [
    ("9999-12-31", {"time": 1470}),
    ("9999-12-31", {"time": 1430, "time1": 20}),
    ("0001-01-01", {"time": 0, "advanceOrderMinutes": 10080})])
def test_extreme_dates_fail_with_friendly_error(day, row):
    data = settings()
    data["customTakeoutOrderBookTimeNew"] = json.dumps([row])
    with pytest.raises(AppError) as error:
        delivery_schedule(data, epoch(), date=day)
    assert error.value.code == "invalid_takeout_date"


def test_horizon_tomorrow_only_zero_and_outside_window():
    value = settings()
    value["customTakeoutBookDay"] = "-1"
    result = delivery_schedule(value, epoch())
    assert result["booking_dates"] == ["2026-10-22"]
    assert result["items"][1]["time_status"] == "outside_booking_window"
    value["customTakeoutBookDay"] = "0"
    assert delivery_schedule(value, epoch())["booking_dates"] == []
    value.pop("customTakeoutBookDay")
    assert len(delivery_schedule(value, epoch())["booking_dates"]) == 7


@pytest.mark.parametrize("field,value", [("customTakeoutBookTime", "invalid"),
    ("customTakeoutBookDay", "999999"), ("isOpenTakeoutBook", "new_mode")])
def test_unknown_constraints_never_claim_time_passed(field, value):
    data = settings()
    data[field] = value
    result = delivery_schedule(data, epoch())
    row = result["items"][-1]
    assert row["time_status"] == "unknown"
    assert row["passes_time_constraints"] is None


def test_booking_disabled_and_legacy_precedence():
    data = settings()
    data["isOpenTakeoutBook"] = "N"
    assert delivery_schedule(data, epoch())["items"][1]["time_status"] == "booking_disabled"
    data["customTakeoutOrderBookTime"] = "11:00-12:00"
    result = delivery_schedule(data, epoch())
    assert result["schedule_status"] == "unsupported_format" and result["items"] == []
    assert delivery_schedule({}, epoch())["schedule_status"] == "not_reported"
    assert business_hours({"shopSalesTime": [{"startSalesTime": "invalid"}]})["status"] == "unknown"


def test_partial_rows_and_private_fields_do_not_escape():
    data = settings()
    rows = json.loads(data["customTakeoutOrderBookTimeNew"])
    rows.extend([{"time": False, "time1": 800}, {"time": 800, "time1": 820, "advanceOrderMinutes": "bad"}])
    rows[0]["customerToken"] = "PRIVATE_MARKER"
    data["customTakeoutOrderBookTimeNew"] = json.dumps(rows)
    result = delivery_schedule(data, epoch())
    assert result["schedule_status"] == "partial" and result["invalid_slot_count"] == 1
    assert next(row for row in result["items"] if row["slot_index"] == 6)["cutoff_at"] is None
    assert "PRIVATE_MARKER" not in json.dumps(result)


def test_schedule_status_recomputed_even_when_raw_rules_are_cached(takeout):
    class Scheduled(Catalog):
        def settings(self, shop_id):
            self.calls.append(("settings", shop_id))
            return settings()
    takeout.client_factory = Scheduled
    takeout.clock = lambda: epoch("2026-10-21T20:19:59+08:00")
    first = takeout.delivery_slots("10", meal_period="宵夜")
    takeout.clock = lambda: epoch("2026-10-21T20:20:01+08:00")
    second = takeout.delivery_slots("10", meal_period="宵夜")
    assert first["items"][0]["time_status"] == "before_cutoff"
    assert second["items"][0]["time_status"] == "cutoff_passed"
    assert second["cached"] and len(Catalog.calls) == 1
    assert first["checked_at"] == second["checked_at"]
    assert first["evaluated_at"] != second["evaluated_at"]


@pytest.mark.parametrize("kwargs", [{"date": "2026-2-1"}, {"date": "2026-02-30"},
    {"meal_period": "unknown"}, {"include_closed": 1}])
def test_invalid_schedule_query_does_not_read(takeout, kwargs):
    with pytest.raises(AppError):
        takeout.delivery_slots("10", **kwargs)
    assert Catalog.calls == []


def test_filter_intersection_known_empty_response_is_not_schema_failure(takeout):
    class Filtered(Catalog):
        def shops(self, query, category, area):
            self.calls.append(("shops", (query, category, area)))
            data = {"template": "one", "showType": "1", "openShopArea": "Y", "showShopWhenOutTime": "",
                "categoryList": [{"id": 1, "categoryName": "午餐"}, {"id": 2, "categoryName": "晚餐"},
                    {"id": 3, "categoryName": "本部宵夜"}, {"id": 4, "categoryName": "东校区宵夜"}],
                "area": [{"id": 700, "areaName": "本部"}, {"id": 800, "areaName": "东校区",
                          "subArea": [{"id": 801, "areaName": "东校区宵夜"}]}]}
            if area == "0":
                data["shopList"] = [{"shopId": "10", "shopName": "合成店", "cacheShopArea": ",800,801,"}]
            return data
    takeout.client_factory = Filtered
    empty = takeout.shops(meal_period="午餐")
    assert empty["total_count"] == 0 and not empty["list_reported_by_source"]
    assert empty["filters"]["category_id"] == "1"
    assert empty["filters"]["area_id"] == "700" and empty["filters"]["area_name"] == "本部"
    assert empty["empty_reason"] == "unknown_filter_intersection_or_provider_availability"
    all_areas = takeout.shops(meal_period="dinner", area_id="0")
    assert all_areas["items"][0]["delivery_area_ids"] == ["800", "801"]
    assert all_areas["filters"]["area_id"] == "0" and all_areas["filters"]["category_id"] == "2"
    assert all_areas["areas"][-1]["parent_area_id"] == "800"
    with pytest.raises(AppError, match="本部/东校区"):
        takeout.shops(meal_period="宵夜")
    with pytest.raises(AppError, match="不同分类"):
        takeout.shops(meal_period="午餐", category_id="2")


@pytest.mark.parametrize("response", [{}, {"shopList": None}, {"shopList": {}},
    {"template": "one", "categoryList": [], "area": []}])
def test_unknown_or_malformed_envelope_is_not_treated_as_empty(takeout, response):
    class Broken(Catalog):
        def shops(self, *_):
            return copy.deepcopy(response)
    takeout.client_factory = Broken
    with pytest.raises(AppError) as error:
        takeout.shops()
    assert error.value.code == "schema_changed"
