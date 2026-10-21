"""Explicit operator-only creation of independent server secret files."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .credentials import validate_secret_directory
from .runtime import AppError


def initialize_secrets(directory: Path) -> dict:
    directory = directory.expanduser().absolute()
    validate_secret_directory(directory)
    try:
        # A new directory provides atomic no-overwrite behavior across operators.
        # Never modify an existing directory, credentials or configuration.
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError:
        raise AppError("secret_directory_exists", "密钥目录已存在；未覆盖或轮换任何密钥。") from None
    paths = {"master_key_file": directory / "master.key", "auth_token_file": directory / "http-token"}
    values = {"master_key_file": Fernet.generate_key(), "auth_token_file": secrets.token_urlsafe(48).encode()}
    created = []
    try:
        for key, path in paths.items():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(values[key] + b"\n")
    except OSError:
        # Only remove files this call created, and only an empty directory.
        # Never recursively clean a user-selected directory or touch old keys.
        try:
            for path in created:
                path.unlink(missing_ok=True)
            directory.rmdir()
        except OSError:
            raise AppError("secret_initialization_incomplete", "初始化未完成，且无法撤销本轮新建文件；"
                           "请本人检查目标目录，未自动覆盖或重试。") from None
        raise AppError("secret_initialization_failed", "初始化未完成，本轮新建文件已撤销；"
                       "请检查目录权限或磁盘后重试。") from None
    return {"ok": True, "status": "server_secrets_created", **{key: str(path) for key, path in paths.items()},
            "message": "已创建独立随机主密钥和 HTTP 令牌；仅输出路径。请自行保护 ACL/权限，"
            "密钥与数据分开备份；未修改客户端配置或启动服务。"}
