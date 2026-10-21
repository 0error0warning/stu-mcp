"""Pure academic page parsing; ambiguous tables never become partial records."""
from __future__ import annotations

import math
import re

from bs4 import BeautifulSoup, Tag

from ...parsing import clean, is_login, item_id
from ...runtime import AppError
from .schema import (
    JW_COLUMNS,
    JW_EMPTY_ROW_PATTERN,
    JW_HOME_MARKERS,
    JW_REQUIRED_COLUMNS,
    JW_SCHEMA_VERSION,
    JW_SUMMARY_INLINE_PATTERN,
    JW_SUMMARY_LABELS,
    JW_TERM_PATTERN,
    JW_TERM_SELECTOR,
)


def _changed(message: str) -> AppError:
    return AppError("schema_changed", message, "jw")


def _page(html: str) -> BeautifulSoup:
    if is_login(html):
        raise AppError("login_expired", "教务登录已过期，请在本地设置页重新登录。", "jw")
    return BeautifulSoup(html, "html.parser")


def jw_authenticated(html: str) -> bool:
    if is_login(html):
        return False
    soup = BeautifulSoup(html, "html.parser")
    if all(soup.select_one(marker) is not None for marker in JW_HOME_MARKERS):
        return True
    raise _changed("教务未返回可识别的学生主页；请检查学校页面，未保存未经验证的会话。")


def _cells(row: Tag) -> list[Tag]:
    return row.find_all(["th", "td"], recursive=False)


def _text(cells: list[Tag]) -> list[str]:
    return [clean(cell.get_text(" ", strip=True)) for cell in cells]


def _columns(cells: list[Tag], kind: str) -> tuple[dict[str, int], bool]:
    labels = [re.sub(r"\s+", "", label) for label in _text(cells)]
    matches = {field: [index for index, label in enumerate(labels) if label in aliases]
               for field, aliases in JW_COLUMNS[kind].items()}
    return ({field: indexes[0] for field, indexes in matches.items() if indexes},
            any(len(indexes) > 1 for indexes in matches.values()))


def _span(cell: Tag, name: str) -> int:
    value = str(cell.get(name, "1"))
    if len(value) > 6 or not re.fullmatch(r"[1-9]\d*", value):
        raise _changed("教务表格含有无法识别的合并单元格，保留原缓存。")
    return int(value)


def _plain(cells: list[Tag]) -> bool:
    return all(_span(cell, "rowspan") == _span(cell, "colspan") == 1 for cell in cells)


def _empty_row(cells: list[Tag], values: list[str], columns: dict[str, int], width: int) -> bool:
    if (not values or not values[0] or any(values[1:])
            or re.fullmatch(JW_EMPTY_ROW_PATTERN, re.sub(r"\s+", "", values[0])) is None):
        return False
    # A marker in a normal course-name cell is not proof of an empty result.
    return (len(cells) == 1 or _span(cells[0], "colspan") > 1
            or len(cells) == width and 0 not in columns.values())


def _summary_row(cells: list[Tag], values: list[str], columns: dict[str, int], width: int) -> bool:
    if not values:
        return False
    label = re.sub(r"\s+", "", values[0])
    if (not any(values[1:]) and (len(cells) == 1 or _span(cells[0], "colspan") > 1)
            and re.fullmatch(JW_SUMMARY_INLINE_PATTERN, label)):
        return True
    if label.rstrip("：:") not in JW_SUMMARY_LABELS:
        return False
    # A complete record whose course title happens to contain 合计 remains a record.
    # Recognize a full-width total only when both identity columns are empty; for
    # a short total, an explicit merged label provides the structural evidence.
    if len(cells) == width:
        if any(values[columns[field]] for field in ("course_code", "title")):
            return False
    elif _span(cells[0], "colspan") == 1:
        return False
    return all(not value or re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:门|学分|人|项|分)?", value)
               for value in values[1:])


