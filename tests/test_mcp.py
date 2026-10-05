import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_real_stdio_handshake_schema_and_feature_gating(tmp_path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "stu_mcp", "serve"],
                                  env={**os.environ, "STU_MCP_HOME": str(tmp_path / "stdio-data")})
    async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=30) as client:
        initialized = await client.initialize()
        assert initialized.server_info.name == "stu-mcp"
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert {"get_capabilities", "refresh_source", "get_grades", "get_tasks", "open_setup"}.issubset(names)
        assert len(names) == 16
        for tool in tools.tools:
            schema = tool.input_schema
            assert not {"password", "username", "cookie", "cookies", "token", "api_key"}.intersection(schema.get("properties", {}))
        capabilities = await client.call_tool("get_capabilities", {})
        result = capabilities.model_dump(by_alias=True)["structuredContent"]
        assert result["privacy"]["model_api_key_required"] is False
        assert result["privacy"]["private_wechat"] is False
        unavailable = await client.call_tool("refresh_source", {"source": "jw"})
        assert unavailable.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        grade = await client.call_tool("get_grades", {})
        assert grade.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        unknown = await client.call_tool("refresh_source", {"source": "nonexistent"})
        assert unknown.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_source"
        public = await client.call_tool("search_notices", {"source": "public"})
        assert public.model_dump(by_alias=True)["structuredContent"]["items"] == []
        assert "password" not in json.dumps(result).lower()
