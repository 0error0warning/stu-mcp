"""Fixed Rain Classroom reads; decoding stays outside transport and orchestration."""
from __future__ import annotations

from ...network import CampusHTTP
from ...vault import Vault
from .parser import Activities, Course, Inventory, parse_activities, parse_announcements, parse_inventory
from .schema import ACTIVITIES_URL_TEMPLATE, ANNOUNCEMENTS_URL_TEMPLATE, COURSES_URL


class YuketangAdapter:
    def __init__(self, vault: Vault, *, http_factory=CampusHTTP):
        self._manager = http_factory("yuketang", vault.load("yuketang"))
        self._http = None

    def __enter__(self):
        self._http = self._manager.__enter__()
        return self

    def __exit__(self, *args):
        return self._manager.__exit__(*args)

    def inventory(self) -> Inventory:
        return parse_inventory(self._http.json(COURSES_URL))

    def activities(self, course: Course, semester: str | None) -> Activities:
        payload = self._http.json(ACTIVITIES_URL_TEMPLATE.format(course_id=course.id))
        return parse_activities(payload, course, semester)

    def announcements(self, course: Course) -> list[dict]:
        payload = self._http.json(ANNOUNCEMENTS_URL_TEMPLATE.format(course_id=course.id))
        return parse_announcements(payload, course)
