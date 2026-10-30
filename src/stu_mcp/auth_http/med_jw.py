"""Medical teaching-platform login with a human captcha and independent proof.

This is the local teaching-platform password route, not medical CAS. No prior
session is loaded, and only the newly issued token survives positive proof.
"""
from __future__ import annotations

import base64
import io
import re
import time
import warnings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..features.med_jw.parser import parse_timetable
from ..features.med_jw.schema import (
    MED_JW_BASE,
    MED_JW_CAPTCHA_URL,
    MED_JW_INFO_URL,
    MED_JW_LOGIN_URL,
    MED_JW_PUBLIC_KEY_B64,
    MED_JW_SOURCE,
    MED_JW_TIMETABLE_BODY,
    MED_JW_TIMETABLE_URL,
    MED_JW_TOKEN_HEADER,
)
from ..runtime import AppError
from .transport import HTTPFlow
from .types import Candidate


def _error(code: str, message: str) -> AppError:
    return AppError(code, message, MED_JW_SOURCE)


def rsa_password(password: str) -> str:
    """Use the upstream fixed PKCS#1 v1.5 wire format, inside verified HTTPS."""
    try:
        raw = password.encode("utf-8") if isinstance(password, str) else b""
    except UnicodeError:
        raw = b""
    if not 1 <= len(raw) <= 53:
        raise _error("invalid_authentication_input", "请填写医学院教务本地口令，长度不能超过 53 个 UTF-8 字节。")
    key = serialization.load_der_public_key(base64.b64decode(MED_JW_PUBLIC_KEY_B64))
    if not isinstance(key, rsa.RSAPublicKey):
        raise _error("authentication_schema_changed", "医学院教务密码编码配置无效。")
    return base64.b64encode(key.encrypt(raw, padding.PKCS1v15())).decode("ascii")


def _ok(response):
    # In particular, do not follow 301/302/307/308 with a token or password.
    if response.status_code in {401, 403}:
        raise _error("login_rejected", "医学院教务未接受本次认证，请重新登录。")
    if response.status_code != 200:
        raise _error("authentication_unconfirmed", "医学院教务未返回预期认证响应；没有重发登录。")
    return response


def _json(response) -> dict:
    try:
        payload = _ok(response).json()
    except ValueError:
        raise _error("authentication_schema_changed", "医学院教务认证响应结构发生变化。") from None
    if not isinstance(payload, dict):
        raise _error("authentication_schema_changed", "医学院教务认证响应结构发生变化。")
    return payload


def _success(payload: dict) -> None:
    code = payload.get("code")
    if type(code) not in {int, str} or code not in {200, "200"}:
        # Provider prose is inspected only for challenge classification, never
        # reflected into errors, logs, the proof object or MCP responses.
        message = payload.get("msg")
        if isinstance(message, str) and "验证码" in message:
            raise _error("captcha_rejected", "验证码未通过或已过期，请重新发起登录获取新图片。")
        raise _error("login_rejected", "医学院教务未接受本次认证，请核对本地口令后重新登录。")
    if any(payload.get(name) in (1, "1", True) for name in ("weakPass", "initPw", "twofactorAuth")):
        raise _error("interaction_required", "医学院教务要求先在官方页面完成密码或身份验证。")


def _identity(payload: dict, username: str) -> str:
    _success(payload)
    user = payload.get("user")
    if not isinstance(user, dict) or type(user.get("usertype")) not in {int, str} or user["usertype"] not in {0, "0"}:
        raise _error("authentication_unconfirmed", "医学院教务未提供学生身份的明确证明。")
    number = user.get("userbh")
    account = user.get("userAccount")
    if not isinstance(number, str) or not number or username not in {number, account if isinstance(account, str) else ""}:
        raise _error("authentication_identity_mismatch", "医学院教务返回的学生身份与本次账号不匹配。")
    return number


def _image(response) -> tuple[bytes, str]:
    from PIL import Image
    response = _ok(response)
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    content = response.content
    if media_type not in {"image/jpeg", "image/png"} or not 1 <= len(content) <= 65536:
        raise _error("captcha_display_unavailable", "医学院教务未返回可用验证码图片。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if (image.format != {"image/jpeg": "JPEG", "image/png": "PNG"}[media_type]
                        or not 1 <= image.width <= 512 or not 1 <= image.height <= 256
                        or getattr(image, "n_frames", 1) != 1):
                    raise ValueError
                image.load()
    except (OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise _error("captcha_display_unavailable", "医学院教务验证码图片无法安全显示。") from None
    return content, media_type


def acquire_state(username: str, password: str, *, captcha, check, transport=None) -> Candidate:
    """Obtain one fresh source token; persistence and logout fencing are shared."""
    if (not isinstance(username, str) or not 1 <= len(username) <= 128
            or username != username.strip() or any(ord(char) < 33 or ord(char) == 127 for char in username)):
        raise _error("invalid_authentication_input", "请填写医学院教务账号。")
    encrypted_password = rsa_password(password)
    password = None
    with HTTPFlow(MED_JW_SOURCE, ("jwgl.med.stu.edu.cn",), transport=transport,
                  timeout=300, max_requests=4,
                  headers={"Accept": "application/json", "Origin": MED_JW_BASE,
                           "Referer": MED_JW_BASE + "/app/index.html"}) as flow:
        check()
        stamp = int(time.time() * 1000)
        content, media_type = _image(flow.get(MED_JW_CAPTCHA_URL + f"?yzmcode={stamp}"))
        check()
        code = captcha(content, media_type=media_type)
        content = None
        if not isinstance(code, str) or re.fullmatch(r"[0-9A-Za-z]{4,5}", code) is None:
            raise _error("invalid_authentication_input", "请填写图片中的字母和数字验证码。")
        check()
        payload = _json(flow.post(MED_JW_LOGIN_URL, credential=True, json={
            "username": username, "password": encrypted_password, "code": "", "appid": None,
            "yzmCode": stamp, "verifyCode": code,
        }))
        encrypted_password = code = None
        check()
        number = _identity(payload, username)
        token = payload["user"].get("token")
        if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(not 33 <= ord(char) <= 126 for char in token):
            raise _error("authentication_unconfirmed", "医学院教务未返回可复用的认证凭证。")
        # Prove the token independently of any incidental authentication cookies.
        flow.client.cookies.clear()
        headers = {MED_JW_TOKEN_HEADER: token}
        identity = _json(flow.get(MED_JW_INFO_URL, headers=headers))
        check()
        if _identity(identity, username) != number:
            raise _error("authentication_identity_mismatch", "医学院教务在认证期间返回了不同学生身份。")
        flow.client.cookies.clear()
        timetable = _json(flow.post(MED_JW_TIMETABLE_URL, headers=headers, json=MED_JW_TIMETABLE_BODY))
        check()
        _success(timetable)
        try:
            parsed = parse_timetable(timetable)
        except AppError:
            raise _error("authentication_schema_changed", "医学院教务未返回可确认的本人课表结构。") from None
        if parsed.get("coverage", {}).get("complete") is not True:
            raise _error("authentication_unconfirmed", "医学院教务课表响应不完整，本次认证未保存。")
        check()
        return Candidate({"cookies": [], "origins": [], "med_jw_token": token}, {
            "authenticated": True, "identity_matched": True, "student_identity": True,
            "timetable_read": True, "transport": "https", "captcha_required": True,
        })
