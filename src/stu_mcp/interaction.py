"""Host-side interactive browser policy shared by login and dorm repair."""
from __future__ import annotations

import os
import sys
import webbrowser

from .runtime import AppError


def interaction_mode() -> str:
    """Select an explicit operator environment; never silently switch to headless."""
    mode = os.environ.get("STU_MCP_INTERACTION", "desktop")
    if mode not in {"desktop", "virtual-display", "disabled"}:
        raise AppError("invalid_interaction_mode", "STU_MCP_INTERACTION 只接受 desktop、virtual-display 或 disabled。")
    return mode


def require_interaction(source: str | None = None) -> str:
    """Fail before downloads or requests when no person can operate the browser.

    A DISPLAY value is a prerequisite, not proof that a virtual display or its
    separately authenticated remote viewer is healthy. Browser startup still
    validates the real display. This module opens no network listener.
    """
    mode = interaction_mode()
    if mode == "disabled":
        raise AppError("interaction_unavailable", "当前宿主已禁用交互浏览器；已有会话的只读查询仍可使用。", source)
    if mode == "virtual-display":
        if sys.platform != "linux" or not os.environ.get("DISPLAY"):
            raise AppError("interaction_unavailable", "virtual-display 需要 Linux DISPLAY 和受保护的远程桌面；"
                           "请先启动虚拟显示及登录界面。", source)
    elif sys.platform == "linux" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise AppError("interaction_unavailable", "此服务器没有可操作的显示环境；请配置受保护的虚拟桌面并设置 "
                       "STU_MCP_INTERACTION=virtual-display，或在有桌面的宿主运行。", source)
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
