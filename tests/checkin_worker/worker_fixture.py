"""Synthetic process fixture for MCP/worker integration; never uses a real account."""
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_app import MemoryKeys, connect, controller  # noqa: E402

from stu_checkin.server import InstanceLock, LocalServer, publish_runtime  # noqa: E402
from stu_checkin.storage import SecureStore  # noqa: E402


def main():
    home = Path(os.environ["STU_CHECKIN_HOME"])
    with InstanceLock(home), pytest.MonkeyPatch.context() as patch:
        fixture = controller.__wrapped__(SecureStore(home, key_store=MemoryKeys()), patch)
        app = next(fixture)
        app.fake_session.courses.append({"CourseID": "course-b", "TClassID": "class-b", "CourseName": "合成第二课程"})
        connect(app)
        app.fake_session.attended = True
        server = LocalServer(app)
        publish_runtime(home, server.info())
        stopped = threading.Event()

        def controls():
            while not stopped.wait(.03):
                try:
                    data = json.loads((home / "fixture-controls.json").read_text())
                    app.fake_session.fail_classes = {"class-b"} if data.get("fail") else set()
                except (OSError, ValueError):
                    pass

        thread = threading.Thread(target=controls, daemon=True)
        thread.start()
        try:
            server.httpd.serve_forever(poll_interval=.05)
        finally:
            stopped.set()
            app.close()
            server.httpd.server_close()
            (home / "runtime.json").unlink(missing_ok=True)
            fixture.close()
            time.sleep(.05)


if __name__ == "__main__":
    main()
