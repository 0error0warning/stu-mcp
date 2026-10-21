"""Pure Rain Classroom decoders; malformed data never proves an empty snapshot."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ...pagination import complete_list
from ...parsing import clean, item_id, stamp, text_body
from ...runtime import AppError
from .schema import (
    ACTIVITY_LIMIT,
    ACTIVITY_LIST_FIELD,
    ANNOUNCEMENT_LIMIT,
    ANNOUNCEMENT_LIST_FIELD,
    COURSE_LIST_FIELD,
    COURSE_URL_TEMPLATE,
    EXERCISE_URL_TEMPLATE,
    MORE_FIELDS,
    PAGE_COUNT_FIELDS,
    TASK_TYPES,
    TOTAL_FIELDS,
)


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    teacher: str
    term: int | str | None
    url: str


@dataclass(frozen=True)
class Inventory:
    courses: list[Course]
    semester: str | None
    complete: bool


@dataclass(frozen=True)
class Activities:
    items: list[dict]
    complete: bool


def _changed(message: str) -> AppError:
    return AppError("schema_changed", message, "yuketang")


def _records(payload: object, field: str, label: str) -> tuple[dict, dict, list[dict]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise _changed(f"雨课堂未返回可识别的{label}数据。")
    data = payload["data"]
    rows = data.get(field)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _changed(f"雨课堂{label}列表字段发生变化；未把结构变化当作空结果。")
    return payload, data, rows


def _text(value: object, label: str) -> str:
    if value is not None and not isinstance(value, str):
        raise _changed(f"雨课堂{label}字段类型发生变化。")
    return clean(value)


def _object(value: object, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _changed(f"雨课堂{label}字段类型发生变化。")
    return value


def _identity(value: object, label: str, *, numeric: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _changed(f"雨课堂{label}缺少可识别的标识。")
    identity = str(value)
    if not identity.strip() or numeric and re.fullmatch(r"[0-9]+", identity) is None:
        raise _changed(f"雨课堂{label}缺少可识别的标识。")
    return identity


def _time(value: object, label: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise _changed(f"雨课堂{label}字段类型发生变化。")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise _changed(f"雨课堂{label}字段不是可识别的时间戳。") from None
    if not math.isfinite(number):
        raise _changed(f"雨课堂{label}字段不是可识别的时间戳。")
    result = stamp(value)
    if number > 0 and result is None:
        raise _changed(f"雨课堂{label}字段超出可识别的时间范围。")
    return result


def _page_complete(payload: dict, size: int, capacity: int | None = None) -> bool:
    """Unknown pagination types can retain records, but cannot authorize pruning."""
    if any(key in payload and payload[key] is not None and type(payload[key]) is not bool
           for key in MORE_FIELDS):
        return False
    for key in (*TOTAL_FIELDS, *PAGE_COUNT_FIELDS):
        if key not in payload or payload[key] is None:
            continue
        value = payload[key]
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return False
        if re.fullmatch(r"[0-9]+", str(value)) is None:
            return False
    pagination = payload.get("pagination")
    if pagination is not None and (not isinstance(pagination, dict)
                                   or not _page_complete(pagination, size)):
        return False
    return complete_list(payload, size, capacity)


def parse_inventory(payload: object) -> Inventory:
    envelope, data, rows = _records(payload, COURSE_LIST_FIELD, "课程")
    courses, identities = [], set()
    for row in rows:
        if row.get("classroom_id") == 0:
            raise _changed("雨课堂课程缺少可识别的标识。")
        cid = _identity(row.get("classroom_id"), "课程", numeric=True)
        if cid in identities:
            raise _changed("雨课堂课程标识重复，无法确认当前课程范围。")
        identities.add(cid)
        nested = _object(row.get("course"), "课程名称")
        nested_title = _text(nested.get("name"), "课程名称")
        flat_title = _text(row.get("name"), "课程名称")
        title = nested_title or flat_title
        if not title:
            raise _changed("雨课堂课程缺少名称，保留原缓存。")
        teacher = _text(_object(row.get("teacher"), "教师").get("name"), "教师名称")
        term = row.get("term")
        if term is not None and (isinstance(term, bool) or not isinstance(term, (int, str))):
            raise _changed("雨课堂课程学期字段类型发生变化，无法确认当前课程范围。")
        courses.append(Course(cid, title, teacher, term, COURSE_URL_TEMPLATE.format(course_id=cid)))
    terms = [course.term for course in courses if type(course.term) is int]
    latest = max(terms) if terms else None
    complete = (_page_complete(data, len(rows)) and _page_complete(envelope, len(rows))
                and len(terms) == len(rows))
    selected = [course for course in courses if course.term == latest] if terms else courses
    return Inventory(selected, str(latest) if latest is not None else None, complete)


def parse_activities(payload: object, course: Course, semester: str | None) -> Activities:
    envelope, data, rows = _records(payload, ACTIVITY_LIST_FIELD, "课程活动")
    items, identities = [], set()
    known_types = True
    for row in rows:
        title = _text(row.get("title"), "活动标题")
        if not title:
            raise _changed("雨课堂活动缺少标题，未把解析失败当作空列表。")
        content = _object(row.get("content"), "活动内容")
        raw_type = row.get("type")
        if raw_type is not None and (isinstance(raw_type, bool) or not isinstance(raw_type, (str, int))):
            raise _changed("雨课堂活动分类字段类型发生变化。")
        known_types &= type(raw_type) is int
        kind = "task" if type(raw_type) is int and raw_type in TASK_TYPES else "resource"
        raw_id = row.get("id")
        if isinstance(raw_id, bool) or raw_id is not None and not isinstance(raw_id, (str, int)):
            raise _changed("雨课堂活动标识字段类型发生变化。")
        identity = _identity(raw_id, "活动") if raw_id else title
        if identity in identities:
            raise _changed("雨课堂活动标识重复，无法唯一确定课程活动。")
        identities.add(identity)
        raw_leaf = content.get("leaf_id")
        if isinstance(raw_leaf, bool) or raw_leaf is not None and not isinstance(raw_leaf, (str, int)):
            raise _changed("雨课堂活动资源标识字段类型发生变化。")
        leaf = _identity(raw_leaf, "活动资源") if raw_leaf else ""
        url = (EXERCISE_URL_TEMPLATE.format(course_id=course.id, leaf_id=leaf)
               if re.fullmatch(r"[0-9]+", leaf) else course.url)
        items.append({
            "id": item_id("yuketang", kind, course.id, identity), "kind": kind, "title": title,
            "course": course.title, "url": url, "course_id": course.id, "semester": semester,
            "term": course.term, "activity_type": raw_type, "leaf_id": leaf or None,
            "due_at": _time(content.get("score_d"), "活动截止时间"), "status": "todo",
            "published_at": _time(row.get("create_time"), "活动发布时间"),
        })
    complete = (known_types and _page_complete(data, len(rows), ACTIVITY_LIMIT)
                and _page_complete(envelope, len(rows)))
    return Activities(items[:ACTIVITY_LIMIT], complete)


def parse_announcements(payload: object, course: Course) -> list[dict]:
    _, _, rows = _records(payload, ANNOUNCEMENT_LIST_FIELD, "课程公告")
    items, identities = [], set()
    for row in rows:
        identity = _identity(row.get("id"), "公告")
        if identity in identities:
            raise _changed("雨课堂公告标识重复，无法唯一确定课程公告。")
        identities.add(identity)
        raw_body = _text(row.get("content"), "公告正文")
        body = text_body(raw_body, 10000)
        title = _text(row.get("title"), "公告标题") or body
        if not title:
            raise _changed("雨课堂公告缺少标题和正文，保留原缓存。")
        published = _time(row.get("publish_time"), "公告发布时间")
        created = _time(row.get("create_time"), "公告创建时间")
        items.append({
            "id": item_id("yuketang", "notice", course.id, identity), "kind": "notice",
            "title": title[:200], "course": course.title, "body": body, "url": course.url,
            "published_at": published if row.get("publish_time") else created,
        })
    return items[:ANNOUNCEMENT_LIMIT]
