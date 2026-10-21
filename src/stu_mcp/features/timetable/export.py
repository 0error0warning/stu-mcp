#!/usr/bin/env python3
"""Expand a reviewed timetable and write local import files; standard library only.

This is a converter, not a school reader or a source verifier. ``latest_verified``
and ``complete`` are assertions made by the agent after reviewing source evidence.
The first teaching week's Monday must come from that review, not a registration day.

Input schema v1 (all keys below required unless marked optional):
  semester: str; calendar: {semester, version, week1_monday, weeks,
    source_url, checked_at, latest_verified: true};
  timetable: {source_url, checked_at, complete: true};
  periods: [{number: int, start: 'HH:MM', end: 'HH:MM'}];
  periods_source?: {source_url, checked_at}; otherwise inherits timetable evidence;
  courses: [{id, title, teacher?: str, location?: str, meetings:
    [{id, weekday: 1..7, weeks: [int], periods: [int], teacher?: str, location?: str}]}];
  Meeting teacher/location override course values, including an explicit empty string.
  oa?: {enabled: false, status: 'not_checked'} or
    {enabled: true, status: 'checked', scope: str, source_url, checked_at};
  pending?: [str]; adjustments?: [{id, kind, date, source_url, checked_at, ...}].

Dates are ISO dates, checked_at is an ISO timestamp with an explicit UTC offset.
Every adjustment selects ORIGINAL occurrences, never another adjustment's output.
cancel removes selected occurrences on date; move removes and relocates them to
to_date. Optional course_id/meeting_id narrow either selection. replace_day removes
the target date's entire timetable and copies teaching_date's ORIGINAL timetable.
Its required source_action='keep'|'cancel' determines whether those original source
occurrences remain. This decision must come from evidence, not from the converter.
An occurrence cannot be affected by multiple adjustments; split conflicting rules
into explicit, nonoverlapping cancel/move operations instead. Unknown fields are
ignored for forwards compatibility; known fields never use implicit coercion.

The output directory must be empty. review.json records each target's result;
--format all can produce ICS while rejecting an unrepresentable WakeUp projection.
Exit 0 means requested files generated, 2 means blocked/partial/invalid input.
File generation does not establish actual import compatibility or change a calendar.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

CST = timezone(timedelta(hours=8), "Asia/Shanghai")
ID = re.compile(r"[A-Za-z0-9._:-]{1,120}\Z")
WAKEUP_HEADER = ["课程名称", "星期", "开始节数", "结束节数", "老师", "地点", "周数"]


class InputError(ValueError):
    """A safe diagnostic containing field paths, never raw input values."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InputError(message)


def obj(value: object, path: str) -> dict:
    require(isinstance(value, dict), f"{path}: expected object")
    return value


def array(value: object, path: str, maximum: int = 20000) -> list:
    require(isinstance(value, list) and len(value) <= maximum, f"{path}: expected bounded array")
    return value


def text(value: object, path: str, *, optional: bool = False) -> str:
    require(isinstance(value, str), f"{path}: expected text")
    require(len(value) <= 10000 and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value),
            f"{path}: invalid text")
    require(optional or bool(value.strip()), f"{path}: must not be blank")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def identity(value: object, path: str) -> str:
    result = text(value, path)
    require(bool(ID.fullmatch(result)), f"{path}: invalid stable identity")
    return result


def integer(value: object, path: str, lower: int, upper: int) -> int:
    require(type(value) is int and lower <= value <= upper, f"{path}: expected integer {lower}..{upper}")
    return value


def day(value: object, path: str) -> date:
    raw = text(value, path)
    require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw)), f"{path}: expected ISO date")
    try:
        result = date.fromisoformat(raw)
    except ValueError as exc:
        raise InputError(f"{path}: invalid date") from exc
    require(2000 <= result.year <= 2100, f"{path}: only modern school dates supported")
    return result


def clock(value: object, path: str) -> time:
    raw = text(value, path)
    require(bool(re.fullmatch(r"\d{2}:\d{2}", raw)), f"{path}: expected HH:MM")
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise InputError(f"{path}: invalid clock time") from exc


