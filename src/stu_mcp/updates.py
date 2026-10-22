"""On-demand official releases; CLI and MCP share this deterministic updater."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import platform
import re
import tempfile
import time
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from . import __version__
from .http_privacy import private_http_logging
from .runtime import AppError
from .update_guard import UpdateBusy, exclusive_update
from .update_install import install_wheel, probe_installation

REPOSITORY = "0error0warning/stu-mcp"
RELEASES = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
MAX_WHEEL = 20 * 1024 * 1024
ASSET_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def installed_version() -> str | None:
    try:
        return importlib.metadata.version("stu-mcp")
    except (importlib.metadata.PackageNotFoundError, OSError, UnicodeError, ValueError):
        return None


def _version(value: str) -> Version:
    try:
        version = Version(value.removeprefix("v"))
        if version.local or version.epoch or version.is_devrelease:
            raise InvalidVersion(value)
        return version
    except (InvalidVersion, TypeError, AttributeError):
        raise AppError("update_release_invalid", "官方发行版本信息无法识别，未执行安装。") from None


def _asset_url(value: str) -> str:
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.hostname not in ASSET_HOSTS or url.username or url.password
                or url.port not in (None, 443) or url.fragment):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise AppError("update_release_invalid", "发行文件地址不符合官方来源要求，未执行安装。") from None
    return value


def _fetch(client: httpx.Client, url: str, limit: int, *, asset: bool = False) -> bytes:
    deadline = time.monotonic() + 40
    for _ in range(6):
        if time.monotonic() > deadline:
            raise AppError("update_download_limit", "更新请求超过时间限制，未执行安装。")
        if asset:
            _asset_url(url)
        with client.stream("GET", url) as response:
            if response.is_redirect and asset:
                url = str(response.url.join(response.headers.get("location", "")))
                continue
            if response.status_code != 200:
                raise AppError("update_network_error", "无法读取官方发行信息或文件，请检查网络后重试。")
            parts, size = [], 0
            for part in response.iter_bytes():
                size += len(part)
                if size > limit or time.monotonic() > deadline:
                    raise AppError("update_download_limit", "更新文件超过大小或时间限制，未执行安装。")
                parts.append(part)
            return b"".join(parts)
    raise AppError("update_release_invalid", "发行文件重定向过多，未执行安装。")


def latest_release(client: httpx.Client) -> dict[str, Any]:
    """The project publishes student previews, so /releases/latest is insufficient."""
    try:
        releases = json.loads(_fetch(client, RELEASES, 4 * 1024 * 1024))
        if not isinstance(releases, list):
            raise ValueError
        candidates = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft") is not False or not release.get("published_at"):
                continue
            try:
                version = _version(release.get("tag_name", ""))
            except AppError:
                continue
            candidates.append((version, release))
        if not candidates:
            raise ValueError
        version, release = max(candidates, key=lambda pair: pair[0])
        tag = release["tag_name"]
        wheel = f"stu_mcp-{version}-py3-none-any.whl"
        assets = release.get("assets", [])
        selected = {}
        for name in (wheel, "SHA256SUMS.txt"):
            matches = [a for a in assets if isinstance(a, dict) and a.get("name") == name]
            if len(matches) != 1:
                raise ValueError
            url = _asset_url(matches[0]["browser_download_url"])
            if url != f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}":
                raise ValueError
            selected[name] = url
        return {"version": str(version), "tag": tag, "wheel": wheel, "assets": selected,
                "release_url": f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
                "prerelease": release.get("prerelease") is True}
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise AppError("update_release_invalid", "官方发行信息或 wheel/校验文件不完整，未执行安装。") from None


def verified_wheel(client: httpx.Client, release: dict, directory: Path) -> Path:
    name = release["wheel"]
    checksum = _fetch(client, release["assets"]["SHA256SUMS.txt"], 64 * 1024, asset=True).decode("ascii")
    hashes = re.findall(r"^([0-9a-fA-F]{64}) [ *]" + re.escape(name) + r"\r?$", checksum, re.MULTILINE)
    if len(hashes) != 1:
        raise AppError("update_checksum_invalid", "发行校验文件缺少唯一的 wheel 校验值，未执行安装。")
    data = _fetch(client, release["assets"][name], MAX_WHEEL, asset=True)
    if hashlib.sha256(data).hexdigest() != hashes[0].lower():
        raise AppError("update_checksum_mismatch", "更新文件 SHA256 不匹配，未执行安装。")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [a for a in archive.infolist() if a.filename.endswith(".dist-info/METADATA")]
            if len(entries) != 1 or entries[0].file_size > 256 * 1024:
                raise ValueError
            metadata = BytesParser().parsebytes(archive.read(entries[0]))
            requirement = metadata.get("Requires-Python")
            if (metadata.get("Name", "").lower().replace("_", "-") != "stu-mcp"
                    or _version(metadata.get("Version", "")) != _version(release["version"])):
                raise ValueError
            if not requirement or Version(platform.python_version()) not in SpecifierSet(requirement):
                raise AppError("update_python_incompatible", "新版本不支持当前 Python，请先调整安装环境。")
    except (ValueError, KeyError, zipfile.BadZipFile, InvalidSpecifier):
        raise AppError("update_wheel_invalid", "更新包的名称、版本或元数据不正确，未执行安装。") from None
    path = directory / name
    path.write_bytes(data)
    return path


class UpdateService:
    def __init__(self, *, transport=None, probe=probe_installation, install=install_wheel):
        self.transport, self.probe, self.install = transport, probe, install
        self.last_result: dict | None = None
        self.restart_required = False

    def capabilities(self) -> dict:
        return {"check_tool": "check_updates", "update_tool": "update_self", "automatic_checks": False,
                "running_version": __version__, "restart_required": self.restart_required,
                "last_result": self.last_result}

    def run(self, *, check_only: bool = False, before_install=None, guard=exclusive_update) -> dict:
        stage = "installation"
        attempted = False
        try:
            installation = self.probe()
            with private_http_logging(), httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=False,
                              headers={"Accept": "application/vnd.github+json", "User-Agent": "stu-mcp-updater"},
                              transport=self.transport) as client:
                stage = "check"
                release = latest_release(client)
                detected = installed_version()
                current = detected or __version__
                available = _version(release["version"]) > _version(current)
                status = "update_available" if available else (
                    "ahead_of_release" if _version(current) > _version(release["version"]) else "up_to_date")
                result = {"ok": True, "status": status,
                          "running_version": __version__, "installed_version": detected,
                          "latest_version": release["version"], "update_available": available,
                          "release_url": release["release_url"], "prerelease": release["prerelease"],
                          "checked_at": time.time(), "scope": "mcp_host", "installation": installation.public(),
                          "restart_required": self.restart_required or _version(current) != _version(__version__)}
                self.last_result = result
                if check_only or not available:
                    return result
                if not installation.public().get("supported"):
                    return self._save(result | {"ok": False, "status": "update_installation_unsupported",
                        "message": installation.public().get("reason", "此安装方式请使用原部署工具更新。")})
                stage = "download"
                with tempfile.TemporaryDirectory(prefix="stu-mcp-update-") as raw:
                    wheel = verified_wheel(client, release, Path(raw))
                    stage = "install"
                    with guard():
                        if installed_version() != detected:
                            raise AppError("update_state_changed", "安装版本已被其他进程改变，请重新检查更新。")
                        if before_install:
                            before_install()
                        attempted = True
                        installed = self.install(installation, wheel, release["version"])
                self.restart_required = True
                return self._save(result | installed | {"ok": True, "status": "updated", "update_available": False,
                    "running_version": __version__, "restart_required": True,
                    "message": "新版已安装并通过启动检查；请重新连接或重启 MCP 使新版生效。"})
        except (httpx.HTTPError, OSError, UnicodeError):
            error = AppError("update_network_error" if stage in {"check", "download"} else "update_failed",
                             "更新未完成，请检查网络或安装环境；未输出认证和代理信息。")
        except AppError as exc:
            error = exc
        except UpdateBusy as exc:
            error = AppError("update_busy", str(exc))
        except Exception:
            error = AppError("update_failed", "更新未完成，请检查安装环境；未输出依赖中的私密信息。")
        if attempted:
            self.restart_required = True
        return self._save(error.result() | {"stage": stage, "scope": "mcp_host", "checked_at": time.time(),
            "running_version": __version__, "installed_version": installed_version(),
            "restart_required": self.restart_required})

    def _save(self, result: dict) -> dict:
        self.last_result = result
        return result
