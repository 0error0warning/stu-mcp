"""Update only the positively identified uv tool; never guess another Python environment."""
from __future__ import annotations

import gc
import hashlib
import importlib
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_cache_path

from .runtime import AppError, reject_symlinks

_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*\Z")
_FLAGS = {"no-index", "compile-bytecode", "no-build", "no-build-isolation", "no-sources"}
_VALUES = {"resolution", "prerelease", "fork-strategy", "exclude-newer", "index-strategy", "link-mode",
           "keyring-provider", "default-index", "index-url", "torch-backend"}
_LISTS = {"index", "extra-index-url", "find-links", "no-binary-package", "no-build-package",
          "no-build-isolation-package", "exclude-newer-package", "prerelease-package", "no-sources-package"}


@dataclass(frozen=True)
class Installation:
    kind: str
    previous_version: str = ""
    python: Path | None = field(default=None, repr=False)
    prefix: Path | None = field(default=None, repr=False)
    uv: Path | None = field(default=None, repr=False)
    receipt: dict = field(default_factory=dict, repr=False)
    base_python: Path | None = field(default=None, repr=False)
    reason: str = ""
    bin_dir: Path | None = field(default=None, repr=False)
    launchers: tuple[Path, ...] = field(default=(), repr=False)

    def public(self) -> dict:
        return {"kind": self.kind, "supported": self.kind == "uv_tool", "reason": self.reason,
                "next_action": "update" if self.kind == "uv_tool" else
                "rebuild_container" if self.kind == "container" else "use_original_installer"}


def _run(args: list[str], *, timeout: int = 15, env: dict | None = None) -> subprocess.CompletedProcess:
    # Installer diagnostics may contain index credentials; never forward its stdout/stderr.
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                          cwd=tempfile.gettempdir(), env=env,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def _name(value) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError("unsupported requirement name")
    return re.sub(r"[-_.]+", "-", value).lower()


def _text(value) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError("unsupported receipt value")
    return value


def _extras(requirement: dict) -> str:
    values = requirement.get("extras", [])
    if not isinstance(values, list):
        raise ValueError("unsupported extras")
    return "[" + ",".join(_name(v) for v in values) + "]" if values else ""


def _requirement(value: dict) -> str:
    if not isinstance(value, dict) or set(value) - {"name", "extras", "specifier", "url", "path", "marker"}:
        raise ValueError("unsupported additional requirement")
    name = _name(value.get("name")) + _extras(value)
    sources = [key for key in ("specifier", "url", "path") if key in value]
    if len(sources) > 1:
        raise ValueError("ambiguous additional requirement")
    if "specifier" in value:
        name += _text(value["specifier"])
    elif "url" in value:
        name += " @ " + _text(value["url"])
    elif "path" in value:
        path = Path(_text(value["path"]))
        if not path.is_absolute() or not path.is_file() or path.suffix != ".whl":
            raise ValueError("additional local source is unavailable")
        name += " @ " + path.as_uri()
    return name + ("; " + _text(value["marker"]) if "marker" in value else "")


def _receipt_args(receipt: dict, wheel: Path, base_python: Path) -> list[str]:
    if not isinstance(receipt, dict) or set(receipt) - {"requirements", "python", "entrypoints", "options"}:
        raise ValueError("unsupported tool receipt")
    requirements = receipt.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("missing tool requirement")
    target = requirements[0]
    if not isinstance(target, dict) or _name(target.get("name")) != "stu-mcp":
        raise ValueError("different uv tool")
    if set(target) - {"name", "extras", "specifier", "url", "path"}:
        raise ValueError("unsupported tool source")
    if "path" in target and not Path(_text(target["path"])).suffix == ".whl":
        raise ValueError("source checkout")
    args = ["tool", "install", "stu-mcp" + _extras(target) + " @ " + wheel.as_uri(),
            "--no-config", "--no-progress", "--no-build"]
    if "python" in receipt:
        args.extend(["--python", _text(receipt["python"])])
    for requirement in requirements[1:]:
        if not isinstance(requirement, dict) or _name(requirement.get("name")) == "stu-mcp":
            raise ValueError("duplicate tool requirement")
        args.extend(["--with", _requirement(requirement)])
    entries = receipt.get("entrypoints", [])
    if not isinstance(entries, list) or not entries:
        raise ValueError("missing tool entrypoints")
    if any(not isinstance(item, dict) for item in entries):
        raise ValueError("invalid tool entrypoint")
    for provider in sorted({_name(item.get("from", "stu-mcp")) for item in entries} - {"stu-mcp"}):
        args.extend(["--with-executables-from", provider])
    options = receipt.get("options", {})
    if not isinstance(options, dict) or set(options) - (_FLAGS | _VALUES | _LISTS):
        raise ValueError("unsupported installer settings")
    for key, value in options.items():
        if key in _FLAGS:
            if type(value) is not bool:
                raise ValueError("invalid installer flag")
            if value and "--" + key not in args:
                args.append("--" + key)
        elif key in _VALUES:
            args.extend(["--" + key, _text(value)])
        else:
            if not isinstance(value, list):
                raise ValueError("invalid installer list")
            for item in value:
                args.extend(["--" + key, _text(item)])
    return args


