"""Execute exported commands from a real isolated uv tool installation (all CI platforms)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stu_mcp import __version__

EXPORT = r'''
import json, sys, zipfile
from pathlib import Path
import tomlkit
from ruamel.yaml import YAML
from stu_mcp.clients import CLIENTS, connect, target
from stu_mcp.runtime import Runtime

root = Path(sys.argv[1])
runtime, home = Runtime(root / "runtime"), root / "client-home"
configs, skills = {}, {}
for client, spec in CLIENTS.items():
    if spec.format == "cordis":
        profile = target(client, home).parent
        profile.mkdir(parents=True)
        (profile / "package.json").write_text("{}")
    result = connect(client, runtime, home=home, apply=True)
    assert result["ok"], result
    if spec.format == "skill":
        with zipfile.ZipFile(result["artifact"]) as archive:
            skills[client] = json.loads(archive.read("stu-campus/runtime.json"))
    elif spec.format == "export":
        configs[client] = result["mcpServers"]["stu-mcp"]
    else:
        raw = target(client, home).read_text(encoding="utf-8")
        if spec.format == "cordis":
            configs[client] = YAML(typ="rt").load(raw)[0]["insert"][0]["config"]
        else:
            node = tomlkit.parse(raw) if spec.format == "toml" else json.loads(raw)
            for key in spec.keys:
                node = node[key]
            configs[client] = dict(node["stu-mcp"])
print(json.dumps({"configs": configs, "skills": skills}))
'''


def run(command: list[str], env: dict, cwd: Path) -> str:
    completed = subprocess.run(command, env=env, cwd=cwd, capture_output=True,
                               text=True, encoding="utf-8", timeout=180)
    if completed.returncode:
        # This check owns a fresh sandbox and contains no student credentials.
        raise RuntimeError("Installed runtime check failed:\n" + completed.stdout[-4000:] + completed.stderr[-4000:])
    return completed.stdout


async def handshake(config: dict, env: dict, cwd: Path) -> None:
    params = StdioServerParameters(command=config["command"], args=config["args"], env=env, cwd=str(cwd))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        initialized = await session.initialize()
        assert initialized.server_info.name == "stu-mcp"
        assert len((await session.list_tools()).tools) == 19


def main() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv must be on PATH for the installed-wheel check")
    wheel = Path(sys.argv[1]).absolute() if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "dist" / f"stu_mcp-{__version__}-py3-none-any.whl")
    with tempfile.TemporaryDirectory(prefix="stu-mcp-installed-runtime-") as directory:
        # macOS's system /var alias is a symlink; fixture writes use its physical directory.
        # Only the disposable data directory is canonicalized, never the Python entry point.
        root = Path(directory).resolve()
        env = {**os.environ, "UV_TOOL_DIR": str(root / "tools"), "UV_TOOL_BIN_DIR": str(root / "bin"),
               "STU_MCP_HOME": str(root / "runtime")}
        env.pop("PYTHONPATH", None)
        run([uv, "tool", "install", "--python", sys.executable, str(wheel)], env, root)
        entry = root / "bin" / ("stu-mcp.exe" if os.name == "nt" else "stu-mcp")
        assert run([str(entry), "--version"], env, root).strip() == __version__
        generic = json.loads(run([str(entry), "connect", "generic"], env, root))["mcpServers"]["stu-mcp"]
        exported = json.loads(run([generic["command"], "-c", EXPORT, str(root)], env, root))
        for name, config in exported["configs"].items():
            assert config["command"] == generic["command"]
            asyncio.run(asyncio.wait_for(handshake(config, env, root), timeout=45))
            print(f"{name}: exported stdio command started and discovered tools", flush=True)
        for name, config in exported["skills"].items():
            assert run([config["command"], *config["args"], "--version"], env, root).strip() == __version__
            assert json.loads(run([config["command"], *config["args"], "status"], env, root))["version"] == __version__
            print(f"{name}: exported Skill command executed", flush=True)
        if os.name != "nt":
            interpreter = Path(generic["command"])
            assert interpreter.is_symlink(), "the POSIX regression must exercise a symlinked uv interpreter"
            base = subprocess.run([str(interpreter.resolve()), "-m", "stu_mcp", "--version"],
                                  env=env, cwd=root, capture_output=True, text=True, timeout=30)
            assert base.returncode != 0 and "No module named stu_mcp" in base.stderr
            print("POSIX: the resolved base interpreter cannot import stu_mcp; exported commands work", flush=True)


if __name__ == "__main__":
    main()
