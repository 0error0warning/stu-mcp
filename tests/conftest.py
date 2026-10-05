from pathlib import Path

import pytest

from stu_mcp.app import App
from stu_mcp.runtime import Runtime
from stu_mcp.vault import Vault


class MemoryKeys:
    def __init__(self):
        self.values = {}
        self.writes = 0

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, password):
        self.values[(service, username)] = password
        self.writes += 1

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


@pytest.fixture
def keys():
    return MemoryKeys()


@pytest.fixture
def app(tmp_path, keys):
    runtime = Runtime(tmp_path / "runtime")
    return App(runtime, Vault(runtime, keys))


@pytest.fixture
def session():
    return {"cookies": [{"name": "sessionid", "value": "SYNTHETIC_SESSION_NEVER_REAL",
                         "domain": "my.stu.edu.cn", "path": "/", "expires": -1,
                         "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": []}


@pytest.fixture
def grades_html():
    return (Path(__file__).parent / "fixtures" / "grades.html").read_text(encoding="utf-8")
