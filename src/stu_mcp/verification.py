"""Bounded check of our installed MCP, independent of any agent configuration."""
from __future__ import annotations

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import __version__
from .clients import server_config
from .runtime import Runtime


async def verify_server(runtime: Runtime) -> dict:
    """Only inspect local capabilities; never run a command from user configuration."""
    base = {"verification": "installed_mcp_only", "agent_connection_verified": False}
    config = server_config()
    # Use the installed environment (including explicitly configured credential
    # backends), never a command or secret copied from an agent config file.
    env = dict(os.environ)
    env["STU_MCP_HOME"] = str(runtime.home)
    params = StdioServerParameters(**config, env=env)
    try:
        async with asyncio.timeout(30):
            # Dependency diagnostics can contain environment values or URLs.
            with open(os.devnull, "w") as errors:
                async with stdio_client(params, errlog=errors) as (read, write), ClientSession(
                    read, write, read_timeout_seconds=20
                ) as session:
                    initialized = await session.initialize()
                    if initialized.server_info.name != "stu-mcp":
                        raise ValueError("unexpected server")
                    discovered = await session.list_tools()
                    names = {tool.name for tool in discovered.tools}
                    if not {"get_capabilities", "open_setup", "search_notices"} <= names:
                        raise ValueError("incomplete tool discovery")
                    response = await session.call_tool("get_capabilities", {})
                    result = response.model_dump(by_alias=True)
                    capabilities = result.get("structuredContent")
                    if result.get("isError") or not isinstance(capabilities, dict) or capabilities.get("ok") is not True:
                        raise ValueError("capabilities failed")
                    if initialized.server_info.version != __version__:
                        raise ValueError("unexpected version")
                    return {**base, "ok": True, "status": "mcp_verified", "version": __version__,
                            "tool_count": len(names), "checks": ["initialize", "tools/list", "get_capabilities"],
                            "next_step": "在 DSH 或其他 agent 中重新加载 MCP，并实际调用 get_capabilities。"
                                         "本检查未读取或执行 agent 的配置。"}
    except Exception:
        return {**base, "ok": False, "status": "mcp_verification_failed",
                "message": "MCP 未能在时限内完成握手、工具发现及状态调用。请检查当前安装与本机凭据后端；"
                           "未输出子进程日志或个人状态。"}
