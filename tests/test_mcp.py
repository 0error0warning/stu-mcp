import json
import os

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stu_mcp.app import App
from stu_mcp.clients import server_config
from stu_mcp.huyou import post_record
from stu_mcp.runtime import Runtime


@pytest.mark.asyncio
async def test_real_stdio_handshake_schema_and_feature_gating(tmp_path):
    app = App(Runtime(tmp_path / "stdio-data"))
    app.store.save_community([post_record({"feedId": "101", "content": "合成公开树洞内容", "status": 1})])
    config = server_config()
    params = StdioServerParameters(command=config["command"], args=config["args"],
                                  env={**os.environ, "STU_MCP_HOME": str(tmp_path / "stdio-data")})
    async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=30) as client:
        initialized = await client.initialize()
        assert initialized.server_info.name == "stu-mcp"
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert {"get_capabilities", "refresh_source", "get_grades", "get_tasks", "open_setup"}.issubset(names)
        assert len(names) == 19
        assert {"search_huyou_posts", "get_huyou_post", "search_huyou_circles"}.issubset(names)
        for tool in tools.tools:
            schema = tool.input_schema
            assert not {"password", "username", "cookie", "cookies", "token", "api_key", "totp", "secret", "encoding"}.intersection(schema.get("properties", {}))
        capabilities = await client.call_tool("get_capabilities", {})
        result = capabilities.model_dump(by_alias=True)["structuredContent"]
        assert result["privacy"]["model_api_key_required"] is False
        assert result["privacy"]["private_wechat"] is False
        assert result["webvpn_auto_login"]["configured"] is False
        unavailable = await client.call_tool("refresh_source", {"source": "jw"})
        assert unavailable.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        grade = await client.call_tool("get_grades", {})
        assert grade.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        unknown = await client.call_tool("refresh_source", {"source": "nonexistent"})
        assert unknown.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_source"
        public = await client.call_tool("search_notices", {"source": "public"})
        assert public.model_dump(by_alias=True)["structuredContent"]["items"] == []
        invalid_plan = await client.call_tool("search_huyou_posts", {"query": "合成问题", "keywords": []})
        assert invalid_plan.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_keywords"
        cached_post = await client.call_tool("get_huyou_post", {"target": "101", "refresh": False})
        community = cached_post.model_dump(by_alias=True)["structuredContent"]
        assert community["item"]["body"] == "合成公开树洞内容" and community["item"]["official"] is False
        assert "password" not in json.dumps(result).lower()
