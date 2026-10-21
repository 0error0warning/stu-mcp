"""Human terminal configuration of the existing opt-in WebVPN renewal flow."""
from __future__ import annotations

import sys

from .terminal import require_terminal, secret_input
from .vault import Vault
from .webvpn import WebVPNConfig


def configure(vault: Vault, *, encoding: str = "auto") -> dict:
    require_terminal()
    # Validate the selected backend before requesting private inputs. Do not read
    # saved credentials, create a browser, or authenticate while configuring.
    vault.key_store()
    print("启用 WebVPN 按需自动重登；仅在受保护 OA 读取需要时使用。\n"
          "保存会断开旧 WebVPN 会话并清除旧 OA 缓存；不进行令牌绑定或验证码识别。\n"
          "以下信息仅在此终端隐藏输入，不要通过聊天或 MCP 提供。", file=sys.stderr, flush=True)
    fields = {}
    try:
        fields = {"enabled": True, "username": secret_input("学校账号："),
                  "password": secret_input("学校密码："),
                  "totp": secret_input("已绑定 TOTP 密钥或 otpauth 地址："), "encoding": encoding}
        return WebVPNConfig(vault).configure(fields)
    finally:
        fields.clear()
