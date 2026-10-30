"""Pure medical timetable parsing, without calendar inference or APP dependencies."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, time

from ...runtime import AppError
from .schema import (
    MED_JW_MAX_JSON_BYTES,
    MED_JW_MAX_PERIOD,
    MED_JW_MAX_ROWS,
    MED_JW_MAX_TEXT,
    MED_JW_MAX_WEEKS,
    MED_JW_SCHEMA_VERSION,
    MED_JW_SOURCE,
)


class _Invalid(ValueError):
    """An unrecognised field; never include upstream values in diagnostics."""


def _changed() -> AppError:
    return AppError("schema_changed", "医学院课表响应结构发生变化，未当作空课表。", MED_JW_SOURCE)


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > MED_JW_MAX_TEXT:
        raise _Invalid
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise _Invalid from None
    return re.sub(r"\s+", " ", value).strip()


def _integer(value: object, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _Invalid
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,3}", raw) or not low <= int(raw) <= high:
        raise _Invalid
    return int(raw)


def _identity(kind: str, *parts: object) -> str:
    # JSON framing avoids ambiguous delimiter joins and Python's randomized hash.
    body = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
    return f"{MED_JW_SOURCE}:{kind}:{digest}"


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Invalid
        result[key] = value
    return result


def _days(payload: object) -> list:
    if not isinstance(payload, dict):
        raise _changed()
    code = payload.get("code")
    if type(code) not in (int, str):
        raise _changed()
    if code in (401, "401", 501, "501"):
        raise AppError("login_expired", "医学院教务登录已过期，请在设置页重新登录。", MED_JW_SOURCE)
    if code not in (200, "200"):
        raise AppError("source_error", "医学院教务返回业务失败，未当作空课表。", MED_JW_SOURCE)
    if "kbList" not in payload:
        raise _changed()
    days = payload["kbList"]
    if isinstance(days, str):
        try:
            if len(days.encode("utf-8")) > MED_JW_MAX_JSON_BYTES:
                raise _changed()
            days = json.loads(days, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError, UnicodeError):
            raise _changed() from None
    # [] is explicit emptiness. Otherwise the endpoint has one bucket per weekday.
    if not isinstance(days, list) or len(days) not in (0, 7):
        raise _changed()
    return days


def _weeks(row: dict) -> list[int]:
    value = row.get("zc")
    if value in (None, ""):
        value = row.get("zcmc")
    if isinstance(value, int) and not isinstance(value, bool):
        return [_integer(value, 1, MED_JW_MAX_WEEKS)]
    raw = re.sub(r"\s+", "", _text(value)).translate(str.maketrans({
        "，": ",", "、": ",", "（": "(", "）": ")", "～": "-", "~": "-", "—": "-",
    }))
    parity = re.search(r"(?:\((单|双)(?:周)?\)|(单|双)周?)$", raw)
    if parity:
        raw = raw[:parity.start()]
    raw = raw.removeprefix("第").removesuffix("周")
    if not re.fullmatch(r"[0-9]{1,2}(?:-[0-9]{1,2})?(?:,[0-9]{1,2}(?:-[0-9]{1,2})?)*", raw):
        raise _Invalid
    weeks = set()
    for part in raw.split(","):
        ends = part.split("-")
        first, last = int(ends[0]), int(ends[-1])
        if not 1 <= first <= last <= MED_JW_MAX_WEEKS:
            raise _Invalid
        weeks.update(range(first, last + 1))
    if parity:
        odd = (parity[1] or parity[2]) == "单"
        weeks = {w for w in weeks if bool(w % 2) == odd}
    if not weeks:
        raise _Invalid
    return sorted(weeks)


def _periods(row: dict) -> list[int]:
    raw = _text(row.get("jcdm2"))
    if raw:
        raw = raw.replace("，", ",")
        if not re.fullmatch(r"[0-9]{1,2}(?:,[0-9]{1,2})*", raw):
            raise _Invalid
        result = [int(p) for p in raw.split(",")]
    else:
        raw = _text(row.get("jcdm"))
        if not re.fullmatch(r"(?:[0-9]{2}){1,30}", raw):
            raise _Invalid
        result = [int(raw[i:i + 2]) for i in range(0, len(raw), 2)]
    # A bucket alone identifies a grid position, not the full duration of a class.
    if result != sorted(set(result)) or not all(1 <= p <= MED_JW_MAX_PERIOD for p in result):
        raise _Invalid
    return result


def _clock(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if not re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", raw):
        raise _Invalid
    try:
        return time.fromisoformat(raw).isoformat()
    except ValueError:
        raise _Invalid from None


def _date(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        raise _Invalid
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise _Invalid from None


def _row(row: object, day: int) -> dict:
    if not isinstance(row, dict):
        raise _Invalid
    title = _text(row.get("kcmc"))
    if not title:
        raise _Invalid
    weekday = _integer(row["xq"], 1, 7) if "xq" in row else day
    periods, weeks = _periods(row), _weeks(row)
    start, end = _clock(row.get("qssj")), _clock(row.get("jssj"))
    if bool(start) != bool(end) or start and start >= end:
        raise _Invalid
    start_date, end_date = _date(row.get("qsrq")), _date(row.get("jsrq"))
    if start_date and end_date and start_date > end_date:
        raise _Invalid
    fields = {key: _text(row.get(field)) for key, field in {
        "course_code": "kcbh", "class_name": "jxbmc", "teacher": "teaxms",
        "room": "jxcdmc", "building": "jzwmc", "campus": "szxqmc", "project": "xmmc",
        "floor": "lch", "address": "address", "course_sequence": "kxh",
        "notes": "sknrjj", "cancellation_flag": "tkbz", "teaching_activity": "jxhjmc",
    }.items()}
    location = " ".join(dict.fromkeys(filter(None, (
        fields["campus"], fields["building"], fields["floor"], fields["room"], fields["address"],
    ))))
    task_type = _integer(row["tasktype"], 0, 999) if row.get("tasktype") not in (None, "") else None
    return {**fields, "title": title, "weekday": weekday, "periods": periods, "weeks": weeks,
            "start_time": start, "end_time": end, "location": location,
            "start_date": start_date, "end_date": end_date, "task_type": task_type}


def _metadata(payload: dict) -> tuple[dict, bool]:
    result = {"semester": None, "native_semester": None, "current_week": None,
              "first_day_of_week": None, "max_week": None, "today": None, "calendar_weeks": []}
    invalid = False
    for field, key in (("xnxqdm", "native_semester"), ("firstDayOfWeek", "first_day_of_week"),
                       ("rq", "today")):
        try:
            if field in payload:
                raw = _text(payload[field])
                result[key] = raw or None
        except _Invalid:
            invalid = True
    result["semester"] = result["native_semester"]
    for field, key in (("zc", "current_week"), ("maxzc", "max_week")):
        try:
            if payload.get(field) not in (None, ""):
                # Schools can report week zero before teaching starts; never infer today's week.
                result[key] = _integer(payload[field], 0, MED_JW_MAX_WEEKS)
        except _Invalid:
            invalid = True
    if "xldata" in payload:
        rows = payload["xldata"]
        if not isinstance(rows, list) or len(rows) > MED_JW_MAX_WEEKS:
            invalid = True
        else:
            for row in rows:
                try:
                    if not isinstance(row, dict):
                        raise _Invalid
                    result["calendar_weeks"].append({"week": _integer(row.get("zc"), 0, MED_JW_MAX_WEEKS),
                        "start_date": _date(row.get("qsrq")), "end_date": _date(row.get("jsrq"))})
                except _Invalid:
                    invalid = True
    return result, invalid


def parse_timetable(payload: object) -> dict:
    """Parse the current Studentkb/index response; incomplete rows remain explicit.

    ``coverage.complete`` describes parsing of this response, not independently
    verified completeness of every teaching activity at the school. Native
    calendar metadata is preserved but never promoted to a reviewed calendar.
    """
    days = _days(payload)
    metadata, invalid_metadata = _metadata(payload)
    courses, meetings, rejected = {}, {}, []
    row_count = parsed_count = rejected_containers = 0
    for day_index, day in enumerate(days, 1):
        # The current APP observed period-keyed day objects. Empty day arrays were
        # also documented by the school bundle; nonempty arrays are unverified.
        if day == []:
            continue
        if not isinstance(day, dict):
            rejected_containers += 1
            continue
        for bucket, rows in day.items():
            try:
                _integer(bucket, 1, MED_JW_MAX_PERIOD)
            except _Invalid:
                rejected_containers += 1
                continue
            if not isinstance(rows, list):
                rejected_containers += 1
                continue
            row_count += len(rows)
            if row_count > MED_JW_MAX_ROWS:
                raise _changed()
            for position, raw in enumerate(rows):
                try:
                    row = _row(raw, day_index)
                except _Invalid:
                    rejected.append({"day_index": day_index, "bucket": str(bucket),
                                     "row_index": position, "reason": "unrecognized_arrangement"})
                    continue
                parsed_count += 1
                cid = _identity("timetable", metadata["native_semester"], row["course_code"],
                                row["title"], row["class_name"])
                course = courses.setdefault(cid, {"id": cid, "title": row["title"],
                    "course_code": row["course_code"], "class_name": row["class_name"],
                    "teachers": set(), "meetings": []})
                if row["teacher"]:
                    course["teachers"].add(row["teacher"])
                # Weekly rows merge only if all non-date arrangement fields agree.
                # Keep source date ranges with their weeks instead of inferring occurrences.
                detail = {key: row[key] for key in (
                    "weekday", "periods", "teacher", "location", "building", "room", "campus",
                    "floor", "address", "class_name", "start_time", "end_time", "project",
                    "course_sequence", "notes", "cancellation_flag", "teaching_activity", "task_type",
                )}
                mid = _identity("meeting", cid, detail)
                if mid not in meetings:
                    meeting = {"id": mid, **detail, "weeks": set(), "date_ranges": [], "online_info": ""}
                    meetings[mid] = meeting
                    course["meetings"].append(meeting)
                meeting = meetings[mid]
                meeting["weeks"].update(row["weeks"])
                if row["start_date"] or row["end_date"]:
                    dates = {"weeks": row["weeks"], "start_date": row["start_date"], "end_date": row["end_date"]}
                    if dates not in meeting["date_ranges"]:
                        meeting["date_ranges"].append(dates)
    for course in courses.values():
        course["teachers"] = sorted(course["teachers"])
        course["teacher"] = "、".join(course["teachers"])
        for meeting in course["meetings"]:
            meeting["weeks"] = sorted(meeting["weeks"])
            meeting["date_ranges"].sort(key=lambda d: (d["weeks"], d["start_date"], d["end_date"]))
            periods = ",".join(str(p) for p in meeting["periods"])
            clock = f" {meeting['start_time']}-{meeting['end_time']}" if meeting["start_time"] else ""
            meeting["raw_time"] = f"周{'一二三四五六日'[meeting['weekday'] - 1]} 第{periods}节{clock}"
        course["meetings"].sort(key=lambda m: (m["weekday"], m["periods"], m["weeks"], m["id"]))
    pending = []
    if rejected:
        pending.append(f"有 {len(rejected)} 条授课记录无法完整解析，须到学校课表核对。")
    if rejected_containers:
        pending.append(f"有 {rejected_containers} 个课表分组结构无法识别，不能认定这些安排为空。")
    if invalid_metadata:
        pending.append("部分学校学期或校历字段无法识别，未推算替代值。")
    return {"schema_version": MED_JW_SCHEMA_VERSION, **metadata, "available_semesters": [],
            "courses": sorted(courses.values(), key=lambda c: c["id"]), "unarranged": [],
            "unplaced_details": rejected, "pending": pending,
            "coverage": {"kind": "medical_current_timetable", "weeks": "all", "complete": not pending,
                "course_count": len(courses), "meeting_count": len(meetings), "row_count": row_count,
                "parsed_row_count": parsed_count, "rejected_row_count": len(rejected),
                "rejected_container_count": rejected_containers, "unplaced_detail_count": len(rejected),
                "day_count": len(days), "current_semester_only": True, "unarranged_included": False,
                "calendar_verified": False, "period_times_verified": False}}
