"""One normal card-query login with a human image challenge and identity proof."""
from __future__ import annotations

import io
import re
import warnings
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ..features.smartcard.parser import decode, parse_profile
from ..runtime import AppError
from ..sources import SMARTCARD_BASE
from .transport import HTTPFlow
from .types import Candidate

LOGIN = SMARTCARD_BASE + "/loginstudent.action"
HOME = SMARTCARD_BASE + "/homeLogin.action"
CAPTCHA = SMARTCARD_BASE + "/getCheckpic.action"
PROFILE = SMARTCARD_BASE + "/accountcardUser.action"


def _route(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.hostname == "smartcard.stu.edu.cn" and parts.port in {None, 80}
            and not parts.query and not parts.fragment
            and parts.path in {"/homeLogin.action", "/getCheckpic.action",
                                   "/loginstudent.action", "/accountcardUser.action"})


def _ok(response):
    if response.status_code != 200:
        raise AppError("authentication_unconfirmed", "一卡通未返回预期认证页面；没有重发登录。", "smartcard")
    return response


def _image(content: bytes, media_type: str) -> None:
    from PIL import Image
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
        raise AppError("captcha_display_unavailable", "一卡通验证码图片无法安全显示。", "smartcard") from None


def acquire_state(username: str, password: str, *, captcha, check, transport=None) -> Candidate:
    if (not isinstance(username, str) or re.fullmatch(r"[0-9]{4,20}", username) is None
            or not isinstance(password, str) or len(password) != 6
            or any(not 33 <= ord(char) <= 126 for char in password)):
        raise AppError("invalid_credentials", "请填写学（工）号及六位一卡通查询密码。", "smartcard")
    with HTTPFlow("smartcard", ("smartcard.stu.edu.cn",), transport=transport,
                  timeout=300, max_requests=5, allow_http=_route) as flow:
        check()
        soup = BeautifulSoup(decode(_ok(flow.get(HOME))), "html.parser")
        # The observed page assigns this literal action in doSummit(); it has
        # no HTML action attribute. Recognize that contract without executing JS.
        scripts = "\n".join(node.get_text() for node in soup.select("script:not([src])"))
        literal_action = re.search(r'''document\.FormPost\.action\s*=\s*["']loginstudent\.action["']''', scripts)
        forms = [form for form in soup.select("form")
                 if (urljoin(HOME, str(form.get("action", ""))) == LOGIN
                     or not form.get("action") and form.get("name") == "FormPost" and literal_action)
                 and str(form.get("method", "")).lower() == "post"]
        if (len(forms) != 1 or not {"name", "passwd", "loginType", "userType", "rand"}.issubset(
                {item.get("name") for item in forms[0].select("[name]")})):
            raise AppError("authentication_schema_changed", "一卡通登录表单发生变化，请核对官网入口。", "smartcard")
        check()
        image = _ok(flow.get(CAPTCHA))
        media_type = image.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in {"image/jpeg", "image/png"} or not 1 <= len(image.content) <= 65536:
            raise AppError("captcha_display_unavailable", "一卡通未返回可用验证码图片。", "smartcard")
        _image(image.content, media_type)
        check()
        code = captcha(image.content, media_type=media_type)
        if not isinstance(code, str) or re.fullmatch(r"[0-9]{4}", code) is None:
            raise AppError("invalid_authentication_input", "验证码须为四位数字。", "smartcard")
        check()
        response = _ok(flow.post(LOGIN, credential=True, data={
            "name": username, "passwd": password, "loginType": "2", "userType": "1",
            "rand": code, "imageField.x": "0", "imageField.y": "0"}))
        code = password = None
        # Never use the login page's arbitrary error prose in a public result.
        html = decode(response)
        if "验证码" in html and any(word in html for word in ("验证码错误", "验证码不正确")):
            raise AppError("captcha_rejected", "验证码未通过，请重新发起登录获取新图片。", "smartcard")
        if BeautifulSoup(html, "html.parser").select('input[type="password"]'):
            raise AppError("login_rejected", "一卡通未接受本次登录，请核对查询密码和验证码。", "smartcard")
        check()
        try:
            parse_profile(decode(_ok(flow.get(PROFILE))), username)
        except AppError as exc:
            if exc.code in {"login_expired", "needs_login"}:
                raise AppError("login_rejected", "一卡通未接受本次登录，请核对查询密码和验证码。", "smartcard") from None
            raise
        check()
        state = flow.state(("smartcard.stu.edu.cn",))
        state["smartcard_account"] = username
        if not state["cookies"]:
            raise AppError("authentication_unconfirmed", "一卡通身份已核对，但未返回可复用会话。", "smartcard")
        return Candidate(state, {"authenticated": True, "identity_matched": True,
                                 "transport": "http", "captcha_required": True})
