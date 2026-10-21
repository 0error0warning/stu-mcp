"""Template safety and synthetic shell supervision, without Docker or school access."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "docker-entrypoint.sh"


@pytest.fixture
def shell():
    if os.name == "nt":
        # Windows' System32 bash may only be an unconfigured WSL launcher.
        candidates = (Path("C:/Program Files/Git/bin/bash.exe"),
                      Path("C:/Program Files (x86)/Git/bin/bash.exe"))
        command = next((str(path) for path in candidates if path.is_file()), None)
    else:
        command = shutil.which("sh")
    if not command:
        pytest.skip("container shell tests require POSIX sh or Git Bash")
    return command


def test_compose_exposes_only_host_loopback_and_keeps_secret_mount_read_only():
    service = YAML(typ="safe").load(ROOT / "compose.yaml")["services"]["stu-mcp"]
    assert service["ports"] and all(port.startswith("127.0.0.1:") for port in service["ports"])
    secrets = next(volume for volume in service["volumes"] if isinstance(volume, dict))
    assert secrets["target"] == "/run/secrets" and secrets["read_only"] is True
    assert "STU_MCP_UID" in service["build"]["args"]["STU_UID"]
    assert "STU_MCP_GID" in service["build"]["args"]["STU_GID"]
    assert "disabled" in service["environment"]["STU_MCP_INTERACTION"]


def test_entrypoint_shell_syntax(shell):
    result = subprocess.run([shell, "-n", ENTRYPOINT.as_posix()], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.parametrize("mode,success", [("disabled", True), ("desktop", False), ("virtual-display", False)])
def test_entrypoint_has_no_unattended_or_unauthenticated_display_fallback(shell, tmp_path, mode, success):
    scripts = tmp_path / "bin"
    scripts.mkdir()
    stub = scripts / "stu-mcp"
    stub.write_text("#!/bin/sh\nprintf 'SYNTHETIC_SERVER_STARTED\\n'\n", encoding="utf-8", newline="\n")
    stub.chmod(0o700)
    environment = {**os.environ, "STU_MCP_INTERACTION": mode, "STU_MCP_SETUP": "0"}
    environment.pop("STU_MCP_VNC_AUTH_FILE", None)
    # cd converts a native path for Git Bash; $PWD then provides a POSIX PATH.
    result = subprocess.run(
        [shell, "-c", 'cd "$1"; PATH="$PWD/bin:$PATH"; export PATH; exec sh "$2" serve',
         "synthetic-entrypoint", tmp_path.as_posix(), ENTRYPOINT.as_posix()],
        env=environment, capture_output=True, timeout=10)
    if success:
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert b"SYNTHETIC_SERVER_STARTED" in result.stdout
    else:
        assert result.returncode != 0
        assert b"SYNTHETIC_SERVER_STARTED" not in result.stdout


def test_entrypoint_kills_and_reaps_term_ignoring_child_without_harming_other_process(shell, tmp_path):
    scripts = tmp_path / "bin"
    scripts.mkdir()
    stub = scripts / "stu-mcp"
    stub.write_text('#!/bin/sh\ntrap "" TERM\nprintf "%s\\n" "$$" > "$CHILD_PID_FILE"\n'
                    'while :; do sleep 0.1; done\n', encoding="utf-8", newline="\n")
    stub.chmod(0o700)
    harness = r'''
cd "$1" || exit 1
PATH="$PWD/bin:$PATH"
CHILD_PID_FILE="$PWD/child.pid"
export PATH CHILD_PID_FILE
entry=""
sentinel=""
cleanup() {
    for pid in "$entry" "$sentinel"; do
        [ -z "$pid" ] || kill -KILL "$pid" 2>/dev/null || true
    done
    [ -z "$entry" ] || wait "$entry" 2>/dev/null || true
    [ -z "$sentinel" ] || wait "$sentinel" 2>/dev/null || true
}
trap cleanup EXIT
sleep 9 &
sentinel=$!
printf '%s\n' "$sentinel" > sentinel.pid
sh "$2" serve &
entry=$!
printf '%s\n' "$entry" > entry.pid
attempts=0
until [ -s "$CHILD_PID_FILE" ]; do
    attempts=$((attempts + 1))
    [ "$attempts" -lt 40 ] || exit 1
    sleep 0.05
done
child=$(cat "$CHILD_PID_FILE")
kill -0 "$child" || exit 1
kill -TERM "$entry" || exit 1
wait "$entry"
result=$?
entry=""
[ "$result" -eq 143 ] || exit 1
if kill -0 "$child" 2>/dev/null; then exit 1; fi
kill -0 "$sentinel" || exit 1
printf 'CHILD_REAPED_OTHER_PROCESS_ALIVE\n'
'''
    environment = {**os.environ, "STU_MCP_INTERACTION": "disabled", "STU_MCP_SETUP": "0"}
    try:
        result = subprocess.run([shell, "-c", harness, "synthetic-shutdown", tmp_path.as_posix(),
                                 ENTRYPOINT.as_posix()], env=environment, capture_output=True, timeout=9)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert b"CHILD_REAPED_OTHER_PROCESS_ALIVE" in result.stdout
    finally:
        # A failing test also cleans up only its recorded PIDs, never a process
        # group or matching application name. No real service is started here.
        pids = [path.read_text().strip() for path in tmp_path.glob("*.pid")]
        pids = [pid for pid in pids if pid.isdecimal()]
        if pids:
            subprocess.run([shell, "-c", 'for pid in "$@"; do kill -KILL "$pid" 2>/dev/null || true; done',
                            "synthetic-cleanup", *pids], capture_output=True, timeout=3)
