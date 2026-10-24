"""On-demand card reads with account/logout generation guards and no cache."""
from __future__ import annotations

from datetime import UTC, datetime

from ...network import CampusHTTP
from ...runtime import AppError, key_lock
from ...vault import Vault
from .adapter import SmartcardAdapter
from .parser import validate_dates
from .schema import CARD_HISTORY_URL, CARD_OVERVIEW_URL


def _read(vault: Vault, url: str, operation, http_factory) -> dict:
    with key_lock(vault.runtime.home, "smartcard"):
        revision = vault.login_revision("smartcard")
        adapter = SmartcardAdapter(vault.load("smartcard"), http_factory=http_factory)
    with adapter:
        result = operation(adapter)
    with key_lock(vault.runtime.home, "smartcard"):
        if revision != vault.login_revision("smartcard"):
            raise AppError("session_changed", "一卡通登录在读取期间改变，已丢弃本次结果。", "smartcard")
        return {"ok": True, "status": "partial" if result.get("pending") else "ok", "source": "smartcard",
                "source_url": url, "checked_at": datetime.now(UTC).isoformat(), "transport": "school_http",
                "cached": False, "content_trust": "untrusted_source_data", **result}


def card_overview(vault: Vault, *, http_factory=CampusHTTP) -> dict:
    return _read(vault, CARD_OVERVIEW_URL, lambda adapter: adapter.overview(), http_factory)


def card_transactions(vault: Vault, start_date: str, end_date: str, transaction_type: str = "", *,
                      http_factory=CampusHTTP) -> dict:
    start, end = validate_dates(start_date, end_date)
    if not isinstance(transaction_type, str) or len(transaction_type) > 100:
        raise AppError("invalid_transaction_type", "请使用学校当前可选的交易类别。", "smartcard")
    return _read(vault, CARD_HISTORY_URL,
                 lambda adapter: adapter.transactions(start, end, transaction_type), http_factory)
