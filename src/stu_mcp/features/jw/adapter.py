"""School query transport and parsing; no authentication or storage policy changes."""
from __future__ import annotations

from ...network import CampusHTTP
from ...vault import Vault
from .parser import jw_exam_semester, parse_jw
from .schema import (
    JW_EXAM_LIST_URL,
    JW_EXAM_QUERY_DEFAULTS,
    JW_EXAM_QUERY_URL,
    JW_GRADE_QUERY_DEFAULTS,
    JW_GRADE_URL,
)


class JwAdapter:
    def __init__(self, vault: Vault, *, http_factory=CampusHTTP):
        legacy = vault.runtime.preferences()["jw_http_compat"]
        self._manager = http_factory("jw", vault.load("jw"), allow_legacy_http=legacy)
        self._http = None

    def __enter__(self):
        self._http = self._manager.__enter__()
        return self

    def __exit__(self, *args):
        return self._manager.__exit__(*args)

    @property
    def transport(self) -> str:
        # Includes an HTTP form redirect even if the final tables use HTTPS.
        return "school_legacy_http" if self._http.used_legacy_http else "https"

    def grades(self, semester: str) -> list[dict]:
        response = self._http.request(JW_GRADE_URL, data=JW_GRADE_QUERY_DEFAULTS | {"kksj": semester})
        return parse_jw(response.text, "grade")

    def exam_semester(self) -> str:
        return jw_exam_semester(self._http.text(JW_EXAM_QUERY_URL))

    def exams(self, semester: str) -> list[dict]:
        response = self._http.request(JW_EXAM_LIST_URL, data=JW_EXAM_QUERY_DEFAULTS | {"xnxqid": semester})
        return parse_jw(response.text, "exam", semester)
