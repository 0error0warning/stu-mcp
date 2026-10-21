import json
import sys
import zipfile
from pathlib import Path

import pytest

from stu_mcp import cli, skill_export
from stu_mcp.clients import connect
from stu_mcp.runtime import AppError, Runtime


@pytest.fixture
def skill_resources(tmp_path, monkeypatch):
    root = tmp_path / "bundled-skills"
    files = {
        "SKILL.md": b"---\nname: synthetic\n---\nUse runtime.json.\n",
        "references/platform.md": "合成官方文档入口".encode(),
        "references/nested/rules.json": b'{"synthetic": true}',
        "scripts/build_timetable.py": b'print("synthetic timetable")\n',
    }
    for name in skill_export.SKILL_NAMES:
        for relative, data in files.items():
            path = root / name / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    monkeypatch.setattr(skill_export, "SKILLS_ROOT", root)
    return root, files


@pytest.mark.parametrize("name", skill_export.SKILL_NAMES)
def test_skill_preview_is_read_only_and_apply_packages_all_resources(tmp_path, skill_resources, name):
    root, files = skill_resources
    runtime = Runtime(tmp_path / "runtime")
    preview = skill_export.export_skill(runtime, name=name)
    assert preview["status"] == "preview"
    assert Path(preview["artifact"]) == runtime.home / "exports" / f"{name}.zip"
    assert not runtime.home.exists()

    # Bytecode created by using a script must not become part of the portable skill.
    compiled = root / name / "scripts" / "__pycache__" / "local.cpython-311.pyc"
    compiled.parent.mkdir()
    compiled.write_bytes(b"not a bundled resource")
    exported = skill_export.export_skill(runtime, name=name, apply=True)
    archive_path = Path(exported["artifact"])
    first = archive_path.read_bytes()
    assert exported["status"] == "skill_exported"
    expected = dict(files)
    if name == "stu-timetable-export":
        expected[skill_export.TIMETABLE_RESOURCE] = skill_export.TIMETABLE_CORE.read_bytes()
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {f"{name}/{path}" for path in expected} | {f"{name}/runtime.json"}
        for relative, data in expected.items():
            assert archive.read(f"{name}/{relative}") == data
        runtime_config = json.loads(archive.read(f"{name}/runtime.json"))
        assert runtime_config == {"command": sys.executable, "args": ["-m", "stu_mcp"]}
        assert runtime_config == exported["runtime"]
    skill_export.export_skill(runtime, name=name, apply=True)
    assert archive_path.read_bytes() == first


@pytest.mark.parametrize("client", ["generic-cli", "doubao-work"])
def test_existing_client_exports_and_default_signature_keep_stu_campus(tmp_path, skill_resources, client):
    runtime = Runtime(tmp_path / "runtime")
    assert skill_export.skill_path(runtime) == runtime.home / "exports" / "stu-campus.zip"
    old = skill_export.export_skill(runtime, apply=True)
    result = connect(client, runtime, home=tmp_path / "unused-client-home", apply=True)
    assert result["artifact"] == old["artifact"]
    assert result["verification"] == "local_execution_required"
    assert result["runtime"] == old["runtime"]
    assert not (tmp_path / "unused-client-home").exists()
    with zipfile.ZipFile(result["artifact"]) as archive:
        assert archive.read("stu-campus/SKILL.md")
        assert all(path.startswith("stu-campus/") for path in archive.namelist())
    assert not (runtime.home / "exports" / "stu-timetable-export.zip").exists()


@pytest.mark.parametrize("name", ["../stu-campus", "../../escape", "/tmp/escape", r"..\escape", "", "other"])
def test_export_skill_name_cannot_select_an_arbitrary_path(tmp_path, skill_resources, name):
    runtime = Runtime(tmp_path / "runtime")
    for apply in (False, True):
        with pytest.raises(AppError) as error:
            skill_export.export_skill(runtime, name=name, apply=apply)
        assert error.value.code == "unknown_skill"
    assert not runtime.home.exists()


