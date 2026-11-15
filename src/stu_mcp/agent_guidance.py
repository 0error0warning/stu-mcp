"""Pure, source-specific response guidance; never authenticates or performs I/O."""
from __future__ import annotations

from copy import deepcopy

from .runtime import AppError

CAPABILITY_SCOPES = ("all", "public", "oa", "jw", "mystu", "yuketang", "huyou", "charging", "smartcard",
                     "med_jw", "repair", "duifene", "takeout", "webvpn", "school", "wechat", "network", "local")
QUERY_SOURCES = {"notice": ("public", "oa", "yuketang"), "grade": ("jw",), "exam": ("jw",),
                 "course": ("mystu", "yuketang"), "task": ("mystu", "yuketang"),
                 "resource": ("mystu", "yuketang"), "event": ("mystu",), "service": ("public",), "post": ("huyou",)}
LOGIN_COMMANDS = {"jw": "stu-mcp login school --services jw", "mystu": "stu-mcp login school --services mystu",
                  "repair": "stu-mcp login school --services repair", "yuketang": "stu-mcp login yuketang",
                  "webvpn": "stu-mcp login webvpn", "smartcard": "stu-mcp login smartcard",
                  "med_jw": "stu-mcp login med_jw", "duifene": "stu-mcp login duifene"}


def capability_view(result: dict, source: str, compact: bool) -> dict:
    if source not in CAPABILITY_SCOPES or type(compact) is not bool:
        raise AppError("invalid_source", "请从 get_capabilities 的来源选项中选择，compact 使用布尔值。")
    if source == "all" and not compact or "capability_catalog" not in result:
        return result
    value = deepcopy(result)
    catalog = value["capability_catalog"]
    special = {"wechat": "wechat_articles", "network": "campus_network_diagnostics", "local": "local_maintenance"}
    services = [item for item in catalog["services"] if source == "all"
                or source in {item.get("source_id"), item.get("login_id"), item.get("configuration_id")}
                or item["service_id"] == special.get(source)]
    omitted = sum(item["integration"] != "implemented" for item in services) if compact else 0
    if compact:
        services = [item for item in services if item["integration"] == "implemented"]
        keep = ("service_id", "label", "integration", "scope", "source_id", "login_id", "configuration_id",
                "setup_command", "features", "limits", "state", "evidence")
        catalog["services"] = [{key: item[key] for key in keep if key in item} for item in services]
    else:
        catalog["services"] = services
    ids = {item["service_id"] for item in services}
    profiles = []
    for profile in catalog["profiles"]:
        matching = [identity for identity in profile["service_ids"] if identity in ids]
        if not matching:
            continue
        profiles.append({key: profile[key] for key in
                         ("configuration_id", "label", "setup_command", "setup_on", "setup_ui")}
                        | {"service_ids": matching})
    catalog["profiles"] = profiles
    if source != "all":
        selected = {item["source_id"] for item in services if item.get("source_id")}
        value["sources"] = [item for item in value["sources"] if item["source"] in selected]
        value["freshness"] = [item for item in value["freshness"] if item["source"] in selected]
        for key in ("profile", "repair", "checkin", "takeout", "network_diagnostics", "network_audit", "webvpn_auto_login"):
            relevant = {"profile": {"local"}, "repair": {"repair", "school"}, "checkin": {"duifene"}, "takeout": {"takeout"},
                        "network_diagnostics": {"network"}, "network_audit": {"network"},
                        "webvpn_auto_login": {"oa", "webvpn"}}.get(key, set())
            if source not in relevant:
                value.pop(key, None)
        if "hosting" in value:
            flows = value["hosting"].get("login_flows", {})
            login_ids = {item["login_id"] for item in services if item.get("login_id")}
            if login_ids.intersection({"jw", "mystu", "repair"}):
                login_ids.add("school")
            value["hosting"]["login_flows"] = {key: flow for key, flow in flows.items() if key in login_ids}
    value["view"] = {"source": source, "compact": compact, "unintegrated_services_omitted": omitted}
    return value


def query_guidance(result: dict, kind: str, sources: tuple[str, ...]) -> dict:
    result["status"] = "partial" if result["unavailable"] or result["unverified_count"] or result["scan_capped"] else "ok"
    result["query_scope"] = "local_cache"
    if result["total_count"]:
        return result
    supported = tuple(source for source in sources if source in QUERY_SOURCES[kind])
    if not supported:
        result.update(empty_reason="unsupported_source_for_kind", next_action="choose_source",
                      supported_sources=list(QUERY_SOURCES[kind]))
        return result
    if result["unavailable"]:
        result.update(empty_reason="cache_unavailable", next_action="check_system_keyring")
        return result
    if result["scan_capped"] or result["unverified_count"]:
        result.update(empty_reason="unverified_or_limited_cache", next_action="refresh_source")
    if kind == "post":
        result.update(empty_reason="no_matching_cached_records", next_action="search_huyou_posts")
        return result
    auth = {item["source"]: item["status"] for item in result.get("auth", [])}
    fresh = {item["source"]: item for item in result["freshness"]}
    pending = [source for source in supported if not fresh.get(source, {}).get("success_at")]
    if len(supported) > 1 and any(source in {"public", "oa"} or auth.get(source) == "session_saved"
                                  for source in supported):
        pending = [source for source in pending if source in {"public", "oa"} or auth.get(source) == "session_saved"]
    if pending:
        anonymous = [source for source in pending if source in {"public", "oa"}]
        pending = anonymous or pending
        calls = [{"tool": "refresh_source", "arguments": {"source": source}} for source in pending
                 if source in {"public", "oa", "jw", "mystu", "yuketang"}
                 and auth.get(source, "session_saved") == "session_saved"]
        result["next_calls"] = calls
        result["empty_reason"] = "not_refreshed" if calls else "login_required"
        result["next_action"] = "refresh_source" if calls else "open_setup"
    else:
        result.setdefault("empty_reason", "no_matching_cached_records")
        result.setdefault("next_action", "refine_query")
    return result