def checked(value: object, path: str) -> str:
    raw = text(value, path)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        require(parsed.utcoffset() is not None and "T" in raw, f"{path}: explicit timezone required")
        require(2000 <= parsed.year <= 2100, f"{path}: timestamp outside supported range")
    except ValueError as exc:
        raise InputError(f"{path}: invalid timestamp with timezone") from exc
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def evidence(value: dict, path: str) -> dict:
    url = text(value.get("source_url"), path + ".source_url")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        require(parts.scheme in ("http", "https") and
                (host == "stu.edu.cn" or host.endswith(".stu.edu.cn")) and
                parts.username is None and parts.password is None and not parts.fragment,
                f"{path}.source_url: expected official school URL without credentials")
        require(not any(re.search(r"ticket|token|password|passwd|cookie|authorization|session", key, re.I)
                        for key, _ in parse_qsl(parts.query)),
                f"{path}.source_url: authentication material must not be recorded")
        require(not any(char.isspace() for char in url), f"{path}.source_url: invalid URL")
    except ValueError as exc:
        raise InputError(f"{path}.source_url: invalid official URL") from exc
    return {"source_url": url, "checked_at": checked(value.get("checked_at"), path + ".checked_at")}


def numbers(value: object, path: str, lower: int, upper: int) -> list[int]:
    values = array(value, path, upper)
    require(bool(values), f"{path}: must not be empty")
    parsed = [integer(number, path, lower, upper) for number in values]
    require(len(set(parsed)) == len(parsed), f"{path}: duplicate number")
    return sorted(parsed)


def occurrence(course: dict, meeting: dict, on: date, periods: dict[int, tuple[time, time]],
               semester: str) -> dict:
    slots = meeting["periods"]
    # Contiguous period numbers may include ordinary breaks between periods.
    start = datetime.combine(on, periods[slots[0]][0], CST)
    end = datetime.combine(on, periods[slots[-1]][1], CST)
    key = json.dumps([semester, course["id"], meeting["id"], on.isoformat()], ensure_ascii=False)
    return {"uid": hashlib.sha256(key.encode()).hexdigest() + "@stu-mcp-timetable",
            "course_id": course["id"], "meeting_id": meeting["id"], "title": course["title"],
            "teacher": course["teacher"], "location": course["location"],
            "original_date": on.isoformat(), "date": on.isoformat(), "periods": slots,
            "start": start.isoformat(), "end": end.isoformat(), "adjustments": []}


