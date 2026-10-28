"""Explicit, minimal feedback submission; never reads campus records or credentials."""
from __future__ import annotations

import os
import re
import uuid
from urllib.parse import urlsplit

import httpx

from . import __version__
from .runtime import AppError

DEFAULT_FEEDBACK_URL = "https://stu-mcp.com/api/feedback"
CATEGORIES = {"bug", "data_error", "suggestion"}


def report_feedback(message: str, tool_name: str = "", category: str = "bug") -> dict:
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
        raise AppError("invalid_feedback", "反馈描述需为 1–4000 字符。")
    if category not in CATEGORIES or not re.fullmatch(r"[a-zA-Z0-9_]{0,80}", tool_name):
        raise AppError("invalid_feedback", "请使用有效的反馈类别和工具名。")
    # Catch common accidental credential pastes. This is not a complete PII detector.
    if re.search(r"(?i)(?:bearer\s+\S+|(?:password|cookie|token|secret|密码|密钥)\s*[:=：]\s*\S+|-----BEGIN .*PRIVATE KEY)", message):
        raise AppError("sensitive_feedback", "请删除凭据，只提交简短问题描述。")
    endpoint = os.environ.get("STU_MCP_FEEDBACK_URL", DEFAULT_FEEDBACK_URL).strip()
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise AppError("invalid_feedback_url", "反馈接收地址必须为不含凭据和查询参数的 HTTPS 地址。")
    report_id = str(uuid.uuid4())
    payload = {"report_id": report_id, "message": message.strip(), "tool_name": tool_name,
               "category": category, "client_version": __version__}
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
