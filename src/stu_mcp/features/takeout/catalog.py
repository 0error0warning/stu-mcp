"""Allowlisted normalization of untrusted provider catalog fields."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ...runtime import AppError
from .client import SOURCE


def numeric(value, *, all_categories=False, optional=False) -> str:
    # This platform sometimes serializes integral IDs as JSON doubles.
    if isinstance(value, float) and value.is_integer() and 0 <= value < 2 ** 53:
        value = int(value)
    text = str(value)
    if (optional and text == "") or (all_categories and text == "-1"):
        return text
    if not re.fullmatch(r"[0-9]{1,20}", text):
        raise AppError("invalid_takeout_id", "请使用外卖查询返回的数字 ID。", SOURCE)
    return text


def price(value) -> str | None:
    try:
        parsed = Decimal(str(value))
        return str(parsed) if parsed.is_finite() and 0 <= parsed <= 1_000_000 else None
    except InvalidOperation:
        return None


def text(value, limit=500) -> str:
    return value[:limit] if isinstance(value, str) else ""


def shop(value: dict) -> dict:
    return {"shop_id": numeric(value.get("shopId", value.get("id", ""))),
            "name": text(value.get("shopName")), "address": text(value.get("address")),
            "min_order_price": price(value.get("cacheMinBookMoney", value.get("minBookPrice"))),
            "rating": price(value.get("cacheShopStar")), "delivery_name": text(value.get("deliveryName")),
            "delivery_fee": price(value.get("takeoutFeeFinalValue")),
            "merchant_notice": text(value.get("summary"), 1000),
            "entry_type": "unverified_provider_catalog_entry",
            "delivery_area_ids": [part for part in text(value.get("cacheShopArea"), 2000).split(",")
                                  if re.fullmatch(r"[0-9]{1,20}", part)][:100],
            "sales_time_status": text(str(value.get("salesTimeStatus", "unknown")), 30)}


def category(value: dict) -> dict:
    return {"category_id": numeric(value.get("id", "")), "name": text(value.get("categoryName"), 100)}


def areas(rows, parent="", depth=0) -> list[dict]:
    if not isinstance(rows, list) or len(rows) > 300 or depth > 3:
        raise AppError("schema_changed", "外卖配送区域结构改变。", SOURCE)
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise AppError("schema_changed", "外卖配送区域结构改变。", SOURCE)
        identifier = numeric(row.get("id", ""))
        result.append({"area_id": identifier, "name": text(row.get("areaName"), 100), "parent_area_id": parent})
        result.extend(areas(row.get("subArea", []), identifier, depth + 1))
    return result


def shop_rows(data: dict) -> list[dict]:
    # The v21 UI initializes shopList=[] when this full list envelope omits it.
    # An arbitrary or malformed response must still fail instead of looking empty.
    if "shopList" not in data and (isinstance(data.get("categoryList"), list)
            and isinstance(data.get("area"), list) and isinstance(data.get("template"), (str, int))
            and all(key in data for key in ("showType", "openShopArea", "showShopWhenOutTime"))):
        return []
    rows = data.get("shopList")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise AppError("schema_changed", "外卖商家列表结构改变。", SOURCE)
    return rows


def product(key: str, value: dict) -> dict:
    ids = value.get("c", [])
    if not isinstance(ids, list):
        raise AppError("schema_changed", "外卖商品分类结构改变。", SOURCE)
    return {"product_id": numeric(value.get("id", key)), "name": text(value.get("n")),
            "base_price": price(value.get("p")), "unit": text(value.get("u"), 30),
            "category_ids": [numeric(item) for item in ids[:100]],
            "promotion_present": any(key.startswith("dp") for key in value),
            "options_unverified": True, "checkout_price_verified": False}
