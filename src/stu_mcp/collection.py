"""Transport-independent collection results shared by feature services."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .runtime import AppError
from .sync import CourseSync


@dataclass
class Collection:
    items: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    private: bool = False
    limited: bool = False
    coverage: dict = field(default_factory=dict)
    session_version: bytes | None = None
    sync: CourseSync | None = None

    def fail(self, part: str, exc: AppError, *, stage: str | None = None,
             course_id: str | None = None, item_id: str | None = None):
        context = {k: v for k, v in {"stage": stage, "course_id": course_id, "item_id": item_id}.items()
                   if v is not None}
        if course_id is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", course_id):
            context.pop("course_id")  # Some legacy course IDs are URLs; don't echo an unsafe URL on failure.
        self.errors.append({"part": part, **context, **exc.result()})

    @property
    def status(self) -> str:
        return "partial" if self.errors or self.limited else "ok"


@dataclass
class Article:
    item: dict
    session_version: bytes | None = None
