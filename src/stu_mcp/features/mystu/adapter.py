"""Bounded source reads and URL policy. This adapter never stores credentials."""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from ...network import CampusHTTP, checked_url
from ...parsing import CST
from ...vault import Vault
from .parser import (
    Activities,
    Course,
    Inventory,
    decode_activities,
    parse_activities,
    parse_assignment,
    parse_elc,
    parse_inventory,
    parse_schedule,
)
from .schema import (
    ACTIVITIES_URL,
    ACTIVITY_QUERY_DEFAULTS,
    COURSES_URL,
    ELC_COURSE_PATH,
    SCHEDULE_URL,
    VALIDATE_URL,
)


class MystuAdapter:
    def __init__(self, vault: Vault, *, http_factory=CampusHTTP):
        self._manager = http_factory("mystu", vault.load("mystu"))
        self._http = None

    def __enter__(self):
        self._http = self._manager.__enter__()
        return self

    def __exit__(self, *args):
        return self._manager.__exit__(*args)

    def inventory(self) -> Inventory:
        self._http.json(VALIDATE_URL)
        return parse_inventory(self._http.json(COURSES_URL))

    def check_url(self, url: str):
        if url:
            checked_url("mystu", url)

    def activities(self, course: Course) -> Activities | None:
        if ELC_COURSE_PATH in course.url:
            # Recognizing an ELC page does not prove all sections were loaded.
            return decode_activities(parse_elc(self._http.text(course.url), course.url), complete=False)
        moodle_id = parse_qs(urlparse(course.url).query).get("id", [""])[0]
        if not moodle_id:
            return None
        query = {"moodleCourseId": moodle_id, **ACTIVITY_QUERY_DEFAULTS}
        return parse_activities(self._http.json(ACTIVITIES_URL + "?" + urlencode(query)))

    def assignment(self, url: str) -> dict:
        self.check_url(url)
        return parse_assignment(self._http.text(url))

    def schedule(self) -> tuple[list[dict], bool]:
        start, end = datetime.now(CST) - timedelta(days=7), datetime.now(CST) + timedelta(days=31)
        query = {"startTime": int(start.timestamp() * 1000),
                 "endTime": int(end.timestamp() * 1000), "category": "all"}
        return parse_schedule(self._http.json(SCHEDULE_URL + "?" + urlencode(query)))
