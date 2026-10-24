"""Pure card contracts: normal forms, identity proof, and unambiguous tables."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from ...parsing import clean
from ...runtime import AppError
from .schema import (
    CARD_FORM_FIELDS,
    CARD_HISTORY_COLUMNS,
    CARD_MAX_ROWS,
    CARD_ORIGIN,
    CARD_PROFILE_LABELS,
    CARD_READ_PATHS,
)


def changed() -> AppError:
    return AppError("schema_changed", "一卡通页面结构发生变化，未返回未经核对的记录。", "smartcard")


def page(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one('input[name="passwd"], input[type="password"]') or soup.select_one(
            'form[action*="loginstudent"], frame[src*="homeLogin"], iframe[src*="homeLogin"]'):
        raise AppError("login_expired", "一卡通会话已过期，请在设置页重新登录。", "smartcard")
    return soup


def decode(response) -> str:
    content = response.content
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            pass
    raise changed()


def _label(value: str) -> str:
    return re.sub(r"[\s:：]", "", value)


def _plain(cells: list[Tag]) -> bool:
    return all(str(cell.get(key, "1")) == "1" for cell in cells for key in ("colspan", "rowspan"))


def money(value: str) -> str:
    text = re.sub(r"\s+", "", value)
    match = re.fullmatch(r"(?:[￥¥])?([+-]?\d+(?:\.\d{1,2})?)(?:元)?", text)
    if not match:
        raise changed()
    try:
        amount = Decimal(match[1])
    except InvalidOperation:
        raise changed() from None
    if not amount.is_finite() or abs(amount) > Decimal("1000000000"):
        raise changed()
    return format(amount, ".2f")


def profile_balance(value: str) -> dict:
    """Keep the three explicitly labelled balances separate; never sum them."""
    text = re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")
    if "(" not in text and ")" not in text:
        return {"balance": money(text)}
    matches = list(re.finditer(r"(?:[¥￥])?([+-]?\d+(?:\.\d{1,2})?)元\(([^()]+)\)", text))
    labels = {"卡余额": "card_balance", "当前过渡余额": "current_transition_balance",
              "上次过渡余额": "previous_transition_balance"}
    if (len(matches) != 3 or "".join(match[0] for match in matches) != text
            or {match[2] for match in matches} != set(labels)):
        raise changed()
    balances = {labels[match[2]]: money(match[1]) for match in matches}
    return {"balance": balances["card_balance"], "balance_breakdown": balances}


def parse_profile(html: str, expected_account: str) -> dict:
    """Require a labelled own-account match, returning only useful card fields."""
    soup = page(html)
    aliases = {_label(alias): field for field, names in CARD_PROFILE_LABELS.items() for alias in names}
    found: dict[str, list[str]] = {}
    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not _plain(cells):
            continue
        for index, cell in enumerate(cells):
            field = aliases.get(_label(cell.get_text(" ", strip=True)))
            if not field:
                continue
            if index + 1 >= len(cells) or cell.find(["table", "input", "select"]):
                raise changed()
            value_cell = cells[index + 1]
            if value_cell.find(["table", "input", "select"]):
                raise changed()
            found.setdefault(field, []).append(clean(value_cell.get_text(" ", strip=True)))
    if any(len(values) != 1 for values in found.values()) or not {"account", "balance"} <= found.keys():
        raise changed()
    if not expected_account or found["account"][0] != expected_account:
        raise AppError("session_invalid", "一卡通当前身份与保存的本人账号不符，请重新登录。", "smartcard")
    result = {field: values[0] for field, values in found.items() if field != "account"}
    result.update(profile_balance(result["balance"]))
    result["currency"] = "CNY"
    # A missing status is unknown, never an invented normal/active state.
    fields = (*CARD_PROFILE_LABELS.keys(), "currency")
    return {field: result.get(field) for field in fields if field != "account"} | {
        key: result[key] for key in ("balance_breakdown",) if key in result}


def read_url(url: str, current_url: str, *, history_only: bool = False) -> str:
    target = urljoin(current_url, url)
    parsed = urlsplit(target)
    origin = urlsplit(CARD_ORIGIN)
    if (parsed.scheme != origin.scheme or parsed.hostname != origin.hostname or parsed.port not in (None, 80)
            or parsed.username or parsed.password or parsed.fragment or parsed.path not in CARD_READ_PATHS
            or history_only and parsed.path != "/accounthisTrjn.action"):
        raise changed()
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if len(query) > 1 or any(key != "__continue" or not value or len(value) > 4096 for key, value in query):
        raise changed()
    return target


@dataclass(frozen=True)
class QueryForm:
    url: str
    data: dict[str, str]
    transaction_types: list[dict]
    account: str = ""


def query_form(html: str, current_url: str, stage: str) -> QueryForm:
    soup = page(html)
    required = {"account", "inputObject"} if stage == "selection" else {"inputStartDate", "inputEndDate"}
    forms = [form for form in soup.select("form")
             if required <= {node.get("name") for node in form.select("input[name],select[name]")}]
    if len(forms) != 1:
        raise changed()
    form = forms[0]
    if str(form.get("method", "get")).lower() != "post":
        raise changed()
    url = read_url(str(form.get("action", "")), current_url, history_only=True)
    data, choices, account = {}, [], ""
    for node in form.select("input[name],select[name],textarea[name],button[name]"):
        kind = str(node.get("type", "text")).lower()
        if node.has_attr("disabled") or node.name == "button" or kind in {"submit", "button", "image", "reset"}:
            continue
        name = str(node["name"])
        if name not in CARD_FORM_FIELDS or name in data:
            raise changed()
        if node.name == "select":
            if node.has_attr("multiple") or name not in {"account", "inputObject"}:
                raise changed()
            options = [option for option in node.select("option") if not option.has_attr("disabled")]
            values = [str(option.get("value", "")) for option in options]
            if not options or len(values) != len(set(values)):
                raise changed()
            selected = [option for option in options if option.has_attr("selected")]
            if len(selected) > 1:
                raise changed()
            data[name] = str((selected or options)[0].get("value", ""))
            if name == "account":
                nonempty = [value for value in values if value]
                if len(nonempty) != 1:
                    raise AppError("unsupported_scope", "一卡通提供多个或未提供卡账户，请先在原站核对。", "smartcard")
                data[name] = account = nonempty[0]
            else:
                choices = [{"value": str(option.get("value", "")),
                            "label": clean(option.get_text(" ", strip=True))} for option in options]
                if any(not item["label"] for item in choices):
                    raise changed()
        elif node.name != "input" or kind not in {"hidden", "text", "date"}:
            raise changed()
        else:
            data[name] = str(node.get("value", ""))
    if not required <= data.keys():
        raise changed()
    if stage == "selection" and (not account or not choices):
        raise changed()
    return QueryForm(url, data, choices, account)


def transaction_type(form: QueryForm, requested: str) -> str:
    choices = form.transaction_types
    if requested:
        if requested not in {item["value"] for item in choices}:
            raise AppError("invalid_transaction_type", "交易类别不在学校当前选项中，请先留空查询全部及可选类别。", "smartcard")
        return requested
    all_choices = [item["value"] for item in choices
                   if _label(item["label"]) in {"全部", "全部类型", "所有", "查询全部"}]
    if len(all_choices) != 1:
        raise changed()
    return all_choices[0]


def continuation(html: str, current_url: str) -> str | None:
    soup = page(html)
    if "操作正进行" not in clean(soup.get_text(" ", strip=True)):
        return None
    forms = soup.select('form#form1, form[name="form1"]')
    if len(forms) != 1:
        raise changed()
    form = forms[0]
    scripts = "\n".join(script.get_text() for script in soup.select("script:not([src])"))
    if (str(form.get("method", "get")).lower() != "post" or form.select("input,select,textarea")
            or not re.search(r"setTimeout\s*\([\s\S]*?,\s*1000\s*\)", scripts)
            or not re.search(r"(?:form1|forms\s*\[[^\]]+\])[\s\S]*?\.submit\s*\(", scripts)):
        raise changed()
    return read_url(str(form.get("action", "")), current_url, history_only=True)


def validate_dates(start_date: str, end_date: str) -> tuple[date, date]:
    try:
        if not all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
                   for value in (start_date, end_date)):
            raise ValueError
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if not 0 <= (end - start).days < 30:
            raise ValueError
        return start, end
    except ValueError:
        raise AppError("invalid_date_range", "请使用 YYYY-MM-DD，单次查询范围需为同一天至30天（含首尾）。", "smartcard") from None


def _timestamp(value: str) -> str:
    match = re.fullmatch(r"(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2}):(\d{2})", value)
    if not match:
        raise changed()
    try:
        result = datetime(*map(int, match.groups()))
    except ValueError:
        raise changed() from None
    return result.isoformat() + "+08:00"


def parse_transactions(html: str, expected_account: str, start: date, end: date) -> dict:
    soup = page(html)
    tables = soup.select("table#tables")
    if len(tables) != 1 or tables[0].select("table"):
        raise changed()
    table = tables[0]
    aliases = {_label(alias): field for field, values in CARD_HISTORY_COLUMNS.items() for alias in values}
    rows = [row for row in table.select("tr") if row.find_parent("table") is table]
    header_index, columns = None, {}
    for index, row in enumerate(rows):
        cells = row.find_all(["th", "td"], recursive=False)
        labels = [_label(cell.get_text(" ", strip=True)) for cell in cells]
        matched = [aliases.get(label) for label in labels]
        if all(field in matched for field in CARD_HISTORY_COLUMNS):
            if header_index is not None or not _plain(cells) or len(matched) != len(set(matched)) or None in matched:
                raise changed()
            header_index, columns = index, {field: offset for offset, field in enumerate(matched)}
        elif header_index is None and any(labels):
            # The observed table has a single ordinary header, not preceding data.
            raise changed()
    if header_index is None:
        raise changed()
    footer = clean(soup.get_text(" ", strip=True))
    footers = re.findall(r"共\s*(\d+)\s*页\s*[,，、]?\s*(?:当前)?第\s*(\d+)\s*页", footer)
    if len(footers) != 1:
        raise changed()
    total_pages, current_page = map(int, footers[0])
    if current_page != 1 or total_pages > 100000:
        raise changed()
    summary_rows = []
    for row in rows[header_index + 1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        text = re.sub(r"\s+", "", row.get_text(" ", strip=True))
        if not text.startswith("本次查询共涉及"):
            continue
        summary = re.fullmatch(
            r"本次查询共涉及[:：](\d+)次交易[;；]总计交易额为[:：]([+-]?\d+(?:\.\d{1,2})?)"
            r"[（(]元[）)]共(\d+)页(?:当前)?第(\d+)页", text)
        if (not summary or len(cells) != 1 or str(cells[0].get("colspan", "1")) != str(len(columns))
                or cells[0].find(["table", "input"]) or rows[-1] is not row):
            raise changed()
        if (int(summary[3]), int(summary[4])) != (total_pages, current_page):
            raise changed()
        money(summary[2])  # Validate, but do not confuse the transaction total with a balance.
        summary_rows.append((row, int(summary[1])))
    if len(summary_rows) != 1:
        raise changed()
    summary_row, total_records = summary_rows[0]
    items = []
    for row in rows[header_index + 1:]:
        if row is summary_row:
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        values = [clean(cell.get_text(" ", strip=True)) for cell in cells]
        if not any(values):
            continue
        if (len(cells) == 1 and re.fullmatch(r"(?:无记录|没有记录|暂无数据|无数据)[!！。.]*", values[0])
                and str(cells[0].get("colspan", "1")) == str(len(columns))):
            continue
        if len(cells) != len(columns) or not _plain(cells) or any(cell.find(["table", "input"]) for cell in cells):
            raise changed()
        record = {field: values[offset] for field, offset in columns.items()}
        if not expected_account or record["account"] != expected_account:
            raise AppError("session_invalid", "一卡通流水的本人身份核对失败，请重新登录。", "smartcard")
        occurred_at = _timestamp(record["occurred_at"])
        occurred_date = date.fromisoformat(occurred_at[:10])
        if not start <= occurred_date <= end or not record["type"] or not re.fullmatch(r"\d+", record["sequence"]):
            raise changed()
        item = {field: record[field] for field in ("type", "subsystem", "category", "sequence", "status")}
        item.update(occurred_at=occurred_at, amount=money(record["amount"]), balance=money(record["balance"]))
        items.append(item)
        if len(items) > CARD_MAX_ROWS:
            raise AppError("response_too_large", "一卡通本页记录超过读取上限，请缩小日期范围。", "smartcard")
    if ((total_pages == 0) != (not items) or total_pages == 1 and not items
            or total_pages <= 1 and total_records != len(items)
            or total_pages > 1 and total_records <= len(items)):
        raise changed()
    complete = total_pages <= 1
    return {"items": items, "coverage": {"complete": complete, "pages_read": 1,
            "total_pages": total_pages, "total_records": total_records, "rows_read": len(items)},
            "pending": [] if complete else ["学校返回多页流水，本次仅核对第一页；请缩小日期范围以取得完整记录。"]}
