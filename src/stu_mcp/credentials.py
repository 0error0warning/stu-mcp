"""Approved credential backends, with explicit opt-in for a headless server.

The default remains the operating system keyring. STU_MCP_KEY_FILE names an
existing external Fernet master-key file; its contents never enter configuration
or tool responses. Each application's home contains only its encrypted mapping.
"""
from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from .runtime import AppError, Runtime, checkin_home

MAX_CREDENTIAL_BYTES = 1024 * 1024


def backend_name() -> str:
    """Report the explicit selection without reading any key or claiming health."""
    return "encrypted_file" if "STU_MCP_KEY_FILE" in os.environ else "os_keyring"


class KeyStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class SystemKeyStore:
    # Do not silently select plaintext, chained third-party or null backends.
    APPROVED = frozenset({"keyring.backends.Windows", "keyring.backends.macOS",
                          "keyring.backends.SecretService", "keyring.backends.kwallet"})

    def __init__(self):
        import keyring
        backend = keyring.get_keyring()
        if type(backend).__module__ == "keyring.backends.chainer":
            backend = next((b for b in backend.backends if type(b).__module__ in self.APPROVED), backend)
        if type(backend).__module__ not in self.APPROVED:
            raise AppError("secure_storage_unavailable", "系统密钥库不可用；公开功能仍可使用。")
        self.backend = backend

    def get_password(self, service: str, username: str) -> str | None:
        return self.backend.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        self.backend.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        from keyring.errors import PasswordDeleteError
        try:
            self.backend.delete_password(service, username)
        except PasswordDeleteError:
            if self.backend.get_password(service, username) is not None:
                raise


def _storage_error(message: str) -> AppError:
    return AppError("secure_storage_unavailable", message)


def _reject_links(path: Path) -> None:
    """Reject symlinks and Windows junction/reparse paths, including ancestors."""
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise _storage_error("安全凭据路径包含链接，已停止操作。")


def validate_secret_directory(path: Path) -> None:
    """Apply the credential path policy before explicit secret initialization."""
    _reject_links(path)
    for home in _known_homes(Runtime.default().home):
        if path.resolve().is_relative_to(home.expanduser().resolve()):
            raise AppError("unsafe_secret_directory", "密钥目录必须位于 MCP 与签到数据目录之外。")


