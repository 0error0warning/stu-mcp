"""Explicit, minimal feedback submission; never reads campus records or credentials."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

import httpx

from . import __version__
from .runtime import AppError

DEFAULT_FEEDBACK_URL = "https://stu-mcp.com/api/feedback"
CATEGORIES = {"bug", "data_error", "suggestion"}
_lock = threading.Lock()
_previews: dict[str, tuple[float, str, dict]] = {}


def report_feedback(message: str, tool_name: str = "", category: str = "bug", *,
                    confirmation_id: str = "", user_confirmed: bool = False) -> dict:
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
        raise AppError("invalid_feedback", "反馈描述需为 1–4000 字符。")
    if category not in CATEGORIES or not re.fullmatch(r"[a-zA-Z0-9_]{0,80}", tool_name):
        raise AppError("invalid_feedback", "请使用有效的反馈类别和工具名。")
    # Catch common accidental credential pastes. This is not a complete PII detector.
    if re.search(r"(?i)(?:bearer\s+\S+|(?:password|cookie|token|secret|totp|otp|captcha|verification_code|密码|密钥|私钥|验证码|动态口令)\s*[:=：]\s*\S+|-----BEGIN .*PRIVATE KEY|otpauth://|https?://\S*[?&](?:ticket|access_token|code|state)=\S+)", message):
        raise AppError("sensitive_feedback", "请删除凭据，只提交简短问题描述。")
    endpoint = os.environ.get("STU_MCP_FEEDBACK_URL", DEFAULT_FEEDBACK_URL).strip()
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise AppError("invalid_feedback_url", "反馈接收地址必须为不含凭据和查询参数的 HTTPS 地址。")
    fields = {"message": message.strip(), "tool_name": tool_name,
              "category": category, "client_version": __version__}
    with _lock:
        now = time.monotonic()
        for key, value in list(_previews.items()):
            if value[0] <= now:
                del _previews[key]
        if not confirmation_id:
            if len(_previews) >= 32:
                raise AppError("feedback_preview_busy", "待确认反馈过多，请稍后再试。")
            confirmation_id = str(uuid.uuid4())
            payload = {"report_id": str(uuid.uuid4()), **fields}
            _previews[confirmation_id] = (now + 600, endpoint, payload)
            privacy_notice = (
                "接收方为 STU MCP 维护者；内容用于排查，保存在其私有数据库，未设置自动删除。服务器能看到网络出口IP，反馈表不记录IP。"
                if endpoint == DEFAULT_FEEDBACK_URL else
                "接收方为宿主配置的自定义服务；其身份、用途、存储及删除策略未经本工具核实，请先向操作者核实并告知用户。服务器能看到网络出口IP。"
            )
            return {"status": "needs_user_confirmation", "confirmation_id": confirmation_id,
                    "destination": endpoint, "payload": dict(payload), "expires_in_seconds": 600,
                    "privacy_notice": privacy_notice,
                    "next_action": "向用户完整展示接收地址、全部 payload 和隐私说明，询问是否允许发送；等待本轮明确同意。拒绝或未回复均不得提交。"}
        preview = _previews.get(confirmation_id)
        if not preview or preview[1] != endpoint or any(preview[2].get(k) != v for k, v in fields.items()):
            raise AppError("feedback_preview_changed", "预览已过期、已使用或内容/接收方变更，请重新预览并征得同意。")
        if user_confirmed is not True:
            raise AppError("feedback_consent_required", "必须先展示本次准确反馈并取得用户明确同意。")
        _, endpoint, payload = _previews.pop(confirmation_id)
    report_id = payload["report_id"]
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(endpoint, json=payload)
        if response.status_code == 429:
            raise AppError("feedback_rate_limited", "反馈提交过于频繁，请稍后再试。")
        if response.status_code != 201:
            raise AppError("feedback_unavailable", "反馈未获接收确认；不影响其他校园工具。")
        receipt = response.json()
        if receipt.get("feedback_id") != report_id or receipt.get("status") != "received":
            raise ValueError("invalid receipt")
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise AppError("feedback_outcome_unknown", "未能确认反馈是否送达；未自动重试。其他校园工具可继续使用。") from None
    return {"feedback_id": report_id, "status": "received", "message": "维护者已收到反馈。"}
