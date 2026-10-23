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
    def __init__(self, code: str, message: str, source: str | None = None, *,
                 http_status: int | None = None, retry_after_seconds: int | None = None,
                 network: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.source = code, message, source
        self.http_status, self.retry_after_seconds = http_status, retry_after_seconds
        self.network = network

    def result(self) -> dict:
        actions = {
            "needs_login": "open_setup", "login_expired": "open_setup", "needs_elc_login": "open_setup",
            "session_invalid": "open_setup", "session_changed": "refresh_source",
            "rate_limited": "wait_then_retry", "source_unavailable": "retry_later",
            "network_error": "check_network", "request_timeout": "retry_later",
            "access_denied": "open_source_page", "not_found": "refresh_then_check_source",
            "source_rejected": "open_source_page", "schema_changed": "report_source_change",
            "activity_password_required": "open_source_page", "resource_locked": "open_source_page",
            "resource_login_required": "open_source_page", "unsupported_activity": "check_supported_scope",
            "request_deadline": "reduce_scope", "request_limit": "reduce_scope",
            "refresh_running": "wait_then_retry", "secure_storage_unavailable": "check_system_keyring",
            "render_unavailable": "check_local_browser", "media_unavailable": "retry_media",
            "operation_failed": "check_local_state", "source_error": "report_source_change",
            "response_too_large": "reduce_scope",
            "authentication_network_error": "check_dns_and_route",
            "authentication_outcome_unknown": "verify_source_login",
            "authentication_schema_changed": "report_source_change",
            "interaction_required": "complete_source_challenge",
            "host_cli_required": "run_host_cli",
            "repair_login_required": "run_host_cli",
            "oa_http_compat_required": "choose_transport_compatibility",
            "oa_route_unavailable": "check_source_resource_catalog",
            "repair_direct_unavailable": "diagnose_campus_network",
            "network_diagnosis_running": "wait_then_retry",
            "takeout_not_configured": "configure_on_host_cli",
            "takeout_config_rejected": "update_takeout_config_on_host",
            "update_busy": "finish_active_operations",
            "update_repair_active": "finish_active_operations",
            "update_worker_active": "stop_checkin_service",
            "update_setup_active": "restart_mcp",
            "update_restart_required": "restart_mcp",
            "update_installation_unsupported": "update_with_original_installer",
            "update_network_error": "check_network",
            "update_state_changed": "check_updates",
            "update_rate_limited": "retry_later",
        }
        result = {"ok": False, "status": self.code, "message": self.message, "source": self.source,
                  "retryable": self.code in {"rate_limited", "source_unavailable", "network_error",
                                              "request_timeout", "refresh_running", "media_unavailable"},
                  "next_action": actions.get(self.code, "check_request")}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        if self.network is not None:
            result["network"] = dict(self.network)
            if self.network.get("failure_layer") in {"dns", "tls", "tls_verification", "connect_or_tls"}:
                result["retryable"] = False
                result["next_action"] = ("check_dns_and_route" if self.network["failure_layer"] == "dns"
                                         else "check_tls" if self.network["failure_layer"] in {"tls", "tls_verification"}
                                         else "check_network")
        return result


def checkin_home() -> Path:
    """One physical worker home for the MCP client and the independent worker."""
    raw = os.environ.get("STU_CHECKIN_HOME")
    if raw:
        return Path(raw).expanduser().resolve()
    # Packaged desktop clients may redirect LocalAppData per process.
    return Path.home() / ".local" / "share" / "stu-checkin"


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
    if name not in {"key", "webvpn", "webvpn-login", "jw", "mystu", "yuketang", "repair", "takeout"}:
        raise AppError("unknown_lock", "不支持此本地状态锁。")
    path = home / f".{name}-lock"
    reject_symlinks(path)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as stream:
        os.chmod(path, 0o600)
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
            # Windows permits locking past EOF. Initialize only while holding
            # byte zero, so another holder cannot reject a pre-lock flush.
            if not os.fstat(stream.fileno()).st_size:
                stream.write(b"0")
                stream.flush()
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
        if service not in ("webvpn", "mystu", "jw", "yuketang", "repair", "takeout"):
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
        result = {"jw_http_compat": isinstance(value, dict) and value.get("jw_http_compat") is True}
        if isinstance(value, dict) and "oa_http_compat" in value:
            result["oa_http_compat"] = value.get("oa_http_compat") is True
        return result

    def save_preferences(self, fields: dict) -> dict:
        if (not fields or set(fields) - {"jw_http_compat", "oa_http_compat"}
                or any(type(value) is not bool for value in fields.values())):
            raise AppError("invalid_preferences", "HTTP 兼容选项必须明确设置为开启或关闭。")
        result = self.preferences() | fields
        private_write(self.home / "preferences.json", json.dumps(result).encode())
        return result