def test_bundled_runtime_config_cannot_override_generated_command(tmp_path, skill_resources):
    root, _ = skill_resources
    runtime = Runtime(tmp_path / "runtime")
    artifact = skill_export.skill_path(runtime)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"previous export")
    (root / "stu-campus" / "runtime.json").write_text('{"command":"do not export"}')
    with pytest.raises(AppError) as error:
        skill_export.export_skill(runtime, apply=True)
    assert error.value.code == "invalid_skill_resource"
    assert artifact.read_bytes() == b"previous export"


def test_missing_main_resource_preserves_existing_export(tmp_path, skill_resources):
    root, _ = skill_resources
    runtime = Runtime(tmp_path / "runtime")
    artifact = skill_export.skill_path(runtime)
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"previous export")
    (root / "stu-campus" / "SKILL.md").unlink()
    with pytest.raises(AppError) as error:
        skill_export.export_skill(runtime, apply=True)
    assert error.value.code == "skill_unavailable"
    assert artifact.read_bytes() == b"previous export"


def test_missing_shared_converter_preserves_previous_skill_export(tmp_path, skill_resources, monkeypatch):
    runtime = Runtime(tmp_path / "runtime")
    artifact = skill_export.skill_path(runtime, name="stu-timetable-export")
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"previous export")
    monkeypatch.setattr(skill_export, "TIMETABLE_CORE", tmp_path / "missing-converter.py")
    with pytest.raises(AppError) as error:
        skill_export.export_skill(runtime, name="stu-timetable-export", apply=True)
    assert error.value.code == "skill_unavailable"
    assert artifact.read_bytes() == b"previous export"


def test_skill_resources_cannot_override_shared_converter(tmp_path, skill_resources):
    root, _ = skill_resources
    (root / "stu-timetable-export" / skill_export.TIMETABLE_RESOURCE).write_bytes(b"duplicate converter")
    runtime = Runtime(tmp_path / "runtime")
    with pytest.raises(AppError) as error:
        skill_export.export_skill(runtime, name="stu-timetable-export", apply=True)
    assert error.value.code == "invalid_skill_resource"
    assert not runtime.home.exists()


def test_resource_symlink_cannot_export_external_content(tmp_path, skill_resources):
    root, _ = skill_resources
    external = tmp_path / "outside.txt"
    external.write_bytes(b"SYNTHETIC_NOT_A_SKILL_RESOURCE")
    link = root / "stu-campus" / "references" / "external.md"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("creating symlinks requires OS permission")
    runtime = Runtime(tmp_path / "runtime")
    with pytest.raises(AppError) as error:
        skill_export.export_skill(runtime, apply=True)
    assert error.value.code == "unsafe_path"
    assert not runtime.home.exists()
    assert external.read_bytes() == b"SYNTHETIC_NOT_A_SKILL_RESOURCE"


def test_skill_cli_can_explicitly_export_without_constructing_app(tmp_path, skill_resources, monkeypatch, capsys):
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("STU_MCP_HOME", str(runtime_home))
    monkeypatch.setenv("SYNTHETIC_TOKEN", "MUST_NOT_BE_IN_RUNTIME")

    def app_is_not_needed():
        raise AssertionError("export does not require credential/cache initialization")

    monkeypatch.setattr(cli, "App", app_is_not_needed)
    assert cli.main(["skill-export", "--skill", "stu-timetable-export"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "preview"
    assert not runtime_home.exists()
    assert cli.main(["skill-export", "--skill", "stu-timetable-export", "--apply"]) == 0
    exported = json.loads(capsys.readouterr().out)
    with zipfile.ZipFile(exported["artifact"]) as archive:
        assert json.loads(archive.read("stu-timetable-export/runtime.json")) == {
            "command": sys.executable, "args": ["-m", "stu_mcp"],
        }
    assert not (runtime_home / "cache.sqlite3").exists()
    assert not (runtime_home / "exports" / "stu-campus.zip").exists()


def test_skill_cli_default_still_selects_stu_campus():
    args = cli.parser().parse_args(["skill-export"])
    assert args.skill == "stu-campus" and args.apply is False
