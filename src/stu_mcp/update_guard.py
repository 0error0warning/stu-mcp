"""Installation-scoped leases for cooperating MCP and check-in processes.

The operating system owns lease lifetime. PID text only supports excluding the
calling process; it is never used as proof that another process is alive.
Older versions without leases are outside this guard's detection scope.
"""
from __future__ import annotations

import errno
import hashlib
import os
import sys
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import BinaryIO

from platformdirs import user_cache_path

from .runtime import reject_symlinks


class UpdateBusy(RuntimeError):
    """A cooperating process or another update owns this installation."""


def _directory(prefix: Path | None, cache_dir: Path | None) -> Path:
    identity = os.path.normcase(str(Path(prefix or sys.prefix).resolve()))
    digest = hashlib.sha256(os.fsencode(identity)).hexdigest()[:24]
    base = cache_dir if cache_dir is not None else user_cache_path("stu-mcp", appauthor=False)
    directory = Path(base) / "updates" / digest
    reject_symlinks(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def _acquire(path: Path) -> BinaryIO | None:
    reject_symlinks(path)
    stream = path.open("a+b")
    try:
        os.chmod(path, 0o600)
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError as exc:
        stream.close()
        if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
            return None
        raise


def _release(stream: BinaryIO) -> None:
    # Closing the descriptor releases the OS lock, including on process death.
    stream.close()


@contextmanager
def _gate(directory: Path):
    stream = _acquire(directory / "update.lock")
    if stream is None:
        raise UpdateBusy("同一安装正在更新，请稍后重试。")
    try:
        yield
    finally:
        _release(stream)


class InstanceLease:
    def __init__(self, path: Path, stream: BinaryIO):
        self._path, self._stream = path, stream

    def close(self) -> None:
        if self._stream.closed:
            return
        _release(self._stream)
        with suppress(PermissionError):
            self._path.unlink(missing_ok=True)

    def __enter__(self) -> InstanceLease:
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def register_instance(kind: str = "mcp", *, prefix: Path | None = None,
                      cache_dir: Path | None = None) -> InstanceLease:
    """Hold a lease until close; registration cannot race an exclusive update."""
    if kind not in {"mcp", "checkin"}:
        raise ValueError("Unsupported update-lease instance kind")
    directory = _directory(prefix, cache_dir)
    with _gate(directory):
        path = directory / f"instance.{os.getpid()}.{kind}.{uuid.uuid4().hex}.lock"
        stream = _acquire(path)
        if stream is None:
            raise UpdateBusy("无法注册当前运行实例。")
        return InstanceLease(path, stream)


def other_instances(*, exclude_pid: int | None = None, prefix: Path | None = None,
                    cache_dir: Path | None = None) -> bool:
    """Read OS leases, without credentials, home directories or PID probing."""
    directory = _directory(prefix, cache_dir)
    for path in directory.glob("instance.*.lock"):
        if exclude_pid is not None and path.name.split(".")[1] == str(exclude_pid):
            continue
        try:
            stream = _acquire(path)
        except FileNotFoundError:
            continue  # An instance closed between listing and opening its lease.
        if stream is None:
            return True
        _release(stream)
        # Each registration has a unique name, so a stale name is never reused.
        # A concurrent reader may still have the stale Windows handle.
        with suppress(PermissionError):
            path.unlink(missing_ok=True)
    return False


@contextmanager
def exclusive_update(*, exclude_pid: int | None = None, prefix: Path | None = None,
                     cache_dir: Path | None = None):
    """Block new registrations and reject all other active instance leases."""
    directory = _directory(prefix, cache_dir)
    with _gate(directory):
        if other_instances(exclude_pid=exclude_pid, prefix=prefix, cache_dir=cache_dir):
            raise UpdateBusy("请先停止同一安装的其他 MCP 实例和签到后台，再更新。")
        yield