def probe_installation() -> Installation:
    """Read the current package, interpreter and uv receipt, without changing any environment."""
    try:
        distribution = metadata.distribution("stu-mcp")
        version = distribution.version
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        if not isinstance(direct, dict):
            raise ValueError("invalid direct URL record")
    except (metadata.PackageNotFoundError, ValueError, OSError):
        return Installation("unknown", reason="无法核实当前 stu-mcp 安装记录。")
    if "dir_info" in direct or "vcs_info" in direct:
        return Installation("source", version, reason="当前运行源码安装，请在源码仓库更新。")
    if Path("/.dockerenv").exists():
        return Installation("container", version, reason="容器安装请重建镜像并重新创建容器，保留原数据卷。")
    prefix = Path(sys.prefix).resolve()
    python = Path(os.path.abspath(sys.executable))  # Preserve a venv symlink on POSIX.
    base = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    uv = shutil.which("uv")
    if not uv:
        return Installation("unknown", version, reason="找不到管理此安装的 uv。")
    try:
        result = _run([uv, "tool", "dir", "--no-config"])
        root = Path(result.stdout.decode("utf-8").strip()).resolve()
        if result.returncode or prefix != root / "stu-mcp":
            raise ValueError("not this uv tool")
        expected = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if os.path.normcase(str(python)) != os.path.normcase(str(expected)):
            raise ValueError("different interpreter")
        package = Path(__file__).with_name("__init__.py").resolve()
        if Path(distribution.locate_file("stu_mcp/__init__.py")).resolve() != package or not package.is_relative_to(prefix):
            raise ValueError("different distribution")
        receipt_path = prefix / "uv-receipt.toml"
        if receipt_path.stat().st_size > 256_000:
            raise ValueError("oversized receipt")
        receipt = tomllib.loads(receipt_path.read_text(encoding="utf-8"))["tool"]
        _receipt_args(receipt, Path(tempfile.gettempdir()).resolve() / "stu_mcp-0-py3-none-any.whl", base)
        bins = {Path(_text(item.get("install-path"))).parent for item in receipt["entrypoints"]}
        if len(bins) != 1 or not next(iter(bins)).is_absolute():
            raise ValueError("unsupported tool entrypoints")
        launchers = tuple(Path(item["install-path"]) for item in receipt["entrypoints"])
        recorded = {Path(distribution.locate_file(item)).resolve() for item in (getattr(distribution, "files", None) or [])}
        launchers += tuple(path for entry in receipt["entrypoints"]
                           if entry.get("from", "stu-mcp") == "stu-mcp"
                           for path in [prefix / ("Scripts" if os.name == "nt" else "bin") /
                                        (_name(entry.get("name")) + (".exe" if os.name == "nt" else ""))]
                           if path.resolve() in recorded)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        kind = "container" if Path("/.dockerenv").exists() else "unknown"
        return Installation(kind, version, reason="当前安装不是可核实且受支持的 uv tool 环境，请沿原安装方式更新。")
    return Installation("uv_tool", version, python, prefix, Path(uv), receipt, base,
                        bin_dir=next(iter(bins)), launchers=launchers)


