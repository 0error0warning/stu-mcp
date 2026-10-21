"""Business validation and in-memory contracts; no browser or network access."""
from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta, timezone
from threading import Event
from typing import Protocol, TypedDict

from ...runtime import AppError
from .schema import BUILDINGS, FIELDS

ACTIVE = {"starting", "preparing_browser", "waiting_for_login", "opening_form", "filling",
          "filled_unsubmitted", "needs_manual_fields", "form_changed", "closing", "awaiting_confirmation",
          "confirmation_invalidated", "confirmation_expired", "submitting", "submission_not_sent"}

def campus_today() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()

def validate_fields(fields: dict, *, today: date | None = None) -> list[dict]:
    """Never invent dates, building identities, codes, causes or user identity."""
    problems = []
    for key, label in FIELDS.items():
        if not fields.get(key):
            problems.append({"field": key, "label": label, "reason": "required"})
    if fields.get("campus") not in (None, "", "桑浦山", "桑浦山校区"):
        raise AppError("unsupported_repair_scope", "此填表适配器仅核验桑浦山宿舍 repair 系统；"
                       "其他校区或校园网故障请查看 get_service_links 的 r 综合报修入口。", "repair")
    if fields.get("building") and fields["building"] not in BUILDINGS:
        problems.append({"field": "building", "label": FIELDS["building"], "reason": "choose_exact_option"})
    if fields.get("phone") and not re.fullmatch(r"[+\d][\d ()-]{4,29}", fields["phone"]):
        problems.append({"field": "phone", "label": FIELDS["phone"], "reason": "invalid_phone"})
    if fields.get("email") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["email"]):
        problems.append({"field": "email", "label": "邮箱", "reason": "invalid_email"})
    if fields.get("visit_date"):
        try:
            value = date.fromisoformat(fields["visit_date"])
            if value.isoformat() != fields["visit_date"] or value < (today or campus_today()):
                raise ValueError
        except ValueError:
            problems.append({"field": "visit_date", "label": FIELDS["visit_date"], "reason": "invalid_or_past_date"})
    hours = {}
    for key in ("visit_start", "visit_end"):
        if fields.get(key):
            if not re.fullmatch(r"(?:0?8|0?9|1[0-8]):00", fields[key]):
                problems.append({"field": key, "label": FIELDS[key], "reason": "whole_hour_8_to_18"})
            else:
                hours[key] = int(fields[key].split(":")[0])
    if len(hours) == 2 and hours["visit_start"] >= hours["visit_end"]:
        problems.append({"field": "visit_end", "label": FIELDS["visit_end"], "reason": "must_follow_start"})
    if fields.get("description") and len(fields["description"]) > 800:
        problems.append({"field": "description", "label": FIELDS["description"], "reason": "max_800"})
    return problems

class FormCapture(TypedDict):
    fields: list[dict[str, str]]
    body: dict[str, list[str]]
    problems: list[dict]
    fingerprint: str
    submission_fingerprint: str


class Review(TypedDict):
    review_id: str
    expires_at: float
    capture: FormCapture


class RepairSession(Protocol):
    """Business operations exposed by one owned school session."""
    @property
    def request_sent(self) -> bool: ...
    def open(self, fields: dict) -> dict | None: ...
    def capture(self) -> FormCapture: ...
    def prepare_receipt(self) -> None: ...
    def submit(self, capture: FormCapture) -> dict: ...
    def check(self) -> dict: ...
    def is_closed(self) -> bool: ...
    def on_form(self) -> bool: ...
    def wait(self, milliseconds: int) -> None: ...


SessionFactory = Callable[[Event, Callable[..., None]], AbstractContextManager[RepairSession]]
