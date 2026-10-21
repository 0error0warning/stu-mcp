from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from stu_mcp.auth import interactive_login
from stu_mcp.runtime import AppError
from stu_mcp.sources import SOURCES


def fake_playwright(tmp_path, session):
    settings = {}
    class Page:
        url = "https://my.stu.edu.cn/discussion/my-courses"
        def goto(self, url, **_):
            self.url = url
        def wait_for_timeout(self, _):
            pass
        def content(self):
            return "<h1>合成课程页面</h1>"
        def locator(self, _):
            return SimpleNamespace(count=lambda: 0)
        def is_closed(self):
            return False
    class Context:
        def route(self, *_):
            pass
        def new_page(self):
            return Page()
        def storage_state(self):
            return session
    class Browser:
        def new_context(self, **kwargs):
            settings.update(kwargs)
            return Context()
        def is_connected(self):
            return True
        def close(self):
            pass
    fake = SimpleNamespace(chromium=SimpleNamespace(executable_path=str(tmp_path / "missing-browser"),
                                                    launch=lambda **_: Browser()))
    return fake, settings


@pytest.mark.usefixtures("synthetic_login_interaction")
def test_first_login_prepares_browser_and_saves_no_password(app, session, tmp_path, monkeypatch):
    import stu_mcp.auth as auth
    fake, settings = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth, "proof", lambda *_, **__: True)
    calls = []
    monkeypatch.setattr(auth.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    phases = []
    result = interactive_login(app.vault, "mystu", on_phase=phases.append)
    assert result["status"] == "session_saved"
    assert phases == ["preparing_browser", "waiting_for_login"]
    assert calls[0][0][1:] == ["-m", "playwright", "install", "chromium"]
    assert "shell" not in calls[0][1]
    assert settings["ignore_https_errors"] is False
    assert app.vault.load("mystu") == session


@pytest.mark.usefixtures("synthetic_login_interaction")
def test_failed_download_does_not_save_authentication(app, session, tmp_path, monkeypatch):
    import stu_mcp.auth as auth
    fake, _ = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=1))
    with pytest.raises(AppError) as error:
        interactive_login(app.vault, "mystu")
    assert error.value.code == "browser_install_failed"
    assert not app.runtime.session_file("mystu").exists()


@pytest.mark.parametrize("service", ["jw", "mystu", "yuketang"])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("action", ["logout", "replace"])
@pytest.mark.usefixtures("synthetic_login_interaction")
def test_manual_login_cannot_restore_logout_or_replace_newer_account(
        app, session, keys, tmp_path, monkeypatch, service, existing, action):
    from stu_mcp import auth
    from stu_mcp.app import App
    from stu_mcp.vault import Vault
    session = deepcopy(session)
    session["cookies"][0]["domain"] = SOURCES[service].hosts[0]
    if existing:
        app.vault.save(service, session)
    fake, _ = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth, "prepare_browser", lambda *_: None)
    peer = App(app.runtime, Vault(app.runtime, keys))
    new_session = deepcopy(session)
    new_session["cookies"][0]["value"] = "SYNTHETIC_NEW_ACCOUNT"
    new_task = {"id": f"{service}:task:new-account", "kind": "task", "title": "合成新账号待办"}
    def change_while_verifying(*_, **__):
        if action == "logout":
            peer.logout(service)
        else:
            peer.vault.save(service, new_session, on_relogin=lambda: peer.store.forget(service))
            peer.store.save_batch(service, [new_task], private=True)
        return True
    monkeypatch.setattr(auth, "proof", change_while_verifying)
    with pytest.raises(AppError) as error:
        interactive_login(app.vault, service)
    assert error.value.code == "session_changed"
    if action == "logout":
        assert app.vault.status(service)["status"] == "needs_login"
        assert app.store.list(sources=(service,))["items"] == []
    else:
        assert app.vault.load(service) == new_session
        assert app.store.get(new_task["id"])["title"] == new_task["title"]


@pytest.mark.parametrize("service", ["jw", "mystu", "yuketang"])
@pytest.mark.usefixtures("synthetic_login_interaction")
def test_fresh_manual_login_after_logout_still_succeeds(app, session, tmp_path, monkeypatch, service):
    from stu_mcp import auth
    session = deepcopy(session)
    session["cookies"][0]["domain"] = SOURCES[service].hosts[0]
    fake, _ = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth, "prepare_browser", lambda *_: None)
    monkeypatch.setattr(auth, "proof", lambda *_, **__: True)
    app.logout(service)
    assert interactive_login(app.vault, service)["status"] == "session_saved"
    assert app.vault.load(service) == session


@pytest.mark.usefixtures("synthetic_login_interaction")
def test_logout_also_cancels_a_login_job_before_its_worker_starts(app, session, tmp_path, monkeypatch):
    from stu_mcp import auth
    fake, _ = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth, "prepare_browser", lambda *_: None)
    monkeypatch.setattr(auth, "proof", lambda *_, **__: True)
    queued = []
    monkeypatch.setattr(auth.threading, "Thread", lambda *, target, **_: SimpleNamespace(start=lambda: queued.append(target)))
    jobs = auth.LoginJobs(app.vault)
    jobs.start("mystu", backend="browser")
    app.logout("mystu")
    queued.pop()()
    assert jobs.snapshot()[0]["result"]["status"] == "session_changed"
    assert app.vault.status("mystu")["status"] == "needs_login"


@pytest.mark.parametrize("source", ["jw", "mystu", "yuketang"])
@pytest.mark.parametrize("status,code", [(401, None), (403, "access_denied"), (429, "rate_limited"),
                                        (503, "source_unavailable")])
def test_login_probe_does_not_mask_non_auth_failures(source, status, code, session, monkeypatch):
    from stu_mcp import auth
    from stu_mcp.network import CampusHTTP
    monkeypatch.setattr(auth, "CampusHTTP", lambda source, state, **kwargs: CampusHTTP(
        source, state, **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(status))))
    if code is None:
        assert auth.proof(source, session) is False
    else:
        with pytest.raises(AppError) as error:
            auth.proof(source, session)
        assert error.value.code == code
