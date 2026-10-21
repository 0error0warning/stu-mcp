"""Human terminal drill of the same HTTP draft/review/single-submit service."""
from __future__ import annotations

import json
import time

from ...runtime import AppError
from ...terminal import require_terminal
from . import RepairDrafts
from .models import ACTIVE


def run_cli(vault, *, fields: dict, submit: bool = False, output=None) -> dict:
    """No credentials in fields; submission requires displayed review + real TTY."""
    if submit:
        require_terminal()
    output = output or (lambda data: print(json.dumps(data, ensure_ascii=False), flush=True))
    drafts = RepairDrafts(vault=vault)
    try:
        result = drafts.prepare(**fields)
        if result["problems"]:
            output(result)
            return result
        draft_id = result["draft_id"]
        drafts.open(draft_id)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = drafts.snapshot(draft_id)
            if result["status"] == "filled_unsubmitted":
                break
            if result["status"] not in ACTIVE or result["status"] in {"form_changed", "needs_manual_fields"}:
                output(result)
                return result
            time.sleep(.05)
        else:
            raise AppError("repair_command_timeout", "报修填写等待已到时，未发送正式提交。", "repair")
        review = drafts.review(draft_id)
        output(review)  # Always the complete actual server-derived preview.
        if not submit or not review.get("review_id"):
            return review
        require_terminal()
        try:
            answer = input("核对以上完整表单后，输入“确认提交”才会发送一次报修；其他输入取消：")
        except (EOFError, KeyboardInterrupt):
            raise AppError("operation_cancelled", "已取消报修提交。", "repair") from None
        if answer.strip() != "确认提交":
            raise AppError("operation_cancelled", "未确认，已取消报修提交。", "repair")
        result = drafts.submit(draft_id, review["review_id"], confirmed=True)
        output(result)
        return result
    finally:
        drafts.shutdown()
