"""Human-only terminal input; never fall back to echoed or piped secrets."""
from __future__ import annotations

import getpass
import sys
import warnings

from .runtime import AppError


def require_terminal() -> None:
    try:
        available = sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, OSError, ValueError):
        available = False
    if not available:
        raise AppError("terminal_required", "此操作需要本人使用交互终端；不接受管道、参数或聊天中的认证信息。")


def secret_input(prompt: str) -> str:
    require_terminal()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt, stream=sys.stderr)
    except (getpass.GetPassWarning, OSError):
        raise AppError("terminal_input_unavailable", "终端无法隐藏输入，已停止操作；未回退到回显输入。") from None
    except (EOFError, KeyboardInterrupt):
        raise AppError("operation_cancelled", "已取消操作；没有输出认证信息。") from None