def validate(payload: object) -> tuple[dict, list[dict], list[dict]]:
    data = obj(payload, "input")
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "schema_version: expected 1")
    semester = text(data.get("semester"), "semester")
    calendar = obj(data.get("calendar"), "calendar")
    require(text(calendar.get("semester"), "calendar.semester") == semester, "calendar.semester: mismatch")
    calendar_record = {**evidence(calendar, "calendar"),
                       "semester": semester, "version": text(calendar.get("version"), "calendar.version"),
                       "latest_verified": calendar.get("latest_verified") is True,
                       "verification_basis": "caller_assertion_from_reviewed_sources"}
    monday = day(calendar.get("week1_monday"), "calendar.week1_monday")
    require(monday.weekday() == 0, "calendar.week1_monday: must be Monday")
    week_count = integer(calendar.get("weeks"), "calendar.weeks", 1, 60)
    calendar_record.update(week1_monday=monday.isoformat(), weeks=week_count)
    timetable = obj(data.get("timetable"), "timetable")
    timetable_record = {**evidence(timetable, "timetable"), "complete": timetable.get("complete") is True}
    periods_source = evidence(obj(data["periods_source"], "periods_source"), "periods_source") \
        if "periods_source" in data else {**evidence(timetable, "timetable"), "inherited_from_timetable": True}
    require(type(calendar.get("latest_verified")) is bool, "calendar.latest_verified: expected boolean")
    require(type(timetable.get("complete")) is bool, "timetable.complete: expected boolean")
    oa = obj(data.get("oa", {"enabled": False, "status": "not_checked"}), "oa")
    require(type(oa.get("enabled")) is bool, "oa.enabled: expected boolean")
    if oa["enabled"]:
        require(oa.get("status") == "checked", "oa.status: enabled OA requires checked search")
        oa_record = {"enabled": True, "status": "checked", "scope": text(oa.get("scope"), "oa.scope"),
                     **evidence(oa, "oa")}
    else:
        require(oa.get("status") == "not_checked", "oa.status: disabled OA must be not_checked")
        oa_record = {"enabled": False, "status": "not_checked"}
    pending = [text(item, "pending[]") for item in array(data.get("pending", []), "pending", 1000)]
    if not calendar_record["latest_verified"]:
        pending.append("目标学期最新有效官方校历尚未核对。")
    if not timetable_record["complete"]:
        pending.append("目标学期课表完整性尚未核对。")
    period_map = {}
    period_records = []
    for item in array(data.get("periods"), "periods", 30):
        item = obj(item, "periods[]")
        number = integer(item.get("number"), "periods[].number", 1, 30)
        start, end = clock(item.get("start"), "periods[].start"), clock(item.get("end"), "periods[].end")
        require(number not in period_map and start < end, "periods[]: duplicate or invalid interval")
        period_map[number] = (start, end)
        period_records.append({"number": number, "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")})
    require(bool(period_map), "periods: must not be empty")
    ordered = sorted(period_map)
    require(all(period_map[a][1] <= period_map[b][0] for a, b in zip(ordered, ordered[1:], strict=False)),
            "periods: times must follow period order without overlaps")
    events = []
    course_ids = set()
    meeting_count = 0
    for course in array(data.get("courses"), "courses", 500):
        course = obj(course, "courses[]")
        cid = identity(course.get("id"), "courses[].id")
        require(cid not in course_ids, "courses[].id: duplicate identity")
        course_ids.add(cid)
        normalized = {"id": cid, "title": text(course.get("title"), "courses[].title"),
                      "teacher": text(course.get("teacher", ""), "courses[].teacher", optional=True),
                      "location": text(course.get("location", ""), "courses[].location", optional=True)}
        meeting_ids = set()
        meetings = array(course.get("meetings"), "courses[].meetings", 100)
        require(bool(meetings), "courses[].meetings: must not be empty")
        for meeting in meetings:
            meeting = obj(meeting, "meetings[]")
            mid = identity(meeting.get("id"), "meetings[].id")
            require(mid not in meeting_ids, "meetings[].id: duplicate identity within course")
            meeting_ids.add(mid)
            meeting_count += 1
            weekday = integer(meeting.get("weekday"), "meetings[].weekday", 1, 7)
            weeks = numbers(meeting.get("weeks"), "meetings[].weeks", 1, week_count)
            slots = numbers(meeting.get("periods"), "meetings[].periods", 1, 30)
            require(all(slot in period_map for slot in slots), "meetings[].periods: unknown period")
            require(slots == list(range(slots[0], slots[-1] + 1)),
                    "meetings[].periods: split noncontiguous periods into separate meetings")
            arrangement = {**normalized,
                           "teacher": text(meeting.get("teacher", normalized["teacher"]),
                                           "meetings[].teacher", optional=True),
                           "location": text(meeting.get("location", normalized["location"]),
                                            "meetings[].location", optional=True)}
            require(len(events) + len(weeks) <= 20000, "courses: too many expanded occurrences")
            for week in weeks:
                on = monday + timedelta(days=7 * (week - 1) + weekday - 1)
                events.append(occurrence(arrangement, {"id": mid, "periods": slots}, on, period_map, semester))
    manifest = {"schema_version": 1, "semester": semester, "timezone": "Asia/Shanghai",
                "calendar": calendar_record, "timetable": timetable_record, "oa": oa_record,
                "periods_source": periods_source,
                "periods": sorted(period_records, key=lambda item: item["number"]),
                "pending": pending, "counts": {"courses": len(course_ids), "meetings": meeting_count,
                                               "original_occurrences": len(events)},
                "validation_scope": "synthetic converter checks; actual source and platform import not verified"}
    return manifest, events, array(data.get("adjustments", []), "adjustments", 1000)


