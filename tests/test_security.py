import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from keyring.backends.null import Keyring

from stu_mcp.runtime import AppError, private_write
from stu_mcp.vault import SystemKeyStore, Vault


def test_sessions_and_personal_cache_are_encrypted(app, session, keys):
    app.vault.save("mystu", session)
    personal = {"id": "mystu:task:synthetic", "kind": "task", "title": "SYNTHETIC_PRIVATE_TASK_TITLE"}
    app.store.save_batch("mystu", [personal], private=True)
    assert app.vault.load("mystu") == session
    assert app.store.get(personal["id"])["title"] == personal["title"]
    assert keys.writes == 1
    combined = b"".join(p.read_bytes() for p in app.runtime.home.rglob("*") if p.is_file())
    assert session["cookies"][0]["value"].encode() not in combined
    assert personal["title"].encode() not in combined
    assert list(keys.values.values())[0].encode() not in combined
    assert session["cookies"][0]["value"] not in json.dumps(app.status())


def test_rejects_plaintext_and_null_keyring(monkeypatch):
    monkeypatch.setattr("keyring.get_keyring", lambda: Keyring())
    with pytest.raises(AppError, match="系统密钥库") as error:
        SystemKeyStore()
    assert error.value.code == "secure_storage_unavailable"


def test_keyring_errors_do_not_leak_secrets(app, session):
    class BrokenKeys:
        def get_password(self, *_):
            raise RuntimeError("SYNTHETIC_PASSWORD_SHOULD_NOT_LEAK")
    app.vault._store = BrokenKeys()
    with pytest.raises(AppError) as error:
        app.vault.save("mystu", session)
    assert error.value.code == "secure_storage_unavailable"
    assert "SYNTHETIC_PASSWORD" not in json.dumps(error.value.result())
    assert not app.runtime.session_file("mystu").exists()


def test_concurrent_first_key_is_not_overwritten(app, keys):
    original = keys.get_password
    def delayed(*args):
        time.sleep(0.03)
        return original(*args)
    keys.get_password = delayed
    barrier = threading.Barrier(2)
    def encrypt(number):
        vault = Vault(app.runtime, keys)
        barrier.wait(timeout=5)
        return vault.protect({"number": number})
    with ThreadPoolExecutor(max_workers=2) as pool:
        ciphertexts = list(pool.map(encrypt, [1, 2]))
    assert keys.writes == 1
    assert [app.vault.unprotect(c)["number"] for c in ciphertexts] == [1, 2]


def test_logout_only_removes_its_source(app, session):
    for source in ("mystu", "yuketang"):
        app.vault.save(source, session)
        app.store.save_batch(source, [{"id": source + ":task:synthetic", "kind": "task", "title": source}], private=True)
    app.logout("mystu")
    assert app.vault.status("mystu")["status"] == "needs_login"
    assert app.vault.status("yuketang")["status"] == "session_saved"
    with pytest.raises(AppError):
        app.store.get("mystu:task:synthetic")
    assert app.store.get("yuketang:task:synthetic")["title"] == "yuketang"


def test_corrupt_and_expired_sessions_are_reported(app, session):
    app.vault.save("mystu", session)
    private_write(app.runtime.session_file("mystu"), b"not-a-valid-encrypted-state")
    assert app.vault.status("mystu")["status"] == "session_invalid"
    session["cookies"][0]["expires"] = 1
    app.vault.save("mystu", session)
    assert app.vault.status("mystu")["status"] == "login_expired"
    session["cookies"][0]["expires"] = "invalid"
    app.vault.save("mystu", session)
    assert app.vault.status("mystu")["status"] == "session_invalid"


def test_relogin_can_clear_old_account_cache_without_other_sources(app, session):
    app.vault.save("mystu", session)
    app.store.save_batch("mystu", [{"id": "mystu:task:old", "kind": "task", "title": "旧合成任务"}], private=True)
    app.store.save_batch("public", [{"id": "public:notice:keep", "kind": "notice", "title": "公开合成通知"}])
    app.vault.save("mystu", session, on_relogin=lambda: app.store.forget("mystu"))
    assert app.store.list(sources=("mystu",))["items"] == []
    assert app.store.get("public:notice:keep")["title"] == "公开合成通知"


@pytest.mark.parametrize("source", ["jw", "mystu", "yuketang"])
def test_personal_sources_cannot_be_saved_unencrypted(app, source):
    with pytest.raises(AppError) as error:
        app.store.save_batch(source, [{"id": source + ":demo", "kind": "task", "title": "合成隐私数据"}])
    assert error.value.code == "private_storage_required"


@pytest.mark.parametrize("name", ["password", "token", "cookie", "model_api_key"])
def test_profile_rejects_credential_fields(app, name):
    with pytest.raises(AppError):
        app.runtime.save_profile({name: "synthetic"})


def test_private_write_rejects_symlink(tmp_path):
    target, link = tmp_path / "target", tmp_path / "link"
    target.write_text("keep", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(AppError):
        private_write(link, b"replacement")
    assert target.read_text(encoding="utf-8") == "keep"
