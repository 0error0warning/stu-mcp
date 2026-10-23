import http.client
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from stu_mcp.setup_web import SetupServer


@pytest.fixture(autouse=True)
def isolated_setup_worker(monkeypatch, tmp_path):
    control = SimpleNamespace(home=tmp_path / "synthetic-worker", status=lambda: {
        "ok": True, "status": "service_not_started", "service_running": False,
        "logged_in": None, "monitoring": False})
    monkeypatch.setattr("stu_mcp.setup_web.CheckinClient", lambda **_: control)
    return control


def test_setup_starts_without_reverse_dns(app, monkeypatch):
    resolver = Mock(side_effect=AssertionError("local setup must not require DNS"))
    monkeypatch.setattr("socket.getfqdn", resolver)
    ui = SetupServer(app)
    try:
        assert ui.httpd.server_name == "127.0.0.1" and ui.httpd.server_port > 0
        resolver.assert_not_called()
    finally:
        ui.httpd.server_close()


def test_rejected_post_with_delayed_body_returns_complete_error_without_side_effects(app):
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        for _ in range(5):
            connection = http.client.HTTPConnection(ui.host, timeout=3)
            try:
                body = b'{"jw_http_compat":true}'
                connection.putrequest("POST", "/api/transport")
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", str(len(body)))
                connection.endheaders()
                time.sleep(.05)
                connection.send(body)
                response = connection.getresponse()
                assert response.status == 403 and b'"forbidden"' in response.read()
            finally:
                connection.close()
        assert not app.runtime.preferences()["jw_http_compat"]
    finally:
        ui.close()


