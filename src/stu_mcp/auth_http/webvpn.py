"""Official ordinary-Web password/TOTP protocol, without browser execution."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..runtime import AppError
from .transport import HTTPFlow

ORIGIN = "https://webvpn.stu.edu.cn"
INIT = ORIGIN + "/por/login_auth.csp?apiversion=1"
CONFIG = ORIGIN + "/public/psw_config?apiversion=1"
PASSWORD = ORIGIN + "/por/login_psw.csp?anti_replay=1&encrypt=1&apiversion=1"
TOTP = ORIGIN + "/auth/token?apiversion=1"
CONF = ORIGIN + "/por/conf.csp?apiversion=1"
RESOURCES = ORIGIN + "/por/rclist.csp?apiversion=1"
WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": ORIGIN + "/portal/", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9",
}
AUTH_FIELDS = frozenset({"ErrorCode", "TwfID", "CSRF_RAND_CODE", "RSA_ENCRYPT_KEY", "RSA_ENCRYPT_EXP",
                         "RndImg", "USE_RAND_CODE", "MID_ATK_CHECK", "NextService", "NextServiceSubType",
                         "TotpStatus", "pwpErrorCode"})
GRAPHICAL_CODES = frozenset({20023, 20041, 20043, 20053})


def _changed() -> AppError:
    return AppError("schema_changed", "WebVPN 认证或目录结构已变化，未继续提交。", "oa")


def _xml(body: bytes, expected: str) -> ET.Element:
    if len(body) > 2_000_000 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise _changed()
    try:
        root = ET.fromstring(body)
    except (ET.ParseError, ValueError):
        raise _changed() from None
    if root.tag != expected:
        if root.tag == "Auth" and expected != "Auth":
            raise AppError("login_expired", "WebVPN 未接受此会话的资源目录读取。", "oa")
        raise _changed()
    return root


def _one(root: ET.Element, name: str, default: str | None = None) -> str:
    found = root.findall(name)
    attribute = root.attrib.get(name)
    if attribute is not None:
        if found:
            raise _changed()
        return attribute.strip()
    if not found and default is not None:
        return default
    if len(found) != 1 or len(found[0]):
        raise _changed()
    return (found[0].text or "").strip()


def auth_fields(body: bytes) -> dict[str, str]:
    root = _xml(body, "Auth")
    values = {}
    for element in root:
        if element.tag not in AUTH_FIELDS:
            continue
        if element.tag in values or len(element):
            raise _changed()
        values[element.tag] = (element.text or "").strip()
    if not re.fullmatch(r"[0-9]{1,6}", values.get("ErrorCode", "")):
        raise _changed()
    return values


def _stage(reply: dict[str, str], *, allow_totp: bool) -> str:
    code = int(reply["ErrorCode"])
    if code in GRAPHICAL_CODES:
        raise AppError("auto_login_interaction_required", "WebVPN 要求人工图形验证，已停止自动认证。", "oa")
    if code not in {1, 2, 20021}:
        raise AppError("auto_login_failed", f"WebVPN 未接受认证（错误码 {code}），未自动重试。", "oa")
    if reply.get("pwpErrorCode", "0") not in {"", "0"}:
        raise AppError("auto_login_interaction_required", "WebVPN 要求更新密码或处理密码策略。", "oa")
    service = reply.get("NextService", "")
    if not service and code in {1, 20021}:
        return "candidate"
    if allow_totp and service == "auth/token" and reply.get("NextServiceSubType") == "totp":
        if reply.get("TotpStatus") != "Bind":
            raise AppError("auto_login_interaction_required", "请先按学校流程绑定令牌；本工具不执行绑定。", "oa")
        return "totp"
    raise AppError("auto_login_interaction_required", "WebVPN 要求其他认证步骤，未代替本人完成。", "oa")


def encrypt_password(config: dict[str, str], password: str) -> tuple[str, str]:
    nonce, modulus, exponent = (config.get(name, "") for name in
                                ("CSRF_RAND_CODE", "RSA_ENCRYPT_KEY", "RSA_ENCRYPT_EXP"))
    if (not nonce or len(nonce) > 1024 or any(ord(c) < 32 for c in nonce)
            or not re.fullmatch(r"[a-fA-F0-9]{256,2048}", modulus)
            or not re.fullmatch(r"[0-9]{1,10}", exponent)):
        raise _changed()
    if any(ord(char) > 0xFFFF or 0xD800 <= ord(char) <= 0xDFFF for char in password + nonce):
        raise AppError("unsupported_credentials", "此密码字符编码尚未验证，未提交密码。", "oa")
    try:
        key = rsa.RSAPublicNumbers(int(exponent), int(modulus, 16)).public_key()
        plain = (password + "_" + nonce).encode("utf-8")
        if not 1024 <= key.key_size <= 8192 or len(plain) > key.key_size // 8 - 11:
            raise ValueError
        return nonce, key.encrypt(plain, padding.PKCS1v15()).hex()
    except ValueError:
        raise _changed() from None


def oa_route(conf_body: bytes, resource_body: bytes) -> tuple[dict | None, dict]:
    """Read only exact OA resource metadata; never retain resource/SSO values."""
    conf, resources = _xml(conf_body, "Conf"), _xml(resource_body, "Resource")
    webvpn = conf.findall("WebVpn")
    if len(webvpn) != 1:
        return None, {"oa_resource": "route_unavailable"}
    config = webvpn[0]
    scheme = _one(config, "scheme", "http:").removesuffix(":")
    port = _one(config, "port", "80")
    hostname = _one(config, "hostname", "webvpn.stu.edu.cn")
    if hostname not in {"", "webvpn.stu.edu.cn"}:
        return None, {"oa_resource": "route_changed"}
    rows = resources.findall("Rcs/Rc")
    if len(rows) > 500:
        raise _changed()
    matches = []
    for row in rows:
        host = _one(row, "host", "")
        svc = _one(row, "svc", "").lower()
        if svc not in {"webapp:http", "webapp:https"}:
            continue
        try:
            target = urlsplit(host)
            if target.hostname != "oa.stu.edu.cn":
                continue
            if (target.scheme != "http" or target.port not in {None, 80} or target.username or target.password
                    or target.fragment or target.path not in {"", "/", "/login/Login.jsp"}
                    or target.query not in {"", "logintype=1"}):
                raise _changed()
        except ValueError:
            raise _changed() from None
        rcid = _one(row, "id")
        if not re.fullmatch(r"[0-9]{1,10}", rcid):
            raise _changed()
        if _one(row, "type") != "0" or _one(row, "attr", "0") != "0":
            return None, {"oa_resource": "policy_requires_review"}
        sso = any(_one(item, "rcid", "") == rcid for item in resources.findall("WebSsoInfos/webssoinfo"))
        legacy = resources.findall("Sso")
        if len(legacy) > 1:
            raise _changed()
        if legacy:
            enabled = _one(legacy[0], "enable", "0")
            if enabled not in {"0", "1"}:
                raise _changed()
            sso |= enabled == "1" and any(part.partition(":")[0] == rcid
                                         for part in _one(legacy[0], "data", "").split(";"))
        easy = any(_one(item, "Id", "") == rcid for item in resources.findall("Easylink/ElnkRc"))
        if sso or easy:
            return None, {"oa_resource": "sso_or_client_requires_review"}
        matches.append(svc)
    if len(matches) != 1:
        return None, {"oa_resource": "missing" if not matches else "ambiguous"}
    if (scheme, port) not in {("http", "8118"), ("https", "443")}:
        return None, {"oa_resource": "unsupported_transport"}
    route = {"scheme": scheme, "host": "oa-stu-edu-cn.webvpn.stu.edu.cn", "port": int(port)}
    return route, {"oa_resource": "catalog_verified", "oa_scheme": scheme, "oa_port": int(port),
                   "oa_http_compat_required": scheme == "http"}


def acquire_state(*, username: str, password: str, totp_code: Callable[[], str],
                  check: Callable[[], None] = lambda: None, on_phase=None, transport=None,
                  timeout: float = 50) -> tuple[dict, dict]:
    if (not isinstance(username, str) or not 1 <= len(username.strip()) <= 128
            or not isinstance(password, str) or not 1 <= len(password) <= 1024
            or any(ord(c) < 32 for c in username)):
        raise AppError("invalid_credentials", "请提供有效的学校账号和密码。", "oa")
    with HTTPFlow("oa", ("webvpn.stu.edu.cn",), transport=transport, timeout=timeout,
                  max_requests=9, headers=WEB_HEADERS) as flow:
        def get(url):
            check()
            response = flow.get(url)
            if response.status_code != 200:
                raise AppError("source_unavailable", "WebVPN 未返回正常认证或目录响应。", "oa",
                               http_status=response.status_code)
            return response.content

        def post(url, data):
            check()
            response = flow.post(url, data=data, headers={"Origin": ORIGIN}, credential=True)
            if response.status_code != 200:
                raise AppError("auto_login_failed", "WebVPN 未接受认证请求，未自动重试。", "oa",
                               http_status=response.status_code)
            return auth_fields(response.content)

        if on_phase:
            on_phase("authenticating_http")
        get(ORIGIN + "/portal/")
        initial = auth_fields(get(INIT))
        config = auth_fields(get(CONFIG))
        fresh = auth_fields(get(INIT))  # Official authPsw refreshes global parameters before encryption.
        if any(item["ErrorCode"] != "1" for item in (initial, config, fresh)):
            raise _changed()
        if (any(item.get("RndImg") != "0" or item.get("MID_ATK_CHECK") != "0"
                for item in (initial, fresh)) or config.get("USE_RAND_CODE") != "0"
                or config.get("MID_ATK_CHECK") != "0"):
            raise AppError("auto_login_interaction_required", "WebVPN 要求人工挑战或本机安全验证。", "oa")
        sid = fresh.get("TwfID", "")
        if not sid or not any(cookie.name == "TWFID" and cookie.value == sid and cookie.path == "/"
                              and cookie.domain.lstrip(".") == "webvpn.stu.edu.cn"
                              for cookie in flow.client.cookies.jar):
            raise _changed()
        nonce, encrypted = encrypt_password(fresh, password)
        reply = post(PASSWORD, {"mitm_result": "", "svpn_req_randcode": nonce,
                                "svpn_name": username.strip(), "svpn_password": encrypted, "svpn_rand_code": ""})
        sid = reply.get("TwfID") or sid
        used_totp = _stage(reply, allow_totp=True) == "totp"
        if used_totp:
            if on_phase:
                on_phase("waiting_for_totp")
            code = totp_code()
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code.strip()):
                raise AppError("invalid_totp", "请输入已绑定令牌当前的六位动态码。", "oa")
            reply = post(TOTP, {"twfid": sid, "svpn_inputtoken": code.strip()})
            _stage(reply, allow_totp=False)
        route, metadata = oa_route(get(CONF), get(RESOURCES))
        check()
        state = flow.state(("webvpn.stu.edu.cn",))
        state["webvpn_catalog_verified"] = True
        if route:
            state["webvpn_oa_route"] = route
        return state, {"method": "http", "authentication_verified": True,
                       "totp_used": used_totp, "portal_catalog_verified": True,
                       "oa_content_verified": False, **metadata}
