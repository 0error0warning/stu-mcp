import io
import json
import threading
from unittest.mock import Mock

import httpx
import pytest

from stu_checkin.auth import AUTH_URL, CALLBACK, callback_code
from stu_checkin.controller import AUTH_URL as LEGACY_AUTH_URL
from stu_checkin.controller import CALLBACK as LEGACY_CALLBACK
from stu_checkin.server import LocalServer, publish_runtime
from stu_mcp import checkin_login, terminal
from stu_mcp.checkin import CheckinClient
from stu_mcp.checkin_process import worker_environment
from stu_mcp.runtime import AppError

CODE = "A" * 32
LINK = "https://www.duifene.com/_FileManage/PdfView.aspx?code=" + CODE


@pytest.mark.parametrize("link", [
    "https://evil.example/?code=" + CODE,
    "http://www.duifene.com/?code=" + CODE,
    "https://www.duifene.com/?code=" + CODE + "&code=" + CODE,
    "https://www.duifene.com/?code=short",
    "https://www.duifene.com/?code=" + "!" * 32,
    "https://[bad/?code=" + CODE,
])
def test_invalid_callback_is_rejected_before_worker_start(tmp_path, link):
    client = CheckinClient(tmp_path)
    client._ensure = Mock(side_effect=AssertionError("no worker for invalid input"))
    with pytest.raises(ValueError):
        client.connect_callback(link)
    client._ensure.assert_not_called()


def test_extracted_authorization_preserves_existing_web_route():
    assert AUTH_URL == LEGACY_AUTH_URL and CALLBACK == LEGACY_CALLBACK
    assert callback_code(LINK) == CODE
    assert callback_code("https://duifene.com/another-public-path?code=" + CODE) == CODE


@pytest.fixture
def worker(tmp_path):
    state = {"ok": True, "status": "not_logged_in", "status_label": "未登录",
             "auth_state": "not_logged_in", "logged_in": False, "monitoring": False,
             "needs_login": True, "resume_enabled": False, "selected_courses": [],
             "courses": [], "course_statuses": {}, "cookie": "synthetic-private-session",
             "auth_url": "synthetic-private-url"}
    calls = []

    class Controller:
        def snapshot(self):
            return dict(state)

        def connect(self, link):
            assert callback_code(link) == CODE
            self.received_link = link
            calls.append("connect")
            state.update(status="paused", status_label="已暂停", auth_state="logged_in",
                         logged_in=True, needs_login=False, courses=[{"id": "one", "name": "合成课程"}])
            return {"ok": True}

    controller = Controller()
    server = LocalServer(controller)
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    publish_runtime(tmp_path, server.info())
    client = CheckinClient(tmp_path, opener=Mock(side_effect=AssertionError("no browser")))
    client._launch = Mock(side_effect=AssertionError("reuse the existing worker"))
    yield client, state, calls, server
    server.close()
    thread.join(timeout=2)


def test_callback_uses_existing_local_worker_and_safe_state(worker):
    client, state, calls, server = worker
    result = client.connect_callback(LINK)
    assert calls == ["connect"]
    assert result["ok"] and result["login_outcome"] == "confirmed"
    assert result["logged_in"] and not result["monitoring"] and not result["resume_enabled"]
    assert result["courses"] == [{"id": "one", "name": "合成课程"}]
    assert server.controller.received_link == "https://www.duifene.com/?code=" + CODE
    assert CODE not in json.dumps(result) and "synthetic-private" not in json.dumps(result)
    client._launch.assert_not_called()
    client.opener.assert_not_called()


def test_existing_authorized_resume_is_reported_without_new_plan_actions(worker):
    client, state, calls, server = worker
    original = server.controller.connect

    def resume(link):
        result = original(link)
        state.update(status="monitoring", monitoring=True, resume_enabled=True, selected_courses=["one"])
        return result

    server.controller.connect = resume
    result = client.connect_callback(LINK)
    assert calls == ["connect"]
    assert result["ok"] and result["monitoring"] and result["resume_enabled"]
    assert result["selected_courses"] == ["one"]


