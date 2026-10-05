"""Local setup, bound to loopback and protected against cross-origin requests."""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .auth import LoginJobs
from .clients import catalog, connect, detected_clients
from .runtime import AppError, reject_symlinks
from .skill_export import skill_path


class SetupServer:
    def __init__(self, app, *, client_home: Path | None = None):
        self.app = app
        self.client_home = client_home
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
                if content_type == "application/zip":
                    self.send_header("Content-Disposition", 'attachment; filename="stu-campus.zip"')
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

            def do_GET(self):
                if not self.allowed(require_secret=self.path.startswith("/api/")):
                    self.json(403, {"ok": False, "status": "forbidden"})
                    return
                if self.path == "/api/status":
                    try:
                        status = owner.app.status()
                        status["available_clients"] = catalog(owner.client_home)
                        if owner.client_home is not None:
                            status["clients"] = detected_clients(owner.client_home)
                        self.json(200, {**status, "jobs": owner.jobs.snapshot()})
                    except AppError as exc:
                        self.json(400, exc.result())
                    return
                if self.path == "/api/skill":
                    path = skill_path(owner.app.runtime)
                    try:
                        reject_symlinks(path)
                        if not path.is_file() or path.stat().st_size > 256 * 1024:
                            raise AppError("skill_not_exported", "请先生成技能包。")
                        self.reply(200, path.read_bytes(), "application/zip")
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
                    self.json(403, {"ok": False, "status": "forbidden"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 4096:
                        raise ValueError
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError
                    allowed_keys = {"/api/login": {"service"}, "/api/logout": {"service"},
                                    "/api/refresh": {"source"}, "/api/connect": {"client"},
                                    "/api/transport": {"jw_http_compat"},
                                    "/api/profile": {"college", "major", "entry_year", "interests"}}
                    if self.path not in allowed_keys or not set(data).issubset(allowed_keys[self.path]):
                        raise ValueError
                    if self.path == "/api/login":
                        result = owner.jobs.start(str(data.get("service", "")))
                    elif self.path == "/api/logout":
                        result = owner.app.logout(str(data.get("service", "")))
                    elif self.path == "/api/refresh":
                        result = owner.app.refresh(str(data.get("source", "")))
                    elif self.path == "/api/connect":
                        client = str(data.get("client", ""))
                        result = connect(client, owner.app.runtime, apply=True, home=owner.client_home)
                    elif self.path == "/api/transport":
                        owner.app.runtime.save_preferences(data)
                        result = {"ok": True, "status": "saved"}
                    else:
                        owner.app.runtime.save_profile(data)
                        result = {"ok": True, "status": "saved"}
                    self.json(200, result)
                except (ValueError, TypeError, KeyError):
                    self.json(400, {"ok": False, "status": "invalid_request", "message": "请求格式无效。"})
                except AppError as exc:
                    self.json(400, exc.result())
                except Exception:
                    self.json(500, {"ok": False, "status": "setup_error", "message": "操作未完成，请重试或通过命令行检查。"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.host = f"127.0.0.1:{self.httpd.server_port}"
        self.origin = "http://" + self.host
        self.url = self.origin + "/#" + self.secret
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="stu-setup")

    def start(self, *, open_browser: bool = True) -> bool:
        self.thread.start()
        return bool(webbrowser.open(self.url)) if open_browser else False

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
