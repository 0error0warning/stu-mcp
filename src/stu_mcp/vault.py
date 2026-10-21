"""Session encryption using a separately protected credential backend."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable

from cryptography.fernet import Fernet, InvalidToken

from .credentials import KeyStore as KeyStore
from .credentials import SystemKeyStore as SystemKeyStore
from .credentials import configured_key_store
from .runtime import AppError, Runtime, key_lock, private_write, reject_symlinks


class Vault:
    def __init__(self, runtime: Runtime, store: KeyStore | None = None):
        self.runtime, self._store = runtime, store
        self.account = hashlib.sha256(str(runtime.home.resolve()).encode()).hexdigest()[:24]
        # Packaged Windows apps can redirect LocalAppData only after the first
        # file is created. The first login then used the logical path's keyring
        # account, while the next process resolves the redirected path. Keep
        # that exact alias readable; never generate a replacement for its key.
        self._logical_account = hashlib.sha256(str(runtime.home.absolute()).encode()).hexdigest()[:24]

    def key_store(self) -> KeyStore:
        return self._store if self._store is not None else configured_key_store(self.runtime.home)

    def fingerprint(self, service: str) -> bytes | None:
        path = self.runtime.session_file(service)
        reject_symlinks(path)
        return hashlib.sha256(path.read_bytes()).digest() if path.is_file() else None

    def login_revision(self, service: str) -> bytes:
        """Caller holds the service lock when taking or comparing a login snapshot."""
        path = self.runtime.session_file(service).with_suffix(".generation")
        reject_symlinks(path)
        generation = path.read_bytes() if path.is_file() else b""
        return hashlib.sha256(generation + (self.fingerprint(service) or b"")).digest()

    def _key(self, create: bool = False) -> bytes:
        try:
            store = self.key_store()
            with key_lock(self.runtime.home):
                value = store.get_password("stu-mcp.session-key", self.account)
                if not value and self._logical_account != self.account:
                    value = store.get_password("stu-mcp.session-key", self._logical_account)
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
        # Caller holds the service lock; App.logout also removes this source's cache.
        path = self.runtime.session_file(service)
        reject_symlinks(path)
        if path.is_symlink():
            raise AppError("unsafe_path", "登录态文件是符号链接，已停止操作。")
        # A logout must also cancel a first login that has not saved any session yet.
        private_write(path.with_suffix(".generation"), uuid.uuid4().hex.encode("ascii"))
        path.unlink(missing_ok=True)
        return {"ok": True, "service": service, "status": "logged_out"}
