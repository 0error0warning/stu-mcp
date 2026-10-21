"""Read-only delivery calendar, based on observed v21 checkout display rules.

This computes time constraints, never checkout eligibility or an order payload.
China campus times use fixed UTC+08, independent of the host's timezone database.
"""
from __future__ import annotations

import json
import re
from datetime import date as Date
from datetime import datetime, timedelta, timezone

from ...runtime import AppError
from .client import SOURCE

CHINA = timezone(timedelta(hours=8), name="Asia/Shanghai")
MEALS = {
    "午餐": ("午餐",), "lunch": ("午餐",), "晚餐": ("晚餐",), "dinner": ("晚餐",),
    "下午茶": ("下午茶",), "afternoon_tea": ("下午茶",),
    "本部夜宵": ("本部宵夜",), "本部宵夜": ("本部宵夜",), "base_late_night": ("本部宵夜",),
    "东校区夜宵": ("东校区宵夜",), "东校区宵夜": ("东校区宵夜",),
    "east_late_night": ("东校区宵夜",), "即点即送": ("即点即送",), "immediate": ("即点即送",),
    "宵夜": ("本部宵夜", "东校区宵夜"), "夜宵": ("本部宵夜", "东校区宵夜"),
    "late_night": ("本部宵夜", "东校区宵夜"),
}


def meal_names(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or value not in MEALS:
        raise AppError("invalid_takeout_meal", "餐段使用午餐、晚餐、下午茶、即点即送、本部宵夜或东校区宵夜。", SOURCE)
    return MEALS[value]


def bounded_int(value, low=0, high=2880) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str) and not re.fullmatch(r"-?[0-9]{1,6}", value):
        return None
    try:
        number = int(value)
        return number if number == float(value) and low <= number <= high else None
    except (ValueError, OverflowError):
        return None


def business_now(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, CHINA)


def requested_date(value: str, now: datetime) -> Date:
    try:
        if value == "":
            return now.date()
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        return Date.fromisoformat(value)
    except ValueError:
        raise AppError("invalid_takeout_date", "日期请使用北京时间 YYYY-MM-DD；留空表示北京时间今天。", SOURCE) from None


def period(start: int) -> str:
    minute = start % 1440
    if minute < 300 or minute >= 1200:
        return "late_night"
    if minute < 600:
        return "breakfast"
    if minute < 840:
        return "lunch"
    return "afternoon_tea" if minute < 1020 else "dinner"


def slot_meal(value: str) -> str:
    if not isinstance(value, str):
        raise AppError("invalid_takeout_meal", "餐段须为名称。", SOURCE)
    aliases = {"午餐": "lunch", "晚餐": "dinner", "下午茶": "afternoon_tea", "早餐": "breakfast",
               "宵夜": "late_night", "夜宵": "late_night"}
    value = aliases.get(value, value)
    if value not in ("", "lunch", "dinner", "afternoon_tea", "breakfast", "late_night", "other"):
        raise AppError("invalid_takeout_meal", "批次餐段使用午餐、晚餐、下午茶、早餐或宵夜。", SOURCE)
    return value