def apply_adjustments(events: list[dict], adjustments: list[dict]) -> tuple[list[dict], list[dict]]:
    active = {event["uid"]: dict(event) for event in events}
    affected: set[str] = set()
    records = []
    ids = set()
    for rule in adjustments:
        rule = obj(rule, "adjustments[]")
        rid = identity(rule.get("id"), "adjustments[].id")
        require(rid not in ids, "adjustments[].id: duplicate identity")
        ids.add(rid)
        record = {"id": rid, **evidence(rule, "adjustments[]")}
        kind = rule.get("kind")
        require(kind in ("cancel", "move", "replace_day"), "adjustments[].kind: unsupported kind")
        unused = {"cancel": ("to_date", "teaching_date", "source_action"),
                  "move": ("teaching_date", "source_action"), "replace_day": ("to_date",)}
        require(not any(key in rule for key in unused[kind]),
                "adjustments[]: fields conflict with selected adjustment kind")
        on = day(rule.get("date"), "adjustments[].date")
        cid = identity(rule["course_id"], "adjustments[].course_id") if "course_id" in rule else None
        mid = identity(rule["meeting_id"], "adjustments[].meeting_id") if "meeting_id" in rule else None
        require(mid is None or cid is not None, "adjustments[].meeting_id: course_id required")
        selected = [event for event in events if event["date"] == on.isoformat() and
                    (cid is None or event["course_id"] == cid) and
                    (mid is None or event["meeting_id"] == mid)]
        record.update(kind=kind, date=on.isoformat())
        to_remove, to_add = selected, []
        if kind == "replace_day":
            require(cid is None and mid is None, "adjustments[]: replace_day must cover whole day")
            teaching = day(rule.get("teaching_date"), "adjustments[].teaching_date")
            action = rule.get("source_action")
            require(action in ("keep", "cancel"), "adjustments[].source_action: explicitly choose keep or cancel")
            require(teaching != on, "adjustments[]: source and target dates must differ")
            source = [event for event in events if event["date"] == teaching.isoformat()]
            require(bool(source), "adjustments[]: teaching_date has no original occurrences")
            to_add = [(event, on) for event in source]
            to_remove = selected + (source if action == "cancel" else [])
            record.update(teaching_date=teaching.isoformat(), source_action=action)
            # Copying a kept day requires a distinct event identity; preserve source UID only when moved.
            touched = {event["uid"] for event in selected + source}
        else:
            require(bool(selected), "adjustments[]: no matching original occurrences")
            touched = {event["uid"] for event in selected}
            if kind == "move":
                destination = day(rule.get("to_date"), "adjustments[].to_date")
                require(destination != on, "adjustments[]: move requires a different date")
                to_add = [(event, destination) for event in selected]
                record["to_date"] = destination.isoformat()
        require(not affected.intersection(touched), "adjustments[]: overlapping rules require review")
        affected.update(touched)
        for event in to_remove:
            active.pop(event["uid"], None)
        for event, destination in to_add:
            updated = dict(event)
            if kind == "replace_day" and action == "keep":
                updated["uid"] = hashlib.sha256((event["uid"] + "|copy|" + rid).encode()).hexdigest() + \
                    "@stu-mcp-timetable"
            updated.update(date=destination.isoformat(), adjustments=[rid])
            for key in ("start", "end"):
                original = datetime.fromisoformat(event[key])
                updated[key] = datetime.combine(destination, original.timetz()).isoformat()
            active[updated["uid"]] = updated
        record.update(removed_occurrences=len(to_remove), placed_occurrences=len(to_add))
        records.append(record)
    return sorted(active.values(), key=lambda item: (item["start"], item["uid"])), records


def conflicts(events: list[dict]) -> list[str]:
    pending = []
    for index, event in enumerate(events):
        for other_index in range(index + 1, len(events)):
            other = events[other_index]
            if other["start"] >= event["end"]:
                break
            if event["start"] < other["end"]:
                pending.append("课次时间冲突：" + event["course_id"] + "/" + event["meeting_id"] +
                               " 与 " + other["course_id"] + "/" + other["meeting_id"] +
                               "，日期 " + event["date"] + "。")
                if len(pending) >= 100:
                    return pending + ["冲突过多；仅列出前100项，请先核对课表。"]
    return pending


def ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line: str) -> str:
    lines, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            lines.append(current)
            current, size = " ", 1
        current += char
        size += width
    return "\r\n".join(lines + [current])