def _check_private_file(info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise _storage_error("安全凭据文件必须是独立的普通文件。")
    if os.name != "nt" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise _storage_error("安全凭据文件须属于当前用户，且不得向组或其他用户开放权限。")


def read_private_file(path: Path, *, limit: int = 65536) -> bytes:
    """Read a bounded private regular file without exposing its path or contents.

    On POSIX the file must belong to the effective user and have no group/other
    permissions. Windows uses the host account's ACLs; links/reparse points and
    hardlinks are rejected on both platforms. No permission is silently changed.
    """
    try:
        if type(limit) is not int or not 0 < limit <= 4 * MAX_CREDENTIAL_BYTES:
            raise _storage_error("安全凭据文件的读取上限无效。")
        path = Path(path).expanduser().absolute()
        _reject_links(path)
        before = path.lstat()
        _check_private_file(before)
        if before.st_size > limit:
            raise _storage_error("安全凭据文件超过允许的大小。")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            _check_private_file(opened)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise _storage_error("安全凭据文件在读取时发生变化，请重试。")
            value = stream.read(limit + 1)
        _reject_links(path)
        if len(value) > limit:
            raise _storage_error("安全凭据文件超过允许的大小。")
        return value
    except AppError:
        raise
    except (OSError, ValueError, TypeError):
        raise _storage_error("无法读取安全凭据文件；请检查文件、路径及访问权限。") from None


def _master_cipher(path: Path) -> Fernet:
    value = read_private_file(path, limit=46)
    if value.endswith(b"\r\n"):
        value = value[:-2]
    elif value.endswith(b"\n"):
        value = value[:-1]
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
        if len(value) != 44 or len(raw) != 32 or base64.urlsafe_b64encode(raw) != value:
            raise ValueError
        return Fernet(value)
    except (ValueError, TypeError):
        raise _storage_error("服务器主密钥文件须包含一个有效的 Fernet 密钥。") from None


def _known_homes(home: Path) -> tuple[Path, ...]:
    # A shared master must stay outside either application's data directory.
    return home, Runtime.default().home, checkin_home()


class FileKeyStore:
    """An encrypted, atomically replaced keyring mapping, never a plaintext fallback."""

    def __init__(self, home: Path, key_file: Path):
        try:
            self.home = Path(home).expanduser().absolute()
            self.path = self.home / "credentials.enc"
            key_file = Path(key_file).expanduser()
            if not key_file.is_absolute():
                raise _storage_error("服务器主密钥文件必须使用绝对路径。")
            _reject_links(self.home)
            _reject_links(key_file)
            key_file = key_file.resolve()
            for application_home in _known_homes(self.home):
                if key_file.is_relative_to(application_home.expanduser().resolve()):
                    raise _storage_error("服务器主密钥文件必须保存在两个应用的数据目录之外。")
            self._cipher = _master_cipher(key_file)
        except AppError:
            raise
        except (OSError, ValueError, TypeError):
            raise _storage_error("服务器安全存储配置不可用，请检查外置主密钥文件。") from None

    @contextmanager
    def _lock(self):
        """Serialize short read/modify/write transactions across processes."""
        stream = None
        locked = False
        try:
            _reject_links(self.home)
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = self.home / ".credentials-lock"
            _reject_links(path)
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            flags |= getattr(os, "O_NONBLOCK", 0)
            stream = os.fdopen(os.open(path, flags, 0o600), "r+b")
            _check_private_file(os.fstat(stream.fileno()))
            if not os.fstat(stream.fileno()).st_size:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 3
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise _storage_error("安全凭据正在由其他进程更新，请稍后重试。") from None
                    time.sleep(0.025)
            yield
        except AppError:
            raise
        except (OSError, ValueError, TypeError):
            raise _storage_error("无法更新加密凭据文件；未退回明文保存。") from None
        finally:
            if stream is not None:
                try:
                    if locked:
                        stream.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    raise _storage_error("无法释放安全凭据文件锁，请检查存储状态。") from None
                finally:
                    stream.close()

    def _read(self) -> dict[str, dict[str, str]]:
        try:
            _reject_links(self.path)
            try:
                self.path.lstat()
            except FileNotFoundError:
                return {}
            payload = self._cipher.decrypt(read_private_file(self.path, limit=MAX_CREDENTIAL_BYTES))
            value = json.loads(payload, object_pairs_hook=_unique_object)
            if not isinstance(value, dict) or set(value) != {"version", "entries"}:
                raise ValueError
            if type(value["version"]) is not int or value["version"] != 1:
                raise ValueError
            entries = value["entries"]
            if not isinstance(entries, dict) or any(
                not isinstance(service, str) or not isinstance(accounts, dict)
                or any(not isinstance(user, str) or not isinstance(secret, str)
                       for user, secret in accounts.items())
                for service, accounts in entries.items()
            ):
                raise ValueError
            return entries
        except AppError:
            raise
        except (OSError, InvalidToken, ValueError, TypeError, UnicodeError):
            raise _storage_error("加密凭据无法读取或主密钥不匹配；已保留原文件，请恢复密钥或备份。") from None

    def _write(self, entries: dict[str, dict[str, str]]) -> None:
        payload = json.dumps({"version": 1, "entries": entries}, ensure_ascii=False).encode("utf-8")
        encrypted = self._cipher.encrypt(payload)
        if len(encrypted) > MAX_CREDENTIAL_BYTES:
            raise _storage_error("加密凭据超过允许的大小，无法保存。")
        _reject_links(self.path)
        fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=self.home)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            _reject_links(self.path)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get_password(self, service: str, username: str) -> str | None:
        with self._lock():
            return self._read().get(service, {}).get(username)

    def set_password(self, service: str, username: str, password: str) -> None:
        if not all(isinstance(value, str) for value in (service, username, password)):
            raise _storage_error("凭据必须使用文本值。")
        with self._lock():
            entries = self._read()
            entries.setdefault(service, {})[username] = password
            self._write(entries)

    def delete_password(self, service: str, username: str) -> None:
        with self._lock():
            entries = self._read()
            if username in entries.get(service, {}):
                del entries[service][username]
                if not entries[service]:
                    del entries[service]
                self._write(entries)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def configured_key_store(home: Path) -> KeyStore:
    """Use the OS keyring unless an external master-key path is explicitly set."""
    key_file = os.environ.get("STU_MCP_KEY_FILE")
    if key_file is not None:
        if not key_file.strip():
            raise _storage_error("STU_MCP_KEY_FILE 已设置但没有指定主密钥文件。")
        return FileKeyStore(home, Path(key_file))
    return SystemKeyStore()
