"""Real OS locks protect initialization as well as the critical section."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from stu_mcp.runtime import key_lock


def test_two_threads_lock_an_empty_file_before_initializing_it(tmp_path, monkeypatch):
    """Force both first lock attempts to see EOF, then force real contention."""
    barrier = threading.Barrier(2)
    first_entered, release_first, contended = threading.Event(), threading.Event(), threading.Event()
    observation_lock = threading.Lock()
    attempted, sizes, entered = set(), [], []
    active = 0
    if os.name == "nt":
        import msvcrt
        native, acquire_operation = msvcrt.locking, msvcrt.LK_NBLCK
        target, attribute = msvcrt, "locking"
    else:
        import fcntl
        native, acquire_operation = fcntl.flock, fcntl.LOCK_EX | fcntl.LOCK_NB
        target, attribute = fcntl, "flock"

    def synchronized_lock(fd, operation, *args):
        if operation == acquire_operation:
            thread = threading.get_ident()
            with observation_lock:
                first_attempt = thread not in attempted
                if first_attempt:
                    attempted.add(thread)
                    sizes.append(os.fstat(fd).st_size)
            if first_attempt:
                barrier.wait(timeout=5)
            try:
                return native(fd, operation, *args)
            except OSError:
                contended.set()
                raise
        return native(fd, operation, *args)

    monkeypatch.setattr(target, attribute, synchronized_lock)

    def use_lock(number):
        nonlocal active
        with key_lock(tmp_path, "webvpn-login"):
            with observation_lock:
                active += 1
                assert active == 1
                entered.append(number)
                first = len(entered) == 1
            if first:
                first_entered.set()
                assert release_first.wait(timeout=5)
            with observation_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(use_lock, number) for number in (1, 2)]
        try:
            assert first_entered.wait(timeout=5)
            assert contended.wait(timeout=5)
            assert len(entered) == 1
            assert sizes == [0, 0]
        finally:
            release_first.set()
        for result in pending:
            result.result(timeout=5)
    assert sorted(entered) == [1, 2] and active == 0
    assert (tmp_path / ".webvpn-login-lock").read_bytes() == b"0"


def test_lock_initializes_once_and_is_reusable_after_body_failure(tmp_path):
    path = tmp_path / ".key-lock"
    try:
        with key_lock(tmp_path):
            assert path.stat().st_size == 1
            raise RuntimeError("synthetic failure")
    except RuntimeError:
        pass
    with key_lock(tmp_path):
        assert path.stat().st_size == 1
    assert path.read_bytes() == b"0"


def test_initialization_failure_also_releases_the_native_lock(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        def failed_stat(_fd):
            raise PermissionError("synthetic initialization failure")
        patch.setattr(os, "fstat", failed_stat)
        with pytest.raises(PermissionError, match="synthetic initialization failure"), key_lock(tmp_path):
            pytest.fail("initialization did not finish")
    with key_lock(tmp_path):
        assert (tmp_path / ".key-lock").stat().st_size == 1
