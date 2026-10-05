from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from stu_mcp.auth import interactive_login
from stu_mcp.runtime import AppError


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


def test_failed_download_does_not_save_authentication(app, session, tmp_path, monkeypatch):
    import stu_mcp.auth as auth
    fake, _ = fake_playwright(tmp_path, session)
    monkeypatch.setattr(auth, "sync_playwright", lambda: nullcontext(fake))
    monkeypatch.setattr(auth.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=1))
    with pytest.raises(AppError) as error:
        interactive_login(app.vault, "mystu")
    assert error.value.code == "browser_install_failed"
    assert not app.runtime.session_file("mystu").exists()
