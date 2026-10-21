"""Natural loopback-control HTTP traces, with no worker or school access."""
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import requests
from test_http_privacy import PRIVATE_COOKIE, transport

from stu_checkin.auth import callback_code
from stu_checkin.controller import Controller
from stu_checkin.server import LocalServer, publish_runtime
from stu_checkin.vendor.duifene.api import DuifeneApi
from stu_checkin.vendor.duifene.rate_limit import RateLimiter
from stu_checkin.vendor.duifene.settings import Settings
from stu_mcp.checkin import CheckinClient
from stu_mcp.checkin_login import login_via_callback

AUTHORIZATION = "SYNTHETIC_PRIVATE_CONTROL_AUTHORIZATION"
CALLBACK = "SYNTHETIC_PRIVATE_CALLBACK_CODE"


def test_worker_session_control_auth_and_callback_are_hidden_from_debug_logs(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    backend, stream = transport()
    with CheckinClient(transport=backend)._client() as client:
        client.headers["Authorization"] = "Bearer " + AUTHORIZATION
        # Exercise both URL and JSON callback representations. The real CLI
        # sends the callback only in its existing one-shot JSON POST.
        client.post("http://127.0.0.1:8766/api/connect?callback=" + CALLBACK,
                    json={"link": "https://www.duifene.com/?code=" + CALLBACK})
    assert AUTHORIZATION.encode() in stream.writes and CALLBACK.encode() in stream.writes
    assert all(value not in caplog.text for value in (PRIVATE_COOKIE, AUTHORIZATION, CALLBACK))
    logging.getLogger("httpx").info("outside_worker_context_visible")
    assert "outside_worker_context_visible" in caplog.text


def test_worker_http_failure_restores_the_logging_context_without_a_retry(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.DEBUG, logger="httpcore.http11")
    backend, stream = transport(fail=True)
    with CheckinClient(transport=backend)._client() as client, pytest.raises(httpx.ReadError):
        client.post("http://127.0.0.1:8766/api/connect?callback=" + CALLBACK,
                    headers={"Authorization": "Bearer " + AUTHORIZATION}, json={"link": CALLBACK})
    assert stream.writes.count(b"POST ") == 1
    assert all(value not in caplog.text for value in (PRIVATE_COOKIE, AUTHORIZATION, CALLBACK))
    logging.getLogger("httpcore.http11").debug("outside_worker_failure_visible")
    assert "outside_worker_failure_visible" in caplog.text


@pytest.mark.parametrize("fail", [False, True])
def test_cli_worker_callback_keeps_real_urllib3_trace_private_on_the_handler_thread(
        tmp_path, monkeypatch, caplog, fail):
    caplog.set_level(logging.DEBUG, logger="urllib3.connectionpool")
    code, calls, auth_threads = "A" * 32, [], []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.send_header("Set-Cookie", "synthetic=" + PRIVATE_COOKIE + "; Path=/")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    upstream = HTTPServer(("127.0.0.1", 0), Upstream)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    owner = Controller.__new__(Controller)  # Never starts a real worker, keyring or school session.
    owner._operation = threading.Lock()
    owner._events_lock, owner._results_lock = threading.Lock(), threading.Lock()
    owner._events, owner._results, owner._revision = [], [], 0
    owner._busy, owner._auth_state = False, "not_logged_in"
    owner.event, owner._restore_plan = Mock(), Mock()
    session = requests.Session()
    session.trust_env = False
    settings = Settings(host=f"http://127.0.0.1:{upstream.server_port}")
    api = DuifeneApi(session, settings, RateLimiter(settings))

    def login(link):
        auth_threads.append(threading.get_ident())
        response = api.login_by_link(callback_code(link))  # Real requests/urllib3 GET, synthetic target only.
        assert response.status_code == 200
        if fail:
            raise requests.ReadTimeout("synthetic_callback_failure")
        return {"ok": True}

    bridge = SimpleNamespace(_api=api, login_by_link=login, _sentinel=Mock(),
                             _watcher=Mock(is_running=False))
    owner._ready = lambda: bridge

    def connect(link):
        try:
            return Controller.connect(owner, link)
        finally:
            # This executes in the real LocalServer handler thread, outside
            # Controller's private auth context even after an upstream failure.
            logging.getLogger("urllib3.connectionpool").debug("worker_after_auth_context_visible")

    def snapshot():
        logged_in = owner._auth_state == "logged_in"
        return {"ok": True, "status": "paused" if logged_in else "not_logged_in",
                "status_label": "synthetic", "logged_in": logged_in, "needs_login": not logged_in,
                "busy": False, "monitoring": False, "resume_enabled": False, "selected_courses": [],
                "courses": [], "course_statuses": {}}

    worker = LocalServer(SimpleNamespace(connect=connect, snapshot=snapshot))
    worker_thread = threading.Thread(target=worker.httpd.serve_forever, daemon=True)
    worker_thread.start()
    publish_runtime(tmp_path, worker.info())
    client = CheckinClient(tmp_path, opener=Mock(side_effect=AssertionError("no browser")))
    client._launch = Mock(side_effect=AssertionError("reuse synthetic worker"))
    monkeypatch.setattr("stu_mcp.checkin_login.require_terminal", lambda: None)
    monkeypatch.setattr("stu_mcp.checkin_login.secret_input", lambda _: "https://www.duifene.com/?code=" + code)
    try:
        result = login_via_callback(client)
        assert result["ok"] is (not fail)
        assert len(calls) == len(auth_threads) == 1 and "code=" + code in calls[0]
        assert auth_threads[0] != threading.get_ident()
        assert code not in caplog.text and PRIVATE_COOKIE not in caplog.text
        assert "worker_after_auth_context_visible" in caplog.text
        if fail:
            owner._restore_plan.assert_not_called()
        else:
            owner._restore_plan.assert_called_once()
        # Unrelated anonymous urllib3 requests remain visible, including their
        # ordinary query text; there is no process-wide log-level change.
        session.get(settings.host + "/public?visible=anonymous_log", timeout=3)
        assert "visible=anonymous_log" in caplog.text
    finally:
        session.close()
        worker.close()
        worker_thread.join(timeout=3)
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=3)
