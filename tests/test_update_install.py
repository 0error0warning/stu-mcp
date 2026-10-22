import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from stu_mcp import update_install as updates
from stu_mcp.runtime import AppError


def receipt(tmp_path):
    return {"requirements": [{"name": "stu-mcp", "extras": ["browser"], "url": "https://example.test/old.whl"},
                             {"name": "extra-package", "specifier": "==1.0"}],
            "entrypoints": [{"name": "stu-mcp", "from": "stu-mcp",
                             "install-path": str(tmp_path / "bin" / "stu-mcp")}],
            "options": {"resolution": "lowest", "no-index": True, "find-links": [tmp_path.as_uri()],
                        "link-mode": "copy"}}


def installation(tmp_path):
    return updates.Installation("uv_tool", "0.6.0", tmp_path / "tool" / "python", tmp_path / "tool",
                                tmp_path / "uv", receipt(tmp_path), tmp_path / "base-python",
                                bin_dir=tmp_path / "bin")


def test_receipt_preserves_extras_additional_packages_options_and_python(tmp_path):
    state = receipt(tmp_path) | {"python": "original-python"}
    args = updates._receipt_args(state, tmp_path / "new.whl", tmp_path / "base-python")
    assert args[:3] == ["tool", "install", "stu-mcp[browser] @ " + (tmp_path / "new.whl").as_uri()]
    assert args[args.index("--python") + 1] == "original-python"
    assert args[args.index("--with") + 1] == "extra-package==1.0"
    assert args[args.index("--resolution") + 1] == "lowest"
    assert args[args.index("--find-links") + 1] == tmp_path.as_uri()
    assert "--no-index" in args
    assert "--force" not in args


@pytest.mark.parametrize("change", [
    {"mystery": True}, {"options": {"future-option": "new"}},
    {"requirements": [{"name": "stu-mcp", "editable": True}]},
    {"requirements": [{"name": "stu-mcp", "path": "checkout"}]},
    {"requirements": [{"name": "other"}]},
    {"entrypoints": []}, {"entrypoints": ["bad"]},
    {"requirements": [{"name": "stu-mcp"}, "bad"]},
])
def test_unknown_installation_settings_fail_before_any_mutation(tmp_path, change):
    with pytest.raises(ValueError):
        updates._receipt_args(receipt(tmp_path) | change, tmp_path / "new.whl", tmp_path / "base-python")


def test_public_installation_never_exports_host_paths_or_receipt_credentials(tmp_path):
    state = installation(tmp_path)
    state.receipt["options"]["default-index"] = "https://user:secret@example.test/simple"
    public = state.public()
    assert public == {"kind": "uv_tool", "supported": True, "reason": "", "next_action": "update"}
    assert "secret" not in repr(state) + json.dumps(public)
    assert str(tmp_path) not in json.dumps(public)


def test_install_uses_identified_tool_paths_then_verifies_new_processes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "_cache_wheel", lambda path: path)

    def run(args, **kwargs):
        calls.append((args, kwargs))
        output = b'["0.6.1", "0.6.1"]' if "-c" in args else b"0.6.1\n"
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(updates, "_run", run)
    result = updates.install_wheel(installation(tmp_path), tmp_path / "new.whl", "0.6.1")
    assert result == {"installed_version": "0.6.1", "running_version": "0.6.0", "restart_required": True}
    assert calls[0][1]["env"]["UV_TOOL_DIR"] == str(tmp_path)
    assert calls[0][1]["env"]["UV_TOOL_BIN_DIR"] == str(tmp_path / "bin")
    assert "--force" not in calls[0][0]
    assert all(call[0][0] == str(tmp_path / "tool" / "python") for call in calls[1:])
    assert calls[2][0][-3:] == ["-m", "stu_mcp", "--version"]


@pytest.mark.parametrize("failure", ["exit", "timeout", "wrong_import", "wrong_cli"])
def test_installation_and_verification_failures_are_accurate_and_private(tmp_path, monkeypatch, failure):
    calls = []
    monkeypatch.setattr(updates, "_cache_wheel", lambda path: path)

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            if failure == "timeout":
                raise subprocess.TimeoutExpired("secret-index-url", 240)
            return subprocess.CompletedProcess(args, 1 if failure == "exit" else 0, b"secret-index-url")
        output = b'["0.6.1","0.6.1"]' if "-c" in args else b"0.6.1\n"
        if failure == "wrong_import" and "-c" in args or failure == "wrong_cli" and "--version" in args:
            output = b"secret-index-url"
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(updates, "_run", run)
    with pytest.raises(AppError) as error:
        updates.install_wheel(installation(tmp_path), tmp_path / "new.whl", "0.6.1")
    assert error.value.code == ("update_install_failed" if failure in {"exit", "timeout"} else
                                "update_verification_failed")
    assert "secret-index-url" not in json.dumps(error.value.result())