def _cache_wheel(wheel: Path) -> Path:
    # uv records the exact source wheel in its receipt. Keep it after the download tempdir closes.
    with wheel.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    parent = user_cache_path("stu-mcp", appauthor=False) / "updates" / "artifacts" / digest
    reject_symlinks(parent)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = parent / wheel.name
    reject_symlinks(target)
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == digest:
                return target
    fd, raw = tempfile.mkstemp(prefix=".download-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as output, wheel.open("rb") as stream:
            shutil.copyfileobj(stream, output)
        with Path(raw).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise OSError("wheel changed while caching")
        os.replace(raw, target)
    finally:
        Path(raw).unlink(missing_ok=True)
    return target


def _windows_launcher(installation: Installation) -> tuple[Path, Path] | None:
    if os.name != "nt":
        return None
    current = Path(os.path.abspath(sys.argv[0]))
    if current.suffix.lower() != ".exe":
        current = Path(str(current) + ".exe")
    # importlib.metadata may cache this launcher's ZIP archive as a sys.path entry.
    importlib.invalidate_caches()
    gc.collect()
    for target in installation.launchers:
        if os.path.normcase(str(target)) != os.path.normcase(str(current)):
            continue
        backup = target.with_name(target.name + ".stu-mcp-update-old")
        # Windows permits renaming a running launcher, but not deleting/overwriting it.
        backup.unlink(missing_ok=True)
        target.rename(backup)
        return target, backup
    return None


def _restore_launcher(launcher) -> None:
    if launcher and not launcher[0].exists():
        with suppress(OSError):
            launcher[1].rename(launcher[0])


def _check_python(installation: Installation) -> None:
    selector = installation.receipt.get("python")
    if not selector:
        return  # No new selector is supplied: uv reuses the existing environment interpreter.
    selected = _run([str(installation.uv), "python", "find", _text(selector), "--no-project",
                     "--no-config", "--no-python-downloads"])
    if selected.returncode:
        raise ValueError("original Python is unavailable")
    path = Path(_text(selected.stdout.decode("utf-8").strip()))
    probe = _run([str(path), "-I", "-c", "import json,sys;print(json.dumps([list(sys.version_info[:3]),"
                  "sys._base_executable,sys.implementation.cache_tag]))"])
    values = json.loads(probe.stdout)
    if probe.returncode or not isinstance(values, list) or len(values) != 3 or \
            values[0] != list(sys.version_info[:3]) or \
            Path(values[1]).resolve() != installation.base_python or values[2] != sys.implementation.cache_tag:
        raise ValueError("original Python selection has changed")


def install_wheel(installation: Installation, wheel: Path, expected_version: str) -> dict:
    """Install a caller-verified local wheel with uv, then verify from the original launch path."""
    if installation.kind != "uv_tool":
        raise AppError("update_installation_unsupported", installation.reason or "此安装方式暂不支持一键更新。")
    try:
        _check_python(installation)
        _receipt_args(installation.receipt, wheel.resolve(), installation.base_python)
        cached = _cache_wheel(wheel)
        args = [str(installation.uv), *_receipt_args(installation.receipt, cached, installation.base_python)]
    except (ValueError, TypeError, OSError, subprocess.SubprocessError) as exc:
        raise AppError("update_installation_unsupported", "安装设置无法完整保留，未执行更新。") from exc
    launcher = None
    try:
        launcher = _windows_launcher(installation)
        # --force recreates the tool environment and breaks running Windows Python. Never use it.
        env = os.environ | {"UV_TOOL_DIR": str(installation.prefix.parent),
                            "UV_TOOL_BIN_DIR": str(installation.bin_dir)}
        for key in ("UV_PYTHON", "UV_MANAGED_PYTHON", "UV_NO_MANAGED_PYTHON"):
            env.pop(key, None)
        installed = _run(args, timeout=240, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        _restore_launcher(launcher)
        raise AppError("update_install_failed", "安装器未正常完成；请检查已安装版本后再重试。") from exc
    if installed.returncode:
        _restore_launcher(launcher)
        raise AppError("update_install_failed", "uv 安装失败；未确认新版已安装，请检查版本后再重试。")
    if launcher:
        with suppress(OSError):
            launcher[1].unlink(missing_ok=True)
    verify = ("import importlib.metadata as m,json,stu_mcp; "
              "print(json.dumps([m.version('stu-mcp'),stu_mcp.__version__]))")
    try:
        imported = _run([str(installation.python), "-I", "-c", verify])
        cli = _run([str(installation.python), "-I", "-m", "stu_mcp", "--version"])
        verified = json.loads(imported.stdout)
        if imported.returncode or cli.returncode or verified != [expected_version, expected_version] or \
                cli.stdout.decode("utf-8").strip() != expected_version:
            raise ValueError("unexpected installed version")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise AppError("update_verification_failed", "安装器已结束，但原启动入口未通过新版验证；请勿当作更新成功。") from exc
    return {"installed_version": expected_version, "running_version": installation.previous_version,
            "restart_required": True}
