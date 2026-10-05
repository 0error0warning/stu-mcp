import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from stu_mcp import collectors
from stu_mcp.runtime import AppError


def test_logout_during_refresh_cannot_recreate_personal_cache(app, session, monkeypatch):
    app.vault.save("mystu", session)
    started, finish = threading.Event(), threading.Event()
    def delayed(_vault, _limit):
        started.set()
        assert finish.wait(timeout=5)
        return collectors.Collection([{ "id": "mystu:task:late", "kind": "task", "title": "合成迟到结果"}], private=True)
    monkeypatch.setattr(collectors, "mystu", delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(app.refresh, "mystu")
        assert started.wait(timeout=5)
        app.logout("mystu")
        finish.set()
        with pytest.raises(AppError) as error:
            pending.result(timeout=5)
        assert error.value.code == "session_changed"
    assert app.store.list(sources=("mystu",))["items"] == []
    assert app.vault.status("mystu")["status"] == "needs_login"
