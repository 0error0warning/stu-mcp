"""Human-only terminal input; never fall back to echoed or piped secrets."""
from __future__ import annotations

import getpass
import io
import os
import re
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


def captcha_input(image: bytes, *, media_type: str = "image/jpeg") -> str:
    """Render one small source image at the human TTY, without a file or browser."""
    require_terminal()
    if (not isinstance(image, bytes) or not 1 <= len(image) <= 65536
            or media_type not in {"image/png", "image/jpeg"}):
        raise AppError("captcha_display_unavailable", "当前终端无法显示此验证码；本次登录未继续。", "smartcard")
    try:
        from PIL import Image
    except ImportError:
        raise AppError("captcha_display_unavailable", "验证码显示组件不可用，请修复安装后重试。", "smartcard") from None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image)) as source:
                expected = {"image/png": "PNG", "image/jpeg": "JPEG"}[media_type]
                if (source.format != expected or not 1 <= source.width <= 512 or not 1 <= source.height <= 256
                        or getattr(source, "n_frames", 1) != 1):
                    raise ValueError
                source.load()
                pixels = source.convert("RGB")
                try:
                    columns = min(100, max(1, os.get_terminal_size(sys.stderr.fileno()).columns - 1))
                except (AttributeError, OSError, ValueError):
                    columns = 79
                pixels.thumbnail((columns, 48), Image.Resampling.LANCZOS)
                lines = []
                for y in range(0, pixels.height, 2):
                    line = []
                    for x in range(pixels.width):
                        upper = pixels.getpixel((x, y))
                        lower = pixels.getpixel((x, y + 1)) if y + 1 < pixels.height else (255, 255, 255)
                        line.append("\x1b[38;2;{};{};{}m\x1b[48;2;{};{};{}m▄".format(*lower, *upper))
                    lines.append("".join(line) + "\x1b[0m")
        print("请读取下方验证码（图片只在终端显示，不写入文件）：", file=sys.stderr)
        print("\n".join(lines), file=sys.stderr, flush=True)
    except (OSError, ValueError, UnicodeError, Image.DecompressionBombWarning,
            Image.DecompressionBombError):
        raise AppError("captcha_display_unavailable", "当前终端无法显示此验证码；请使用私密设置页或兼容的终端。", "smartcard") from None
    value = secret_input("图片中的四位数字（隐藏输入）：").strip()
    if re.fullmatch(r"[0-9]{4}", value) is None:
        raise AppError("invalid_authentication_input", "验证码须为四位数字。", "smartcard")
    return value
