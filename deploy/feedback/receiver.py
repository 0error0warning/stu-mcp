"""Small loopback-only feedback receiver and local administration CLI (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 20000


class Inbox:
    def __init__(self, path: str):
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, category TEXT NOT NULL,
                tool_name TEXT NOT NULL, message TEXT NOT NULL, client_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new')""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def save(self, data):
        if not isinstance(data, dict) or set(data) != {
                "report_id", "category", "tool_name", "message", "client_version"}:
            raise ValueError("invalid fields")
        if any(not isinstance(v, str) for v in data.values()):
            raise ValueError("invalid types")
        if str(uuid.UUID(data["report_id"])) != data["report_id"]:
            raise ValueError("invalid id")
        if (data["category"] not in {"bug", "data_error", "suggestion"}
                or not re.fullmatch(r"[a-zA-Z0-9_]{0,80}", data["tool_name"])
                or not 1 <= len(data["message"].strip()) <= 4000
                or not re.fullmatch(r"[a-zA-Z0-9.+_-]{1,40}", data["client_version"])):
            raise ValueError("invalid values")
        values = tuple(data[k] for k in ("category", "tool_name", "message", "client_version"))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT category,tool_name,message,client_version FROM feedback WHERE id=?",
                                  (data["report_id"],)).fetchone()
            if previous is not None:
                if previous != values:
                    raise ValueError("conflicting id")
                return
            if db.execute("SELECT count(*) FROM feedback").fetchone()[0] >= 100000:
                raise OverflowError("inbox full")
            db.execute("INSERT INTO feedback(id,created_at,category,tool_name,message,client_version) VALUES(?,?,?,?,?,?)",
                       (data["report_id"], datetime.now(UTC).isoformat(), *values))


class Receiver(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *_):
        pass  # Socket disconnects must not print peer identities or request tracebacks.

    def __init__(self, address, inbox):
        self.inbox = inbox
        self.rate_lock = threading.Lock()
        self.rates = {}
        super().__init__(address, Handler)

    def allowed(self, peer):
        minute = int(time.monotonic() // 60)
        with self.rate_lock:
            self.rates = {k: v for k, v in self.rates.items() if v[0] == minute}
            global_count = self.rates.get("*", (minute, 0))[1]
            count = self.rates.get(peer, (minute, 0))[1]
            if global_count >= 120 or count >= 10:
                return False
            self.rates["*"] = (minute, global_count + 1)
            self.rates[peer] = (minute, count + 1)
            return True


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        pass  # No body, header, URL or identity logging.

    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 405,
                   {"status": "ok"} if self.path == "/health" else {"error": "method_not_allowed"})

    def do_POST(self):
        if self.path != "/api/feedback":
            return self.reply(404, {"error": "not_found"})
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("unsupported transfer")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(min(max(length, 0), MAX_BODY + 1))
            # Only loopback Caddy connects here; its X-Forwarded-For is authoritative.
            peer = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[-1].strip()
            if not self.server.allowed(peer):
                return self.reply(429, {"error": "rate_limited"})
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {"error": "body_too_large"})
            if len(body) != length:
                raise ValueError("incomplete body")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, {"error": "json_required"})
            data = json.loads(body)
            self.server.inbox.save(data)
        except (ValueError, UnicodeError):
            return self.reply(400, {"error": "invalid_feedback"})
        except (sqlite3.Error, OSError, OverflowError):
            return self.reply(503, {"error": "storage_unavailable"})
        self.reply(201, {"feedback_id": data["report_id"], "status": "received"})


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="/var/lib/stu-mcp-feedback/feedback.sqlite3")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=18765)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    mark = sub.add_parser("mark")
    mark.add_argument("id")
    mark.add_argument("status", choices=["new", "resolved", "ignored"])
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    inbox = Inbox(args.db)
    if args.command == "serve":
        Receiver(("127.0.0.1", args.port), inbox).serve_forever()
    elif args.command == "list":
        with inbox.connect() as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
                                  (max(1, min(args.limit, 100)),)):
                print(json.dumps(dict(row), ensure_ascii=True))
    else:
        with inbox.connect() as db:
            result = db.execute("UPDATE feedback SET status=? WHERE id=?", (args.status, args.id))
            print(json.dumps({"updated": result.rowcount}))


if __name__ == "__main__":
    main()
