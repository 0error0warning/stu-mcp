"""Local setup, bound to loopback and protected against cross-origin requests."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from stu_checkin.http_server import LoopbackHTTPServer

from .auth import LoginJobs
from .interaction import open_local_page
from .runtime import AppError
from .webvpn import WebVPNConfig


class _SetupHTTPServer(LoopbackHTTPServer):
    def server_bind(self):
        if os.name == "nt":
            # Windows SO_REUSEADDR permits a second process to hijack an active
            # fixed port. Keep this page exclusive without changing POSIX reuse.
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class SetupServer:
    """Sign-in only. Client setup, refresh and profile belong to the agent via CLI/MCP."""

    def __init__(self, app, *, port: int = 0, opener: Callable[[str], bool] | None = None):
        self.app = app
        if type(port) is not int or not 0 <= port <= 65535:
            raise AppError("invalid_setup_port", "设置页端口必须是 0–65535 的整数。")
        self.opener = opener if opener is not None else open_local_page
        self.secret = secrets.token_urlsafe(32)
        self.jobs = LoginJobs(app.vault)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # Never log setup capabilities, request bodies or login URLs.

            def reply(self, code: int, body: bytes, content_type: str = "application/json; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; "
                                 "style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                 "form-action 'none'")
                self.end_headers()
                self.wfile.write(body)

            def json(self, code: int, data: dict):
                self.reply(code, json.dumps(data, ensure_ascii=False).encode())

            def allowed(self, require_secret: bool = True) -> bool:
                if self.headers.get("Host") != owner.host:
                    return False
                origin = self.headers.get("Origin")
                if origin and origin != owner.origin:
                    return False
                if self.command == "POST" and origin != owner.origin:
                    return False
                return not require_secret or hmac.compare_digest(self.headers.get("X-STU-Setup", ""), owner.secret)

            def reject_post(self):
                # Unread POST bytes can reset a closing Windows socket before the
                # client receives the 403. Discard only a bounded body, never parse it.
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if 0 < length <= 4096 and not self.headers.get("Transfer-Encoding"):
                        self.connection.settimeout(1)
                        self.rfile.read(length)
                except (OSError, ValueError):
                    pass
                self.json(403, {"ok": False, "status": "forbidden"})

            def do_GET(self):
                if not self.allowed(require_secret=self.path.startswith("/api/")):
                    self.json(403, {"ok": False, "status": "forbidden"})
                    return
                if self.path == "/api/status":
                    try:
                        self.json(200, {**owner.app.status(), "jobs": owner.jobs.snapshot()})
                    except AppError as exc:
                        self.json(400, exc.result())
                    return
                assets = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8")}
                if self.path not in assets:
                    self.json(404, {"ok": False, "status": "not_found"})
                    return
                file, kind = assets[self.path]
                self.reply(200, (Path(__file__).parent / "web" / file).read_bytes(), kind)

            def do_POST(self):
                if not self.allowed() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.reject_post()
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096:
                        raise ValueError
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError
                    allowed_keys = {"/api/login": {"service"}, "/api/logout": {"service"},
                                    "/api/transport": {"jw_http_compat"},
                                    "/api/webvpn-auto": {"enabled", "username", "password", "totp", "encoding"},
                                    "/api/webvpn-auto/remove": set()}
                    if self.path not in allowed_keys or not set(data).issubset(allowed_keys[self.path]):
                        raise ValueError
                    if self.path == "/api/login":
                        result = owner.jobs.start(str(data.get("service", "")))
                    elif self.path == "/api/logout":
                        result = owner.app.logout(str(data.get("service", "")))
                    elif self.path == "/api/transport":
                        owner.app.runtime.save_preferences(data)
                        result = {"ok": True, "status": "saved"}
                    elif self.path == "/api/webvpn-auto":
                        result = WebVPNConfig(owner.app.vault).configure(data)
                    else:
                        result = WebVPNConfig(owner.app.vault).remove()
                    self.json(200, result)
                except (ValueError, TypeError, KeyError):
                    self.json(400, {"ok": False, "status": "invalid_request", "message": "请求格式无效。"})
                except AppError as exc:
                    self.json(400, exc.result())
                except Exception:
                    self.json(500, {"ok": False, "status": "setup_error", "message": "操作未完成，请重试或通过命令行检查。"})

        self.httpd = _SetupHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.host = f"127.0.0.1:{self.httpd.server_port}"
        self.origin = "http://" + self.host
        self.url = self.origin + "/#" + self.secret
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="stu-setup")

    def start(self, *, open_browser: bool = True) -> bool:
        self.thread.start()
        return bool(self.opener(self.url)) if open_browser else False

    def close(self):
        # shutdown waits for serve_forever; calling it after Thread.start failed
        # would wait forever because no serving thread can signal completion.
        if self.thread.is_alive():
            self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
