from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .runtime import AppError, Runtime, reject_symlinks
from .vault import Vault


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, runtime: Runtime, vault: Vault):
        self.runtime, self.vault = runtime, vault
        runtime.ensure()
        with self.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    source TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
                    payload BLOB NOT NULL, private INTEGER NOT NULL, collected_at TEXT NOT NULL,
                    PRIMARY KEY(source,kind,id));
                CREATE TABLE IF NOT EXISTS source_status (
                    source TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, success_at TEXT,
                    status TEXT NOT NULL, saved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS task_overrides (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        reject_symlinks(self.runtime.db)
        c = sqlite3.connect(self.runtime.db, timeout=10)
        if os.name != "nt":
            self.runtime.db.chmod(0o600)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=10000")
        try:
            with c:
                yield c
        finally:
            c.close()

    def save_batch(self, source: str, records: list[dict], *, private: bool = False) -> int:
        if source not in ("public", "oa", "jw", "mystu", "yuketang", "local"):
            raise AppError("unknown_source", "不支持此数据来源。")
        if source in {"jw", "mystu", "yuketang"} and not private:
            raise AppError("private_storage_required", "此来源必须加密保存。", source)
        timestamp = now()
        cipher = self.vault._cipher(create=True) if records and private else None
        rows = []
        for item in records:
            data = {**item, "source": source, "collected_at": timestamp}
            payload = self.vault.protect(data, cipher=cipher) if private else json.dumps(data, ensure_ascii=False).encode()
            rows.append((source, item["kind"], item["id"], payload, int(private), timestamp))
        with self.connect() as c:
            c.executemany("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)", rows)
        return len(rows)

    def record_status(self, source: str, status: str, saved: int = 0) -> None:
        with self.connect() as c:
            old = c.execute("SELECT success_at FROM source_status WHERE source=?", (source,)).fetchone()
            success = now() if status in ("ok", "partial") else (old[0] if old else None)
            c.execute("INSERT OR REPLACE INTO source_status VALUES (?,?,?,?,?)",
                      (source, now(), success, status, saved))

    def freshness(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM source_status ORDER BY source")]

    def list(self, *, sources: tuple[str, ...], kind: str | None = None, limit: int = 50,
             query: str = "", offset: int = 0, _all_items: bool = False) -> dict:
        if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
            raise AppError("invalid_limit", "每页 1–50 条，偏移量最大 10000。")
        clauses, params = ["source IN (" + ",".join("?" for _ in sources) + ")"], list(sources)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        with self.connect() as c:
            rows = c.execute("SELECT * FROM records WHERE " + " AND ".join(clauses) +
                             " ORDER BY collected_at DESC, id ASC LIMIT 5000", params).fetchall()
            overrides = {r[0]: r[1] for r in c.execute("SELECT id,status FROM task_overrides")}
        items, unavailable = [], []
        cipher, key_problem = None, None
        if any(row["private"] for row in rows):
            try:
                cipher = self.vault._cipher()
            except AppError as exc:
                key_problem = exc
        for row in rows:
            try:
                if row["private"] and key_problem:
                    raise key_problem
                item = self.vault.unprotect(bytes(row["payload"]), cipher=cipher) if row["private"] else json.loads(row["payload"])
            except AppError as exc:
                unavailable.append({"source": row["source"], "status": exc.code})
                continue
            if query and not all(t.casefold() in json.dumps(item, ensure_ascii=False).casefold()
                                 for t in query.split()):
                continue
            if item["kind"] == "task" and item["id"] in overrides:
                item["status"] = overrides[item["id"]]
            items.append(item)
        return {"ok": True, "items": items if _all_items else items[offset:offset + limit], "total_count": len(items),
                "offset": offset, "has_more": len(items) > offset + limit, "cached": True,
                "unavailable": list({(r["source"], r["status"]): r for r in unavailable}.values()),
                "scan_capped": len(rows) == 5000, "freshness": self.freshness()}

    def get(self, item_id: str) -> dict:
        with self.connect() as c:
            row = c.execute("SELECT * FROM records WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise AppError("not_cached", "缓存中尚无此记录；这不表示学校没有该事项。")
        return self.vault.unprotect(bytes(row["payload"])) if row["private"] else json.loads(row["payload"])

    def set_task_status(self, item_id: str, status: str) -> dict:
        if status not in ("todo", "done", "ignored") or self.get(item_id)["kind"] != "task":
            raise AppError("invalid_task", "请选择待办，并使用 todo、done 或 ignored 状态。")
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO task_overrides VALUES (?,?)", (item_id, status))
        return {"ok": True, "id": item_id, "status": status}

    def forget(self, source: str) -> None:
        with self.connect() as c:
            c.execute("DELETE FROM task_overrides WHERE id IN (SELECT id FROM records WHERE source=?)", (source,))
            c.execute("DELETE FROM records WHERE source=?", (source,))
            c.execute("DELETE FROM source_status WHERE source=?", (source,))