def _end_minute(start: int, end: int) -> int:
    """Roll a clock-style end forward, also accepting already expanded minutes."""
    return end + max(0, (start - end + 1439) // 1440) * 1440


def business_hours(settings: dict) -> dict:
    rows = settings.get("shopSalesTime")
    if not isinstance(rows, list) or len(rows) > 100:
        return {"status": "unknown", "intervals": []}
    intervals = []
    for row in rows:
        if not isinstance(row, dict):
            return {"status": "unknown", "intervals": []}
        start, end = bounded_int(row.get("startSalesTime")), bounded_int(row.get("endSalesTime"))
        if start is None or end is None:
            return {"status": "unknown", "intervals": []}
        end = _end_minute(start, end)
        intervals.append({"start_minute": start, "end_minute": end,
                          "start_time": f"{start % 1440 // 60:02}:{start % 60:02}",
                          "end_time": f"{end % 1440 // 60:02}:{end % 60:02}",
                          "start_day_offset": start // 1440, "end_day_offset": end // 1440})
    return {"status": "reported" if intervals else "unknown", "intervals": intervals,
            "scope": "provider_recurring_business_hours_not_delivery_slots_or_live_open_status"}


def delivery_schedule(settings: dict, timestamp: float, date="", meal_period="", include_closed=True) -> dict:
    now = business_now(timestamp)
    selected = requested_date(date, now)
    meal = slot_meal(meal_period)
    if type(include_closed) is not bool:
        raise AppError("invalid_takeout_query", "include_closed须为布尔值。", SOURCE)
    horizon_raw = settings.get("customTakeoutBookDay", "")
    horizon = 7 if horizon_raw in (None, "") else bounded_int(horizon_raw, -1, 31)
    days = ([now.date() + timedelta(days=1)] if horizon == -1 else
            [now.date() + timedelta(days=i) for i in range(horizon)] if horizon is not None else [])
    mode = settings.get("isOpenTakeoutBook")
    booking_enabled = True if mode in ("Y", "S", "T") else False if mode == "N" else None
    result = {"timezone": "Asia/Shanghai", "utc_offset": "+08:00", "evaluated_at": now.isoformat(),
              "business_today": now.date().isoformat(), "date": selected.isoformat(),
              "booking_enabled": booking_enabled, "booking_mode_code": mode if isinstance(mode, str) else "",
              "booking_day_count_code": str(horizon_raw)[:100] if isinstance(horizon_raw, (str, int, float)) else "",
              "booking_dates": [day.isoformat() for day in days], "date_in_booking_window":
                  selected in days if horizon is not None else None,
              "business_hours": business_hours(settings), "meal_period_filter": meal,
              "provider_rule_codes": {key: settings.get(key, "")[:100] if isinstance(settings.get(key, ""), str) else ""
                  for key in ("isOpenTakeoutOrder", "cannotOrderWhenOutTime", "cannotOrderWhenOutTimeReserve")},
              "meal_period_basis": "inferred_from_delivery_start_not_provider_meal_category",
              "meal_period_bands": {"breakfast": "05:00–10:00", "lunch": "10:00–14:00",
                  "afternoon_tea": "14:00–17:00", "dinner": "17:00–20:00", "late_night": "20:00–次日05:00"},
              "time_constraint_scope": "cutoff_and_booking_window",
              "checkout_eligibility_verified": False, "items": [],
              "note": "仅核算平台批次时间约束；餐段按配送开始时间推断。营业、库存、地址和最终可下单性仍需微信核对。"}
    # Legacy field has precedence in the observed UI. Do not silently replace it
    # with the newer field or guess an unverified comma-separated time format.
    raw = settings.get("customTakeoutOrderBookTime") or settings.get("customTakeoutOrderBookTimeNew")
    if not raw:
        return {**result, "schedule_status": "not_reported", "total_count": 0}
    if not isinstance(raw, str) or len(raw) > 128_000:
        return {**result, "schedule_status": "unsupported_format", "total_count": 0}
    try:
        rows = json.loads(raw)
    except (ValueError, TypeError):
        return {**result, "schedule_status": "unsupported_format", "total_count": 0}
    if not isinstance(rows, list) or len(rows) > 200 or any(not isinstance(row, dict) for row in rows):
        return {**result, "schedule_status": "unsupported_format", "total_count": 0}
    if not rows:
        return {**result, "schedule_status": "not_reported", "total_count": 0}
    fallback_raw = settings.get("customTakeoutBookTime", "")
    fallback = 0 if fallback_raw in (None, "") else bounded_int(fallback_raw, 0, 10080)
    midnight = datetime.combine(selected, datetime.min.time(), CHINA)
    items, invalid = [], 0
    for index, row in enumerate(rows):
        start = bounded_int(row.get("time"))
        end_raw = row.get("time1")
        end = None if end_raw in (None, "") else bounded_int(end_raw)
        advance_raw = row.get("advanceOrderMinutes", "")
        advance = 0 if advance_raw in (None, "") else bounded_int(advance_raw, 0, 10080)
        if start is None or (end is None and end_raw not in (None, "")):
            invalid += 1
            continue
        if end is not None:
            end = _end_minute(start, end)
        lead = fallback if advance == 0 else advance
        try:
            start_at = midnight + timedelta(minutes=start)
            end_at = midnight + timedelta(minutes=end) if end is not None else None
            cutoff = start_at - timedelta(minutes=lead) if lead is not None else None
        except OverflowError:
            raise AppError("invalid_takeout_date", "日期超出可计算的配送时间范围，请选择临近的北京时间日期。", SOURCE) from None
        delivery_in_window = start_at.date() in days if horizon is not None else None
        enabled = row.get("status") != "N"  # observed UI removes only explicitly disabled rows
        if not enabled:
            status = "disabled"
        elif booking_enabled is False:
            status = "booking_disabled"
        elif horizon is not None and (selected not in days or not delivery_in_window):
            status = "outside_booking_window"
        elif cutoff is not None and now > cutoff:
            status = "cutoff_passed"
        elif cutoff is None or horizon is None or booking_enabled is None:
            status = "unknown"
        else:
            status = "before_cutoff"
        item = {"slot_index": index, "delivery_start": start_at.isoformat(),
                "delivery_end": end_at.isoformat() if end_at else None,
                "start_day_offset": start // 1440, "end_day_offset": end // 1440 if end is not None else None,
                "delivery_date_in_booking_window": delivery_in_window,
                "advance_order_minutes": lead, "cutoff_at": cutoff.isoformat() if cutoff else None,
                "cutoff_basis": ("unrecognized_advance_minutes" if lead is None else
                                 "slot_advance_minutes" if advance != 0 else "shop_advance_minutes"),
                "seconds_until_cutoff": int((cutoff - now).total_seconds()) if cutoff else None,
                "enabled_by_source": enabled, "time_status": status,
                "passes_time_constraints": status == "before_cutoff" if status != "unknown" else None,
                "meal_period_inferred": period(start),
                "provider_prefix": row.get("frontText", "")[:100] if isinstance(row.get("frontText", ""), str) else "",
                "provider_suffix": row.get("afterText", "")[:100] if isinstance(row.get("afterText", ""), str) else ""}
        if (not meal or meal == item["meal_period_inferred"]) and (include_closed or status in ("before_cutoff", "unknown")):
            items.append(item)
    items.sort(key=lambda item: (item["delivery_start"], item["slot_index"]))
    return {**result, "schedule_status": "partial" if invalid else "reported", "invalid_slot_count": invalid,
            "items": items, "total_count": len(items), "include_closed": include_closed}
