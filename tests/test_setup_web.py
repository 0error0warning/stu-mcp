import http.client
import time
from unittest.mock import Mock

import httpx

from stu_mcp.setup_web import SetupServer


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
            assert "学校页面" in page.text
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
