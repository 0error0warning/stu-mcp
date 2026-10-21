"""Execute exported commands from a real isolated uv tool installation (all CI platforms)."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
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
import stu_mcp.features.repair as repair_feature
import stu_mcp.skill_export as skill_export_module
from stu_mcp.features.timetable import export as timetable_export
from stu_mcp.features.repair.service import RepairService
from stu_mcp.repair import RepairDrafts as CompatibleRepairDrafts
from stu_mcp import collectors, parsers
from stu_mcp.collection import Article, Collection
from stu_mcp.features.notices.parser import parse_public
from stu_mcp.features.mystu.parser import parse_assignment, payload_records
from stu_mcp.features.jw.parser import jw_exam_semester, parse_jw
from stu_mcp.features.jw.schema import JW_SCHEMA_VERSION
from stu_mcp.features.jw.service import jw
from stu_mcp.features.yuketang.parser import parse_inventory, parse_activities, parse_announcements
from stu_mcp.features.yuketang.service import yuketang
from stu_mcp.charging import ChargingClient, ChargingService
from stu_mcp.features.charging.adapter import ChargingClient as InstalledChargingClient
from stu_mcp.features.charging.service import ChargingService as InstalledChargingService
from stu_mcp.features.charging.parser import discover_script, parse_envelope, parse_ports
from stu_mcp import huyou
from stu_mcp.features.huyou.service import HuyouClient
from stu_mcp.features.huyou.parser import post_record
from stu_mcp.features.huyou.cache import merge_post
from ruamel.yaml import YAML
from stu_mcp.clients import CLIENTS, connect, target
from stu_mcp.runtime import Runtime
from stu_mcp.skill_export import export_skill

root = Path(sys.argv[1])
assert Path(stu_checkin.__file__).is_relative_to(root / "tools"), "worker must come from the installed wheel"
assert Path(repair_feature.__file__).is_relative_to(root / "tools"), "repair must come from the installed wheel"
assert Path(skill_export_module.__file__).is_relative_to(root / "tools"), "skill export must come from the installed wheel"
assert Path(timetable_export.__file__).is_relative_to(root / "tools"), "timetable core must come from the installed wheel"
assert CompatibleRepairDrafts is repair_feature.RepairDrafts
repairs = repair_feature.RepairDrafts()
assert isinstance(repairs, RepairService)
assert repairs.prepare(title="合成安装验证")["status"] == "needs_information"
repairs.shutdown()
assert collectors.Collection is Collection and collectors.Article is Article
for decoder in (parse_public, parse_assignment, payload_records, parse_jw, jw_exam_semester, jw,
                parse_inventory, parse_activities, parse_announcements, yuketang,
                InstalledChargingClient, InstalledChargingService, discover_script, parse_envelope, parse_ports,
                HuyouClient, post_record, merge_post):
    assert Path(sys.modules[decoder.__module__].__file__).is_relative_to(root / "tools")
assert parsers.parse_public is parse_public and parsers.parse_assignment is parse_assignment
assert parse_public('<li><a href="/info/1/2.htm">synthetic notice</a></li>',
                    "https://www.stu.edu.cn/", "synthetic", 1)[0]["title"] == "synthetic notice"
assert parse_assignment('<div id="intro">synthetic assignment</div>')["due_at"] is None
assert payload_records({"fields": "id,name", "items": [[1, "synthetic"]]}) == [{"id": 1, "name": "synthetic"}]
assert parsers.parse_jw is parse_jw and parsers.jw_exam_semester is jw_exam_semester
assert parsers.JW_SCHEMA_VERSION == JW_SCHEMA_VERSION == 2
academic = ('<table><tr><th>学期</th><th>课程编号</th><th>课程名称</th><th>成绩</th><th>学分</th><th>绩点</th></tr>'
            '<tr><td>2026-2027-1</td><td>SYNTHETIC</td><td>synthetic course</td><td>90</td><td>2</td><td>4</td></tr></table>')
grade = parse_jw(academic, "grade")[0]
assert grade["score"] == "90" and grade["credits"] == 2 and grade["gpa"] == 4
assert jw_exam_semester('<select name="xnxqid"><option value="">请选择</option>'
                        '<option value="2026-2027-1" selected>synthetic term</option></select>') == "2026-2027-1"
inventory = parse_inventory({"data": {"list": [{"classroom_id": 7, "term": 20261, "name": "synthetic course"}]}})
assert inventory.complete and inventory.semester == "20261"
course = inventory.courses[0]
assert parse_activities({"data": {"activities": []}}, course, inventory.semester).complete
assert parse_announcements({"data": {"data": [{"id": 9, "content": "synthetic notice"}]}}, course)[0]["title"] == "synthetic notice"
assert not parse_activities({"data": {"activities": [{"id": 8, "title": "synthetic activity", "type": "19"}]}},
                            course, inventory.semester).complete
assert issubclass(ChargingClient, InstalledChargingClient) and issubclass(ChargingService, InstalledChargingService)
assert discover_script('<script src=/static/js/index.abcdef12.js></script>') == '/static/js/index.abcdef12.js'
assert parse_envelope({"code": 200, "data": 6}).data == 6
assert parse_ports([{"num": 1, "state": 1}], 2)["counts"]["unknown"] == 1
assert huyou.HuyouClient is HuyouClient and huyou.merge_post is merge_post
assert post_record({"feedId": "9", "status": 1, "content": "synthetic post"})["body"] == "synthetic post"
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
timetable = export_skill(runtime, name="stu-timetable-export", apply=True)
skill_source = Path(skill_export_module.__file__).parent / "skills" / "stu-timetable-export"
resources = {path.relative_to(skill_source).as_posix(): path.read_bytes()
             for path in skill_source.rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}}
assert "SKILL.md" in resources and "scripts/build_timetable.py" in resources
assert any(path.startswith("references/") for path in resources)
resources["scripts/_timetable_core.py"] = Path(timetable_export.__file__).read_bytes()
with zipfile.ZipFile(timetable["artifact"]) as archive:
    assert set(archive.namelist()) == {"stu-timetable-export/" + path for path in resources} | {"stu-timetable-export/runtime.json"}
    for path, data in resources.items():
        assert archive.read("stu-timetable-export/" + path) == data
    skills["stu-timetable-export"] = json.loads(archive.read("stu-timetable-export/runtime.json"))
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
        installed_tools = (await session.list_tools()).tools
        names = {tool.name for tool in installed_tools}
        assert {"get_capabilities", "get_charging_overview", "get_charging_device", "get_checkin_status",
                "open_checkin_page", "list_checkin_courses", "select_checkin_courses", "start_checkin_monitor",
                "pause_checkin_monitor", "get_checkin_results", "stop_checkin_service",
                "diagnose_campus_network", "audit_campus_network"} <= names
        # Exercise the installed diagnostic without contacting a school endpoint.
        invalid = await session.call_tool("diagnose_campus_network", {"service_id": "https://invalid.example/"})
        assert invalid.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_service"
        audit_tool = next(tool for tool in installed_tools if tool.name == "audit_campus_network")
        assert audit_tool.annotations.read_only_hint is True
        assert audit_tool.input_schema["properties"]["compare_public_dns"]["default"] is False
        invalid_audit = await session.call_tool("audit_campus_network", {"location_hint": "guess_from_ip"})
        assert invalid_audit.model_dump(by_alias=True)["structuredContent"]["status"] == "invalid_network_location"


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
        env.pop("STU_MCP_KEY_FILE", None)
        env.pop("STU_MCP_INSTANCE_NAME", None)
        # Validate the locked dependency set. A fresh CI cache may contain wheels
        # from uv sync but no package-index metadata, so allow bounded online resolution.
        constraints = root / "constraints.txt"
        constraints.write_text(run([uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"],
                                   env, Path(__file__).resolve().parents[1]), encoding="utf-8")
        run([uv, "tool", "install", "--constraint", str(constraints),
             "--python", sys.executable, str(wheel)], env, root)
        entry = root / "bin" / ("stu-mcp.exe" if os.name == "nt" else "stu-mcp")
        assert run([str(entry), "--version"], env, root).strip() == __version__
        generic = json.loads(run([str(entry), "connect", "generic"], env, root))["mcpServers"]["stu-mcp"]
        secrets = json.loads(run([generic["command"], "-m", "stu_mcp", "server-init",
                                  str(root / "server-secrets")], env, root))
        assert secrets["status"] == "server_secrets_created"
        env["STU_MCP_KEY_FILE"] = secrets["master_key_file"]
        # Use the exported interpreter verbatim: resolving a POSIX uv symlink
        # would escape its installed wheel environment.
        http_check = Path(__file__).with_name("check_http_runtime.py").resolve()
        print(run([generic["command"], str(http_check), generic["command"], str(root),
                   secrets["auth_token_file"]], env, root).strip(), flush=True)
        exported = json.loads(run([generic["command"], "-c", EXPORT, str(root)], env, root))
        timetable_cli = json.loads(run([str(entry), "skill-export", "--skill", "stu-timetable-export", "--apply"], env, root))
        assert timetable_cli["status"] == "skill_exported"
        assert timetable_cli["runtime"] == exported["skills"]["stu-timetable-export"]
        skill_directory = root / "exported-skill"
        with zipfile.ZipFile(timetable_cli["artifact"]) as archive:
            archive.extractall(skill_directory)
        helper = skill_directory / "stu-timetable-export" / "scripts" / "build_timetable.py"
        checked = "2026-10-20T09:00:00+08:00"
        synthetic = {
            "schema_version": 1, "semester": "synthetic-2026",
            "calendar": {"semester": "synthetic-2026", "version": "synthetic-v1", "weeks": 16,
                         "week1_monday": "2026-09-07", "source_url": "https://jwc.stu.edu.cn/synthetic-calendar",
                         "checked_at": checked, "latest_verified": True},
            "timetable": {"source_url": "https://jw.stu.edu.cn/synthetic-timetable",
                          "checked_at": checked, "complete": True},
            "periods": [{"number": 1, "start": "08:00", "end": "08:45"}],
            "courses": [{"id": "synthetic-course", "title": "合成安装课程", "meetings": [
                {"id": "synthetic-meeting", "weekday": 1, "weeks": [1, 3], "periods": [1]},
            ]}],
        }
        reviewed = root / "reviewed-synthetic.json"
        reviewed.write_text(json.dumps(synthetic, ensure_ascii=False), encoding="utf-8")
        exported_timetable = root / "synthetic-timetable"
        built = json.loads(run([generic["command"], "-I", "-S", str(helper), "--input", str(reviewed),
                               "--output-dir", str(exported_timetable)], env, root))
        assert built["status"] == "generated"
        report = json.loads((exported_timetable / "review.json").read_bytes())
        assert report["oa"] == {"enabled": False, "status": "not_checked"}
        assert [event["date"] for event in report["events"]] == ["2026-09-07", "2026-09-21"]
        assert (exported_timetable / "schedule.ics").is_file()
        assert (exported_timetable / "wakeup.csv").is_file()
        assert (exported_timetable / "wakeup-settings.json").is_file()
        print("timetable: installed skill exports complete resources and builds synthetic CSV/ICS", flush=True)
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
