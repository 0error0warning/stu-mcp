"""Export a portable local-command Skill without guessing an agent's config path."""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from .runtime import Runtime, private_write


def skill_path(runtime: Runtime) -> Path:
    return runtime.home / "exports" / "stu-campus.zip"


def export_skill(runtime: Runtime, *, apply: bool = False) -> dict:
    source = Path(__file__).parent / "skills" / "stu-campus" / "SKILL.md"
    command = {"command": str(Path(sys.executable).resolve()), "args": ["-m", "stu_mcp"]}
    result = {"ok": True, "status": "preview", "artifact": str(skill_path(runtime)),
              "runtime": command, "message": "生成供本地命令调用的 Skill；导入后仍需验证 agent 的本机执行权限。"}
    if apply:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("stu-campus/SKILL.md", source.read_bytes())
            archive.writestr("stu-campus/runtime.json", json.dumps(command, ensure_ascii=False, indent=2) + "\n")
        private_write(skill_path(runtime), stream.getvalue())
        result["status"] = "skill_exported"
    return result