def test_unsupported_installation_never_invokes_installer(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_run", lambda *a, **k: pytest.fail("must not start installer"))
    with pytest.raises(AppError, match="source"):
        updates.install_wheel(updates.Installation("source", reason="source checkout"), tmp_path / "new.whl", "1")


def probe_fixture(tmp_path, monkeypatch, *, direct=None, different_prefix=False):
    prefix = tmp_path / "tools" / "stu-mcp"
    prefix.mkdir(parents=True)
    package = prefix / "lib" / "stu_mcp" / "__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("")
    python = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    state = receipt(tmp_path)
    import tomlkit
    (prefix / "uv-receipt.toml").write_text(tomlkit.dumps({"tool": state}), encoding="utf-8")
    distribution = SimpleNamespace(version="0.6.0", read_text=lambda name: json.dumps(direct or {}),
                                   locate_file=lambda path: package)
    monkeypatch.setattr(updates.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(updates.sys, "prefix", str(tmp_path / "different" if different_prefix else prefix))
    monkeypatch.setattr(updates.sys, "executable", str(python))
    monkeypatch.setattr(updates, "__file__", str(package.with_name("update_install.py")))
    monkeypatch.setattr(updates.shutil, "which", lambda name: str(tmp_path / "uv"))
    monkeypatch.setattr(updates, "_run", lambda *a, **k: subprocess.CompletedProcess([], 0,
                        str(tmp_path / "tools").encode("utf-8")))
    return prefix, package


def test_probe_requires_actual_uv_tool_directory_interpreter_and_distribution(tmp_path, monkeypatch):
    prefix, _ = probe_fixture(tmp_path, monkeypatch)
    found = updates.probe_installation()
    assert found.kind == "uv_tool"
    assert found.prefix == prefix.resolve()
    assert found.previous_version == "0.6.0"


def test_installer_marker_alone_does_not_prove_uv_tool_ownership(tmp_path, monkeypatch):
    probe_fixture(tmp_path, monkeypatch, different_prefix=True)
    assert not updates.probe_installation().public()["supported"]


def test_editable_source_is_not_self_mutated(tmp_path, monkeypatch):
    probe_fixture(tmp_path, monkeypatch, direct={"dir_info": {"editable": True}})
    assert updates.probe_installation().kind == "source"


def test_different_distribution_is_not_self_mutated(tmp_path, monkeypatch):
    _, package = probe_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(updates.metadata, "distribution", lambda name: SimpleNamespace(
        version="0.6.0", read_text=lambda name: "{}", locate_file=lambda name: package.parent / "different.py"))
    assert not updates.probe_installation().public()["supported"]


def test_cached_wheel_survives_download_cleanup_and_rejects_corruption(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(updates, "user_cache_path", lambda *a, **k: cache)
    wheel = tmp_path / "stu_mcp-0.6.1-py3-none-any.whl"
    wheel.write_bytes(b"synthetic-verified-wheel")
    cached = updates._cache_wheel(wheel)
    cached.write_bytes(b"corrupted-cache")
    assert updates._cache_wheel(wheel) == cached
    wheel.unlink()
    assert cached.read_bytes() == b"synthetic-verified-wheel"


@pytest.mark.parametrize("overwrite", [False, True])
def test_installer_failure_restores_only_missing_launcher(tmp_path, monkeypatch, overwrite):
    target, backup = tmp_path / "launcher", tmp_path / "launcher.old"
    target.write_bytes(b"old-launcher")

    def rotate(state):
        target.rename(backup)
        return target, backup

    def run(*args, **kwargs):
        if overwrite:
            target.write_bytes(b"new-unknown-launcher")
        raise subprocess.TimeoutExpired("synthetic-installer", 240)

    monkeypatch.setattr(updates, "_windows_launcher", rotate)
    monkeypatch.setattr(updates, "_cache_wheel", lambda path: path)
    monkeypatch.setattr(updates, "_run", run)
    with pytest.raises(AppError) as error:
        updates.install_wheel(installation(tmp_path), tmp_path / "new.whl", "0.6.1")
    assert error.value.code == "update_install_failed"
    assert target.read_bytes() == (b"new-unknown-launcher" if overwrite else b"old-launcher")


@pytest.mark.parametrize("changed", ["version", "path", "cache_tag", None])
def test_original_python_selector_must_still_resolve_to_same_runtime(tmp_path, monkeypatch, changed):
    state = installation(tmp_path)
    state.receipt["python"] = "3.12"
    values = [list(updates.sys.version_info[:3]), str(state.base_python), updates.sys.implementation.cache_tag]
    if changed == "version":
        values[0] = [3, 0, 0]
    elif changed == "path":
        values[1] = str(tmp_path / "different-python")
    elif changed == "cache_tag":
        values[2] = "different-abi"
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        output = str(tmp_path / "selected-python").encode() if len(calls) == 1 else json.dumps(values).encode()
        return subprocess.CompletedProcess(args, 0, output)

    monkeypatch.setattr(updates, "_run", run)
    if changed:
        with pytest.raises(ValueError, match="selection has changed"):
            updates._check_python(state)
    else:
        updates._check_python(state)
    assert calls[0][-1] == "--no-python-downloads"


def test_installer_options_never_replay_no_build_twice(tmp_path):
    state = receipt(tmp_path)
    state["options"]["no-build"] = True
    args = updates._receipt_args(state, tmp_path / "new.whl", tmp_path / "base-python")
    assert args.count("--no-build") == 1
