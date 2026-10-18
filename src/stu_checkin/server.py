"""Buildless local UI and worker, with no dependency on an MCP client."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import suppress
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .controller import Controller, OperationError
from .http_server import LoopbackHTTPServer
from .storage import StorageError, default_home

WEB = Path(__file__).parent / "web"
COOKIE = "stu_checkin_browser"
PROTOCOL_VERSION = 1


class LocalServer:
    def __init__(self, controller, *, port=0):
        self.controller = controller
        self.session = secrets.token_urlsafe(32)
        self.instance_id = secrets.token_hex(16)
        self.control_lock = threading.Lock()
        self.shutting_down = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(15)

            def reply(self, status, body, content_type="application/json; charset=utf-8", *, cookie=False):
                if isinstance(body, dict):
                    body = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                                 "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; "
                                 "base-uri 'none'; form-action 'none'")
                if cookie:
                    self.send_header("Set-Cookie", f"{owner.cookie_name}={owner.session}; HttpOnly; SameSite=Strict; Path=/")
                self.end_headers()
                with suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(body)

            def allowed(self, *, api=False):
                if self.headers.get("Host") != owner.host:
                    return False
                origin = self.headers.get("Origin")
                if origin and origin != owner.url.rstrip("/"):
                    return False
                if self.command == "POST" and origin != owner.url.rstrip("/"):
                    return False
                if not api:
                    return True
                try:
                    cookies = SimpleCookie(self.headers.get("Cookie", ""))
                    value = cookies[owner.cookie_name].value if owner.cookie_name in cookies else ""
                except Exception:
                    return False
                return self.headers.get("X-STU-Client") == "local-ui" and hmac.compare_digest(value, owner.session)

            def do_GET(self):
                api = self.path.startswith("/api/")
                if not self.allowed(api=api):
                    self.reply(403, {"ok": False, "message": "本地连接已过期，请重新打开页面。"})
                    return
                if self.path == "/health":
                    self.reply(200, owner.info() | {"ok": True, "shutting_down": owner.shutting_down})
                    return
                if self.path == "/api/state":
                    self.reply(200, owner.controller.snapshot())
                    return
                if self.path == "/api/results":
                    self.reply(200, owner.controller.results())
                    return
                assets = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                    "/icon.svg": ("icon.svg", "image/svg+xml"),
                }
                if self.path not in assets:
                    self.reply(404, {"ok": False, "message": "页面不存在。"})
                    return
                name, kind = assets[self.path]
                self.reply(200, (WEB / name).read_bytes(), kind, cookie=self.path == "/")

            def reject_post(self, code, message):
                # Preserve a readable error response when a Windows client sends
                # headers and body separately. Never parse or retain rejected data.
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if 0 < size <= 8192 and not self.headers.get("Transfer-Encoding"):
                        self.connection.settimeout(1)
                        self.rfile.read(size)
                except (OSError, ValueError):
                    pass
                self.reply(code, {"ok": False, "message": message})

            def do_POST(self):
                if not self.allowed(api=True):
                    self.reject_post(403, "请求来源不被允许。")
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.reject_post(415, "请求格式不正确。")
                    return
                with owner.control_lock:
                    if owner.shutting_down:
                        self.reject_post(409, "服务正在退出，请稍候。")
                        return
                    self.dispatch_post()

            def dispatch_post(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 8192:
                        raise ValueError
                    data = json.loads(self.rfile.read(size))
                    keys = {"/api/connect": {"link"}, "/api/start": {"course_ids", "minutes"},
                            "/api/select": {"course_ids"},
                            "/api/pause": set(), "/api/disconnect": set(), "/api/quit": set()}
                    if not isinstance(data, dict) or self.path not in keys or set(data) != keys[self.path]:
                        raise ValueError
                    if self.path == "/api/connect":
                        result = owner.controller.connect(data["link"])
                    elif self.path == "/api/start":
                        result = owner.controller.start(data["course_ids"], data["minutes"])
                    elif self.path == "/api/select":
                        result = owner.controller.select(data["course_ids"])
                    elif self.path == "/api/pause":
                        result = owner.controller.pause()
                    elif self.path == "/api/disconnect":
                        result = owner.controller.disconnect()
                    else:
                        result = {"ok": True}
                        owner.shutting_down = True
                        threading.Thread(target=owner.httpd.shutdown, daemon=True).start()
                    self.reply(200, result)
                except (ValueError, TypeError, KeyError):
                    self.reply(400, {"ok": False, "message": "请求内容不正确，请刷新页面。"})
                except (OperationError, StorageError) as exc:
                    self.reply(400, {"ok": False, "message": str(exc)})
                except Exception:
                    self.reply(500, {"ok": False, "message": "操作未完成，请稍后重试。"})

        self.httpd = LoopbackHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.host = f"127.0.0.1:{self.httpd.server_port}"
        self.cookie_name = f"{COOKIE}_{self.httpd.server_port}"
        self.url = f"http://{self.host}/"

    def info(self):
        return {"url": self.url, "pid": os.getpid(), "service": "stu-checkin",
                "instance_id": self.instance_id, "protocol_version": PROTOCOL_VERSION}

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class InstanceLock:
    def __init__(self, home: Path):
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = (home / "worker.lock").open("a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()

    def __enter__(self):
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise OperationError("本地服务已在运行。") from None
        return self

    def __exit__(self, *_):
        self.handle.close()


def publish_runtime(home, info):
    fd, path = tempfile.mkstemp(prefix=".runtime-", dir=home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(info, stream)
        os.replace(path, home / "runtime.json")
    finally:
        if os.path.exists(path):
            os.unlink(path)


def existing_url(home, *, timeout=3):
    """Duplicate launchers wait for discovery; stale PIDs/URLs are never trusted."""
    import requests

    deadline = time.monotonic() + timeout
    with requests.Session() as client:
        client.trust_env = False
        while time.monotonic() < deadline:
            try:
                info = json.loads((home / "runtime.json").read_text(encoding="utf-8"))
                from urllib.parse import urlparse
                parsed = urlparse(info["url"])
                if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                        or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/"):
                    return None
                response = client.get(info["url"] + "health", timeout=1, allow_redirects=False)
                health = response.json()
                if (response.status_code == 200 and health.get("service") == "stu-checkin"
                        and health.get("pid") == info.get("pid") and info.get("instance_id")
                        and health.get("instance_id") == info["instance_id"] and not health.get("shutting_down")):
                    return info["url"]
            except (OSError, ValueError, KeyError, requests.RequestException):
                pass
            time.sleep(0.1)
    return None


def main():
    parser = argparse.ArgumentParser(description="轻量本地课堂签到页")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    home = default_home()
    try:
        with InstanceLock(home):
            # Only the lock owner may retire stale discovery data from a previous process.
            (home / "runtime.json").unlink(missing_ok=True)
            controller = Controller(home)
            server = None
            try:
                server = LocalServer(controller, port=args.port)
                publish_runtime(home, server.info())
                if sys.stdout:
                    print("Local: " + server.url, flush=True)
                if not args.no_browser:
                    webbrowser.open(server.url)
                server.httpd.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                pass
            finally:
                controller.close()
                if server:
                    server.httpd.server_close()
                (home / "runtime.json").unlink(missing_ok=True)
    except OperationError:
        if not args.no_browser and (url := existing_url(home)):
            webbrowser.open(url)


if __name__ == "__main__":
    main()
