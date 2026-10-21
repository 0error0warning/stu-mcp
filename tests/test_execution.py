"""Execution labels are explicit metadata, never discovered machine identities."""
import json
import socket
from types import SimpleNamespace

import pytest

from stu_mcp import execution
from stu_mcp.execution import execution_context


def test_execution_context_is_safe_without_configuration(monkeypatch):
    monkeypatch.delenv("STU_MCP_INSTANCE_NAME", raising=False)
    monkeypatch.setattr(socket, "gethostname", lambda: pytest.fail("do not read the hostname"))
    monkeypatch.setattr(socket, "gethostbyname", lambda *_: pytest.fail("do not resolve the host"))
    monkeypatch.setenv("COMPUTERNAME", "PRIVATE_MACHINE")
    monkeypatch.setenv("HOSTNAME", "PRIVATE_MACHINE")
    result = execution_context()
    assert result == {"scope": "mcp_host", "instance_name": "unnamed", "client_network_checked": False,
                      "school_route_automatic": False, "physical_location_detection": False,
                      "client_connection_check": "transport_handshake_only"}
    assert "PRIVATE_MACHINE" not in json.dumps(result)


@pytest.mark.parametrize("value", ["", " ", "a" * 65, "private.example", "192.168.1.2", "::1",
                                   "https://private.invalid", "C:\\Users\\PRIVATE", "/home/PRIVATE",
                                   "name\ninjected", "name\x00private", "<script>", "-server"])
def test_invalid_labels_fall_back_without_exporting_raw_value(monkeypatch, value):
    monkeypatch.setattr(execution, "os", SimpleNamespace(environ={"STU_MCP_INSTANCE_NAME": value}))
    assert execution_context()["instance_name"] == "unnamed"


@pytest.mark.parametrize("value,expected", [("student-server", "student-server"), (" home_PC-2 ", "home_PC-2"),
                                          ("a" * 64, "a" * 64)])
def test_explicit_labels_are_bounded_and_detached(monkeypatch, value, expected):
    monkeypatch.setenv("STU_MCP_INSTANCE_NAME", value)
    first = execution_context()
    assert first["instance_name"] == expected
    first["scope"] = "client"
    monkeypatch.setenv("STU_MCP_INSTANCE_NAME", "replacement")
    second = execution_context()
    assert second["instance_name"] == "replacement" and second["scope"] == "mcp_host"
