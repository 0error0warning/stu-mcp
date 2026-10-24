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
                                  env={**os.environ, "STU_MCP_HOME": str(tmp_path / "stdio-data"),
                                       "STU_CHECKIN_HOME": str(tmp_path / "checkin-data")})
    async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=30) as client:
        initialized = await client.initialize()
        assert initialized.server_info.name == "stu-mcp"
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        assert {"get_capabilities", "refresh_source", "get_grades", "get_tasks", "open_setup"}.issubset(names)
        assert len(names) == 48
        assert "get_academic_timetable" in names
        assert {"search_takeout_shops", "get_takeout_shop", "get_takeout_menu", "prepare_takeout_selection"} <= names
        assert "get_takeout_product" in names
        assert "get_takeout_delivery_slots" in names
        assert "find_takeout_meal_shops" in names
        assert "diagnose_campus_network" in names
        assert "audit_campus_network" in names
        assert {"prepare_repair_draft", "open_repair_form", "get_repair_draft", "close_repair_form"} <= names
        assert {"review_repair_draft", "submit_repair_draft"} <= names
        assert "check_repair_submission" in names
        assert {"get_checkin_status", "list_checkin_courses", "select_checkin_courses", "start_checkin_monitor",
                "pause_checkin_monitor", "get_checkin_results", "open_checkin_page", "stop_checkin_service"} <= names
        assert {"search_huyou_posts", "get_huyou_post", "search_huyou_circles"}.issubset(names)
        assert {"get_charging_overview", "get_charging_device"}.issubset(names)
        for tool in tools.tools:
            schema = tool.input_schema
            assert not {"password", "username", "cookie", "cookies", "token", "api_key", "totp", "secret", "encoding"}.intersection(schema.get("properties", {}))
        capabilities = await client.call_tool("get_capabilities", {})
        result = capabilities.model_dump(by_alias=True)["structuredContent"]
        assert result["privacy"]["model_api_key_required"] is False
        assert result["privacy"]["private_wechat"] is False
        assert result["takeout"]["configured"] is False
        assert result["takeout"]["ordering_supported"] is False
        takeout = await client.call_tool("search_takeout_shops", {"query": "奶茶"})
        assert takeout.model_dump(by_alias=True)["structuredContent"]["status"] == "takeout_not_configured"
        assert result["webvpn_auto_login"]["configured"] is False
        assert result["checkin"]["status"] == "service_not_started"
        assert result["repair"]["submission_supported"] is True
        assert result["repair"]["confirmation_required"] is True
        assert result["repair"]["submission_live_verified"] is False
        assert result["repair"]["transport"] == "direct"
        assert result["repair"]["read_only_submission_check"] is True
        assert result["network_diagnostics"]["changes_system_settings"] is False
        assert result["network_diagnostics"]["automatic_proxy_fallback"] is False
        assert result["network_diagnostics"]["local_proxy_comparison_default"] is False
        assert result["network_audit"]["changes_system_settings"] is False
        assert result["network_audit"]["public_dns_comparison_default"] is False
        assert result["network_audit"]["physical_location_detection"] is False
        assert "network_repair_http" in result["network_diagnostics"]["service_ids"]
        schema = next(t.input_schema for t in tools.tools if t.name == "diagnose_campus_network")
        assert schema["properties"]["compare_proxy"]["default"] is False
        assert schema["properties"]["check_login"]["default"] is None
        # Invalid input exercises the real tool without network traffic.
        invalid_network = await client.call_tool("diagnose_campus_network", {"service_id": "https://evil.invalid/"})
        assert invalid_network.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_service"
        invalid_audit = await client.call_tool("audit_campus_network", {"location_hint": "guess_from_ip"})
        assert invalid_audit.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_location"
        draft = await client.call_tool("prepare_repair_draft", {"title": "合成空调故障"})
        prepared = draft.model_dump(by_alias=True)["structuredContent"]
        assert prepared["status"] == "needs_information" and prepared["submission_supported"] is True
        denied = await client.call_tool("submit_repair_draft", {"draft_id": prepared["draft_id"], "review_id": "none"})
        assert denied.model_dump(by_alias=True)["structuredContent"]["status"] == "repair_confirmation_required"
        no_review = await client.call_tool("review_repair_draft", {"draft_id": prepared["draft_id"]})
        assert no_review.model_dump(by_alias=True)["structuredContent"]["status"] == "repair_window_required"
        no_submission = await client.call_tool("check_repair_submission", {"draft_id": prepared["draft_id"]})
        assert no_submission.model_dump(by_alias=True)["structuredContent"]["status"] == "repair_not_submitted"
        opened = await client.call_tool("open_repair_form", {"draft_id": prepared["draft_id"]})
        assert opened.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_information"
        readback = await client.call_tool("get_repair_draft", {"draft_id": prepared["draft_id"]})
        assert readback.model_dump(by_alias=True)["structuredContent"]["preview"]["title"] == "合成空调故障"
        closed = await client.call_tool("close_repair_form", {"draft_id": prepared["draft_id"]})
        assert closed.model_dump(by_alias=True)["structuredContent"]["status"] == "closed"
        by_name = {t.name: t for t in tools.tools}
        assert by_name["get_repair_draft"].annotations.read_only_hint is True
        assert by_name["open_repair_form"].annotations.read_only_hint is False
        assert by_name["submit_repair_draft"].annotations.read_only_hint is False
        assert by_name["check_repair_submission"].annotations.read_only_hint is True
        assert by_name["diagnose_campus_network"].annotations.read_only_hint is True
        assert by_name["audit_campus_network"].annotations.read_only_hint is True
        assert by_name["audit_campus_network"].input_schema["properties"]["compare_public_dns"]["default"] is False
        status = await client.call_tool("get_checkin_status", {})
        assert status.model_dump(by_alias=True)["structuredContent"]["monitoring"] is False
        assert not (tmp_path / "checkin-data").exists()
        unavailable = await client.call_tool("refresh_source", {"source": "jw"})
        assert unavailable.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        grade = await client.call_tool("get_grades", {})
        assert grade.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        timetable = await client.call_tool("get_academic_timetable", {})
        assert timetable.model_dump(by_alias=True)["structuredContent"]["status"] == "needs_login"
        unknown = await client.call_tool("refresh_source", {"source": "nonexistent"})
        assert unknown.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_source"
        public = await client.call_tool("search_notices", {"source": "public"})
        assert public.model_dump(by_alias=True)["structuredContent"]["items"] == []
        services = await client.call_tool("get_service_links", {"query": "校园网 报修"})
        directory = services.model_dump(by_alias=True)["structuredContent"]
        assert directory["total_count"] == 2 and directory["availability_checked"] is False
        assert directory["items"][0]["url"] == "https://r.stu.edu.cn/"
        assert directory["items"][0]["service_id"] == "campus_repair"
        assert directory["items"][0]["form_verified"] is True
        assert directory["items"][0]["submission_verified"] is False
        assert directory["items"][0]["workflow_verified"] is False
        assert directory["items"][1]["recommended"] is False
        assert directory["items"][1]["migration_confirmed"] is False
        invalid_plan = await client.call_tool("search_huyou_posts", {"query": "合成问题", "keywords": []})
        assert invalid_plan.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_keywords"
        cached_post = await client.call_tool("get_huyou_post", {"target": "101", "refresh": False})
        community = cached_post.model_dump(by_alias=True)["structuredContent"]
        assert community["item"]["body"] == "合成公开树洞内容" and community["item"]["official"] is False
        assert "password" not in json.dumps(result).lower()
        charging = await client.call_tool("get_charging_overview", {"refresh": False})
        overview = charging.model_dump(by_alias=True)["structuredContent"]
        assert overview["source"] == "charging" and overview["coverage"]["catalog_device_count"] == 14
        assert len(overview["items"]) == 4 and overview["has_more"] and overview["counts"] is None
        invalid_device = await client.call_tool("get_charging_device", {"device_code": "SYNTHETIC_UNKNOWN"})
        assert invalid_device.model_dump(by_alias=True)["structuredContent"]["status"] == "unknown_device"
