"""Private per-user runtime paths; never read a project .env or Hermes home."""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path


class AppError(Exception):
    def __init__(self, code: str, message: str, source: str | None = None):
        super().__init__(message)
        self.code, self.message, self.source = code, message, source

    def result(self) -> dict:
        return {"ok": False, "status": self.code, "message": self.message, "source": self.source}


def private_write(path: Path, data: bytes) -> None:
    reject_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise AppError("unsafe_path", "目标是符号链接，已停止写入。")
    fd, name = tempfile.mkstemp(prefix=".stu-", dir=path.parent)
    try:
        os.chmod(name, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def reject_symlinks(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise AppError("unsafe_path", "路径包含符号链接，已停止操作。")


@contextmanager
def key_lock(home: Path, name: str = "key"):
    """Serialize key creation / short session mutations across MCP processes."""
    if name not in {"key", "webvpn", "webvpn-login", "jw", "mystu", "yuketang"}:
        raise AppError("unknown_lock", "不支持此本地状态锁。")
    path = home / f".{name}-lock"
    reject_symlinks(path)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as stream:
        os.chmod(path, 0o600)
        if not path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 5
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AppError("local_state_busy", "本地安全状态正在变更，请稍后重试。") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class Runtime:
    home: Path

    @classmethod
    def default(cls) -> Runtime:
        raw = os.environ.get("STU_MCP_HOME")
        return cls(Path(raw).expanduser().resolve() if raw else user_data_path("stu-mcp", appauthor=False))

    def ensure(self) -> None:
        reject_symlinks(self.home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.home.chmod(0o700)

    @property
    def db(self) -> Path:
        return self.home / "cache.sqlite3"

    def session_file(self, service: str) -> Path:
        if service not in ("webvpn", "mystu", "jw", "yuketang"):
            raise AppError("unknown_service", "不支持此登录服务。")
        return self.home / "sessions" / f"{service}.enc"

    def profile(self) -> dict:
        path = self.home / "profile.json"
        reject_symlinks(path)
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (ValueError, OSError):
            return {}

    def save_profile(self, fields: dict) -> dict:
        allowed = {"college", "major", "entry_year", "interests"}
        if set(fields) - allowed:
            raise AppError("invalid_profile", "画像只接受学院、专业、入学年份和关注方向。")
        if len(json.dumps(fields, ensure_ascii=False)) > 4000:
            raise AppError("invalid_profile", "画像内容过长。")
        if any(not isinstance(v, str) for v in fields.values()):
            raise AppError("invalid_profile", "画像字段必须是文字，不接收账号凭据或复杂对象。")
        profile = self.profile() | fields
        private_write(self.home / "profile.json", json.dumps(profile, ensure_ascii=False).encode())
        return profile

    def preferences(self) -> dict:
        path = self.home / "preferences.json"
        reject_symlinks(path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            value = {}
        return {"jw_http_compat": isinstance(value, dict) and value.get("jw_http_compat") is True}

    def save_preferences(self, fields: dict) -> dict:
        if set(fields) != {"jw_http_compat"} or type(fields["jw_http_compat"]) is not bool:
            raise AppError("invalid_preferences", "教务 HTTP 兼容选项必须明确设置为开启或关闭。")
        private_write(self.home / "preferences.json", json.dumps(fields).encode())
        return fields
