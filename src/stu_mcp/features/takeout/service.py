"""Bounded catalog tools with allowlisted output and a nontransactional meal selection."""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps

from ...runtime import AppError
from .catalog import areas, category, numeric, price, product, shop, shop_rows, text
from .client import SOURCE, TakeoutClient
from .configuration import load_config
from .schedule import MEALS, business_now, delivery_schedule, meal_names, requested_date, slot_meal


def consistent_read(method):
    """Fence a whole business read, including cache hits and nested service calls."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._operation():
            return method(self, *args, **kwargs)
    return wrapped


class TakeoutService:
    TTL = 30

    def __init__(self, vault, *, client_factory=TakeoutClient, clock=time.time):
        self.vault, self.client_factory, self.clock = vault, client_factory, clock
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self._local = threading.local()

    def _check_revision(self, revision):
        if revision != self.vault.fingerprint(SOURCE):
            raise AppError("session_changed", "外卖配置在读取期间改变，已丢弃此次结果。", SOURCE)

    @contextmanager
    def _operation(self):
        existing = getattr(self._local, "scope", None)
        if existing is not None:
            self._check_revision(existing[0])
            yield
            self._check_revision(existing[0])
            return
        revision = self.vault.fingerprint(SOURCE)
        config = load_config(self.vault)
        self._check_revision(revision)
        self._local.scope = revision, config
        try:
            yield
            self._check_revision(revision)
        finally:
            self._local.scope = None

    def status(self) -> dict:
        configured = self.vault.fingerprint(SOURCE) is not None
        return {"source": SOURCE, "provider": "STU外卖+ · 维订第三方平台", "official": False,
                "configured": configured, "verified_live": False, "requires_wechat_running": False,
                "catalog_reads_supported": True, "selection_supported": True,
                "meal_filters_supported": True, "delivery_slots_supported": True,
                "meal_shop_scan_supported": True,
                "ordering_supported": False, "payment_supported": False,
                "configuration_on": "mcp_host_cli", "credential_storage": "vault",
                "status": "configuration_saved" if configured else "not_configured"}

    def _read(self, operation: str, arguments: tuple, refresh: bool = False) -> tuple[dict, dict]:
        revision, config = self._local.scope
        self._check_revision(revision)
        key = (operation, arguments, revision)
        with self.lock:
            previous = self.cache.get(key)
            if previous and not refresh and 0 <= self.clock() - previous[0] < self.TTL:
                self._check_revision(revision)
                self.cache.move_to_end(key)
                return copy.deepcopy(previous[1]), {"cached": True, "observed_at": previous[0]}
        with self.client_factory(config) as client:
            data = getattr(client, operation)(*arguments)
        self._check_revision(revision)
        if not isinstance(data, dict):
            raise AppError("schema_changed", "外卖响应结构改变。", SOURCE)
        now = self.clock()
        with self.lock:
            self.cache[key] = now, copy.deepcopy(data)
            self.cache.move_to_end(key)
            if len(self.cache) > 32:
                self.cache.popitem(last=False)
        return data, {"cached": False, "observed_at": now}

    @staticmethod
    def envelope(freshness: dict) -> dict:
        return {"ok": True, "status": "ok", "source": SOURCE, "official": False,
                "provider": "STU外卖+", "content_trust": "untrusted_source_data",
                "checked_at": datetime.fromtimestamp(freshness["observed_at"], UTC).isoformat(),
                "cached": freshness["cached"], "cache_ttl_seconds": TakeoutService.TTL,
                "ordering_supported": False, "payment_supported": False}

    @staticmethod
    def page(items: list, limit: int, offset: int) -> dict:
        return {"items": items[offset:offset + limit], "total_count": len(items), "offset": offset,
                "has_more": offset + limit < len(items), "pagination": "local_slice_of_complete_response"}

    @staticmethod
    def validate_page(query: str, limit: int, offset: int):
        if (not isinstance(query, str) or len(query) > 100 or type(limit) is not int or not 1 <= limit <= 50
                or type(offset) is not int or not 0 <= offset <= 10000):
            raise AppError("invalid_takeout_query", "关键词最多100字，每页1–50项，偏移0–10000。", SOURCE)

    @consistent_read
    def shops(self, query="", category_id="-1", area_id="", limit=20, offset=0, refresh=False,
              meal_period="") -> dict:
        self.validate_page(query, limit, offset)
        category_id, area_id = numeric(category_id, all_categories=True), numeric(area_id, optional=True)
        targets = meal_names(meal_period) if meal_period else ()
        if not isinstance(meal_period, str):
            raise AppError("invalid_takeout_meal", "餐段须为名称。", SOURCE)
        # Resolve the host default explicitly so the result identifies the actual
        # filter. "0" is the observed all-area sentinel, not the host default.
        effective_area = area_id or self._local.scope[1].get("default_area", "")
        area_catalog_count = None
        if targets:
            catalog, _ = self._read("shops", ("", "-1", effective_area), refresh)
            area_catalog_count = len(shop_rows(catalog))
            groups = catalog.get("categoryList")
            if not isinstance(groups, list):
                raise AppError("schema_changed", "外卖商家分类结构改变。", SOURCE)
            matches = [category(row) for row in groups if isinstance(row, dict) and row.get("categoryName") in targets]
            if len(matches) != 1:
                raise AppError("takeout_meal_needs_category", "请明确本部/东校区餐段，或使用当前返回的分类ID。", SOURCE)
            if category_id not in ("-1", matches[0]["category_id"]):
                raise AppError("invalid_takeout_meal", "meal_period与category_id指向不同分类。", SOURCE)
            category_id = matches[0]["category_id"]
        data, stamp = self._read("shops", (query, category_id, effective_area), refresh)
        rows = shop_rows(data)
        categories = data.get("categoryList", [])
        if not isinstance(categories, list):
            raise AppError("schema_changed", "外卖商家分类结构改变。", SOURCE)
        groups = [category(row) for row in categories if isinstance(row, dict)]
        regions = areas(data.get("area", []))
        area_name = next((row["name"] for row in regions if row["area_id"] == effective_area), "")
        return {**self.envelope(stamp), **self.page([shop(row) for row in rows], limit, offset),
                "categories": groups, "meal_categories": [row for row in groups
                    if any(row["name"] in names for names in MEALS.values())],
                "areas": [{"area_id": "0", "name": "全部区域", "parent_area_id": ""}, *regions],
                "filters": {"category_id": category_id, "category_name": next((row["name"] for row in groups
                    if row["category_id"] == category_id), ""), "meal_period": meal_period,
                    "area_id": effective_area, "area_name": "全部区域" if effective_area == "0" else area_name,
                    "area_selection": "explicit" if area_id else "host_default"},
                "list_reported_by_source": "shopList" in data,
                "meal_filter_basis": "provider_category_only" if targets or category_id != "-1" else "none",
                "area_catalog_count": area_catalog_count,
                "empty_reason": "unknown_filter_intersection_or_provider_availability" if not rows else None,
                "availability_note": "平台午餐/晚餐分类未覆盖所有校区。按实际餐段查店用find_takeout_meal_shops逐页核对批次；目录含公告等条目，条数不是已验证商家数。全区域命中不保证可配送到本人地址。",
                "query": query, "search_scope": "provider_shop_and_associated_product_search"}

    def _settings(self, shop_id, refresh):
        settings, stamp = self._read("settings", (shop_id,), refresh)
        if numeric(settings.get("shopId", "")) != shop_id:
            raise AppError("schema_changed", "外卖店铺规则不匹配。", SOURCE)
        return settings, stamp

    @staticmethod
    def _freshness(stamps):
        return {"cached": all(stamp["cached"] for stamp in stamps),
                "observed_at": min(stamp["observed_at"] for stamp in stamps)}

    @consistent_read
    def meal_shops(self, area_id: str, meal_period: str, date="", query="", scan_limit=5,
                   offset=0, include_closed=False, refresh=False) -> dict:
        """Scan one bounded catalog page; a zero page is never an area-wide result."""
        area_id = numeric(area_id)
        meal = slot_meal(meal_period)
        if not meal or meal == "other":
            raise AppError("invalid_takeout_meal", "请明确午餐、晚餐、下午茶、早餐或宵夜。", SOURCE)
        self.validate_page(query, scan_limit, offset)
        if scan_limit > 10 or type(include_closed) is not bool:
            raise AppError("invalid_takeout_query", "每次扫描1–10条目录记录，include_closed须为布尔值。", SOURCE)
        date = requested_date(date, business_now(self.clock())).isoformat()
        data, stamp = self._read("shops", (query, "-1", area_id), refresh)
        rows = shop_rows(data)
        regions = areas(data.get("area", []))
        area_name = next((row["name"] for row in regions if row["area_id"] == area_id), "")
        items, unknown, stamps = [], [], [stamp]
        excluded, failures = 0, 0
        candidates = rows[offset:offset + scan_limit]
        for row in candidates:
            entry = shop(row)
            try:
                settings, rules_stamp = self._settings(entry["shop_id"], refresh)
                stamps.append(rules_stamp)
                schedule = delivery_schedule(settings, self.clock(), date, meal, include_closed=True)
            except AppError as exc:
                if exc.code == "session_changed":
                    raise
                failures += 1
                unknown.append({**entry, "reason": "read_failed", "error_code": exc.code})
                continue
            slots = schedule["items"]
            passing = [slot for slot in slots if slot["passes_time_constraints"] is True]
            uncertain = [slot for slot in slots if slot["passes_time_constraints"] is None]
            selected = [slot for slot in slots if slot["passes_time_constraints"] is not None] if include_closed else passing
            summary = {**entry, "schedule_status": schedule["schedule_status"],
                       "booking_enabled": schedule["booking_enabled"], "evaluated_at": schedule["evaluated_at"],
                       "time_constraint_scope": schedule["time_constraint_scope"],
                       "unknown_slot_count": len(uncertain),
                       "checkout_eligibility_verified": False}
            if selected:
                items.append({**summary, "slots": selected, "passing_slot_count": len(passing)})
            elif (uncertain or schedule["schedule_status"] != "reported"):
                unknown.append({**summary, "reason": "schedule_unknown_or_not_reported", "slots": uncertain})
            else:
                excluded += 1
        next_offset = offset + len(candidates)
        return {**self.envelope(self._freshness(stamps)), "status": "partial" if failures else "ok",
                "area_id": area_id, "area_name": "全部区域" if area_id == "0" else area_name,
                "meal_period": meal, "date": date, "timezone": "Asia/Shanghai", "query": query,
                "meal_filter_basis": "inferred_delivery_slots_not_provider_category", "items": items,
                "matched_in_page": len(items), "unknown_items": unknown, "read_error_count": failures,
                "candidate_total_count": len(rows), "scanned_count": len(candidates), "excluded_count": excluded,
                "offset": offset, "next_offset": next_offset if next_offset < len(rows) else None,
                "has_more": next_offset < len(rows), "include_closed": include_closed,
                "pagination": "area_catalog_scan_not_global_matches",
                "note": "仅检查本页目录条目；零命中不代表整个区域无该餐段。无固定批次可能支持即时配送，单列为未知。目录可能含公告；批次时间通过不证明营业、库存或地址可用。"}

    @consistent_read
    def detail(self, shop_id: str, refresh=False) -> dict:
        shop_id = numeric(shop_id)
        data, stamp = self._read("detail", (shop_id,), refresh)
        value = data.get("shopVo", {}).get("shop") if isinstance(data.get("shopVo"), dict) else None
        if not isinstance(value, dict) or numeric(value.get("id", "")) != shop_id:
            raise AppError("schema_changed", "外卖店铺详情不匹配。", SOURCE)
        settings, rules_stamp = self._settings(shop_id, refresh)
        combined = self._freshness([stamp, rules_stamp])
        rules = {key: text(str(settings.get(key, "")), 100) for key in (
            "isOpenTakeoutOrder", "isOpenTakeoutBook", "openCoupon", "openAddress",
            "takeoutFeeType", "takeoutFeeRecalculateType", "takeoutFeeValue", "isNeedTakeoutFee",
            "needCustomerNameField", "needCustomerAddressField", "needCustomerTelephoneField")}
        rules["minBookPrice"] = price(settings.get("minBookPrice"))
        return {**self.envelope(combined), "shop": {**shop(value), "telephone": text(value.get("telephone"), 80)},
                "delivery_schedule": delivery_schedule(settings, self.clock()),
                "provider_rule_codes": rules, "checkout_quote_verified": False,
                "next_step": "在微信 STU外卖 中打开该店核对营业、配送和结算信息。"}

    @consistent_read
    def delivery_slots(self, shop_id: str, date="", meal_period="", include_closed=True, refresh=False) -> dict:
        shop_id = numeric(shop_id)
        # Validate caller input before any network I/O.
        requested_date(date, business_now(self.clock()))
        slot_meal(meal_period)
        if type(include_closed) is not bool:
            raise AppError("invalid_takeout_query", "include_closed须为布尔值。", SOURCE)
        settings, stamp = self._settings(shop_id, refresh)
        return {**self.envelope(stamp), "shop_id": shop_id,
                **delivery_schedule(settings, self.clock(), date, meal_period, include_closed)}

    @consistent_read
    def product(self, shop_id: str, product_id: str, refresh=False) -> dict:
        shop_id, product_id = numeric(shop_id), numeric(product_id)
        detail, detail_stamp = self._read("product", (shop_id, product_id), refresh)
        values, stamp = self._read("properties", (product_id,), refresh)
        rows = values.get("items")
        if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
                or numeric(rows[0].get("id", "")) != product_id or numeric(rows[0].get("sid", "")) != shop_id
                or numeric(detail.get("shopId", "")) != shop_id):
            raise AppError("schema_changed", "外卖商品详情或所属店铺不匹配。", SOURCE)
        value = rows[0]
        groups = value.get("pts", [])
        if not isinstance(groups, list) or any(not isinstance(group, dict) for group in groups):
            raise AppError("schema_changed", "外卖商品规格结构改变。", SOURCE)
        options = []
        for group in groups:
            choices = group.get("pvs", [])
            if not isinstance(choices, list) or any(not isinstance(choice, dict) for choice in choices):
                raise AppError("schema_changed", "外卖商品选项结构改变。", SOURCE)
            options.append({"group_id": numeric(group.get("pid", "")), "name": text(group.get("pn")),
                "required": group.get("pnn") == "Y", "selection_mode_code": str(group.get("pt", "")),
                "selection_count_code": str(group.get("pc", "")),
                "choices": [{"option_id": numeric(choice.get("vid", "")), "name": text(choice.get("vn")),
                             "price_delta": price(choice.get("vp"))} for choice in choices]})
        combined = self._freshness([stamp, detail_stamp])
        return {**self.envelope(combined), "shop_id": shop_id,
                "product": {**product(product_id, value), "options_unverified": False,
                            "option_groups": options, "packing_fee_name": text(detail.get("feeName"), 100),
                            "packing_fee_amount": price(detail.get("feeAmount")),
                            "provider_display_price": price(detail.get("thisMenuPrice"))},
                "price_note": "规格与加价来自当前平台响应；促销叠加、库存和最终结算价仍需微信确认。"}

    @consistent_read
    def menu(self, shop_id: str, query="", category_id="", limit=30, offset=0, refresh=False) -> dict:
        self.validate_page(query, limit, offset)
        shop_id, category_id = numeric(shop_id), numeric(category_id, optional=True)
        data, stamp = self._read("menu", (shop_id,), refresh)
        groups, group_stamp = self._read("categories", (shop_id,), refresh)
        rows = groups.get("menuCategoryList")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AppError("schema_changed", "外卖菜单分类结构改变。", SOURCE)
        if any(not isinstance(value, dict) or "n" not in value for value in data.values()):
            raise AppError("schema_changed", "外卖菜单结构改变。", SOURCE)
        items = [product(key, value) for key, value in data.items()]
        items = [item for item in items if (not query or query.casefold() in item["name"].casefold())
                 and (not category_id or category_id in item["category_ids"])]
        combined = self._freshness([stamp, group_stamp])
        return {**self.envelope(combined), **self.page(items, limit, offset), "shop_id": shop_id,
                "categories": [category(row) for row in rows], "filter_scope": "local_product_name_and_category",
                "price_note": "base_price为普通标价；促销、规格和最终结算价请在微信核对。"}

    @consistent_read
    def selection(self, shop_id: str, items: list[dict]) -> dict:
        shop_id = numeric(shop_id)
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise AppError("invalid_takeout_selection", "选餐清单需1–10项商品，每项1–9份。", SOURCE)
        requested = {}
        for item in items:
            if not isinstance(item, dict) or set(item) != {"product_id", "quantity"}:
                raise AppError("invalid_takeout_selection", "每项仅填写product_id和quantity。", SOURCE)
            product_id, quantity = numeric(item["product_id"]), item["quantity"]
            if type(quantity) is not int or not 1 <= quantity <= 9 or product_id in requested:
                raise AppError("invalid_takeout_selection", "商品不能重复，每项数量为1–9。", SOURCE)
            requested[product_id] = quantity
        detail = self.detail(shop_id, refresh=True)
        raw, stamp = self._read("menu", (shop_id,), refresh=True)
        selected = []
        for product_id, quantity in requested.items():
            value = raw.get(product_id)
            if not isinstance(value, dict) or "n" not in value:
                raise AppError("takeout_product_unavailable", "所选商品不在该店当前菜单中，请重新查询。", SOURCE)
            current = product(product_id, value)
            subtotal = str(Decimal(current["base_price"]) * quantity) if current["base_price"] else None
            selected.append({**current, "quantity": quantity, "base_subtotal": subtotal})
        total = (str(sum((Decimal(item["base_subtotal"]) for item in selected), Decimal(0)))
                 if all(item["base_subtotal"] is not None for item in selected) else None)
        return {**self.envelope(stamp), "status": "selection_only", "shop": detail["shop"], "items": selected,
                "base_price_total": total, "submitted": False, "order_id": None,
                "amount_scope": "普通标价相加，不含规格调整、优惠、配送费或打包费，不是报价或应付金额。",
                "next_step": "在微信 STU外卖 中选择规格、核对地址与应付金额，再由本人下单支付。"}
