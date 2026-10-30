"""Bounded, source-isolated reads of the medical school's current timetable."""
from __future__ import annotations

from urllib.parse import urlsplit

from ...auth_http.transport import HTTPFlow
from ...runtime import AppError
from .parser import parse_timetable
from .schema import (
    MED_JW_BASE,
    MED_JW_SOURCE,
    MED_JW_TIMETABLE_BODY,
    MED_JW_TIMETABLE_URL,
    MED_JW_TOKEN_HEADER,
)


class MedJwAdapter:
    """The token is used only on one fixed read endpoint and is never returned."""

    def __init__(self, state: dict, *, transport=None):
        token = state.get("med_jw_token") if isinstance(state, dict) else None
        if (not isinstance(token, str) or not token or len(token) > 8192
                or any(not 33 <= ord(char) <= 126 for char in token)):
            raise AppError("session_invalid", "医学院会话缺少有效令牌，请重新登录。", MED_JW_SOURCE)
        self._token = token
        self._flow = HTTPFlow(MED_JW_SOURCE, (urlsplit(MED_JW_BASE).hostname,),
                              transport=transport, timeout=30, max_requests=1)

    def __enter__(self):
        self._flow.__enter__()
        return self

    def __exit__(self, *args):
        self._token = ""
        return self._flow.__exit__(*args)

    def timetable(self) -> dict:
        try:
            response = self._flow.post(MED_JW_TIMETABLE_URL, json=dict(MED_JW_TIMETABLE_BODY),
                                       headers={MED_JW_TOKEN_HEADER: self._token})
        except AppError as exc:
            # HTTPFlow owns request/body budgets and private direct transport. Its
            # authentication-specific wording is not appropriate for a read.
            codes = {
                "authentication_network_error": ("network_error", "医学院教务读取失败；未自动重试。"),
                "authentication_response_limit": ("response_limit", "医学院课表响应超过大小或时间上限。"),
                "authentication_budget": ("request_limit", "医学院课表读取达到时间或请求上限。"),
            }
            if exc.code in codes:
                code, message = codes[exc.code]
                raise AppError(code, message, MED_JW_SOURCE) from None
            raise
        status = response.status_code
        if status in {401, 403}:
            raise AppError("login_expired", "医学院登录已过期，请重新登录。", MED_JW_SOURCE,
                           http_status=status)
        if 300 <= status < 400:
            # Even an apparently harmless same-host redirect may target another
            # business. Never forward the token beyond the fixed read endpoint.
            raise AppError("unexpected_redirect", "医学院课表返回未核验跳转；已停止读取。", MED_JW_SOURCE,
                           http_status=status)
        if not 200 <= status < 300:
            raise AppError("source_error", "医学院教务未完成本次课表读取。", MED_JW_SOURCE,
                           http_status=status)
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            raise AppError("schema_changed", "医学院课表未返回预期 JSON 数据。", MED_JW_SOURCE) from None
        return parse_timetable(payload)
