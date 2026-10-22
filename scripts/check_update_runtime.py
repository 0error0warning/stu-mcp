"""Offline uv self-update acceptance in disposable tool/cache/bin directories only."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


def wheel(root: Path, name: str, version: str, *, installer: str = "", cli: str = "") -> Path:
    package = name.replace("-", "_")
    info = f"{package}-{version}.dist-info"
    files = {f"{package}/__init__.py": f"__version__ = {version!r}\n",
             f"{info}/WHEEL": "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
             f"{info}/METADATA": f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n",
             f"{info}/RECORD": ""}
    if installer:
        files.update({f"{package}/update_install.py": installer, f"{package}/cli.py": cli,
                      f"{package}/__main__.py": "from .cli import main\nmain()\n",
                      f"{package}/runtime.py": "class AppError(Exception):\n def __init__(self,code,message):\n"
                      "  super().__init__(message); self.code=code; self.message=message\n"
                      "def reject_symlinks(path):\n"
                      " if any(p.is_symlink() for p in (path,*path.parents)):raise AppError('unsafe_path','symlink')\n",
                      f"{info}/entry_points.txt": "[console_scripts]\nstu-mcp = stu_mcp.cli:main\n"
                      "stu = stu_mcp.cli:main\n",
                      "platformdirs.py": "import os\nfrom pathlib import Path\n"
                      "def user_cache_path(*a,**kw):return Path(os.environ['UV_CACHE_DIR']).parent/'update-cache'\n"})
        files[f"{info}/METADATA"] += ('Provides-Extra: browser\n'
                                        'Requires-Dist: update-extra==1.0; extra == "browser"\n')
    target = root / f"{package}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(target, "w") as archive:
        for path, contents in files.items():
            archive.writestr(path, contents)
    return target


def main() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is required for this isolated acceptance")
    source = Path(__file__).resolve().parents[1]
    installer = (source / "src/stu_mcp/update_install.py").read_text(encoding="utf-8")
    cli = '''import json,sys
from pathlib import Path
from . import __version__
def main():
 if len(sys.argv) > 1 and sys.argv[1] == "self-update":
  from .update_install import probe_installation,install_wheel
  state=probe_installation()
  assert state.kind == "uv_tool", state.public()
  result=install_wheel(state,Path(sys.argv[2]),sys.argv[3])
  print(json.dumps({"result":result,"loaded_version":__version__,"python":sys.executable}))
 else: print(__version__)
if __name__ == "__main__": main()
'''
    with tempfile.TemporaryDirectory(prefix="stu-update-runtime-") as raw:
        root = Path(raw).resolve()
        env = os.environ | {"UV_TOOL_DIR": str(root / "tools"), "UV_TOOL_BIN_DIR": str(root / "bin"),
                            "UV_CACHE_DIR": str(root / "cache"), "UV_NO_CONFIG": "1",
                            "PYTHONIOENCODING": "utf-8"}
        versions = [wheel(root, "stu-mcp", version, installer=installer, cli=cli)
                    for version in ("0.0.1", "0.0.2", "0.0.3", "0.0.4", "0.0.5", "0.0.6")]
        wheel(root, "update-extra", "1.0")
        wheel(root, "update-with", "1.0")
        config = root / "user-data" / "config.json"
        config.parent.mkdir()
        config.write_bytes(b'{"synthetic-setting":"preserved"}')
        before_data = config.read_bytes()
        env["STU_MCP_HOME"] = str(config.parent)
        env["STU_CHECKIN_HOME"] = str(root / "checkin-data")
        encrypted = config.parent / "sessions.enc"
        encrypted.write_bytes(b"synthetic-encrypted-session-bytes")
        before_encrypted = encrypted.read_bytes()

        def run(args: list[str]) -> str:
            result = subprocess.run(args, env=env, cwd=root, capture_output=True, encoding="utf-8",
                                    errors="replace", timeout=90, check=False)
            if result.returncode:
                raise AssertionError(f"isolated command failed ({result.returncode}): {result.stderr}")
            return result.stdout.strip()

        run([uv, "tool", "install", "stu-mcp[browser] @ " + versions[0].as_uri(), "--python", sys.executable,
             "--with", "update-with==1.0", "--no-index", "--find-links", str(root), "--link-mode", "copy",
             "--resolution", "lowest"])
        prefix = root / "tools" / "stu-mcp"
        python = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = root / "bin" / ("stu-mcp.exe" if os.name == "nt" else "stu-mcp")
        alias = root / "bin" / ("stu.exe" if os.name == "nt" else "stu")
        internal = prefix / ("Scripts" if os.name == "nt" else "bin")
        receipt_path = prefix / "uv-receipt.toml"
        before = tomllib.loads(receipt_path.read_text(encoding="utf-8"))["tool"]
        # Exercise both embedded clients' fixed Python path and the real installed command launcher.
        launches = [[str(python), "-m", "stu_mcp"], [str(command)], [str(alias)],
                    [str(internal / command.name)], [str(internal / alias.name)]]
        for index, launch in enumerate(launches, 1):
            old, new, target = f"0.0.{index}", f"0.0.{index + 1}", versions[index]
            result = json.loads(run([*launch, "self-update", str(target), new]))
            assert result["result"] == {"installed_version": new, "running_version": old, "restart_required": True}
            assert result["loaded_version"] == old
            assert Path(result["python"]) == python
            assert run([str(python), "-I", "-m", "stu_mcp", "--version"]) == new
            assert run([str(command), "--version"]) == new
            after = tomllib.loads(receipt_path.read_text(encoding="utf-8"))["tool"]
            assert after["python"] == before["python"]
            assert before["options"] | {"no-build": True} == after["options"]
            assert before["requirements"][0]["extras"] == after["requirements"][0]["extras"]
            assert before["requirements"][1:] == after["requirements"][1:]
            assert before["entrypoints"] == after["entrypoints"]
            assert run([str(python), "-I", "-c", "import update_extra,update_with; print('extras retained')"]) == \
                "extras retained"
            assert config.read_bytes() == before_data
            assert encrypted.read_bytes() == before_encrypted
            target.unlink()
            assert Path(after["requirements"][0]["path"]).is_file()
        print(json.dumps({"ok": True, "platform": sys.platform, "upgrades": len(launches),
                          "launchers": ["python-module", "installed-command", "alias", "internal-command", "internal-alias"],
                          "network": "offline",
                          "extras_options_python_data_preserved": True}))


if __name__ == "__main__":
    main()
