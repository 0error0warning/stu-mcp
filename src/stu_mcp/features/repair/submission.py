"""School-specific single-POST transport; only an approved service command arms it."""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from urllib.parse import parse_qs

from .parser import normalize_body
from .receipt import ReceiptVerifier
from .schema import BUSINESS_FIELDS, POSTBACK_FIELDS, REPAIR_FORM


@dataclass
class SubmissionGate:
    """One POST matching the reviewed business payload, armed only by the worker."""
    approved_body: dict | None = None
    sent: bool = False
    cancelled: Callable[[], bool] = lambda: False
    verifier: ReceiptVerifier = field(default_factory=ReceiptVerifier)

    def allows(self, url: str, method: str, post_data: str | None) -> bool:
        if (self.approved_body is None or self.sent or self.cancelled() or url != REPAIR_FORM or
                method != "POST" or not post_data):
            return False
        if len(post_data) > 262144:
            return False
        try:
            data = parse_qs(post_data, keep_blank_values=True, max_num_fields=64)
        except ValueError:
            return False
        if (set(data) - POSTBACK_FIELDS or data.get("__EVENTTARGET") != ["btn_OK"] or
                data.get("__EVENTARGUMENT", [""]) != [""]):
            return False
        body = normalize_body({k: v for k, v in data.items() if k in BUSINESS_FIELDS})
        if body != self.approved_body:
            return False
        self.sent = True  # Consume before network IO; no retry on uncertain outcomes.
        return True

def forward_submission(route) -> None:
    """Send the approved request once; never let redirects replay its POST body.

    Playwright keeps authentication inside its own request/cookie context. Do not
    read headers, hidden fields or response bodies into the MCP application.
    """
    try:
        response = route.fetch(max_redirects=0, max_retries=0, timeout=10000)
        response.dispose()
        # All outcomes are subsequently verified through fixed, read-only URLs.
        # In particular, do not expose a 307/308 that can replay the user's POST.
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body="<p>报修请求已尝试发送，正在核对学校单据。</p>")
    except Exception:
        with suppress(Exception):
            route.abort()

def submit_reviewed_form(page, gate: SubmissionGate, capture: dict) -> dict:
    """The sole call site that clicks btn_OK, after manager confirmation checks."""
    if gate.sent:
        return check_submission_result(page, gate)
    if gate.verifier.known_orders is None:
        return {"status": "submission_not_sent", "request_sent": False, "submitted_by_mcp": False,
                "message": "缺少提交前本人列表核对，请重新生成预览并确认；当前未提交。"}
    gate.approved_body, gate.sent = capture["body"], False
    gate.verifier.capture = deepcopy(capture)
    started = time.monotonic()
    def on_dialog(dialog):
        # Never automatically accept an unexpected confirmation/terms dialog.
        with suppress(Exception):
            dialog.dismiss()
    page.on("dialog", on_dialog)
    try:
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=10000):
                page.locator("#btn_OK").click(timeout=5000)
        except Exception:
            pass  # The request may have reached school even if the browser times out.
        if not gate.sent:
            return {"status": "submission_not_sent", "request_sent": False, "submitted_by_mcp": False,
                    "message": "未发出正式提交请求；可能需要检查学校页面提示，请重新预览后确认。"}
        result = check_submission_result(page, gate, timeout=max(.001, min(10, 20 - (time.monotonic() - started))))
        result["submission_elapsed_ms"] = round((time.monotonic() - started) * 1000)
        return result
    finally:
        gate.approved_body = None
        with suppress(Exception):
            page.remove_listener("dialog", on_dialog)

def check_submission_result(page, gate: SubmissionGate, *, timeout: float = 10) -> dict:
    """Read only. An unavailable refresh never erases a previously verified order."""
    started = time.monotonic()
    previously_verified = gate.verifier.receipt is not None
    receipt = gate.verifier.verify(page, timeout=timeout)
    timing = {"verification_elapsed_ms": round((time.monotonic() - started) * 1000)}
    if receipt or gate.verifier.receipt:
        return {"status": "submitted", "request_sent": True, "submitted_by_mcp": True,
                "receipt": deepcopy(receipt or gate.verifier.receipt), "receipt_fresh": bool(receipt),
                "verification_issue": None if receipt else gate.verifier.last_check, **timing,
                "message": ("已核对学校单号及当前处理状态。" if previously_verified else
                            "已核对学校单号、表单内容和处理状态。") if receipt else
                "此单此前已核对成功，本次未能刷新；请查看回执中的上次核对时间，不要重复提交。"}
    return {"status": "submission_unknown", "request_sent": True, "submitted_by_mcp": False,
            "receipt_fresh": False, "verification_issue": gate.verifier.last_check, **timing,
            "message": "已发送一次请求，尚未找到唯一且内容一致的学校单据；可用check_repair_submission只查结果，禁止重发。"}
