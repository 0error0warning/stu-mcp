import io
import zipfile

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
            modes = {c["id"]: c["mode"] for c in status.json()["available_clients"]}
            assert modes["deepseek-harness"] == "cordis" and modes["doubao-work"] == "skill"
            assert ui.secret not in status.text
            assert client.get("/api/status", headers={**headers, "Host": "evil.example"}).status_code == 403
            assert client.get("/api/status", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
            assert client.post("/api/profile", headers={"X-STU-Setup": ui.secret}, json={"major": "合成专业"}).status_code == 403
            assert client.post("/api/profile", headers=headers, json={"password": "synthetic"}).status_code == 400
            assert client.post("/api/profile", headers=headers, json={"major": "合成专业"}).status_code == 200
            assert app.runtime.profile()["major"] == "合成专业"
            page = client.get("/")
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            assert "Access-Control-Allow-Origin" not in page.headers
            assert "学校页面" in page.text
            config = client.post("/api/connect", headers=headers, json={"client": "generic"}).json()["config"]
            assert set(config["mcpServers"]["stu-mcp"]) == {"command", "args"}
            assert client.get("/api/skill").status_code == 403
            assert client.get("/api/skill", headers=headers).status_code == 400
            exported = client.post("/api/connect", headers=headers, json={"client": "doubao-work"}).json()
            assert exported["status"] == "skill_exported"
            skill = client.get("/api/skill", headers=headers)
            assert skill.status_code == 200
            assert skill.headers["content-type"] == "application/zip"
            assert "attachment" in skill.headers["content-disposition"]
            with zipfile.ZipFile(io.BytesIO(skill.content)) as archive:
                assert "stu-campus/SKILL.md" in archive.namelist()
    finally:
        ui.close()
