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
from types import SimpleNamespace

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


def test_committed_contract_has_all_45_unique_public_interfaces():
    baseline = contract()
    assert len(baseline) == len({tool["name"] for tool in baseline}) == 47
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
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     listener_port=first_port)
    other = None
    try:
        other = runtime.OwnedHTTPProcess([sys.executable, "-c", listener_code(second_port)], env=os.environ.copy(),
                                         cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         listener_port=second_port)
        wait_listener(first_port, owned.process)
        owned.listener_seen = True
        wait_listener(second_port, other.process)
        other.listener_seen = True
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


def denied_group(monkeypatch, number, *, platform="darwin", returncode=0, seen=True):
    owned = object.__new__(runtime.OwnedHTTPProcess)
    owned.process = SimpleNamespace(pid=987654321, returncode=returncode)
    owned.listener_port, owned.listener_seen = number, seen
    calls = []

    def denied(pid, sig):
        calls.append((pid, sig))
        raise PermissionError("synthetic exited process group")

    monkeypatch.setattr(runtime.sys, "platform", platform)
    monkeypatch.setattr(runtime.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(runtime.os, "killpg", denied, raising=False)
    return owned, calls


def test_darwin_exited_group_eperm_requires_known_listener_to_be_closed(monkeypatch):
    owned, calls = denied_group(monkeypatch, port())
    owned._kill_remaining_group()
    assert calls == [(owned.process.pid, runtime.signal.SIGKILL)]


def test_darwin_exited_group_eperm_does_not_hide_a_live_listener(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        owned, calls = denied_group(monkeypatch, listener.getsockname()[1])
        with pytest.raises(RuntimeError, match="listener remained open"):
            owned._kill_remaining_group()
        assert calls == [(owned.process.pid, runtime.signal.SIGKILL)]


@pytest.mark.parametrize("platform,returncode,seen", [
    ("linux", 0, True), ("darwin", None, True), ("darwin", 0, False),
])
def test_group_eperm_outside_confirmed_darwin_cleanup_remains_an_error(monkeypatch, platform, returncode, seen):
    owned, calls = denied_group(monkeypatch, port(), platform=platform, returncode=returncode, seen=seen)
    with pytest.raises(PermissionError):
        owned._kill_remaining_group()
    assert calls == [(owned.process.pid, runtime.signal.SIGKILL)]
