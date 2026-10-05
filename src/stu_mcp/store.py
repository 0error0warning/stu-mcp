from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .huyou import merge_post, searchable_text
from .runtime import AppError, Runtime, reject_symlinks
from .sync import COURSE_KINDS, CourseSync, in_scope
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
                CREATE TABLE IF NOT EXISTS course_scopes (
                    source TEXT PRIMARY KEY, payload BLOB NOT NULL);
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

    def save_batch(self, source: str, records: list[dict], *, private: bool = False,
                   sync: CourseSync | None = None) -> int:
        if source not in ("public", "oa", "jw", "mystu", "yuketang", "huyou", "local"):
            raise AppError("unknown_source", "不支持此数据来源。")
        if source in {"jw", "mystu", "yuketang"} and not private:
            raise AppError("private_storage_required", "此来源必须加密保存。", source)
        if sync is not None and source not in {"mystu", "yuketang"}:
            raise AppError("invalid_sync", "此来源不支持课程范围同步。", source)
        if source == "huyou":
            if private:
                raise AppError("unsupported_auth", "狐友来源仅缓存匿名读取的公开帖子。", source)
            return len(self.save_community(records))
        timestamp = now()
        cipher = self.vault._cipher(create=True) if private and (records or sync is not None) else None
        rows = []
        for item in records:
            data = {**item, "source": source, "collected_at": timestamp}
            payload = self.vault.protect(data, cipher=cipher) if private else json.dumps(data, ensure_ascii=False).encode()
            rows.append((source, item["kind"], item["id"], payload, int(private), timestamp))
        with self.connect() as c:
            if sync is not None:
                incoming_ids = {item["id"] for item in records}
                old = c.execute("SELECT * FROM records WHERE source=? AND kind IN ('course','task','resource')",
                                (source,)).fetchall()
                retired = []
                for row in old:
                    item = self.vault.unprotect(bytes(row["payload"]), cipher=cipher)
                    if sync.obsolete(item, incoming_ids):
                        retired.append((source, row["kind"], row["id"]))
                c.executemany("DELETE FROM records WHERE source=? AND kind=? AND id=?", retired)
                c.executemany("DELETE FROM task_overrides WHERE id=?", [(r[2],) for r in retired])
                if sync.course_ids is not None:
                    scope = {**sync.scope(), "collected_at": timestamp}
                    c.execute("INSERT OR REPLACE INTO course_scopes VALUES (?,?)",
                              (source, self.vault.protect(scope, cipher=cipher)))
            c.executemany("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)", rows)
        return len(rows)

    def save_community(self, records: list[dict]) -> list[dict]:
        """Atomic public-post merge: a search snippet never replaces a fetched body/thread."""
        timestamp, saved = now(), []
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            for incoming in records:
                if incoming.get("source") != "huyou" or incoming.get("kind") != "post":
                    raise AppError("invalid_post", "此缓存入口仅接受狐友公开帖子。", "huyou")
                row = c.execute("SELECT payload FROM records WHERE source='huyou' AND kind='post' AND id=?",
                                (incoming["id"],)).fetchone()
                item = merge_post(json.loads(row[0]), incoming) if row else incoming.copy()
                item.update(source="huyou", collected_at=timestamp)
                c.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?)",
                          ("huyou", "post", item["id"], json.dumps(item, ensure_ascii=False).encode(), 0, timestamp))
                saved.append(item)
        return saved

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
            scope_rows = c.execute("SELECT * FROM course_scopes WHERE source IN (" +
                                   ",".join("?" for _ in sources) + ")", list(sources)).fetchall() if (
                                       kind is None or kind in COURSE_KINDS) else []
        items, unavailable = [], []
        cipher, key_problem = None, None
        if scope_rows or any(row["private"] for row in rows):
            try:
                cipher = self.vault._cipher()
            except AppError as exc:
                key_problem = exc
        scopes, blocked_scopes, unverified_count = {}, set(), 0
        for row in scope_rows:
            try:
                if key_problem:
                    raise key_problem
                scopes[row["source"]] = self.vault.unprotect(bytes(row["payload"]), cipher=cipher)
            except AppError as exc:
                unavailable.append({"source": row["source"], "status": exc.code})
                blocked_scopes.add(row["source"])
        for row in rows:
            try:
                if row["private"] and key_problem:
                    raise key_problem
                item = self.vault.unprotect(bytes(row["payload"]), cipher=cipher) if row["private"] else json.loads(row["payload"])
            except AppError as exc:
                unavailable.append({"source": row["source"], "status": exc.code})
                continue
            if row["source"] in blocked_scopes and item["kind"] in COURSE_KINDS:
                continue
            if row["source"] in scopes and not in_scope(item, scopes[row["source"]]):
                unverified_count += 1
                continue
            haystack = searchable_text(item) if item["kind"] == "post" else json.dumps(item, ensure_ascii=False)
            if query and not all(t.casefold() in haystack.casefold() for t in query.split()):
                continue
            if item["kind"] == "task" and item["id"] in overrides:
                item["status"] = overrides[item["id"]]
            items.append(item)
        return {"ok": True, "items": items if _all_items else items[offset:offset + limit], "total_count": len(items),
                "offset": offset, "has_more": len(items) > offset + limit, "cached": True,
                "unavailable": list({(r["source"], r["status"]): r for r in unavailable}.values()),
                "unverified_count": unverified_count,
                "scopes": [{"source": source, "semester": scope["semester"],
                            "course_count": len(scope["course_ids"]), "collected_at": scope["collected_at"]}
                           for source, scope in scopes.items()],
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
            c.execute("DELETE FROM course_scopes WHERE source=?", (source,))
