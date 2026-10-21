"""Offline release-check boundaries, including owned child-tree cleanup."""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest
from mcp_types import Tool

_SPEC = importlib.util.spec_from_file_location(
    "_stu_release_runtime_check", Path(__file__).resolve().parents[1] / "scripts" / "check_http_runtime.py")
assert _SPEC is not None and _SPEC.loader is not None
runtime = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runtime
_SPEC.loader.exec_module(runtime)


def contract():
    return json.loads(runtime.CONTRACT.read_text(encoding="utf-8"))["tools"]


def tools(payload):
    return [Tool.model_validate(value) for value in payload]


def test_committed_contract_has_all_38_unique_public_interfaces():
    baseline = contract()
    assert len(baseline) == len({tool["name"] for tool in baseline}) == 38
    assert runtime.assert_tool_contract(tools(baseline)) == []


def test_description_changes_are_reported_without_breaking_tool_interfaces():
    payload = contract()
    payload[0]["description"] = "Synthetic clarification."
    assert runtime.assert_tool_contract(tools(payload)) == [payload[0]["name"]]


@pytest.mark.parametrize("field,value", [
    ("name", "synthetic_changed_tool"),
    ("inputSchema", {"type": "object", "required": ["new_required_field"]}),
    ("outputSchema", {"type": "array"}),
    ("annotations", {"readOnlyHint": False, "destructiveHint": True}),
])
def test_public_contract_changes_fail_instead_of_only_counting_tools(field, value):
    payload = deepcopy(contract())
    payload[0][field] = value
    with pytest.raises(AssertionError):
        runtime.assert_tool_contract(tools(payload))


@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_missing_or_duplicate_tools_are_rejected(change):
    payload = contract()
    if change == "missing":
        payload.pop()
    else:
        payload[-1] = deepcopy(payload[0])
    with pytest.raises(AssertionError):
        runtime.assert_tool_contract(tools(payload))


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_listener(number, process):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        assert process.poll() is None, "synthetic listener exited during startup"
        try:
            with socket.create_connection(("127.0.0.1", number), timeout=.1):
                return
        except OSError:
            time.sleep(.05)
    raise AssertionError("synthetic listener did not start")


def listener_code(number):
    return ("import socket,time; s=socket.socket(); s.bind(('127.0.0.1'," + str(number)
            + ")); s.listen(8); time.sleep(30)")


def test_cleanup_reaps_own_descendant_listener_and_preserves_another_process(tmp_path):
    first_port, second_port = port(), port()
    descendant = listener_code(first_port)
    parent = ("import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"
              + repr(descendant) + "]); time.sleep(30)")
    owned = runtime.OwnedHTTPProcess([sys.executable, "-c", parent], env=os.environ.copy(), cwd=tmp_path,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    other = None
    try:
        other = runtime.OwnedHTTPProcess([sys.executable, "-c", listener_code(second_port)], env=os.environ.copy(),
                                         cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_listener(first_port, owned.process)
        wait_listener(second_port, other.process)
        owned.close()
        owned.close()  # Idempotent; no process/port scan or PID reuse on another close.
        assert owned.process.poll() is not None
        runtime.assert_listener_closed(first_port)
        assert other.process.poll() is None
        with socket.create_connection(("127.0.0.1", second_port), timeout=.5):
            pass
    finally:
        owned.close()
        if other is not None:
            other.close()
    runtime.assert_listener_closed(second_port)
