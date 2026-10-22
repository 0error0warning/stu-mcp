from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager

import pytest

from stu_mcp.update_guard import UpdateBusy, exclusive_update, other_instances, register_instance


@pytest.fixture
def installation(tmp_path):
    return {"prefix": tmp_path / "python", "cache_dir": tmp_path / "cache"}


@contextmanager
def child_instance(installation, tmp_path, kind):
    ready = tmp_path / "ready"
    script = """
import sys
import time
from pathlib import Path
from stu_mcp.update_guard import register_instance
lease = register_instance(sys.argv[4], prefix=Path(sys.argv[1]), cache_dir=Path(sys.argv[2]))
Path(sys.argv[3]).write_text('ready')
time.sleep(60)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(installation["prefix"]),
         str(installation["cache_dir"]), str(ready), kind],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "Child did not acquire its synthetic instance lease"
        yield child
    finally:
        if child.poll() is None:
            child.kill()
        _stdout, stderr = child.communicate(timeout=5)
        assert not stderr, stderr.decode(errors="replace")


def test_instance_closes_idempotently_and_exclusion_is_explicit(installation):
    lease = register_instance(**installation)
    try:
        assert other_instances(**installation)
        assert not other_instances(exclude_pid=os.getpid(), **installation)
        with pytest.raises(UpdateBusy, match="其他 MCP"), exclusive_update(**installation):
            pytest.fail("An instance must block a CLI update")
        with exclusive_update(exclude_pid=os.getpid(), **installation):
            pass
    finally:
        lease.close()
        lease.close()
    assert not other_instances(**installation)


def test_update_excludes_registrations_and_another_update(installation):
    with exclusive_update(**installation):
        with pytest.raises(UpdateBusy, match="正在更新"):
            register_instance(**installation)
        with pytest.raises(UpdateBusy, match="正在更新"), exclusive_update(**installation):
            pytest.fail("Two installers must not share the update gate")
    with register_instance(**installation):
        assert other_instances(**installation)


@pytest.mark.parametrize("operation", ["register_instance", "exclusive_update"])
def test_update_gate_is_enforced_in_another_process(installation, operation):
    script = """
import sys
from pathlib import Path
from stu_mcp.update_guard import UpdateBusy, exclusive_update, register_instance
operation = {'register_instance': register_instance, 'exclusive_update': exclusive_update}[sys.argv[3]]
try:
    with operation(prefix=Path(sys.argv[1]), cache_dir=Path(sys.argv[2])):
        pass
except UpdateBusy:
    sys.exit(7)
sys.exit(9)
"""
    with exclusive_update(**installation):
        result = subprocess.run(
            [sys.executable, "-c", script, str(installation["prefix"]),
             str(installation["cache_dir"]), operation],
            capture_output=True, timeout=10,
        )
    assert result.returncode == 7, result.stderr.decode(errors="replace")


@pytest.mark.parametrize("kind", ["mcp", "checkin"])
def test_other_process_blocks_update_and_death_releases_os_lease(installation, tmp_path, kind):
    with child_instance(installation, tmp_path, kind):
        assert other_instances(exclude_pid=os.getpid(), **installation)
        with pytest.raises(UpdateBusy), exclusive_update(exclude_pid=os.getpid(), **installation):
            pytest.fail("A live independent instance must block updating its installation")
    # SIGKILL/TerminateProcess leaves a stale file, but the kernel released its lock.
    assert not other_instances(**installation)
    with exclusive_update(**installation):
        pass


def test_pid_text_without_an_os_lock_is_not_a_live_instance(installation):
    lease = register_instance(**installation)
    path = lease._path
    lease.close()
    path.write_bytes(b"0")
    assert f".{os.getpid()}." in path.name
    assert not other_instances(**installation)
    assert not path.exists()


def test_runtime_home_does_not_split_the_installation_guard(installation, tmp_path, monkeypatch):
    monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "first-home"))
    with register_instance(**installation):
        monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "second-home"))
        with pytest.raises(UpdateBusy), exclusive_update(**installation):
            pytest.fail("A second data home must not evade an installation lease")
        separate = installation | {"prefix": tmp_path / "another-python"}
        with exclusive_update(**separate):
            pass


def test_context_exception_releases_lease_and_update_gate(installation):
    with pytest.raises(ValueError), register_instance(**installation):
        raise ValueError("synthetic failure")
    with pytest.raises(ValueError), exclusive_update(**installation):
        raise ValueError("synthetic failure")
    assert not other_instances(**installation)
    with exclusive_update(**installation):
        pass


def test_unknown_instance_kind_is_rejected(installation):
    with pytest.raises(ValueError):
        register_instance("../other", **installation)
