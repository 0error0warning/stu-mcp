"""Academic collection limits and partial failure policy, independent of HTML."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from ...collection import Collection
from ...network import CampusHTTP
from ...runtime import AppError, key_lock
from ...vault import Vault
from .adapter import JwAdapter
from .schema import JW_GRADE_ROW_LIMIT, JW_TERM_PATTERN, JW_TIMETABLE_URL


def jw(vault: Vault, limit: int, semester: str, *, http_factory=CampusHTTP) -> Collection:
    result = Collection(private=True, limited=True, coverage={
        "grade_scope": semester or "available_table", "max_grade_rows": JW_GRADE_ROW_LIMIT,
        "exam_semester": semester or None, "transport": "https", "login_entry": "jwglxt",
    })
    with JwAdapter(vault, http_factory=http_factory) as adapter:
        # A failed grade read aborts the refresh before the Store can replace data.
        grades = adapter.grades(semester)
        result.coverage["grade_rows_read"] = len(grades)
        result.items.extend(grade for grade in grades[:JW_GRADE_ROW_LIMIT]
                            if not semester or grade["semester"] == semester)
        try:
            term = semester or adapter.exam_semester()
            result.coverage["exam_semester"] = term
            exams = adapter.exams(term)
            result.items.extend(exams[:limit])
            result.coverage["exam_rows_read"] = len(exams)
        except AppError as exc:
            # Independent exams must not suppress a successful grade read.
            result.fail("考试安排", exc)
        result.coverage["transport"] = adapter.transport
    return result


def academic_timetable(vault: Vault, semester: str = "", *, http_factory=CampusHTTP) -> dict:
    """Read a complete theoretical-page snapshot without using the incremental Store."""
    if not isinstance(semester, str) or semester and not re.fullmatch(JW_TERM_PATTERN, semester):
        raise AppError("invalid_semester", "学期格式为 2026-2027-1；留空使用学校当前选定学期。", "jw")
    with key_lock(vault.runtime.home, "jw"):
        revision = vault.login_revision("jw")
        adapter = JwAdapter(vault, http_factory=http_factory)
    with adapter:
        form = adapter.timetable_form()
        selected = semester or form.semester
        if selected not in {item["semester"] for item in form.semesters}:
            raise AppError("invalid_semester", "学校本人课表未提供该学期，请先留空查询当前课表及可选学期。", "jw")
        result = adapter.timetable(form, selected)
        transport = adapter.transport
    with key_lock(vault.runtime.home, "jw"):
        if revision != vault.login_revision("jw"):
            raise AppError("session_changed", "教务登录在读取期间改变，已丢弃本次课表。", "jw")
        return {"ok": True, "status": "partial" if result["pending"] else "ok", "source": "jw",
                "source_url": JW_TIMETABLE_URL, "checked_at": datetime.now(UTC).isoformat(),
                "transport": transport, "cached": False, "content_trust": "untrusted_source_data", **result}
