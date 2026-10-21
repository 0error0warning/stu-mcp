"""Bounded read-only school receipt acquisition; parsing lives in parser.py."""
from __future__ import annotations

import time
from contextlib import suppress

from ...runtime import AppError
from .parser import clean, list_rows, match_detail, on_page, refresh_detail, school_time
from .schema import DETAIL_SCRIPT, LIST_SCRIPT, LIST_URL


def read_list(page, *, timeout: int) -> list[dict]:
    raw = page.locator("body").evaluate(LIST_SCRIPT, timeout=timeout)
    if raw.get("problem") == "login_required":
        raise AppError("repair_login_required", "学校登录已失效，请在报修窗口重新登录。", "repair")
    if raw.get("problem") == "source_error":
        raise AppError("repair_source_error", "学校报修列表返回服务器错误，请稍后再试。", "repair")
    try:
        return list_rows(raw)
    except (ValueError, KeyError, TypeError):
        raise AppError("schema_changed", "学校报修列表结构变化或筛选条件不明确，停止核对。", "repair") from None


class ReceiptVerifier:
    """Only retained in the browser owner thread; all network operations are GET."""
    def __init__(self):
        self.known_orders: frozenset[str] | None = None
        self.capture: dict | None = None
        self.receipt: dict | None = None
        self.result_page = None
        self.last_check = "not_checked"

    def prepare(self, page) -> None:
        # The filled form remains untouched. A fresh list view has no search filters.
        self.known_orders = None
        tab = page.context.new_page()
        try:
            tab.goto(LIST_URL, wait_until="domcontentloaded", timeout=5000)
            if not on_page(tab.url, "/student.aspx"):
                raise ValueError("login required")
            rows = read_list(tab, timeout=3000)
            self.known_orders = frozenset(r["order_id"] for r in rows)
        except AppError:
            raise
        except Exception:
            raise AppError("repair_list_unavailable", "未能读取本人报修列表，暂不生成提交确认；请检查直连和学校登录。", "repair") from None
        finally:
            with suppress(Exception):
                tab.close()

    def verify(self, page, *, timeout: float = 10) -> dict | None:
        if self.capture is None or self.known_orders is None:
            self.last_check = "baseline_missing"
            return None
        deadline = time.monotonic() + timeout

        def remaining():
            return max(1, int((deadline - time.monotonic()) * 1000))

        try:
            # A failed POST can still be replacing its page with a network error.
            # Read in an owned tab so recovery cannot race/cancel that navigation.
            if self.result_page is None or self.result_page.is_closed():
                self.result_page = page.context.new_page()
            target = self.result_page
            if self.receipt:
                row = self.receipt
            else:
                source = page
                if not on_page(page.url, "/student.aspx"):
                    self.last_check = "list_navigation"
                    target.goto(LIST_URL, wait_until="domcontentloaded", timeout=remaining())
                    source = target
                if not on_page(source.url, "/student.aspx"):
                    self.last_check = "login_required"
                    return None
                self.last_check = "list_read"
                rows = read_list(source, timeout=remaining())
                values = {f["key"]: f["value"] for f in self.capture["fields"]}
                timestamp = school_time(values.get("tb_happentime", ""))
                if not timestamp:
                    self.last_check = "form_timestamp_missing"
                    return None
                candidates = [r for r in rows if r["order_id"] not in self.known_orders and
                              r["order_id"].startswith(timestamp.strftime("%Y%m%d")) and
                              school_time(r["time"]) == timestamp and
                              clean(values.get("tb_title", "")).startswith(r["title"].removesuffix("...").removesuffix("…"))]
                if len(candidates) != 1:
                    self.last_check = "no_unique_new_order"
                    return None
                row = candidates[0]
            if time.monotonic() >= deadline:
                self.last_check = "deadline_exceeded"
                return None
            self.last_check = "detail_navigation"
            target.goto(row["detail_url"], wait_until="domcontentloaded", timeout=remaining())
            if target.url != row["detail_url"]:
                self.last_check = "detail_redirected"
                return None
            self.last_check = "detail_read"
            raw = target.locator("body").evaluate(DETAIL_SCRIPT, timeout=remaining())
            if raw.get("problem"):
                self.last_check = raw["problem"]
                return None
            receipt = refresh_detail(raw, self.receipt) if self.receipt else match_detail(raw, self.capture, row)
            if receipt:
                self.receipt = receipt
            self.last_check = "verified" if receipt else "detail_mismatch"
            return receipt
        except AppError as exc:
            self.last_check = exc.code
            return None
        except Exception:
            self.last_check += "_unavailable"
            return None  # Raw personal pages, errors and login URLs are never returned.
