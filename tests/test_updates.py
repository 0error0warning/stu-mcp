"""Synthetic releases and packages; no school accounts or real installation writes."""
import hashlib
import io
import json
import logging
import zipfile
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from stu_mcp import updates
from stu_mcp.runtime import AppError

VERSION = "99.1.0"
WHEEL = f"stu_mcp-{VERSION}-py3-none-any.whl"
BASE = f"https://github.com/{updates.REPOSITORY}/releases/download/v{VERSION}/"


def wheel(*, name="stu-mcp", version=VERSION, python=">=3.11"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(f"stu_mcp-{VERSION}.dist-info/METADATA",
                        f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\nRequires-Python: {python}\n")
    return stream.getvalue()


def release(version=VERSION, *, draft=False, prerelease=True):
    tag = "v" + version
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": "2026-10-22T01:00:00Z",
            "assets": [{"name": name, "browser_download_url":
                        f"https://github.com/{updates.REPOSITORY}/releases/download/{tag}/{name}"}
                       for name in (f"stu_mcp-{version}-py3-none-any.whl", "SHA256SUMS.txt")]}


def service(monkeypatch, *, blob=None, checksum=None, releases=None, handler=None, supported=True):
    blob = wheel() if blob is None else blob
    if checksum is None:
        checksum = f"{hashlib.sha256(blob).hexdigest()}  {WHEEL}\n".encode()
    calls = []

    def route(request):
        calls.append(request)
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        if handler:
            intercepted = handler(request)
            if intercepted:
                return intercepted
        if str(request.url) == updates.RELEASES:
            return httpx.Response(200, json=[release()] if releases is None else releases)
        if str(request.url) == BASE + WHEEL:
            return httpx.Response(200, content=blob)
        if str(request.url) == BASE + "SHA256SUMS.txt":
            return httpx.Response(200, content=checksum)
        raise AssertionError("Unexpected network destination")

    monkeypatch.setattr(updates, "installed_version", lambda: "0.6.0")
    installation = SimpleNamespace(public=lambda: {"kind": "uv_tool" if supported else "source",
                                                   "supported": supported, "reason": "使用原部署方式更新。"})
    install = Mock(return_value={"installed_version": VERSION})
    updater = updates.UpdateService(transport=httpx.MockTransport(route), probe=lambda: installation, install=install)
    return updater, install, calls


def test_check_is_immediate_read_only_and_includes_student_previews(monkeypatch):
    updater, install, calls = service(monkeypatch, releases=[release("99.0.0", prerelease=False), release()])
    result = updater.run(check_only=True)
    assert result["status"] == "update_available" and result["latest_version"] == VERSION
    assert result["prerelease"] and result["scope"] == "mcp_host"
    assert len(calls) == 1
    install.assert_not_called()
    assert updater.capabilities()["automatic_checks"] is False
    updater.run(check_only=True)
    assert len(calls) == 2  # no hidden twelve-hour cache or scheduling


def test_update_checks_exact_package_and_uses_shared_installation(monkeypatch, tmp_path):
    updater, install, calls = service(monkeypatch)
    sentinel = tmp_path / "encrypted-session"
    sentinel.write_bytes(b"SYNTHETIC_ENCRYPTED_BYTES")

    def installed(installation, path, expected):
        assert path.name == WHEEL and path.read_bytes() == wheel()
        assert expected == VERSION and installation.public()["supported"]
        return {"installed_version": VERSION}

    install.side_effect = installed
    before = Mock()
    result = updater.run(before_install=before, guard=nullcontext)
    assert result["status"] == "updated" and result["installed_version"] == VERSION
    assert result["running_version"] == updates.__version__ and result["restart_required"]
    assert updater.restart_required
    assert len(calls) == 3
    before.assert_called_once()
    assert sentinel.read_bytes() == b"SYNTHETIC_ENCRYPTED_BYTES"


@pytest.mark.parametrize("bad", [b"0" * 64 + b"  " + WHEEL.encode(), b"missing", b"\xff"])
def test_checksum_failure_never_runs_installer(monkeypatch, bad):
    updater, install, _ = service(monkeypatch, checksum=bad)
    result = updater.run(guard=nullcontext)
    assert not result["ok"] and result["stage"] == "download"
    assert not result["restart_required"]
    install.assert_not_called()


@pytest.mark.parametrize("blob,code", [
    (b"not a wheel", "update_wheel_invalid"),
    (wheel(name="somebody-else"), "update_wheel_invalid"),
    (wheel(version="1.0.0"), "update_wheel_invalid"),
    (wheel(python=">=99"), "update_python_incompatible"),
    (wheel(python="invalid"), "update_wheel_invalid"),
])
def test_wheel_metadata_and_python_compatibility_precede_install(monkeypatch, blob, code):
    updater, install, _ = service(monkeypatch, blob=blob)
    result = updater.run(guard=nullcontext)
    assert result["status"] == code
    install.assert_not_called()


def test_unknown_installation_can_check_but_cannot_write(monkeypatch):
    updater, install, calls = service(monkeypatch, supported=False)
    assert updater.run(check_only=True)["update_available"]
    result = updater.run(guard=nullcontext)
    assert result["status"] == "update_installation_unsupported" and not result["ok"]
    assert len(calls) == 2
    install.assert_not_called()


def test_network_failure_is_unknown_and_does_not_expose_proxy_credentials(monkeypatch):
    def fail(request):
        raise httpx.ConnectError("https://user:SYNTHETIC_PROXY_SECRET@example.invalid", request=request)

    updater, install, _ = service(monkeypatch, handler=fail)
    result = updater.run(check_only=True)
    assert not result["ok"] and result["status"] == "update_network_error"
    assert "SYNTHETIC_PROXY_SECRET" not in json.dumps(result)
    assert "update_available" not in result
    install.assert_not_called()


@pytest.mark.parametrize("releases", [[], {}, [release(draft=True)], [release() | {"assets": []}]])
def test_invalid_or_incomplete_latest_release_does_not_fall_back_silently(monkeypatch, releases):
    updater, install, _ = service(monkeypatch, releases=releases)
    assert updater.run()["status"] == "update_release_invalid"
    install.assert_not_called()


@pytest.mark.parametrize("location", ["https://attacker.invalid/a.whl", "http://github.com/a", "file:///tmp/a"])
def test_download_redirects_cannot_escape_approved_https_hosts(monkeypatch, location):
    def redirect(request):
        if str(request.url) == BASE + WHEEL:
            return httpx.Response(302, headers={"location": location})
        return None

    updater, install, _ = service(monkeypatch, handler=redirect)
    assert updater.run(guard=nullcontext)["status"] == "update_release_invalid"
    install.assert_not_called()


def test_approved_github_asset_redirect_is_followed_without_secrets(monkeypatch):
    blob = wheel()

    def redirect(request):
        if str(request.url) == BASE + WHEEL:
            return httpx.Response(302, headers={"location": "https://release-assets.githubusercontent.com/asset"})
        if request.url.host == "release-assets.githubusercontent.com":
            return httpx.Response(200, content=blob)
        return None

    updater, install, _ = service(monkeypatch, handler=redirect)
    assert updater.run(guard=nullcontext)["status"] == "updated"
    install.assert_called_once()


def test_active_transaction_blocks_install_before_mutation(monkeypatch):
    updater, install, _ = service(monkeypatch)

    def blocked():
        raise AppError("update_repair_active", "活动报修")

    result = updater.run(before_install=blocked, guard=nullcontext)
    assert result["status"] == "update_repair_active" and not result["restart_required"]
    install.assert_not_called()


def test_install_failure_requires_restart_and_does_not_claim_success(monkeypatch):
    updater, install, _ = service(monkeypatch)
    install.side_effect = AppError("update_install_failed", "安装失败，请使用原安装方式恢复。")
    result = updater.run(guard=nullcontext)
    assert not result["ok"] and result["status"] == "update_install_failed"
    assert result["stage"] == "install" and result["installed_version"] == "0.6.0"
    assert result["restart_required"] and updater.restart_required


def test_no_update_does_not_download_or_run_installer(monkeypatch):
    updater, install, calls = service(monkeypatch, releases=[release("0.6.0")])
    assert updater.run()["status"] == "up_to_date"
    assert len(calls) == 1
    install.assert_not_called()


def test_size_limit_prevents_install(monkeypatch):
    monkeypatch.setattr(updates, "MAX_WHEEL", 1)
    updater, install, _ = service(monkeypatch)
    assert updater.run(guard=nullcontext)["status"] == "update_download_limit"
    install.assert_not_called()


def test_signed_asset_urls_are_not_exposed_by_debug_logging(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    blob = wheel()

    def redirect(request):
        if str(request.url) == BASE + WHEEL:
            return httpx.Response(302, headers={"location":
                "https://release-assets.githubusercontent.com/asset?token=SYNTHETIC_ASSET_SECRET"})
        if request.url.host == "release-assets.githubusercontent.com":
            return httpx.Response(200, content=blob)
        return None

    updater, _, _ = service(monkeypatch, handler=redirect)
    result = updater.run(guard=nullcontext)
    assert result["ok"]
    assert "SYNTHETIC_ASSET_SECRET" not in caplog.text + json.dumps(result)


def test_unreadable_installed_metadata_remains_unknown_on_error(monkeypatch):
    monkeypatch.setattr(updates.importlib.metadata, "version", Mock(side_effect=OSError("private-install-path")))

    def disconnected(request):
        raise httpx.ConnectError("offline", request=request)

    state = SimpleNamespace(public=lambda: {"supported": False})
    updater = updates.UpdateService(probe=lambda: state, transport=httpx.MockTransport(disconnected))
    result = updater.run(check_only=True)
    assert result["status"] == "update_network_error" and result["installed_version"] is None
    assert "private-install-path" not in json.dumps(result)
