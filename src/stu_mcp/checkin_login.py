"""Human CLI entry for the existing Duifene WeChat callback workflow."""
from __future__ import annotations

import sys

from stu_checkin.auth import AUTH_URL, callback_code

from .checkin import CheckinClient
from .runtime import AppError
from .terminal import require_terminal, secret_input


def login_via_callback(client=None) -> dict:
    require_terminal()
    print("请在微信中打开授权链接；跳转后复制完整页面链接，在下方隐藏输入。不要发到聊天或命令参数中。",
          file=sys.stderr)
    print(AUTH_URL, file=sys.stderr)
    link = secret_input("对分易返回链接（隐藏输入）：")
    try:
        try:
            callback_code(link)
        except ValueError:
            raise AppError("invalid_callback", "返回链接无效；请重新获取微信打开后、包含 code 的对分易完整链接。") from None
        control = client if client is not None else CheckinClient(opener=lambda _: False)
        return control.connect_callback(link)
    finally:
        # Drop this reference promptly; immutable Python strings are not securely wipeable.
        link = ""
