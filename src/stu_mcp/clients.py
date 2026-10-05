"""Reversible, idempotent MCP connection. No credentials are written to agent files."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import tomlkit

from .runtime import AppError, Runtime, private_write, reject_symlinks


def server_config() -> dict:
    return {"command": str(Path(sys.executable).resolve()), "args": ["-m", "stu_mcp", "serve"]}


def target(client: str, home: Path | None = None) -> Path:
    user_home = home or Path.home()
    if client == "codex":
        config_home = Path(os.environ.get("CODEX_HOME", str(user_home / ".codex"))) if home is None else user_home / ".codex"
        return config_home / "config.toml"
    if client == "claude-code":
        return user_home / ".claude.json"
    if client == "cursor":
        return user_home / ".cursor" / "mcp.json"
    raise AppError("unknown_client", "请选择 codex、claude-code 或 cursor；其他客户端可使用通用 JSON。")


def connect(client: str, runtime: Runtime, *, apply: bool = False, replace: bool = False,
            home: Path | None = None) -> dict:
    path, config = target(client, home), server_config()
    reject_symlinks(path)
    raw = path.read_bytes() if path.exists() else b""
    try:
        if client == "codex":
            doc = tomlkit.parse(raw.decode("utf-8-sig")) if raw else tomlkit.document()
            servers = doc.get("mcp_servers", {})
        else:
            doc = json.loads(raw.decode("utf-8-sig")) if raw else {}
            if not isinstance(doc, dict):
                raise ValueError
            servers = doc.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError
    except (ValueError, tomlkit.exceptions.TOMLKitError, UnicodeError):
        raise AppError("invalid_client_config", "现有客户端配置无法解析，已保留原文件。") from None
    existing = servers.get("stu-mcp")
    if existing == config:
        return {"ok": True, "status": "already_connected", "client": client, "path": str(path)}
    ours = isinstance(existing, dict) and existing.get("args") == ["-m", "stu_mcp", "serve"]
    if existing and not ours and not replace:
        raise AppError("client_config_conflict", "已有同名 MCP 配置；请检查后使用 --replace 明确替换。")
    if client == "codex":
        if "mcp_servers" not in doc:
            doc["mcp_servers"] = tomlkit.table()
        doc["mcp_servers"]["stu-mcp"] = config
        new = tomlkit.dumps(doc).encode("utf-8")
    else:
        doc.setdefault("mcpServers", {})["stu-mcp"] = config
        new = (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    result = {"ok": True, "status": "preview", "client": client, "path": str(path),
              "server": config, "next_step": "保存后请重新加载 MCP 或重启客户端，并按客户端要求启用。"}
    if apply:
        # An atomic replacement is checked against the bytes inspected above.
        if (path.read_bytes() if path.exists() else b"") != raw:
            raise AppError("config_changed", "客户端配置正在被其他程序修改，请重试。")
        backup = None
        if raw:
            suffix = hashlib.sha256(str(path).encode()).hexdigest()[:12]
            backup = runtime.home / "backups" / f"{client}-{suffix}-{time.time_ns()}.bak"
            private_write(backup, raw)
        private_write(path, new)
        result.update(status="connected", backup=str(backup) if backup else None)
    return result


def detected_clients(home: Path | None = None) -> list[str]:
    return [name for name in ("codex", "claude-code", "cursor")
            if target(name, home).exists() or target(name, home).parent.exists()]
