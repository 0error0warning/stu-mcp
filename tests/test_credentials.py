"""Synthetic server-key tests: no operating-system credentials or school traffic."""
import json
import os
import stat
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from stu_checkin.storage import SecureStore, StorageError
from stu_mcp import credentials
from stu_mcp.credentials import FileKeyStore, configured_key_store, read_private_file
from stu_mcp.runtime import AppError, Runtime
from stu_mcp.vault import KeyStore, SystemKeyStore, Vault


@pytest.fixture
def server_key(tmp_path, monkeypatch):
    monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "mcp"))
    monkeypatch.setenv("STU_CHECKIN_HOME", str(tmp_path / "checkin"))
    master = tmp_path / "external-master.key"
    master.write_bytes(Fernet.generate_key())
    master.chmod(0o600)
    monkeypatch.setenv("STU_MCP_KEY_FILE", str(master))
    return master


def test_default_factory_preserves_system_keyring_and_compatibility(monkeypatch, tmp_path):
    monkeypatch.delenv("STU_MCP_KEY_FILE", raising=False)
    sentinel = object()
    monkeypatch.setattr(credentials, "SystemKeyStore", lambda: sentinel)
    assert configured_key_store(tmp_path) is sentinel
    assert Vault(Runtime(tmp_path)).key_store() is sentinel
    # Existing integrations can still import the types from vault.
    assert SystemKeyStore.__name__ == "SystemKeyStore"
    assert KeyStore is credentials.KeyStore


def test_explicit_empty_file_configuration_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("STU_MCP_KEY_FILE", "")
    monkeypatch.setattr(credentials, "SystemKeyStore", lambda: pytest.fail("Must not fall back"))
    with pytest.raises(AppError, match="没有指定"):
        configured_key_store(tmp_path)


def test_file_store_keeps_multiple_services_and_accounts_encrypted(tmp_path, server_key):
    home = tmp_path / "mcp"
    store = configured_key_store(home)
    assert isinstance(store, FileKeyStore)
    assert store.get_password("webvpn", "account-a") is None
    assert not store.path.exists()
    items = [("webvpn", "account-a", "SYNTHETIC_PRIVATE_PASSWORD"),
             ("webvpn", "account-b", "SYNTHETIC_PRIVATE_TOTP"),
             ("session", "account-a", "SYNTHETIC_PRIVATE_SESSION_KEY")]
    for service, user, value in items:
        store.set_password(service, user, value)
    reopened = configured_key_store(home)
    for service, user, value in items:
        assert reopened.get_password(service, user) == value
    combined = b"".join(path.read_bytes() for path in home.rglob("*") if path.is_file())
    assert server_key.read_bytes() not in combined
    for _service, user, value in items:
        assert value.encode() not in combined
        assert user.encode() not in combined
    store.delete_password("webvpn", "account-a")
    store.delete_password("missing", "missing")
    assert store.get_password("webvpn", "account-a") is None
    assert store.get_password("webvpn", "account-b") == items[1][2]
    assert store.get_password("session", "account-a") == items[2][2]
    assert not list(home.glob(".credentials-*.tmp"))
    if os.name != "nt":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
        assert stat.S_IMODE((home / ".credentials-lock").stat().st_mode) == 0o600


def test_vault_and_checkin_share_master_but_keep_independent_maps(tmp_path, server_key):
    mcp_home, checkin_home = tmp_path / "mcp", tmp_path / "checkin"
    vault = Vault(Runtime(mcp_home))
    session = {"cookies": [{"name": "synthetic", "value": "SYNTHETIC_COOKIE"}]}
    vault.save("mystu", session)
    checkin = SecureStore(checkin_home)
    checkin.save_cookie("session=SYNTHETIC_CHECKIN_COOKIE")
    assert Vault(Runtime(mcp_home)).load("mystu") == session
    assert SecureStore(checkin_home).load_cookie() == "session=SYNTHETIC_CHECKIN_COOKIE"
    mcp_entries = json.loads(Fernet(server_key.read_bytes()).decrypt((mcp_home / "credentials.enc").read_bytes()))
    checkin_entries = json.loads(
        Fernet(server_key.read_bytes()).decrypt((checkin_home / "credentials.enc").read_bytes()))
    assert set(mcp_entries["entries"]) == {"stu-mcp.session-key"}
    assert set(checkin_entries["entries"]) == {"stu-checkin"}