def test_setup_csrf_host_and_secret(app):
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            assert client.get("/api/status").status_code == 403
            assert client.get("/api/status", headers={"X-STU-Setup": "wrong"}).status_code == 403
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            status = client.get("/api/status", headers=headers)
            assert status.status_code == 200
            assert ui.secret not in status.text
            assert client.get("/api/status", headers={**headers, "Host": "evil.example"}).status_code == 403
            assert client.get("/api/status", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
            assert client.post("/api/logout", headers={"X-STU-Setup": ui.secret}, json={"service": "jw"}).status_code == 403
            assert client.post("/api/login", headers=headers, json={"service": "jw", "password": "synthetic"}).status_code == 400
            page = client.get("/")
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            assert "Access-Control-Allow-Origin" not in page.headers
            assert 'src="/app.js"' in page.text
            assert "img-src 'self' data:" in page.headers["content-security-policy"]
    finally:
        ui.close()


def test_setup_page_only_handles_sign_in(app):
    """Client setup, refresh and profile go through the agent (CLI/MCP), not the page."""
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            for path, body in (("/api/connect", {"client": "generic"}), ("/api/refresh", {"source": "public"}),
                               ("/api/profile", {"major": "合成专业"})):
                assert client.post(path, headers=headers, json=body).status_code == 400
            assert client.get("/api/skill", headers=headers).status_code == 404
            assert "available_clients" not in client.get("/api/status", headers=headers).json()
            assert app.runtime.profile().get("major", "") == ""
    finally:
        ui.close()


def test_school_setup_starts_http_task_but_rejects_initial_credentials(app, monkeypatch):
    core = Mock(return_value={"ok": True, "status": "school_login_complete"})
    monkeypatch.setattr("stu_mcp.auth_http.login_school", core)
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            result = client.post("/api/login", headers=headers, json={"service": "school", "backend": "http"})
            assert result.json()["status"] == "running" and result.json()["id"]
            for fields in ({"password": "SYNTHETIC_SECRET"}, {"username": "SYNTHETIC_ACCOUNT"}):
                rejected = client.post("/api/login", headers=headers, json={"service": "school", **fields})
                assert rejected.status_code == 400 and "SYNTHETIC" not in rejected.text
            blocked = client.post("/api/login", headers=headers, json={"service": "school", "backend": "browser"})
            assert blocked.json()["status"] == "invalid_login_options"
    finally:
        ui.close()


def test_private_challenge_api_accepts_once_never_echoes_and_requires_all_guards(app, monkeypatch, capsys):
    def core(_vault, service, *, interaction, check_cancelled, **_):
        value = interaction.credentials()
        assert value.password == "SYNTHETIC_PRIVATE_PASSWORD"
        check_cancelled()
        return {"ok": True, "status": "session_saved", "service": service, "message": value.password}

    monkeypatch.setattr("stu_mcp.auth_http.login_http", core)
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            started = client.post("/api/login", headers=headers, json={"service": "mystu"}).json()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = client.get("/api/status", headers=headers).json()
                job = next(row for row in status["jobs"] if row["id"] == started["id"])
                if job.get("challenge"):
                    break
                time.sleep(.005)
            assert job["challenge"]["kind"] == "credentials"
            body = {"id": job["id"], "challenge_id": job["challenge"]["id"],
                    "username": "synthetic-student", "password": "SYNTHETIC_PRIVATE_PASSWORD"}
            for extra in ({"Origin": "https://evil.example"}, {"X-STU-Setup": "wrong"}, {"Host": "evil.example"}):
                denied = client.post("/api/login/input", headers={**headers, **extra}, json=body)
                assert denied.status_code == 403 and "SYNTHETIC" not in denied.text
            accepted = client.post("/api/login/input", headers=headers, json=body)
            assert accepted.json() == {"ok": True, "status": "input_received"}
            assert client.post("/api/login/input", headers=headers, json=body).status_code == 400
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                response = client.get("/api/status", headers=headers)
                job = next(row for row in response.json()["jobs"] if row["id"] == started["id"])
                if job["status"] == "finished":
                    break
                time.sleep(.005)
            assert job["result"]["status"] == "session_saved" and "challenge" not in job
            assert "SYNTHETIC_PRIVATE_PASSWORD" not in response.text
            assert "synthetic-student" not in response.text and ui.secret not in response.text
            assert "SYNTHETIC" not in capsys.readouterr().err
    finally:
        ui.close()


def test_private_input_cancel_and_invalid_payloads_are_bounded(app, monkeypatch):
    monkeypatch.setattr("stu_mcp.auth_http.login_http", lambda _v, _s, *, interaction, **_: interaction.credentials())
    ui = SetupServer(app)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            task = client.post("/api/login", headers=headers, json={"service": "mystu"}).json()
            invalid = ({}, {"id": task["id"], "extra": "SYNTHETIC_SECRET"},
                       {"id": [], "challenge_id": "bad"}, {"id": task["id"], "challenge_id": "bad",
                         "password": "X" * 20000})
            for value in invalid:
                rejected = client.post("/api/login/input", headers=headers, json=value)
                assert rejected.status_code == 400 and "SYNTHETIC" not in rejected.text
            cancelled = client.post("/api/login/cancel", headers=headers, json={"id": task["id"]})
            assert cancelled.status_code == 200
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                job = next(row for row in client.get("/api/status", headers=headers).json()["jobs"]
                           if row["id"] == task["id"])
                if job["status"] == "finished":
                    break
                time.sleep(.005)
            assert job["result"]["status"] == "operation_cancelled" and "challenge" not in job
    finally:
        ui.close()


def test_setup_status_reuses_one_passive_worker_read_and_projects_safe_state(app, tmp_path):
    control = SimpleNamespace(home=tmp_path / "worker", status=Mock(return_value={
        "ok": True, "status": "paused", "logged_in": True, "monitoring": False, "service_running": True,
        "courses": ["SYNTHETIC_PRIVATE_COURSE"], "cookie": "SYNTHETIC_PRIVATE_COOKIE"}))
    ui = SetupServer(app, checkin=control)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as client:
            result = client.get("/api/status", headers={"X-STU-Setup": ui.secret, "Origin": ui.origin})
        control.status.assert_called_once_with()
        state = result.json()["checkin"]
        assert state == {"ok": True, "status": "paused", "logged_in": True,
                         "monitoring": False, "service_running": True}
        profile = next(row for row in result.json()["capability_catalog"]["profiles"]
                       if row["configuration_id"] == "duifene")
        assert profile["state"]["status"] == "paused"
        assert profile["state"]["services"]["duifene_checkin"]["logged_in"] is True
        assert "SYNTHETIC_PRIVATE" not in result.text
        assert ui.jobs.checkin_factory() is control
    finally:
        ui.close()


@pytest.mark.parametrize("worker_state", [ValueError("SYNTHETIC_PRIVATE_ERROR"), {"status": [], "ok": True}, None])
def test_bad_worker_status_does_not_break_other_configuration_groups(app, worker_state):
    control = SimpleNamespace(status=Mock(side_effect=worker_state) if isinstance(worker_state, Exception)
                              else Mock(return_value=worker_state))
    ui = SetupServer(app, checkin=control)
    try:
        state = ui.status()
        assert state["ok"] is True and state["checkin"]["status"] == "query_error"
        assert len(state["sources"]) == 7 and state["capability_catalog"]["profiles"]
        assert "SYNTHETIC_PRIVATE_ERROR" not in str(state)
    finally:
        ui.close()
