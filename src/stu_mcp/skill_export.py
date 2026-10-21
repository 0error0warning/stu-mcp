"""Export optional skill resources and the generating machine's command config."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from .runtime import AppError, Runtime, private_write, reject_symlinks

SKILL_NAMES = ("stu-campus", "stu-timetable-export")
SKILLS_ROOT = Path(__file__).parent / "skills"
TIMETABLE_CORE = Path(__file__).parent / "features" / "timetable" / "export.py"
TIMETABLE_RESOURCE = "scripts/_timetable_core.py"


def skill_path(runtime: Runtime, *, name: str = "stu-campus") -> Path:
    if name not in SKILL_NAMES:
        raise AppError("unknown_skill", "请选择已随 STU MCP 分发的技能。")
    return runtime.home / "exports" / f"{name}.zip"


def _files(name: str) -> list[tuple[str, bytes]]:
    """Read only a fixed packaged skill; never follow resource links out of it."""
    source = SKILLS_ROOT / name
    reject_symlinks(source)
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        raise AppError("skill_unavailable", "已安装的技能资源不完整，请重新安装 STU MCP。")
    resources = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        reject_symlinks(path)
        if any("\\" in part or ":" in part for part in relative.parts) or not path.resolve().is_relative_to(source.resolve()):
            raise AppError("unsafe_path", "技能资源路径超出分发目录，已停止导出。")
        if path.is_file():
            if relative.as_posix().casefold() == "runtime.json":
                raise AppError("invalid_skill_resource", "技能分发目录不应包含本机运行配置。")
            if name == "stu-timetable-export" and relative.as_posix().casefold() == TIMETABLE_RESOURCE:
                raise AppError("invalid_skill_resource", "课表共享实现由打包器提供，请移除重复资源。")
            resources.append((f"{name}/{relative.as_posix()}", path.read_bytes()))
    if name == "stu-timetable-export":
        # Bundle the canonical implementation, not a separately maintained copy.
        reject_symlinks(TIMETABLE_CORE)
        if not TIMETABLE_CORE.is_file():
            raise AppError("skill_unavailable", "已安装的课表转换实现不完整，请重新安装 STU MCP。")
        resources.append((f"{name}/{TIMETABLE_RESOURCE}", TIMETABLE_CORE.read_bytes()))
    return resources


def export_skill(runtime: Runtime, *, apply: bool = False, name: str = "stu-campus") -> dict:
    artifact = skill_path(runtime, name=name)
    command = {"command": sys.executable, "args": ["-m", "stu_mcp"]}
    result = {"ok": True, "status": "preview", "artifact": str(artifact),
              "runtime": command,
              "message": "技能 ZIP 是可选资源包；runtime.json 记录生成机器的 Python 入口，仍需配置并验证客户端执行权限。"}
    if apply:
        resources = _files(name)
        resources.append((f"{name}/runtime.json", (json.dumps(command, ensure_ascii=False, indent=2) + "\n").encode()))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in resources:
                info = zipfile.ZipInfo(path)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        private_write(artifact, stream.getvalue())
        result["status"] = "skill_exported"
    return result