@pytest.mark.parametrize("location", ["current", "mcp", "checkin"])
def test_master_must_be_outside_both_application_homes(tmp_path, server_key, location):
    current = tmp_path / "custom-home"
    home = {"current": current, "mcp": tmp_path / "mcp", "checkin": tmp_path / "checkin"}[location]
    home.mkdir()
    master = home / "bad-location.key"
    master.write_bytes(server_key.read_bytes())
    master.chmod(0o600)
    with pytest.raises(AppError, match="目录之外"):
        FileKeyStore(current, master)


def test_relative_master_path_is_rejected(tmp_path, server_key):
    with pytest.raises(AppError, match="绝对路径"):
        FileKeyStore(tmp_path / "mcp", Path("external-master.key"))


@pytest.mark.parametrize("ending", [b"", b"\n", b"\r\n"])
def test_master_accepts_canonical_fernet_with_optional_one_line_ending(tmp_path, server_key, ending):
    server_key.write_bytes(server_key.read_bytes() + ending)
    FileKeyStore(tmp_path / "mcp", server_key).set_password("test", "user", "synthetic")


@pytest.mark.parametrize("payload", [b"", b"wrong", b"A" * 44, b" " + b"A" * 43,
                                      b"A" * 43 + b"=\n\n", b"A" * 44 + b"=",
                                      b"SYNTHETIC_SECRET_IS_NOT_A_FERNET_MASTER"])
def test_bad_master_is_reported_without_values_or_plaintext(tmp_path, server_key, payload):
    server_key.write_bytes(payload)
    with pytest.raises(AppError) as error:
        configured_key_store(tmp_path / "mcp")
    assert error.value.code == "secure_storage_unavailable"
    assert str(server_key) not in str(error.value)
    if payload:
        assert payload.decode() not in str(error.value)
    assert not (tmp_path / "mcp").exists()


def test_missing_master_is_never_generated_and_does_not_leak_path(tmp_path, server_key):
    server_key.unlink()
    with pytest.raises(AppError) as error:
        configured_key_store(tmp_path / "mcp")
    assert error.value.code == "secure_storage_unavailable"
    assert str(server_key) not in str(error.value)
    assert not server_key.exists()
    with pytest.raises(StorageError):
        SecureStore(tmp_path / "checkin").save_cookie("synthetic")
    assert not (tmp_path / "checkin" / "state.enc").exists()


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_corrupt_credentials_are_not_treated_as_empty_or_overwritten(tmp_path, server_key, operation):
    store = FileKeyStore(tmp_path / "mcp", server_key)
    store.set_password("webvpn", "synthetic", "password")
    original = b"SYNTHETIC_CORRUPT_CIPHERTEXT"
    store.path.write_bytes(original)
    with pytest.raises(AppError) as error:
        if operation == "get":
            store.get_password("webvpn", "synthetic")
        elif operation == "set":
            store.set_password("other", "synthetic", "value")
        else:
            store.delete_password("webvpn", "synthetic")
    assert store.path.read_bytes() == original
    assert error.value.code == "secure_storage_unavailable"
    assert "SYNTHETIC" not in str(error.value)


@pytest.mark.parametrize("payload", [b"{}", b'[]', b'{"version":2,"entries":{}}',
                                      b'{"version":true,"entries":{}}',
                                      b'{"version":1,"entries":{"s":{"u":3}}}',
                                      b'{"version":1,"entries":{},"entries":{}}'])
def test_invalid_encrypted_schema_is_preserved(tmp_path, server_key, payload):
    store = FileKeyStore(tmp_path / "mcp", server_key)
    store.home.mkdir()
    original = Fernet(server_key.read_bytes()).encrypt(payload)
    store.path.write_bytes(original)
    store.path.chmod(0o600)
    with pytest.raises(AppError):
        store.set_password("test", "user", "new")
    assert store.path.read_bytes() == original


def test_changed_master_does_not_destroy_existing_credentials(tmp_path, server_key):
    store = FileKeyStore(tmp_path / "mcp", server_key)
    store.set_password("test", "user", "synthetic")
    original = store.path.read_bytes()
    server_key.write_bytes(Fernet.generate_key())
    reopened = FileKeyStore(store.home, server_key)
    with pytest.raises(AppError, match="主密钥不匹配"):
        reopened.set_password("other", "user", "new")
    assert store.path.read_bytes() == original


