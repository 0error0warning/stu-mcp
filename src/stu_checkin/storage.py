"""Small encrypted state file, using the shared explicit credential policy."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from stu_mcp.credentials import configured_key_store
from stu_mcp.runtime import AppError, checkin_home, key_lock


class StorageError(RuntimeError):
    pass


def default_home() -> Path:
    return checkin_home()


class SecureStore:
    def __init__(self, home: Path, key_store=None):
        self.home = home.resolve()
        self.path = self.home / "state.enc"
        self.key_store = key_store
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    def _cipher(self, *, create: bool = False) -> Fernet:
        try:
            backend = self.key_store if self.key_store is not None else configured_key_store(self.home)
            account = "session:" + str(self.home)
            with key_lock(self.home):
                raw = backend.get_password("stu-checkin", account)
                if not raw and create:
                    raw = Fernet.generate_key().decode("ascii")
                    backend.set_password("stu-checkin", account, raw)
            if not raw:
                raise StorageError("找不到本机密钥，请重新连接微信。")
            return Fernet(raw.encode("ascii"))
        except StorageError:
            raise
        except AppError as exc:
            raise StorageError(exc.message) from None
        except Exception:
            raise StorageError("无法访问系统密钥库，请检查本机凭据服务。") from None

    def _read(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        if self.path.is_symlink() or any(p.is_symlink() for p in self.home.parents):
            raise StorageError("本地数据路径不可用。")
        if not self.path.exists():
            self._data = {"cookie": "", "settings": {}, "centers": {}, "events": []}
        else:
            try:
                data = json.loads(self._cipher().decrypt(self.path.read_bytes()))
                if not isinstance(data, dict):
                    raise ValueError
                self._data = data
            except (OSError, InvalidToken, ValueError, UnicodeError):
                raise StorageError("本机连接信息无法解密，请断开后重新连接。") from None
        return self._data

    def get(self, key: str, default=None):
        with self._lock:
            return copy.deepcopy(self._read().get(key, default))

    def update(self, **values) -> None:
        with self._lock:
            data = {**self._read(), **copy.deepcopy(values)}
            cipher = self._cipher(create=True)
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(prefix=".state-", dir=self.home)
            try:
                os.chmod(temporary, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(cipher.encrypt(json.dumps(data, ensure_ascii=False).encode()))
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self._data = data

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._data = {"cookie": "", "settings": {}, "centers": {}, "events": []}

    # Compatibility with the upstream engine's storage interface.
    def ensure_exists(self) -> bool:
        return False

    def load_cookie(self) -> str | None:
        return self.get("cookie") or None

    def save_cookie(self, cookie: str) -> None:
        self.update(cookie=cookie, events=[], centers={}, results=[])

    def load_settings(self) -> dict:
        return self.get("settings", {})

    def save_settings(self, values) -> None:
        self.update(settings=dict(values))

    def load_center(self, class_id: str):
        center = self.get("centers", {}).get(str(class_id))
        return tuple(center) if center else None

    def save_center(self, class_id: str, longitude: float, latitude: float) -> None:
        centers = self.get("centers", {})
        centers[str(class_id)] = [longitude, latitude]
        self.update(centers=centers)
