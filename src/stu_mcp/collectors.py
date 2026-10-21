"""Stable collection entry points; feature-specific workflows live in features/."""
from __future__ import annotations

from datetime import datetime

from .collection import Article as Article
from .collection import Collection as Collection
from .features.jw.service import jw as collect_jw
from .features.mystu.service import mystu as collect_mystu
from .features.notices import service as notices
from .features.yuketang.service import yuketang as collect_yuketang
from .network import CampusHTTP
from .pagination import complete_list as complete_list
from .parsing import CST
from .vault import Vault
from .webvpn import protected_access


def public(limit: int) -> Collection:
    return notices.public(limit, http_factory=CampusHTTP)


def oa(vault: Vault, limit: int) -> Collection:
    return notices.oa(vault, limit, http_factory=CampusHTTP, protected_reader=protected_access)


def mystu(vault: Vault, limit: int) -> Collection:
    return collect_mystu(vault, limit, http_factory=CampusHTTP)


def article(record: dict, vault: Vault) -> Article:
    return notices.article(record, vault, http_factory=CampusHTTP, protected_reader=protected_access)


def jw(vault: Vault, limit: int, semester: str) -> Collection:
    return collect_jw(vault, limit, semester, http_factory=CampusHTTP)


def default_semester() -> str:
    today = datetime.now(CST)
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-{year + 1}-{'1' if today.month >= 8 or today.month == 1 else '2'}"


def yuketang(vault: Vault, limit: int) -> Collection:
    return collect_yuketang(vault, limit, http_factory=CampusHTTP)
