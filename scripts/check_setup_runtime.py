"""Exercise the installed private-page HTTP flow without a browser or school I/O."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from stu_mcp.app import App
from stu_mcp.auth_http import Candidate, cas
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import Runtime
from stu_mcp.setup_web import SetupServer


def main() -> None:
    root = Path(sys.argv[1])
    assert importlib.util.find_spec("playwright") is None
    app = App(Runtime(root / "setup-data"))
    calls = []

    def synthetic(source, username, password, *, check, **_):
        check()
        assert (username, password) == ("synthetic-student", "SYNTHETIC_PRIVATE_PASSWORD")
        calls.append(source)
        return Candidate({"cookies": [], "origins": []}, {"authenticated": True})

    cas.acquire_state = synthetic
    worker = SimpleNamespace(status=lambda: {"ok": True, "status": "service_not_started",
                                            "service_running": False, "logged_in": False, "monitoring": False})
    ui = SetupServer(app, checkin=worker)
    ui.start(open_browser=False)
    try:
        with httpx.Client(base_url=ui.origin, trust_env=False) as browser:
            headers = {"X-STU-Setup": ui.secret, "Origin": ui.origin}
            assert browser.get("/").status_code == 200
            job = browser.post("/api/login", headers=headers, json={"service": "school"}).json()
            deadline = time.monotonic() + 20
            answered = False
            while time.monotonic() < deadline:
                state = browser.get("/api/status", headers=headers).json()
                current = next(item for item in state["jobs"] if item["id"] == job["id"])
                assert "SYNTHETIC_PRIVATE_PASSWORD" not in json.dumps(state)
                if current.get("challenge") and not answered:
                    response = browser.post("/api/login/input", headers=headers, json={
                        "id": job["id"], "challenge_id": current["challenge"]["id"],
                        "username": "synthetic-student", "password": "SYNTHETIC_PRIVATE_PASSWORD"})
                    assert response.json()["ok"]
                    answered = True
                if current["status"] == "finished":
                    assert current["result"]["ok"], current["result"]
                    break
                time.sleep(.02)
            else:
                raise AssertionError("installed private setup did not finish within its budget")
            assert calls == ["jw", "mystu", "repair"]
            assert app.vault.status("jw")["status"] == "session_saved"
            assert app.vault.status("mystu")["status"] == "session_saved"
            assert app.vault.status("repair")["status"] == "session_saved"
            assert "challenge" not in app.status()
            host = HostRuntime(App(Runtime(app.runtime.home)), checkin=worker)
            try:
                capabilities = host.capabilities()
                school = next(profile for profile in capabilities["capability_catalog"]["profiles"]
                              if profile["configuration_id"] == "school")
                assert school["state"]["saved_session_count"] == 3
                assert "challenge" not in capabilities and "SYNTHETIC_PRIVATE_PASSWORD" not in json.dumps(capabilities)
            finally:
                host.close()
    finally:
        ui.close()
    print("setup: installed private-page HTTP flow saved separate sessions with no TTY or Playwright")


if __name__ == "__main__":
    main()
