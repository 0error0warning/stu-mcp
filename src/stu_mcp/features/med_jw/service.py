"""On-demand medical timetable snapshots using the shared Vault lifecycle."""
from __future__ import annotations

from datetime import UTC, datetime

from ...runtime import AppError, key_lock
from ...vault import Vault
from .adapter import MedJwAdapter
from .schema import MED_JW_SOURCE, MED_JW_TIMETABLE_URL


def academic_timetable(vault: Vault, semester: str = "", *, transport=None) -> dict:
    """Read the source-selected term; no cache replacement or calendar inference."""
    if not isinstance(semester, str) or semester:
        raise AppError("unsupported_semester", "医学院目前只支持读取学校当前课表，请将学期留空。", MED_JW_SOURCE)
    with key_lock(vault.runtime.home, MED_JW_SOURCE):
        revision = vault.login_revision(MED_JW_SOURCE)
        state = vault.load(MED_JW_SOURCE)
    with MedJwAdapter(state, transport=transport) as adapter:
        result = adapter.timetable()
    with key_lock(vault.runtime.home, MED_JW_SOURCE):
        if revision != vault.login_revision(MED_JW_SOURCE):
            raise AppError("session_changed", "医学院登录在读取期间改变，已丢弃本次课表。", MED_JW_SOURCE)
        partial = bool(result["pending"]) or not result["coverage"]["complete"]
        return {"ok": True, "status": "partial" if partial else "ok", "source": MED_JW_SOURCE,
                "source_url": MED_JW_TIMETABLE_URL, "checked_at": datetime.now(UTC).isoformat(),
                "transport": "https", "cached": False, "content_trust": "untrusted_source_data", **result}
