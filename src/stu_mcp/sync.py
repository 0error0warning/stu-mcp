"""Explicit course inventory and activity coverage; never infer deletion from an empty batch."""
from __future__ import annotations

from dataclasses import dataclass, field

COURSE_KINDS = frozenset({"course", "task", "resource"})


@dataclass
class CourseSync:
    # None means the inventory is incomplete/unknown; an empty set means confirmed empty.
    course_ids: frozenset[str] | None = None
    semester: str | None = None
    complete_courses: set[str] = field(default_factory=set)

    @property
    def complete(self) -> bool:
        return self.course_ids is not None and self.course_ids.issubset(self.complete_courses)

    def scope(self) -> dict:
        return {"course_ids": sorted(self.course_ids or ()), "semester": self.semester}

    def obsolete(self, item: dict, incoming_ids: set[str]) -> bool:
        if item["kind"] not in COURSE_KINDS or item["id"] in incoming_ids:
            return False
        if self.complete:
            return True
        cid = item.get("course_id")
        if self.course_ids is not None:
            if cid and cid not in self.course_ids:
                return True
            if self.semester and item.get("semester") and item["semester"] != self.semester:
                return True
        return item["kind"] in {"task", "resource"} and cid in self.complete_courses


def in_scope(item: dict, scope: dict) -> bool:
    if item["kind"] not in COURSE_KINDS:
        return True
    # Legacy records lack course provenance: retain them, but don't present them as current.
    cid = item.get("course_id")
    if not cid or cid not in scope["course_ids"]:
        return False
    return not scope["semester"] or item.get("semester") == scope["semester"]
