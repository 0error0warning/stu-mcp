"""Academic collection limits and partial failure policy, independent of HTML."""
from __future__ import annotations

from ...collection import Collection
from ...network import CampusHTTP
from ...runtime import AppError
from ...vault import Vault
from .adapter import JwAdapter
from .schema import JW_GRADE_ROW_LIMIT


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