def _table(html: BeautifulSoup, kind: str) -> tuple[list[Tag], dict[str, int], int, Tag]:
    required = JW_REQUIRED_COLUMNS[kind]
    candidates = []
    for table in html.select("table"):
        # Layout tables can surround the real table, but never own its rows.
        rows = [row for row in table.select("tr") if row.find_parent("table") is table]
        headers = []
        for row in rows:
            cells = _cells(row)
            if any(cell.find("table") is not None for cell in cells):
                continue
            columns, duplicate = _columns(cells, kind)
            if required.issubset(columns):
                if duplicate:
                    raise _changed("教务表头存在重复或同义字段，无法唯一确定列，保留原缓存。")
                if not _plain(cells):
                    raise _changed("教务表头存在合并单元格，无法唯一确定列，保留原缓存。")
                headers.append((row, columns, len(cells)))
        if headers:
            first, columns, width = headers[0]
            if any(mapping != columns or count != width for _, mapping, count in headers[1:]):
                raise _changed("教务同一表格存在互相冲突的表头，保留原缓存。")
            candidates.append((rows, columns, width, first))
    if not candidates:
        raise _changed("教务表头缺少预期字段；未把此页面当作空结果。")
    if len(candidates) != 1:
        raise _changed("教务返回多个符合字段的表格，无法唯一确定结果，保留原缓存。")
    return candidates[0]


def _number(value: str) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def parse_jw(html: str, kind: str, semester: str = "") -> list[dict]:
    rows, columns, width, header = _table(_page(html), kind)
    records, seen = [], set()
    before_header = True
    for row in rows:
        cells = _cells(row)
        if row is header:
            before_header = False
        if before_header:
            # A preceding rowspan can carry a value into the recognized table.
            if any(_span(cell, "rowspan") != 1 for cell in cells):
                raise _changed("教务表格存在跨行单元格，无法唯一对应记录，保留原缓存。")
            # A merged TH title is decoration. A merged TD may instead be a
            # damaged record: a late thead must not turn it into an empty result.
            if len(cells) == 1 and cells[0].name == "th" and _span(cells[0], "colspan") > 1:
                continue
        if not cells:
            continue
        mapping, duplicate = _columns(cells, kind)
        if JW_REQUIRED_COLUMNS[kind].issubset(mapping):
            if duplicate or mapping != columns or len(cells) != width or not _plain(cells):
                raise _changed("教务重复表头存在冲突，保留原缓存。")
            continue
        if any(cell.find("table") is not None for cell in cells):
            raise _changed("教务记录包含嵌套表格，无法唯一对应字段，保留原缓存。")
        values = _text(cells)
        if any(_span(cell, "rowspan") != 1 for cell in cells):
            raise _changed("教务记录存在跨行单元格，无法唯一对应字段，保留原缓存。")
        if _empty_row(cells, values, columns, width) or _summary_row(cells, values, columns, width):
            continue
        if (all(cell.name == "th" for cell in cells)
                or {"course_code", "title"}.issubset(mapping) and len(mapping) >= 3):
            raise _changed("教务记录中出现无法识别的表头，保留原缓存。")
        if len(cells) != width or not _plain(cells):
            raise _changed("教务记录与表头不匹配，保留原缓存。")
        if not any(values):
            continue
        record = {field: values[index] for field, index in columns.items()}
        if not record["course_code"] or not record["title"]:
            raise _changed("教务记录缺少课程编号或名称，保留原缓存。")
        record["jw_schema_version"] = JW_SCHEMA_VERSION
        if kind == "grade":
            for key in ("credits", "gpa"):
                record[key] = _number(record[key])
            record.update(id=item_id("jw", kind, record["semester"], record["course_code"],
                                     record.get("exam_type", ""), record.get("group", "")), kind=kind)
        else:
            record.update(id=item_id("jw", kind, semester, record["course_code"], record["exam_time"]),
                          kind=kind, semester=semester)
        if record["id"] in seen:
            raise _changed("教务记录身份重复，无法区分记录，保留原缓存。")
        seen.add(record["id"])
        records.append(record)
    return records


def jw_exam_semester(html: str) -> str:
    soup = _page(html)
    fields = soup.select(JW_TERM_SELECTOR)
    if len(fields) != 1 or fields[0].has_attr("multiple"):
        raise _changed("教务未返回唯一的考试学期控件；请明确指定学期后重试。")
    all_options = fields[0].find_all("option")
    options = [option for option in all_options if option.has_attr("value")]
    values = [str(option["value"]) for option in options]
    if len(set(values)) != len(values):
        raise _changed("教务考试学期选项重复；请明确指定学期后重试。")
    selected = [option for option in all_options if option.has_attr("selected")]
    if len(selected) > 1:
        raise _changed("教务同时选中了多个考试学期；请明确指定学期后重试。")
    if not selected and not options:
        raise _changed("教务未返回可识别的考试学期；请明确指定学期后重试。")
    chosen = str((selected[0] if selected else options[0]).get("value", ""))
    if not re.fullmatch(JW_TERM_PATTERN, chosen):
        raise _changed("教务未选中可识别的考试学期；请明确指定学期后重试。")
    return chosen
