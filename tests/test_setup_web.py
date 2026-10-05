import httpx

from stu_mcp.setup_web import SetupServer


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
