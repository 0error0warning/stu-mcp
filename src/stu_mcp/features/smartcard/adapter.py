"""Bounded official card reads over the independent encrypted session."""
from __future__ import annotations

import time
from datetime import date

from ...network import CampusHTTP
from ...runtime import AppError
from .parser import (
    continuation,
    decode,
    parse_profile,
    parse_transactions,
    query_form,
    read_url,
    transaction_type,
)
from .schema import CARD_HISTORY_URL, CARD_MAX_CONTINUATIONS, CARD_MAX_REQUESTS, CARD_OVERVIEW_URL


class SmartcardAdapter:
    def __init__(self, state: dict, *, http_factory=CampusHTTP, sleep=time.sleep):
        self.account = state.get("smartcard_account")
        if not isinstance(self.account, str) or not self.account or len(self.account) > 80:
            raise AppError("session_invalid", "一卡通会话缺少本人账号关联，请重新登录。", "smartcard")
        self._manager = http_factory("smartcard", state)
        self._http = None
        self._count = 0
        self._sleep = sleep

    def __enter__(self):
        self._http = self._manager.__enter__()
        return self

    def __exit__(self, *args):
        return self._manager.__exit__(*args)

    def _request(self, url: str, data: dict | None = None) -> tuple[str, str]:
        read_url(url, url)
        if self._count >= CARD_MAX_REQUESTS:
            raise AppError("request_limit", "一卡通查询已达到请求上限，请稍后重试。", "smartcard")
        self._count += 1
        response = self._http.request(url, data=data)
        actual = read_url(str(response.url), url)
        return decode(response), actual

    def overview(self) -> dict:
        html, _ = self._request(CARD_OVERVIEW_URL)
        return parse_profile(html, self.account)

    def transactions(self, start: date, end: date, selected_type: str) -> dict:
        # Reconfirm the live identity even for an empty history result.
        self.overview()
        html, url = self._request(CARD_HISTORY_URL)
        selection = query_form(html, url, "selection")
        value = transaction_type(selection, selected_type)
        html, url = self._request(selection.url, selection.data | {"inputObject": value})
        dates = query_form(html, url, "dates")
        if ("account" in dates.data and dates.data["account"] != selection.account
                or "inputObject" in dates.data and dates.data["inputObject"] != value):
            raise AppError("schema_changed", "一卡通查询条件发生变化，已停止本次读取。", "smartcard")
        html, url = self._request(dates.url, dates.data | {
            "inputStartDate": start.strftime("%Y%m%d"), "inputEndDate": end.strftime("%Y%m%d")})
        count = 0
        while target := continuation(html, url):
            if count >= CARD_MAX_CONTINUATIONS:
                raise AppError("request_limit", "一卡通查询仍在进行，已停止自动续行，请稍后重试。", "smartcard")
            count += 1
            self._sleep(1)
            html, url = self._request(target, {})
        result = parse_transactions(html, self.account, start, end)
        label = next(item["label"] for item in selection.transaction_types if item["value"] == value)
        if value != transaction_type(selection, "") and any(item["type"] != label for item in result["items"]):
            raise AppError("schema_changed", "一卡通返回的交易类别与本次筛选不符，未返回混合记录。", "smartcard")
        return result | {"query": {"start_date": start.isoformat(), "end_date": end.isoformat(),
                                   "transaction_type": value},
                         "currency": "CNY", "available_transaction_types": selection.transaction_types}
