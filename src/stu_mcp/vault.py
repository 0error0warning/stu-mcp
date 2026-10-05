"""Session encryption. The encryption key exists only in an approved OS keyring."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from .runtime import AppError, Runtime, key_lock, private_write, reject_symlinks


class KeyStore(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


class SystemKeyStore:
    # Reject plaintext, chained third-party and null backends rather than relying on priority.
    APPROVED = frozenset({"keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService",
                         "keyring.backends.kwallet"})

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


class Vault:
    def __init__(self, runtime: Runtime, store: KeyStore | None = None):
        self.runtime, self._store = runtime, store
        self.account = hashlib.sha256(str(runtime.home.resolve()).encode()).hexdigest()[:24]

    def key_store(self) -> KeyStore:
        return self._store or SystemKeyStore()

    def fingerprint(self, service: str) -> bytes | None:
        path = self.runtime.session_file(service)
        reject_symlinks(path)
        return hashlib.sha256(path.read_bytes()).digest() if path.is_file() else None

    def _key(self, create: bool = False) -> bytes:
        try:
            store = self.key_store()
            with key_lock(self.runtime.home):
                value = store.get_password("stu-mcp.session-key", self.account)
                if not value and create:
                    value = Fernet.generate_key().decode("ascii")
                    store.set_password("stu-mcp.session-key", self.account, value)
            if not value:
                raise AppError("needs_login", "尚未建立本地登录会话，请打开设置页登录。")
            return value.encode("ascii")
        except AppError:
            raise
        except Exception:
            raise AppError("secure_storage_unavailable", "无法访问系统密钥库；未退回明文保存。") from None

    def _cipher(self, *, create: bool = False) -> Fernet:
        return Fernet(self._key(create=create))

    def protect(self, value: dict, *, cipher: Fernet | None = None) -> bytes:
        return (cipher or self._cipher(create=True)).encrypt(json.dumps(value, ensure_ascii=False).encode())

    def unprotect(self, value: bytes, *, cipher: Fernet | None = None) -> dict:
        try:
            result = json.loads((cipher or self._cipher()).decrypt(value))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (InvalidToken, ValueError, UnicodeError):
            raise AppError("session_invalid", "本地加密数据无效，请重新登录相关服务。") from None

    def save(self, service: str, state: dict, *, on_relogin: Callable[[], None] | None = None,
             guard: Callable[[], None] | None = None) -> bytes:
        if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
            raise AppError("session_invalid", "无法保存无效的登录态。", service)
        path = self.runtime.session_file(service)
        reject_symlinks(path)
        with key_lock(self.runtime.home, service):
            if guard:
                guard()
            payload = self.protect({"saved_at": time.time(), "state": state})
            if on_relogin:
                on_relogin()
            private_write(path, payload)
            return hashlib.sha256(payload).digest()

    def load(self, service: str) -> dict:
        path = self.runtime.session_file(service)
        if not path.is_file() or path.is_symlink():
            raise AppError("needs_login", "此功能需要单独登录；其他功能不受影响。", service)
        try:
            state = self.unprotect(path.read_bytes())["state"]
            if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
                raise ValueError
            return state
        except (OSError, KeyError, ValueError):
            raise AppError("session_invalid", "无法读取此服务的加密登录态。", service) from None

    def status(self, service: str) -> dict:
        try:
            state = self.load(service)
            expiries = [float(c.get("expires", -1)) for c in state.get("cookies", [])
                        if float(c.get("expires", -1)) > 0]
            if expiries and max(expiries) <= time.time():
                return {"status": "login_expired", "verified_live": False}
            return {"status": "session_saved", "verified_live": False}
        except (TypeError, ValueError, AttributeError):
            return {"status": "session_invalid", "verified_live": False}
        except AppError as exc:
            return {"status": exc.code, "verified_live": False}

    def logout(self, service: str) -> dict:
        # App.logout also removes this source's cache.
        path = self.runtime.session_file(service)
        reject_symlinks(path)
        if path.is_symlink():
            raise AppError("unsafe_path", "登录态文件是符号链接，已停止操作。")
        path.unlink(missing_ok=True)
        return {"ok": True, "service": service, "status": "logged_out"}
