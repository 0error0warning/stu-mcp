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

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from stu_mcp import __version__
from stu_mcp.checkin import CheckinClient

EXPORT = r'''
import json, sys, zipfile
from pathlib import Path
import tomlkit
import stu_checkin
from ruamel.yaml import YAML
from stu_mcp.clients import CLIENTS, connect, target
from stu_mcp.runtime import Runtime

root = Path(sys.argv[1])
assert Path(stu_checkin.__file__).is_relative_to(root / "tools"), "worker must come from the installed wheel"
for asset in ("index.html", "app.js", "style.css", "icon.svg"):
    assert (Path(stu_checkin.__file__).parent / "web" / asset).is_file(), asset
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
        names = {tool.name for tool in (await session.list_tools()).tools}
        assert {"get_capabilities", "get_charging_overview", "get_charging_device", "get_checkin_status",
                "open_checkin_page", "list_checkin_courses", "select_checkin_courses", "start_checkin_monitor",
                "pause_checkin_monitor", "get_checkin_results", "stop_checkin_service"} <= names


async def check_checkin(config: dict, env: dict, cwd: Path) -> None:
    """Launch from the installed interpreter; no account, platform call or browser window."""
    observer = CheckinClient(Path(env["STU_CHECKIN_HOME"]))
    code = ("import webbrowser; webbrowser.open=lambda *a,**k: True; "
            "from stu_mcp.server import build_server; build_server().run(transport='stdio')")
    params = StdioServerParameters(command=config["command"], args=["-c", code], env=env, cwd=str(cwd))
    try:
        async with stdio_client(params) as (read, write), ClientSession(read, write, read_timeout_seconds=40) as session:
            await session.initialize()
            result = await session.call_tool("list_checkin_courses", {})
            started = result.model_dump(by_alias=True)["structuredContent"]
            assert started["status"] == "not_logged_in", started
        after = observer.status()
        assert after["status"] == "not_logged_in", after
        assert after["service_instance"] == started["service_instance"]
        info = json.loads((observer.home / "runtime.json").read_text())
        with httpx.Client(base_url=info["url"], trust_env=False) as browser:
            for asset in ("", "app.js", "style.css", "icon.svg"):
                response = browser.get(asset)
                assert response.status_code == 200 and response.content, asset
        assert not (observer.home / "state.enc").exists()
        print("checkin: installed worker/web assets work and worker survives MCP shutdown", flush=True)
    finally:
        assert observer.stop_service()["status"] == "service_not_started"


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
               "STU_MCP_HOME": str(root / "runtime"), "STU_CHECKIN_HOME": str(root / "checkin")}
        env.pop("PYTHONPATH", None)
        env.pop("STU_CHECKIN_PYTHON", None)
        # uv sync/build already cached this dependency set. Avoid resolving a
        # different/newer set over the network during the installed-wheel check.
        constraints = root / "constraints.txt"
        constraints.write_text(run([uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"],
                                   env, Path(__file__).resolve().parents[1]), encoding="utf-8")
        run([uv, "tool", "install", "--offline", "--constraint", str(constraints),
             "--python", sys.executable, str(wheel)], env, root)
        entry = root / "bin" / ("stu-mcp.exe" if os.name == "nt" else "stu-mcp")
        assert run([str(entry), "--version"], env, root).strip() == __version__
        generic = json.loads(run([str(entry), "connect", "generic"], env, root))["mcpServers"]["stu-mcp"]
        exported = json.loads(run([generic["command"], "-c", EXPORT, str(root)], env, root))
        asyncio.run(asyncio.wait_for(check_checkin(generic, env, root), timeout=90))
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
