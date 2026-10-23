"""The shared MCP/CLI and setup views reuse local facts, never start authentication."""
from types import SimpleNamespace
from unittest.mock import Mock

from stu_mcp.hosting import HostRuntime


def test_app_and_host_publish_additive_catalog_without_authentication(app, monkeypatch):
    monkeypatch.setattr("stu_mcp.auth_http.login_http", Mock(side_effect=AssertionError("no sign in")))
    monkeypatch.setattr("stu_mcp.app.detected_clients", lambda: [])
    calls = []
    worker = SimpleNamespace(status=lambda: calls.append("passive_status") or {"status": "service_not_started"})
    host = HostRuntime(app, checkin=worker)
    try:
        local = app.status()
        remote = host.capabilities()
        assert calls == ["passive_status"]
        for old_key in ("sources", "repair", "takeout", "network_diagnostics", "network_audit"):
            assert old_key in local and old_key in remote
        assert len(local["sources"]) == 7
        assert remote["hosting"]["login_flows"]["school"]["input"] == "host_tty_once"
        assert not remote["hosting"]["login_flows"]["school"]["sessions_shared"]
        catalog = remote["capability_catalog"]
        school = next(p for p in catalog["profiles"] if p["configuration_id"] == "school")
        assert len(school["service_ids"]) == 3
        assert all(s["integration"] != "implemented" for s in catalog["services"]
                   if s["service_id"] in school["not_integrated_service_ids"])
        assert next(s for s in catalog["services"] if s["service_id"] == "duifene_checkin")["state"][
            "worker_status"] == "service_not_started"
    finally:
        host.close()
