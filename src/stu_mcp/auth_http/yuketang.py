"""Rain Classroom's phone-authorized QR flow, without a browser or stored secrets.

Only the official QR issue, one long poll, session exchange and read-only student
course proof are supported. Account binding and additional challenges stop the
flow. The caller displays the QR privately and owns encrypted session storage.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable

from ..features.yuketang.parser import parse_inventory
from ..features.yuketang.schema import COURSES_URL
from ..runtime import AppError
from ..sources import YUKETANG_BASE
from .transport import HTTPFlow
from .types import Candidate

HOST = "changjiang.yuketang.cn"
ISSUE_URL = YUKETANG_BASE + "/api/v3/user/login/app-web-pre-info"
WAIT_URL = YUKETANG_BASE + "/api/v3/user/login/app-web-login"
EXCHANGE_URL = YUKETANG_BASE + "/pc/web_login"
BINDING_URL = YUKETANG_BASE + "/api/web/checkin/pro_bind?user_id="
MAX_WAIT_SECONDS = 180
HEADERS = {
    "Accept": "application/json,text/html,*/*",
    "xtbz": "ykt",
    "Xt-Agent": "h5",
    "X-Client": "h5",
    "Origin": YUKETANG_BASE,
    "Referer": YUKETANG_BASE + "/web",
}


def _schema() -> AppError:
    return AppError("schema_changed", "雨课堂扫码认证数据结构发生变化；本次会话未保存。", "yuketang")


def _markers(payload: dict, *, required: str | None = None) -> None:
    """Every present status must agree; missing status cannot prove success."""
    if required is not None and required not in payload:
        raise _schema()
    markers = []
    for key in ("code", "errcode"):
        if key not in payload:
            continue
        value = payload[key]
        if type(value) not in (int, str) or type(value) is str and not value.isascii():
            raise _schema()
        markers.append(value == 0 if type(value) is int else value == "0")
    if "success" in payload:
        if type(payload["success"]) is not bool:
            raise _schema()
        markers.append(payload["success"])
    if not markers or not all(markers):
        raise AppError("login_rejected", "雨课堂未确认此次认证；本次会话未保存。", "yuketang")


def validate_student_courses(payload: object) -> dict:
    """Positive business proof, including valid empty/partial inventories.

    Keep account and course identities out of the returned authentication result.
    The normal inventory decoder validates every row before selecting a term.
    """
    if not isinstance(payload, dict):
        raise _schema()
    _markers(payload)
    inventory = parse_inventory(payload)
    return {
        "authenticated": True,
        "endpoint": "student_courses",
        "response_course_count": len(payload["data"]["list"]),
        "response_list_empty": not payload["data"]["list"],
        "inventory": {
            "complete": inventory.complete,
            "empty": not inventory.courses,
            "course_count": len(inventory.courses),
            "semester": inventory.semester,
        },
    }


def _qr_data(payload: dict) -> dict:
    # The current v3 QR protocol uses an integer code. Additional response
    # metadata is intentionally ignored, including Name/Nickname/Avatar.
    if type(payload.get("code")) is not int:
        raise _schema()
    if payload["code"] in (50000, 50080):
        raise AppError("interaction_required", "雨课堂要求额外验证，已停止本次扫码。", "yuketang")
    _markers(payload, required="code")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise _schema()
    return data


def _alias(data: dict, upper: str, lower: str) -> object:
    primary, fallback = data.get(upper), data.get(lower)
    if primary is not None and fallback is not None and (
        type(primary) is not type(fallback) or primary != fallback
    ):
        raise _schema()
    return primary if primary is not None else fallback


def _authorization(response) -> str | None:
    values = response.headers.get_list("set-auth")
    if not values:
        return None
    if len(set(values)) != 1:
        raise _schema()
    value = values[0]
    result = value if value.startswith("Bearer ") else "Bearer " + value
    if (not 8 <= len(result) <= 8192
            or re.fullmatch(r"Bearer [\x21-\x7e]+", result) is None):
        raise _schema()
    return result


def _csrf(flow: HTTPFlow) -> str:
    # CookieJar constructs the request's own matching cookie header; this honors
    # domain, path, expiry and secure flags without reading other sources.
    request = flow.client.build_request("POST", EXCHANGE_URL)
    values = []
    for pair in request.headers.get("cookie", "").split(";"):
        key, separator, value = pair.strip().partition("=")
        if separator and key == "csrftoken":
            values.append(value)
    if len(set(values)) > 1:
        raise _schema()
    value = values[0] if values else ""
    if len(value) > 8192 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise _schema()
    return value


def acquire_state(*, show_qr: Callable[[str], None], check: Callable[[], None] = lambda: None,
                  timeout: float = MAX_WAIT_SECONDS, transport=None) -> Candidate:
    """Request one QR and wait once for the owner's phone authorization.

    ``show_qr`` is a private terminal callback, never an MCP result or log sink.
    ``check`` raises when cancelled or when a login/logout generation changes.
    Interrupts are allowed to propagate; ambiguous POST outcomes are not retried.
    """
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise AppError("invalid_timeout", "扫码等待时间必须是有限的正数。", "yuketang")
    budget = min(timeout, MAX_WAIT_SECONDS)
    deadline = time.monotonic() + budget
    with HTTPFlow("yuketang", (HOST,), transport=transport, timeout=budget,
                  max_requests=5, headers=HEADERS) as flow:

        def request(method, url, *, wait=False, **kwargs):
            check()
            flow.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppError("authentication_budget", "此次扫码等待已结束；本次会话未保存。", "yuketang")
            response = flow.request(method, url, timeout=remaining if wait else min(15, remaining), **kwargs)
            check()
            if response.status_code != 200:
                unknown = kwargs.get("credential") and not 400 <= response.status_code < 500
                raise AppError("authentication_outcome_unknown" if unknown else "login_rejected",
                               "雨课堂未确认此次认证请求的结果；未重发，也未保存会话。",
                               "yuketang", http_status=response.status_code)
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                raise _schema() from None
            if not isinstance(payload, dict):
                raise _schema()
            return response, payload

        issue_response, issued = request("GET", ISSUE_URL)
        data = _qr_data(issued)
        content, token = data.get("qrContent"), data.get("token")
        if (not isinstance(content, str) or not 1 <= len(content) <= 16384
                or not isinstance(token, str) or not 1 <= len(token) <= 4096):
            raise _schema()
        authorization = _authorization(issue_response)
        check()
        show_qr(content)
        check()
        wait_response, waited = request("POST", WAIT_URL, json={"token": token},
                                        credential=True, wait=True)
        authorization = _authorization(wait_response) or authorization
        authenticated = _qr_data(waited)
        user_id = _alias(authenticated, "UserID", "user_id")
        auth = _alias(authenticated, "Auth", "auth")
        if user_id is not None and auth is not None:
            if (type(user_id) not in (str, int)
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(user_id)) is None
                    or not isinstance(auth, str) or not 1 <= len(auth) <= 8192):
                raise _schema()
            # Official Zepto sends JSON.stringify(data) with its default form
            # content type. Encoding this as a form changes the actual protocol.
            _, exchanged = request(
                "POST", EXCHANGE_URL, credential=True,
                content=json.dumps({"UserID": user_id, "Auth": auth}, separators=(",", ":")),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Requested-With": "XMLHttpRequest", "X-CSRFToken": _csrf(flow)},
            )
            _markers(exchanged, required="success")
        elif user_id is not None or auth is not None:
            raise _schema()
        # With no credential pair the official client proceeds using the newly
        # issued cookies. Neither that branch nor an exchange is itself proof.
        _, binding = request("GET", BINDING_URL, headers={"X-Requested-With": "XMLHttpRequest"})
        _markers(binding, required="success")
        if type(binding.get("bind")) is not bool:
            raise _schema()
        if not binding["bind"]:
            raise AppError("account_not_bound", "雨课堂账号尚未绑定学校；未执行账号绑定。", "yuketang")
        _, courses = request("GET", COURSES_URL,
                             headers={"Authorization": authorization} if authorization else None)
        proof = validate_student_courses(courses)
        check()
        state = flow.state((HOST,))
        if authorization:
            state["yuketang_authorization"] = authorization
        return Candidate(state=state, proof=proof)