def test_atomic_write_failure_preserves_original_and_scrubs_error(tmp_path, server_key, monkeypatch):
    store = FileKeyStore(tmp_path / "mcp", server_key)
    store.set_password("test", "user", "synthetic")
    original = store.path.read_bytes()
    def fail_replace(*_):
        raise OSError("SYNTHETIC_PRIVATE_DISK_ERROR")
    monkeypatch.setattr(credentials.os, "replace", fail_replace)
    with pytest.raises(AppError) as error:
        store.set_password("other", "user", "new")
    assert "SYNTHETIC" not in str(error.value)
    assert store.path.read_bytes() == original
    assert sorted(path.name for path in store.home.iterdir()) == [".credentials-lock", "credentials.enc"]


def _write_process_entries(args):
    home, master, worker = args
    store = FileKeyStore(Path(home), Path(master))
    for index in range(4):
        store.set_password("concurrent", f"{worker}:{index}", f"synthetic-{worker}-{index}")


def test_file_store_transactions_are_safe_across_processes(tmp_path, server_key):
    home = tmp_path / "mcp"
    with ProcessPoolExecutor(max_workers=3) as workers:
        list(workers.map(_write_process_entries,
                         [(str(home), str(server_key), worker) for worker in range(3)]))
    store = FileKeyStore(home, server_key)
    for worker in range(3):
        for index in range(4):
            assert store.get_password("concurrent", f"{worker}:{index}") == f"synthetic-{worker}-{index}"


def test_concurrent_first_session_keys_remain_decryptable(tmp_path, server_key):
    runtime = Runtime(tmp_path / "mcp")
    def protect(index):
        return Vault(runtime).protect({"index": index})
    with ThreadPoolExecutor(max_workers=4) as workers:
        encrypted = list(workers.map(protect, range(8)))
    assert [Vault(runtime).unprotect(value)["index"] for value in encrypted] == list(range(8))


@pytest.mark.parametrize("mode,uid,allowed", [(0o600, 100, True), (0o400, 100, True),
                                            (0o644, 100, False), (0o640, 100, False),
                                            (0o600, 101, False)])
def test_posix_owner_and_permissions_policy_is_tested_on_every_platform(monkeypatch, mode, uid, allowed):
    monkeypatch.setattr(credentials, "os", SimpleNamespace(name="posix", geteuid=lambda: 100))
    info = SimpleNamespace(st_mode=stat.S_IFREG | mode, st_uid=uid, st_nlink=1)
    if allowed:
        credentials._check_private_file(info)
    else:
        with pytest.raises(AppError):
            credentials._check_private_file(info)


def test_private_file_rejects_directories_large_files_and_invalid_limit(tmp_path):
    with pytest.raises(AppError):
        read_private_file(tmp_path)
    path = tmp_path / "synthetic-private"
    path.write_bytes(b"abc")
    path.chmod(0o600)
    assert read_private_file(path, limit=3) == b"abc"
    for limit in [2, 0, -1, True, 5 * credentials.MAX_CREDENTIAL_BYTES]:
        with pytest.raises(AppError):
            read_private_file(path, limit=limit)


@pytest.mark.parametrize("parent_link", [False, True])
def test_private_file_rejects_symlinks_and_ancestor_links(tmp_path, parent_link):
    target = tmp_path / "real"
    target.mkdir()
    file = target / "private"
    file.write_bytes(b"synthetic")
    file.chmod(0o600)
    link = tmp_path / "link"
    try:
        link.symlink_to(target if parent_link else file, target_is_directory=parent_link)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(AppError, match="包含链接"):
        read_private_file(link / "private" if parent_link else link)


def test_private_file_rejects_hardlinks(tmp_path):
    path, link = tmp_path / "private", tmp_path / "hardlink"
    path.write_bytes(b"synthetic")
    path.chmod(0o600)
    os.link(path, link)
    with pytest.raises(AppError, match="独立的普通文件"):
        read_private_file(path)


def test_no_secret_details_in_vault_error_or_public_status(tmp_path, server_key):
    server_key.write_bytes(b"SYNTHETIC_SECRET_IN_INVALID_MASTER")
    vault = Vault(Runtime(tmp_path / "mcp"))
    with pytest.raises(AppError) as error:
        vault.protect({"private": "SYNTHETIC_PRIVATE_STATE"})
    result = json.dumps(error.value.result(), ensure_ascii=False)
    assert "SYNTHETIC" not in result
    # Public/status reads do not eagerly initialize this optional backend.
    assert vault.status("jw")["status"] == "needs_login"
