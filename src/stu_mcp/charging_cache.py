"""Atomic public charging snapshots and leases shared by local MCP processes."""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable

from .store import Store

TTL = 60
STALE_AFTER = 120
LEASE_SECONDS = 60


class ChargingCache:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock
        with store.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS charging_snapshots (
                    code TEXT PRIMARY KEY, payload TEXT, error TEXT,
                    attempted_at REAL, retry_at REAL NOT NULL DEFAULT 0,
                    lease_until REAL NOT NULL DEFAULT 0, lease_id TEXT);
                CREATE TABLE IF NOT EXISTS charging_cooldown (
                    id INTEGER PRIMARY KEY CHECK(id=1), retry_at REAL NOT NULL, error TEXT NOT NULL);
            """)

    def read(self, code: str) -> dict:
        with self.store.connect() as c:
            row = c.execute("SELECT * FROM charging_snapshots WHERE code=?", (code,)).fetchone()
        return dict(row) if row else {}

    def claim(self, code: str) -> tuple[str | None, dict, dict | None]:
        """A lease, a recent attempt, or a provider cooldown prevents duplicate reads."""
        now = self.clock()
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM charging_snapshots WHERE code=?", (code,)).fetchone()
            previous = dict(row) if row else {}
            if previous.get("lease_until", 0) > now:
                return None, previous, {"ok": False, "status": "refresh_running", "source": "charging",
                                        "message": "此设备正在由另一个本机查询刷新，请稍后读取缓存。",
                                        "retryable": True, "retry_after_seconds": 1}
            if previous.get("retry_at", 0) > now:
                return None, previous, None
            cooldown = c.execute("SELECT * FROM charging_cooldown WHERE id=1").fetchone()
            if cooldown and cooldown["retry_at"] > now:
                error = json.loads(cooldown["error"])
                error["retry_after_seconds"] = max(1, int(cooldown["retry_at"] - now + 0.999))
                return None, previous, error
            token = uuid.uuid4().hex
            c.execute("INSERT OR IGNORE INTO charging_snapshots(code) VALUES (?)", (code,))
            c.execute("UPDATE charging_snapshots SET attempted_at=?,retry_at=?,lease_until=?,lease_id=? WHERE code=?",
                      (now, now + TTL, now + LEASE_SECONDS, token, code))
            return token, previous, None

    def finish(self, code: str, token: str, payload: dict | None, error: dict | None) -> dict:
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM charging_snapshots WHERE code=?", (code,)).fetchone()
            if row and row["lease_id"] == token:
                # A failed attempt never replaces the last successful sample or its timestamp.
                saved = json.dumps(payload, ensure_ascii=False) if payload is not None else row["payload"]
                retry_at = max(row["retry_at"], self.clock() + min(86400, error.get("retry_after_seconds") or 0)) if error else row["retry_at"]
                c.execute("UPDATE charging_snapshots SET payload=?,error=?,retry_at=?,lease_until=0,lease_id=NULL WHERE code=?",
                          (saved, json.dumps(error, ensure_ascii=False) if error else None, retry_at, code))
        return self.read(code)

    def cooldown(self, error: dict) -> None:
        delay = max(TTL, min(86400, error.get("retry_after_seconds") or TTL))
        until = self.clock() + delay
        with self.store.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("INSERT INTO charging_cooldown VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET "
                      "retry_at=excluded.retry_at,error=excluded.error WHERE excluded.retry_at>charging_cooldown.retry_at",
                      (until, json.dumps(error, ensure_ascii=False)))
