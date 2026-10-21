"""Explicit host-side configuration import into the existing encrypted Vault."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from ...credentials import read_private_file
from ...runtime import AppError
from .client import BASE, SOURCE


def validate_config(value: dict) -> dict:
    fail = AppError("invalid_takeout_config", "外卖配置格式不受支持；请使用已验证的本机配置文件。", SOURCE)
    if not isinstance(value, dict) or value.get("server", BASE) != BASE:
        raise fail
    clean = {"server": BASE}
    for key in ("userId", "appletId"):
        text = str(value.get(key, ""))
        if not re.fullmatch(r"[0-9]{1,20}", text):
            raise fail
        clean[key] = text
    for key in ("apiToken", "salt", "signToken"):
        text = value.get(key)
        if not isinstance(text, str) or not 1 <= len(text) <= 256 or not text.isascii():
            raise fail
        clean[key] = text
    if len(clean["salt"]) < 61:
        raise fail
    area = str(value.get("default_area", ""))
    if area and not re.fullmatch(r"[0-9]{1,20}", area):
        raise fail
    clean["default_area"] = area
    proxy = value.get("proxy", "")
    if not isinstance(proxy, str):
        raise fail
    if proxy:
        try:
            parsed = urlsplit(proxy)
            valid = (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                     and parsed.port and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment and parsed.path in ("", "/"))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise fail
        clean["proxy"] = proxy
    headers = value.get("headers", {})
    if not isinstance(headers, dict):
        raise fail
    clean["headers"] = {}
    for key, text in headers.items():
        if (not isinstance(key, str) or key.lower() not in {"user-agent", "referer", "accept", "xweb_xhr"}
                or not isinstance(text, str) or len(text) > 1024
                or any(ord(char) < 32 or ord(char) == 127 or ord(char) > 255 for char in text)
                or text[:1].isspace()):
            raise fail
        if key.lower() == "referer" and not re.fullmatch(
                r"https://servicewechat\.com/wx[0-9a-f]{16}/\d+/page-frame\.html", text):
            raise fail
        clean["headers"][key] = text
    return clean


def load_config(vault) -> dict:
    try:
        state = vault.load(SOURCE)
    except AppError as exc:
        if exc.code == "needs_login":
            raise AppError("takeout_not_configured", "请由操作者在 MCP 宿主运行 stu-mcp takeout configure --file 本机配置文件。"
                           "不要通过聊天或 MCP 传递签名材料。", SOURCE) from None
        raise
    return validate_config(state.get("takeout_config"))


def import_config(vault, path: Path) -> dict:
    try:
        value = json.loads(read_private_file(path, limit=65536))
    except (ValueError, UnicodeError):
        raise AppError("invalid_takeout_config", "无法读取外卖配置文件；未输出文件内容。", SOURCE) from None
    clean = validate_config(value)
    vault.save(SOURCE, {"cookies": [], "takeout_config": clean})
    return {"ok": True, "source": SOURCE, "status": "configured", "encrypted": True,
            "verified_live": False, "ordering_supported": False,
            "message": "已保存外卖目录读取配置；尚未执行在线验证，不包含下单和支付能力。"}
