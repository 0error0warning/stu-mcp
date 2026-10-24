"""Local setup, bound to loopback and protected against cross-origin requests."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from stu_checkin.http_server import LoopbackHTTPServer

from .auth_http.school import SCHOOL_SERVICES
from .capability_catalog import build_capability_catalog
from .checkin import CheckinClient
from .interaction import open_local_page
from .runtime import AppError
from .setup_auth import SetupAuthJobs, checkin_storage_preflight


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

    def __init__(self, app, *, port: int = 0, opener: Callable[[str], bool] | None = None, checkin=None):
        self.app = app
        if type(port) is not int or not 0 <= port <= 65535:
            raise AppError("invalid_setup_port", "设置页端口必须是 0–65535 的整数。")
        self.opener = opener if opener is not None else open_local_page
        self.secret = secrets.token_urlsafe(32)
        self.checkin = checkin if checkin is not None else CheckinClient(opener=lambda _: False)
        self.jobs = SetupAuthJobs(app.vault, checkin_factory=lambda: self.checkin,
                                 checkin_preflight=lambda: checkin_storage_preflight(getattr(self.checkin, "home", None)))
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
                                 "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                                 "frame-ancestors 'none'; base-uri 'none'; "
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

            def reject_post(self, code: int = 403):
                # Unread POST bytes can reset a closing Windows socket before the
                # client receives the error. This is only called BEFORE any body
                # read: discard at most 64 KiB within one second, without parsing.
                self.close_connection = True
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if (0 < length <= 65536 and not self.headers.get("Transfer-Encoding")
                            and len(self.headers.get_all("Content-Length", [])) == 1):
                        deadline = time.monotonic() + 1
                        while length:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                break
                            self.connection.settimeout(remaining)
                            data = self.rfile.read1(min(length, 8192))
                            if not data:
                                break
                            length -= len(data)
                except (OSError, ValueError):
                    pass
                self.json(code, {"ok": False, "status": "forbidden"} if code == 403 else {
                    "ok": False, "status": "invalid_request", "message": "请求格式无效。"})

            def do_GET(self):
                if not self.allowed(require_secret=self.path.startswith("/api/")):
                    self.json(403, {"ok": False, "status": "forbidden"})
                    return
                if self.path == "/api/status":
                    try:
                        # A finished job must precede the account-state read.
                        # An older running snapshot simply schedules one more poll.
                        jobs = owner.jobs.snapshot()
                        self.json(200, {**owner.status(), "jobs": jobs})
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
                    if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                        raise ValueError
                    length = int(self.headers.get("Content-Length", "0"))
                    maximum = 16384 if self.path == "/api/login/input" else 4096
                    if not 0 < length <= maximum:
                        self.reject_post(400)
                        return
                    self.connection.settimeout(2)
                    try:
                        payload = self.rfile.read(length)
                    except OSError:
                        raise ValueError from None
                    if len(payload) != length:
                        raise ValueError
                    data = json.loads(payload)
                    if not isinstance(data, dict):
                        raise ValueError
                    allowed_keys = {"/api/login": {"service", "reauthenticate"},
                                    "/api/login/input": {"id", "challenge_id", "username", "password", "totp", "code", "callback"},
                                    "/api/login/cancel": {"id"}, "/api/logout": {"service"}}
                    if self.path not in allowed_keys or not set(data).issubset(allowed_keys[self.path]):
                        raise ValueError
                    if self.path == "/api/login":
                        result = owner.jobs.start(**data)
                    elif self.path == "/api/login/input":
                        result = owner.jobs.submit_input(**data)
                    elif self.path == "/api/login/cancel":
                        result = owner.jobs.cancel(**data)
                    else:
                        result = owner.logout(data.get("service"))
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

    def logout(self, service: str) -> dict:
        """Remove a page configuration as a unit; source-specific CLI stays separate."""
        if not isinstance(service, str) or service not in {"school", "webvpn", "yuketang", "smartcard"}:
            raise AppError("unknown_service", "请选择已配置的账号。")
        # Cancellation and generation fences stop in-flight logins from restoring it.
        for task in self.jobs.snapshot():
            if task["service"] == service and task["status"] == "running":
                self.jobs.cancel(task["id"])
        results = [self.app.logout(source) for source in (SCHOOL_SERVICES if service == "school" else (service,))]
        return {"ok": all(result["ok"] for result in results), "status": "logged_out", "service": service}

    def status(self) -> dict:
        result = self.app.status()
        try:
            raw = self.checkin.status()  # Passive local worker read; never launches or queries the school.
        except Exception:
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        allowed = {"service_not_started", "not_logged_in", "paused", "monitoring", "query_error", "starting", "stopping"}
        status = raw.get("status")
        state = {"status": status if isinstance(status, str) and status in allowed else "query_error",
                 "ok": raw.get("ok") is True}
        for key in ("logged_in", "monitoring", "service_running"):
            state[key] = raw.get(key) if type(raw.get(key)) is bool else None
        result["checkin"] = state
        result["capability_catalog"] = build_capability_catalog(
            result["sources"], repair_status=result["repair"]["auth"], checkin_status=state,
            takeout_status=result["takeout"], freshness=result["freshness"])
        return result

    def start(self, *, open_browser: bool = True) -> bool:
        self.thread.start()
        return bool(self.opener(self.url)) if open_browser else False

    def close(self):
        self.jobs.close()
        # shutdown waits for serve_forever; calling it after Thread.start failed
        # would wait forever because no serving thread can signal completion.
        if self.thread.is_alive():
            self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
