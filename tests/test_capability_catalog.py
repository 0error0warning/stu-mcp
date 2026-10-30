import ast
import json
from copy import deepcopy
from pathlib import Path

from stu_mcp.capability_catalog import build_capability_catalog
from stu_mcp.sources import SOURCES


def by_id(rows, key):
    return {row[key]: row for row in rows}


def test_configuration_groups_describe_existing_tools_without_adding_or_losing_interfaces():
    catalog = build_capability_catalog()
    profiles = by_id(catalog["profiles"], "configuration_id")
    assert set(profiles) == {"anonymous", "school", "webvpn", "yuketang", "duifene", "smartcard", "med_jw", "takeout", "local"}
    services = by_id(catalog["services"], "service_id")
    assert all(service_id in services for profile in profiles.values() for service_id in profile["service_ids"])
    assert all(services[service_id]["integration"] == "implemented"
               for profile in profiles.values() for service_id in profile["service_ids"])
    server = Path(__file__).parents[1] / "src" / "stu_mcp" / "server.py"
    tree = ast.parse(server.read_text(encoding="utf-8"))
    tool_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and any(isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
                          and decorator.func.id == "tool" for decorator in node.decorator_list)}
    catalog_tools = {tool for service in services.values() for feature in service["features"]
                     for tool in feature["tools"]}
    assert catalog_tools == tool_names
    assert all(service["evidence"]["verified_on"] and service["evidence"]["document"]
               for service in services.values())


def test_school_family_keeps_three_authentication_states_and_does_not_unlock_gaps():
    catalog = build_capability_catalog(
        [{"source": "jw", "auth": {"status": "session_saved", "verified_live": True}},
         {"source": "mystu", "auth": {"status": "login_expired"}}],
        repair_status={"status": "needs_login"})
    profiles = by_id(catalog["profiles"], "configuration_id")
    services = by_id(catalog["services"], "service_id")
    school = profiles["school"]
    assert school["setup_command"] == "stu-mcp login school"
    assert school["sessions_shared"] is False
    assert {services[key]["login_id"] for key in school["service_ids"]} == {"jw", "mystu", "repair"}
    assert school["state"]["status"] == "partially_configured"
    assert school["state"]["saved_session_count"] == 1
    assert services["jw_academics"]["state"]["session_saved"] is True
    assert services["mystu_learning"]["state"]["status"] == "login_expired"
    assert services["sangpushan_repair"]["state"]["status"] == "needs_login"
    for service_id in school["not_integrated_service_ids"]:
        service = services[service_id]
        assert not service["features"] and service["login_id"] is None
        assert service["state"]["status"] == "not_integrated"
    assert all(service["state"]["current_access"] == "not_checked" for service in services.values())
    assert all(service["state"]["business_read"] == "not_checked" for service in services.values())


def test_saved_all_school_sessions_still_does_not_claim_live_business_success():
    saved = {"status": "session_saved", "verified_live": True}
    catalog = build_capability_catalog({"jw": saved, "mystu": saved}, repair_status=saved)
    school = by_id(catalog["profiles"], "configuration_id")["school"]
    assert school["state"]["status"] == "sessions_saved"
    assert school["state"]["saved_session_count"] == school["state"]["session_count"] == 3
    assert school["state"]["business_read"] == "not_checked"
    assert school["state"]["current_access"] == "not_checked"
    assert "campus_repair" not in school["service_ids"]
    assert "campus_repair" in school["not_integrated_service_ids"]


def test_oa_anonymous_reading_is_independent_of_optional_webvpn_session():
    absent = build_capability_catalog({"oa": {"auth": {"status": "needs_login"}}})
    saved = build_capability_catalog({"oa": {"auth": {"status": "session_saved"}}})
    for catalog in (absent, saved):
        services = by_id(catalog["services"], "service_id")
        oa = services["oa_notices"]
        assert oa["configuration_id"] == "anonymous"
        assert oa["state"]["authentication"] == "not_required"
        assert oa["integration"] == "implemented"
        assert oa["configuration_ids"] == ["anonymous", "webvpn"]
    profiles = by_id(absent["profiles"], "configuration_id")
    assert profiles["anonymous"]["state"]["status"] == "not_required"
    assert profiles["webvpn"]["state"]["status"] == "needs_login"
    profiles = by_id(saved["profiles"], "configuration_id")
    assert profiles["webvpn"]["state"]["status"] == "session_saved"
    assert {feature["id"] for feature in profiles["webvpn"]["features"]} == {"oa_access_channel"}


def test_same_host_does_not_merge_course_access_with_unadapted_booking():
    catalog = build_capability_catalog({"mystu": {"auth": {"status": "session_saved"}}})
    services = by_id(catalog["services"], "service_id")
    courses, booking = services["mystu_learning"], services["elc_cill_booking"]
    assert courses["login_id"] == "mystu" and courses["integration"] == "implemented"
    assert booking["entry_urls"] == ["http://my.stu.edu.cn/courses/elc/blocks/mrbs/web/index.php"]
    assert booking["integration"] == "not_integrated" and booking["login_id"] is None
    assert booking["auth_family"] == "not_verified_for_business_path"
    assert services["library_catalog"]["configuration_id"] == "anonymous"
    assert services["library_reader"]["configuration_id"] == "unverified"
    assert services["library_catalog"]["entry_urls"] != services["library_reader"]["entry_urls"]


