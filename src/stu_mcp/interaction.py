"""Manual-browser prerequisites, separate from callback and headless authentication."""
from __future__ import annotations

import os
import sys
import webbrowser

from .runtime import AppError


def interaction_mode() -> str:
    """Select a manual-browser policy; never silently replace an authentication flow."""
    mode = os.environ.get("STU_MCP_INTERACTION", "desktop")
    if mode not in {"desktop", "virtual-display", "disabled"}:
        raise AppError("invalid_interaction_mode", "STU_MCP_INTERACTION 只接受 desktop、virtual-display 或 disabled。")
    return mode


def require_interaction(source: str | None = None) -> str:
    """Fail before downloads or requests when no person can operate the browser.

    This guard belongs only to existing user-operated browser flows. Callback
    login and WebVPN's own headless renewal do not call it. A DISPLAY value is
    a prerequisite, not proof of a working browser; no display service is started.
    """
    mode = interaction_mode()
    if mode == "disabled":
        raise AppError("interaction_unavailable", "当前宿主已禁用交互浏览器；已有会话的只读查询仍可使用。", source)
    if mode == "virtual-display":
        if sys.platform != "linux" or not os.environ.get("DISPLAY"):
            raise AppError("interaction_unavailable", "此兼容选项需要已有的 Linux DISPLAY；程序不提供或启动显示服务。", source)
    elif sys.platform == "linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise AppError("interaction_unavailable", "此操作需要本人操作学校浏览器，当前宿主没有可用显示环境。"
                       "此来源尚未实现无头首次登录；已有会话读取、对分易回调和 WebVPN 自动重登不依赖显示。", source)
    return mode


def open_local_page(url: str) -> bool:
    """Open only a desktop on this host, never imply opening the caller's device."""
    try:
        # A virtual desktop is for the school's browser, not for launching a
        # second admin page inside itself. The CLI prints the loopback URL.
        if require_interaction() != "desktop":
            return False
        return bool(webbrowser.open(url))
    except (AppError, webbrowser.Error, OSError):
        return False
