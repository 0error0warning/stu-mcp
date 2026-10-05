"""Official client formats, reversible configuration and honest export-only modes."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import tomlkit
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from .runtime import AppError, Runtime, key_lock, private_write, reject_symlinks
from .skill_export import export_skill


@dataclass(frozen=True)
class Client:
    name: str
    label: str
    format: str
    parts: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    home_env: str = ""
    docs: tuple[str, ...] = ()
    next_step: str = "请重新加载 MCP 或重启客户端，并按客户端要求启用 STU MCP。"


CLIENTS = {
    c.name: c for c in (
        Client("codex", "Codex", "toml", (".codex", "config.toml"), ("mcp_servers",), "CODEX_HOME"),
        Client("claude-code", "Claude Code", "json", (".claude.json",), ("mcpServers",)),
        Client("cursor", "Cursor", "json", (".cursor", "mcp.json"), ("mcpServers",)),
        Client("workbuddy", "WorkBuddy", "json", (".workbuddy", "mcp.json"), ("mcpServers",), docs=(
            "https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide",
            "https://open.workbuddy.cn/docs/connector",
        ), next_step="在 WorkBuddy 的插件 / MCP 服务器中确认 STU MCP 已启用，并完成客户端要求的授权。"),
        Client("zcode", "ZCode", "json", (".zcode", "cli", "config.json"), ("mcp", "servers"), docs=(
            "https://www.zcode.network/cn/docs/mcp-services/",
        ), next_step="在 ZCode 设置 → MCP 服务器确认 STU MCP 已启用，重新加载或打开新会话。"),
        Client("grok-build", "Grok Build", "toml", (".grok", "config.toml"), ("mcp_servers",), "GROK_HOME", (
            "https://docs.x.ai/build/features/mcp-servers", "https://docs.x.ai/build/settings",
        ), "在 Grok Build 使用 /mcps 检查服务并刷新，或重新启动 Grok Build。"),
        Client("deepseek-harness", "DeepSeek Harness 桌面端", "cordis",
               (".dsh", "profiles", "desktop", "cordis.patch.yml"), home_env="DSH_HOME", docs=(
                   "https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md",
                   "https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/boot/app-boot/README.zh.md",
                   "https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.zh.md",
               ), next_step="重新加载或重启 DeepSeek Harness 桌面端；确认工具列表出现 STU MCP 后再报告已接通。"),
        Client("doubao-work", "豆包工作 · Skill / 本地命令", "skill", docs=(
            "https://www.feishu.cn/content/article/7677519271848610746",
        ), next_step="在豆包工作的技能入口导入生成的 ZIP；选本地电脑环境，执行版本 / 状态命令验证本地调用权限。"
                     "官方公开资料尚不足以确认本地 MCP 配置格式，本次没有配置原生 MCP。"),
        Client("generic", "其他本地 MCP 客户端", "export",
               next_step="将生成的配置添加到支持本地 stdio MCP 的客户端，再验证工具发现。"),
        Client("generic-cli", "其他可执行本地命令的 agent", "skill",
               next_step="导入生成的 Skill，或将其中的调用说明提供给 agent；先验证它能执行本机的版本 / 状态命令。"),
    )
}


def server_config(client: str = "generic") -> dict:
    # Keep the virtualenv entry point: resolving its symlink loses installed packages.
    config = {"command": sys.executable, "args": ["-m", "stu_mcp", "serve"]}
    return {"type": "stdio", **config} if client == "workbuddy" else config


def target(client: str, home: Path | None = None) -> Path:
    spec = CLIENTS.get(client)
    if spec is None or not spec.parts:
        raise AppError("unknown_client", "请选择受支持的本地客户端，或使用 generic / generic-cli 导出接入说明。")
    user_home = home or Path.home()
    if home is None and spec.home_env and os.environ.get(spec.home_env):
        return Path(os.environ[spec.home_env]).expanduser().joinpath(*spec.parts[1:])
    return user_home.joinpath(*spec.parts)


def catalog(home: Path | None = None) -> list[dict]:
    return [{"id": s.name, "label": s.label, "mode": s.format,
             "action": "生成技能包" if s.format == "skill" else "显示接入配置" if s.format == "export" else "保存接入",
             "detected": bool(s.parts and (target(s.name, home).exists() or target(s.name, home).parent.exists())),
             "docs": list(s.docs), "next_step": s.next_step} for s in CLIENTS.values()]


def _json(raw: bytes) -> dict:
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value:
                raise ValueError("duplicate key")
            value[k] = v
        return value
    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs) if raw else {}
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


def _section(doc: dict, keys: tuple[str, ...]) -> dict:
    node = doc
    for key in keys:
        if key not in node:
            node[key] = {}
        node = node[key]
        if not isinstance(node, dict):
            raise ValueError("not a server map")
    return node


def _yaml() -> YAML:
    # Round-trip mode preserves comments and !!js tags as data; it never evaluates them.
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.allow_duplicate_keys = False
    return yaml


def _patches(raw: bytes, yaml: YAML) -> list:
    patches = yaml.load(raw.decode("utf-8-sig")) if raw else []
    if not isinstance(patches, list) or any(not isinstance(p, dict) for p in patches):
        raise ValueError("not a patch list")
    return patches


def _owned_rows(value, *, seen=None):
    seen = set() if seen is None else seen
    if not isinstance(value, (dict, list)) or id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, dict):
        cfg = value.get("config")
        if value.get("id") == "mcp-stu-mcp" or isinstance(cfg, dict) and cfg.get("serverName") == "stu-mcp":
            yield value
        for child in value.values():
            yield from _owned_rows(child, seen=seen)
    else:
        for child in value:
            yield from _owned_rows(child, seen=seen)


def _cordis(raw: bytes, config: dict, *, replace: bool) -> tuple[bytes, bool]:
    yaml = _yaml()
    patches = _patches(raw, yaml)
    rows = list(_owned_rows(patches))
    cfg = {"serverName": "stu-mcp", "transport": "stdio", **config}
    insert_rows = []
    for patch in patches:
        if "insert" in patch:
            if not isinstance(patch["insert"], list) or any(not isinstance(r, dict) for r in patch["insert"]):
                raise ValueError("invalid insert")
            insert_rows.extend(patch["insert"])
    if len(rows) > 1 or rows and not any(rows[0] is row for row in insert_rows):
        raise AppError("client_config_conflict", "Cordis 中已有嵌套或覆盖的同名配置，已保留；请在客户端检查 STU MCP。")
    if rows:
        row = rows[0]
        existing = row.get("config", {})
        ours = row.get("name") == "@deepseek-ai/dsh-mcp-client" and isinstance(existing, dict) and existing.get("args") == config["args"]
        if not ours and not replace:
            raise AppError("client_config_conflict", "已有同名 MCP 配置；请检查后使用 --replace 明确替换。")
        if ours and all(existing.get(k) == v for k, v in cfg.items()):
            return raw, True
        if ours:
            existing.update(cfg)
        else:
            row.clear()
            row.update({"id": "mcp-stu-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": cfg})
    else:
        patches.append({"insert": [{"id": "mcp-stu-mcp", "name": "@deepseek-ai/dsh-mcp-client", "config": cfg}]})
    out = io.StringIO()
    yaml.dump(patches, out)
    return out.getvalue().encode("utf-8"), False


def _read(path: Path) -> bytes:
    reject_symlinks(path)
    return path.read_bytes() if path.exists() else b""


def connect(client: str, runtime: Runtime, *, apply: bool = False, replace: bool = False,
            home: Path | None = None) -> dict:
    spec = CLIENTS.get(client)
    if spec is None:
        raise AppError("unknown_client", "客户端未知；使用 stu-mcp clients 查看接入方式。")
    config = server_config(client)
    base = {"ok": True, "client": client, "next_step": spec.next_step,
            "verification": "configuration_only", "docs": list(spec.docs)}
    if spec.format == "export":
        return {**base, "status": "exported", "config": {"mcpServers": {"stu-mcp": config}},
                "mcpServers": {"stu-mcp": config}}
    if spec.format == "skill":
        return {**base, **export_skill(runtime, apply=apply), "verification": "local_execution_required"}
    path = target(client, home)
    base["path"] = str(path)
    if spec.format == "cordis" and not (path.parent / "package.json").is_file():
        return {**base, "ok": False, "status": "client_initialization_required",
                "message": "请先安装并打开一次 DeepSeek Harness 桌面端，再保存接入；不会代建它的桌面 profile。"}
    raw = _read(path)
    watched = {path: raw}
    migrated = 0
    try:
        if spec.format == "cordis":
            home_patch = path.parents[2] / "cordis.patch.yml"
            parent_raw = _read(home_patch)
            watched[home_patch] = parent_raw
            if parent_raw and list(_owned_rows(_patches(parent_raw, _yaml()))):
                raise AppError("client_config_conflict", "DSH_HOME 的全局 patch 已配置同名服务；请先检查它与桌面 profile 的优先级。")
            new, unchanged = _cordis(raw, config, replace=replace)
        else:
            doc = tomlkit.parse(raw.decode("utf-8-sig")) if raw and spec.format == "toml" else tomlkit.document() if spec.format == "toml" else _json(raw)
            servers = _section(doc, spec.keys)
            if client == "zcode" and not servers:
                fallback = (home or Path.home()) / ".agents" / "mcp.json"
                fallback_raw = _read(fallback)
                watched[fallback] = fallback_raw
                inherited = _section(_json(fallback_raw), ("mcpServers",))
                # ZCode skips the entire fallback once a native server exists.
                servers.update(inherited)
                migrated = len(inherited)
            existing = servers.get("stu-mcp")
            ours = isinstance(existing, dict) and existing.get("args") == config["args"]
            if "stu-mcp" in servers and not ours and not replace:
                raise AppError("client_config_conflict", "已有同名 MCP 配置；请检查后使用 --replace 明确替换。")
            unchanged = bool(ours and all(existing.get(k) == v for k, v in config.items()) and not migrated)
            if not unchanged:
                if ours:
                    existing.update(config)
                else:
                    servers["stu-mcp"] = config
            new = tomlkit.dumps(doc).encode("utf-8") if spec.format == "toml" else (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except (ValueError, TypeError, tomlkit.exceptions.TOMLKitError, UnicodeError, YAMLError):
        raise AppError("invalid_client_config", "现有客户端配置无法安全解析，已保留原文件；请使用客户端界面检查。") from None
    if unchanged:
        return {**base, "status": "already_connected"}
    result = {**base, "status": "preview", "server": config, "preserved_fallback_servers": migrated}
    if apply:
        with key_lock(runtime.home):
            if any(_read(p) != before for p, before in watched.items()):
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
    return [entry["id"] for entry in catalog(home) if entry["detected"]]