def test_active_monitor_is_not_paused_or_replaced(worker):
    client, state, calls, _ = worker
    state.update(status="monitoring", monitoring=True, resume_enabled=True)
    result = client.connect_callback(LINK)
    assert not result["ok"] and result["login_outcome"] == "not_sent"
    assert result["monitoring"] and result["resume_enabled"] and calls == []


def test_rejected_callback_does_not_treat_old_session_as_success(worker):
    client, state, calls, server = worker
    state.update(status="paused", logged_in=True, needs_login=False)

    def rejected(_link):
        from stu_checkin.controller import OperationError
        calls.append("connect")
        raise OperationError("合成过期回调")

    server.controller.connect = rejected
    result = client.connect_callback(LINK)
    assert calls == ["connect"] and result["logged_in"] is True
    assert not result["ok"] and result["login_outcome"] == "rejected"
    assert CODE not in json.dumps(result)
    client.opener.assert_not_called()


def test_unknown_callback_outcome_reads_state_and_never_resends(worker):
    client, state, calls, server = worker
    state.update(status="paused", logged_in=True, needs_login=False)
    seen = []
    real = httpx.HTTPTransport()

    def request(req):
        if req.method == "POST":
            seen.append(req.url.path)
            raise httpx.ReadTimeout("sensitive callback " + CODE)
        return real.handle_request(req)

    client.transport = httpx.MockTransport(request)
    try:
        result = client.connect_callback(LINK)
    finally:
        real.close()
    assert seen == ["/api/connect"] and calls == []
    assert not result["ok"] and result["login_outcome"] == "unknown"
    assert result["current_state"]["logged_in"] is True
    assert CODE not in json.dumps(result) and "sensitive" not in json.dumps(result)
    client.opener.assert_not_called()


def test_cli_rejects_pipes_without_reading_secret_or_worker(monkeypatch):
    monkeypatch.setattr(terminal.sys, "stdin", io.StringIO(LINK))
    secret = Mock(side_effect=AssertionError("must not read piped callback"))
    client = Mock()
    monkeypatch.setattr(checkin_login, "secret_input", secret)
    with pytest.raises(AppError) as error:
        checkin_login.login_via_callback(client)
    assert error.value.code == "terminal_required"
    secret.assert_not_called()
    client.connect_callback.assert_not_called()


def test_cli_validates_hidden_input_before_worker_creation(monkeypatch, capsys):
    monkeypatch.setattr(checkin_login, "require_terminal", lambda: None)
    monkeypatch.setattr(checkin_login, "secret_input", lambda _: "https://evil.example/?code=" + CODE)
    create = Mock(side_effect=AssertionError("bad input must not construct client"))
    monkeypatch.setattr(checkin_login, "CheckinClient", create)
    with pytest.raises(AppError) as error:
        checkin_login.login_via_callback()
    assert error.value.code == "invalid_callback"
    output = capsys.readouterr()
    assert not output.out and CODE not in output.err and CODE not in json.dumps(error.value.result())
    create.assert_not_called()


def test_cli_returns_only_connection_state(monkeypatch, capsys):
    monkeypatch.setattr(checkin_login, "require_terminal", lambda: None)
    monkeypatch.setattr(checkin_login, "secret_input", lambda _: LINK)
    client = Mock()
    client.connect_callback.return_value = {"ok": True, "monitoring": False, "resume_enabled": False}
    result = checkin_login.login_via_callback(client)
    client.connect_callback.assert_called_once_with(LINK)
    output = capsys.readouterr()
    assert not output.out and CODE not in output.err and CODE not in json.dumps(result)
    assert AUTH_URL in output.err


def test_windows_worker_passes_backend_paths_without_unrelated_secrets():
    configured = {"STU_MCP_HOME": "app-data", "STU_MCP_KEY_FILE": "external/master.key",
                  "STU_CHECKIN_HOME": "worker-data", "OPENAI_API_KEY": "synthetic-secret",
                  "STU_MCP_TOKEN": "synthetic-token", "STU_MCP_MASTER_KEY": "synthetic-key-value"}
    assert set(worker_environment(configured)) == {
        "STU_MCP_HOME=app-data", "STU_MCP_KEY_FILE=external/master.key", "STU_CHECKIN_HOME=worker-data"}