def test_repair_scope_stays_exact_and_both_network_tools_share_one_feature():
    services = by_id(build_capability_catalog()["services"], "service_id")
    dorm, campus = services["sangpushan_repair"], services["campus_repair"]
    assert dorm["entry_urls"] == ["https://repair.stu.edu.cn/"]
    assert campus["entry_urls"] == ["https://r.stu.edu.cn/"]
    assert dorm["integration"] == "implemented" and campus["integration"] == "navigation_only"
    assert campus["evidence"]["level"] == "authenticated_form"
    network = services["campus_network_diagnostics"]
    assert len(network["features"]) == 1
    assert set(network["features"][0]["tools"]) == {"diagnose_campus_network", "audit_campus_network"}


def test_stored_refresh_history_is_not_a_current_read_or_network_probe():
    catalog = build_capability_catalog({"jw": {"status": "session_saved"}}, freshness=[{
        "source": "jw", "status": "partial", "attempted_at": "2026-10-22T19:20:00+00:00",
        "success_at": "2026-10-20T19:20:00+00:00", "saved": 12, "error": "private detail"}])
    state = by_id(catalog["services"], "service_id")["jw_academics"]["state"]
    assert state["last_refresh"] == {"status": "partial", "attempted_at": "2026-10-22T19:20:00+00:00",
                                      "success_at": "2026-10-20T19:20:00+00:00", "historical": True}
    assert state["current_access"] == state["business_read"] == "not_checked"


def test_worker_and_external_configuration_keep_observed_local_state_only():
    catalog = build_capability_catalog(checkin_status={"status": "paused", "logged_in": True,
        "service_running": True, "monitoring": False, "account": "SYNTHETIC_PRIVATE"},
        takeout_status={"configured": True, "verified_live": True, "token": "SYNTHETIC_PRIVATE"})
    profiles = by_id(catalog["profiles"], "configuration_id")
    assert profiles["duifene"]["state"]["status"] == "paused"
    assert profiles["takeout"]["state"]["status"] == "configuration_saved"
    assert profiles["duifene"]["state"]["current_access"] == "not_checked"
    assert profiles["takeout"]["state"]["current_access"] == "not_checked"
    assert "SYNTHETIC_PRIVATE" not in json.dumps(catalog)
    default = by_id(build_capability_catalog()["profiles"], "configuration_id")
    assert default["duifene"]["state"]["status"] == "unknown"
    assert default["takeout"]["state"]["status"] == "unknown"


def test_projection_does_not_echo_credentials_and_returns_independent_metadata():
    sources = [{"source": "jw", "auth": {"status": "session_saved", "account": "SYNTHETIC_PRIVATE",
                "cookies": [{"name": "private", "value": "SYNTHETIC_PRIVATE"}]},
                "message": "SYNTHETIC_PRIVATE"}]
    before = deepcopy(sources)
    first = build_capability_catalog(sources, repair_status={"status": "SYNTHETIC_PRIVATE"})
    assert sources == before and "SYNTHETIC_PRIVATE" not in json.dumps(first)
    first["services"][0]["features"][0]["tools"].append("invented_tool")
    first["services"][0]["entry_urls"].append("https://untrusted.example/")
    second = build_capability_catalog(sources)
    assert "invented_tool" not in json.dumps(second) and "untrusted.example" not in json.dumps(second)


def test_metadata_never_enrolls_unadapted_services_as_sources_or_probes():
    before = deepcopy(SOURCES)
    catalog = build_capability_catalog()
    assert before == SOURCES
    assert all(service["login_id"] is None for service in catalog["services"]
               if service["integration"] != "implemented")
    assert not {"student_affairs", "dorm_utilities", "campus_repair", "library_reader"}.intersection(SOURCES)


def test_unknown_status_shapes_are_not_fatal_or_echoed():
    catalog = build_capability_catalog({"jw": {"auth": {"status": ["SYNTHETIC_PRIVATE"]}},
                                       "mystu": {"auth": "SYNTHETIC_PRIVATE"}},
        repair_status={"status": {"SYNTHETIC_PRIVATE": True}},
        freshness={"jw": {"status": [], "attempted_at": "SYNTHETIC_PRIVATE", "success_at": False}},
        checkin_status={"status": {}}, takeout_status={"configured": 1})
    services = by_id(catalog["services"], "service_id")
    assert services["jw_academics"]["state"]["status"] == "unknown"
    assert services["mystu_learning"]["state"]["status"] == "unknown"
    assert services["takeout_catalog"]["state"]["status"] == "unknown"
    assert "SYNTHETIC_PRIVATE" not in json.dumps(catalog)
