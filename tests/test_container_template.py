"""Deployment safety contracts; these do not establish a successful Docker build."""
import json
import shlex
from pathlib import Path, PurePosixPath

from ruamel.yaml import YAML

from stu_mcp.cli import parser

ROOT = Path(__file__).resolve().parents[1]


def image_settings():
    source = (ROOT / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    instructions = {}
    for line in source.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            name, _, value = line.partition(" ")
            instructions[name] = value.strip()
    environment = dict(field.split("=", 1) for field in shlex.split(instructions["ENV"]))
    return instructions, environment


def test_image_launches_one_authenticated_http_service_without_a_shell_supervisor():
    instructions, environment = image_settings()
    entrypoint = json.loads(instructions["ENTRYPOINT"])
    assert entrypoint[-1] == "stu-mcp" and PurePosixPath(entrypoint[0]).name == "tini"
    options = parser().parse_args(json.loads(instructions["CMD"]))
    assert options.command == "serve" and options.transport == "streamable-http"
    assert options.host == "0.0.0.0" and options.port == 8765
    assert str(options.auth_token_file).replace("\\", "/") == "/run/secrets/http-token"
    assert environment["STU_MCP_KEY_FILE"] == "/run/secrets/master.key"
    assert options.auth_token_file.name != PurePosixPath(environment["STU_MCP_KEY_FILE"]).name


def test_compose_publishes_only_private_mcp_and_mounts_secrets_read_only():
    services = YAML(typ="safe").load(ROOT / "compose.yaml")["services"]
    assert set(services) == {"stu-mcp"}
    service = services["stu-mcp"]
    assert service["ports"] == ["127.0.0.1:8765:8765"]
    mounts = service["volumes"]
    secrets = next(mount for mount in mounts if isinstance(mount, dict))
    assert secrets["target"] == "/run/secrets" and secrets["read_only"] is True
    assert secrets["source"].startswith("${STU_MCP_SECRETS_DIR:?")
    assert "STU_MCP_UID" in service["build"]["args"]["STU_UID"]
    assert "STU_MCP_GID" in service["build"]["args"]["STU_GID"]
    # The baseline cannot silently enable a desktop or second setup process.
    environment = service.get("environment", {})
    assert not set(environment).intersection({"DISPLAY", "XAUTHORITY", "STU_MCP_SETUP", "STU_MCP_VNC_AUTH_FILE"})


def test_nonroot_image_persists_both_domains_while_separating_external_master_key():
    instructions, environment = image_settings()
    assert instructions["USER"] not in {"root", "0", "0:0"}
    campus = PurePosixPath(environment["STU_MCP_HOME"])
    checkin = PurePosixPath(environment["STU_CHECKIN_HOME"])
    key = PurePosixPath(environment["STU_MCP_KEY_FILE"])
    assert campus != checkin
    assert campus.is_relative_to("/var/lib/stu-mcp") and checkin.is_relative_to("/var/lib/stu-mcp")
    assert not key.is_relative_to("/var/lib/stu-mcp")
    service = YAML(typ="safe").load(ROOT / "compose.yaml")["services"]["stu-mcp"]
    assert "stu-mcp-data:/var/lib/stu-mcp" in service["volumes"]