def utc(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def make_ics(manifest: dict, events: list[dict]) -> bytes:
    timestamps = [manifest["calendar"]["checked_at"], manifest["timetable"]["checked_at"],
                  manifest["periods_source"]["checked_at"]]
    timestamps.extend(rule["checked_at"] for rule in manifest["adjustments"])
    stamp = max(utc(value) for value in timestamps)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//stu-mcp//Reviewed Timetable//EN", "CALSCALE:GREGORIAN"]
    for event in events:
        description = "学期：" + manifest["semester"]
        if event["teacher"]:
            description += "\n教师：" + event["teacher"]
        description += "\n课表来源：" + manifest["timetable"]["source_url"]
        description += "\n校历来源：" + manifest["calendar"]["source_url"]
        for rule in manifest["adjustments"]:
            if rule["id"] in event["adjustments"]:
                description += "\n调整依据：" + rule["source_url"]
        lines.extend(["BEGIN:VEVENT", "UID:" + event["uid"], "DTSTAMP:" + stamp,
                      "DTSTART:" + utc(event["start"]), "DTEND:" + utc(event["end"]),
                      "SUMMARY:" + ics_text(event["title"]), "LOCATION:" + ics_text(event["location"]),
                      "DESCRIPTION:" + ics_text(description), "END:VEVENT"])
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode("utf-8")


def week_ranges(weeks: set[int]) -> str:
    spans = []
    start = previous = min(weeks)
    for week in sorted(weeks)[1:]:
        if week != previous + 1:
            spans.append(f"{start}-{previous}")
            start = week
        previous = week
    spans.append(f"{start}-{previous}")
    return "、".join(spans)


def make_wakeup(manifest: dict, events: list[dict]) -> tuple[bytes, dict]:
    monday = date.fromisoformat(manifest["calendar"]["week1_monday"])
    groups: dict[tuple, set[int]] = {}
    for event in events:
        on = date.fromisoformat(event["date"])
        week = (on - monday).days // 7 + 1
        require(1 <= week <= manifest["calendar"]["weeks"],
                "wakeup: actual occurrence outside reviewed teaching-week grid; use ICS or review calendar")
        key = (event["course_id"], event["meeting_id"], event["title"], on.isoweekday(),
               event["periods"][0], event["periods"][-1], event["teacher"] or "无", event["location"] or "无")
        groups.setdefault(key, set()).add(week)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(WAKEUP_HEADER)
    for key, weeks in sorted(groups.items()):
        writer.writerow([*key[2:], week_ranges(weeks)])
    settings = {"semester": manifest["semester"], "timezone": "Asia/Shanghai",
                "week1_monday": monday.isoformat(), "weeks": manifest["calendar"]["weeks"],
                "periods": manifest["periods"], "automatic_settings_import": False,
                "instructions": "CSV不包含学期开始日和节次时刻；请按本文件在目标WakeUp版本中手动设置并核对。",
                "official_documentation": "https://www.wakeup.fun/doc/import_from_csv.html"}
    return stream.getvalue().encode("utf-8-sig"), settings


def convert(payload: object, target: str = "all") -> tuple[dict, dict[str, bytes]]:
    require(target in ("all", "ics", "wakeup"), "format: unsupported target")
    manifest, original, adjustments = validate(payload)
    events, adjustment_records = apply_adjustments(original, adjustments)
    manifest.update(adjustments=adjustment_records, events=events)
    manifest["counts"]["actual_occurrences"] = len(events)
    manifest["pending"].extend(conflicts(events))
    targets = ("ics", "wakeup") if target == "all" else (target,)
    manifest["targets"] = {}
    files = {}
    for name in targets:
        if manifest["pending"]:
            manifest["targets"][name] = {"status": "blocked", "reason": "unresolved_review_items"}
            continue
        try:
            if name == "ics":
                files["schedule.ics"] = make_ics(manifest, events)
                filenames = ["schedule.ics"]
            else:
                body, settings = make_wakeup(manifest, events)
                files["wakeup.csv"] = body
                files["wakeup-settings.json"] = json_bytes(settings)
                filenames = ["wakeup.csv", "wakeup-settings.json"]
            manifest["targets"][name] = {"status": "generated", "files": filenames,
                                         "import_verification": "not_performed"}
        except InputError as exc:
            manifest["targets"][name] = {"status": "unsupported", "reason": str(exc)}
    states = [item["status"] for item in manifest["targets"].values()]
    manifest["status"] = "generated" if all(state == "generated" for state in states) else \
        "partial" if "generated" in states else "blocked"
    files["review.json"] = json_bytes(manifest)
    return manifest, files


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "input: duplicate JSON key requires review")
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="-", help="Reviewed JSON file; - reads stdin")
    parser.add_argument("--output-dir", required=True, type=Path, help="New or empty local output directory")
    parser.add_argument("--format", choices=("all", "ics", "wakeup"), default="all")
    args = parser.parse_args(argv)
    try:
        require(not args.output_dir.exists() or (args.output_dir.is_dir() and not any(args.output_dir.iterdir())),
                "output-dir: must be new or empty; preserve earlier exports separately")
        if args.input == "-":
            raw = sys.stdin.buffer.read(10_000_001).decode("utf-8-sig")
        else:
            with Path(args.input).open(encoding="utf-8-sig") as handle:
                raw = handle.read(10_000_001)
        require(len(raw) <= 10_000_000, "input: exceeds size limit")
        try:
            payload = json.loads(raw, object_pairs_hook=unique_object)
        except InputError:
            raise
        except (ValueError, RecursionError) as exc:
            raise InputError("input: invalid JSON") from exc
        manifest, files = convert(payload, args.format)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for filename, body in files.items():
            (args.output_dir / filename).write_bytes(body)
        print(json.dumps({"status": manifest["status"], "counts": manifest["counts"],
                          "targets": manifest["targets"], "review": "review.json"}, ensure_ascii=True))
        return 0 if manifest["status"] == "generated" else 2
    except (InputError, OSError, UnicodeError) as exc:
        # OS diagnostics may include local user paths; keep CLI failures concise.
        message = str(exc) if isinstance(exc, InputError) else "local file read/write failed"
        print(json.dumps({"status": "invalid", "error": message}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
