"""Pure source decoders. Unknown pages and ambiguous identities are not empty snapshots."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ...pagination import complete_list
from ...parsing import clean, is_login, item_id, parse_date, stamp
from ...runtime import AppError
from .schema import (
    ACTIVITY_FIELDS,
    ACTIVITY_LIMIT,
    ACTIVITY_LINK_SELECTOR,
    ACTIVITY_LIST_FIELD,
    ACTIVITY_SELECTOR,
    ACTIVITY_TITLE_SELECTOR,
    ARRAY_FIELDS_FIELD,
    ASSIGNMENT_PAGE_SELECTOR,
    COURSE_CONTENT_SELECTOR,
    COURSE_FIELDS,
    DESCRIPTION_SELECTOR,
    DETAIL_LABELS,
    EVENT_LIMIT,
    ITEMS_FIELD,
    SCHEDULE_FIELDS,
    TASK_CATEGORIES,
)


def schema_error(message: str) -> AppError:
    return AppError("schema_changed", message, "mystu")


def payload_records(payload: dict) -> list[dict]:
    """Decode the observed object/column-array variants without dropping malformed rows."""
    if not isinstance(payload, dict) or not isinstance(payload.get(ITEMS_FIELD), list):
        raise schema_error("MySTU 未返回可识别的记录列表；未把结构变化当作空结果。")
    rows = payload[ITEMS_FIELD]
    fields = []
    if any(isinstance(row, list) for row in rows):
        raw_fields = payload.get(ARRAY_FIELDS_FIELD)
        if not isinstance(raw_fields, str):
            raise schema_error("MySTU 数组记录缺少列名。")
        fields = [field.strip() for field in raw_fields.split(",")]
        if not fields or any(not field for field in fields) or len(set(fields)) != len(fields):
            raise schema_error("MySTU 数组记录的列名缺失或重复。")
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(dict(row))
        elif isinstance(row, list) and len(row) == len(fields):
            result.append(dict(zip(fields, row, strict=True)))
        else:
            raise schema_error("MySTU 记录与列名不匹配，保留原缓存。")
    return result


def current_courses(courses: list[dict]) -> list[dict]:
    dated = [course for course in courses if type(course.get(COURSE_FIELDS["year"])) is int
             and type(course.get(COURSE_FIELDS["term"])) is int]
    if not dated:
        return courses
    term = max((course[COURSE_FIELDS["year"]], course[COURSE_FIELDS["term"]]) for course in dated)
    return [course for course in dated
            if (course[COURSE_FIELDS["year"]], course[COURSE_FIELDS["term"]]) == term]


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    url: str
    year: object
    term: object
    teacher: str


@dataclass(frozen=True)
class Inventory:
    courses: list[Course]
    complete: bool
    semester: str | None


@dataclass(frozen=True)
class Activity:
    title: str
    url: str
    category: str
    due_at: str | None
    description: str

    @property
    def kind(self) -> str:
        return "task" if self.category in TASK_CATEGORIES else "resource"


@dataclass(frozen=True)
class Activities:
    items: list[Activity]
    complete: bool


def optional_text(value: object, label: str) -> str:
    if isinstance(value, bool) or value is not None and not isinstance(value, (str, int, float)):
        raise schema_error(f"MySTU {label}字段类型发生变化。")
    return clean(value)


def course_url(value: object) -> str:
    """Upgrade the observed legacy ELC link; never enable authenticated HTTP."""
    url = optional_text(value, "课程链接")
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (parsed.scheme == "http" and parsed.hostname == "my.stu.edu.cn"
                and parsed.port in {None, 80} and not parsed.username and not parsed.password
                and not parsed.fragment and parsed.path == "/courses/elc/course/view.php"
                and set(query) == {"id"} and len(query["id"]) == 1
                and re.fullmatch(r"[0-9]{1,20}", query["id"][0])):
            return urlunparse(parsed._replace(scheme="https", netloc="my.stu.edu.cn"))
    except ValueError:
        pass  # The adapter's existing URL policy rejects malformed/unknown links.
    return url


def parse_inventory(payload: dict) -> Inventory:
    courses = payload_records(payload)
    known_ids = set()
    for course in courses:
        if isinstance(course.get(COURSE_FIELDS["id"]), bool):
            raise schema_error("MySTU 课程标识变为布尔值，无法确认当前课程范围。")
        if any(isinstance(course.get(COURSE_FIELDS[field]), bool) for field in ("year", "term")):
            raise schema_error("MySTU 课程年份或学期变为布尔值，无法确认当前课程范围。")
        identity = course.get(COURSE_FIELDS["id"]) or course.get(COURSE_FIELDS["url"])
        if not isinstance(identity, (str, int)) or isinstance(identity, bool) or not str(identity).strip():
            raise schema_error("MySTU 课程缺少可识别的记录。")
        cid = str(identity)
        if cid in known_ids:
            raise schema_error("MySTU 课程标识重复，无法确认当前课程范围。")
        known_ids.add(cid)
    selected = current_courses(courses)
    dated = [course for course in courses if type(course.get(COURSE_FIELDS["year"])) is int
             and type(course.get(COURSE_FIELDS["term"])) is int]
    complete = complete_list(payload, len(courses)) and len(dated) == len(courses)
    semester = (f"{selected[0][COURSE_FIELDS['year']]}-{selected[0][COURSE_FIELDS['term']]}"
                if selected and dated else None)
    result = []
    for course in selected:
        name = next((course.get(key) for key in COURSE_FIELDS["title"] if course.get(key)), None)
        title = optional_text(name, "课程名称")
        if not title:
            raise schema_error("MySTU 课程缺少名称，保留原缓存。")
        result.append(Course(
            id=str(course.get(COURSE_FIELDS["id"]) or course[COURSE_FIELDS["url"]]), title=title,
            url=course_url(course.get(COURSE_FIELDS["url"])),
            year=course.get(COURSE_FIELDS["year"]), term=course.get(COURSE_FIELDS["term"]),
            teacher=optional_text(course.get(COURSE_FIELDS["teacher"]), "教师")))
    return Inventory(result, complete, semester)


def decode_activities(rows: list, *, complete: bool) -> Activities:
    if any(not isinstance(row, dict) for row in rows):
        raise schema_error("MySTU 活动字段发生变化。")
    result, identities = [], set()
    for row in rows[:ACTIVITY_LIMIT]:
        if isinstance(row.get(ACTIVITY_FIELDS["due_at"]), bool):
            raise schema_error("MySTU 活动截止时间字段类型发生变化。")
        title = optional_text(row.get(ACTIVITY_FIELDS["title"]), "活动标题")
        if not title:
            raise schema_error("MySTU 活动缺少标题，未把解析失败当作空列表。")
        activity = Activity(
            title=title, url=optional_text(row.get(ACTIVITY_FIELDS["url"]), "活动链接"),
            category=optional_text(row.get(ACTIVITY_FIELDS["category"]), "活动分类") or "resource",
            due_at=stamp(row.get(ACTIVITY_FIELDS["due_at"])),
            description=optional_text(row.get(ACTIVITY_FIELDS["description"]), "活动内容")[:6000])
        identity = (activity.kind, activity.url or activity.title)
        if identity in identities:
            raise schema_error("MySTU 活动标识重复，无法确认课程活动范围。")
        identities.add(identity)
        result.append(activity)
    return Activities(result, complete)


def parse_activities(payload: dict) -> Activities:
    rows = payload.get(ACTIVITY_LIST_FIELD) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise schema_error("MySTU 活动字段发生变化。")
    return decode_activities(rows, complete=complete_list(payload, len(rows), ACTIVITY_LIMIT))


def parse_elc(html: str, base: str) -> list[dict]:
    if is_login(html):
        raise AppError("needs_elc_login", "ELC 还需在学校页面完成登录；请重新打开 MySTU 登录。", "mystu")
    soup = BeautifulSoup(html, "html.parser")
    if len(soup.select(COURSE_CONTENT_SELECTOR)) != 1:
        raise schema_error("ELC 未返回唯一可识别的课程内容。")
    records, seen = [], set()
    for node in soup.select(ACTIVITY_SELECTOR):
        if "modtype_label" in node.get("class", []):
            # Moodle labels are inline course material, not separately linked
            # activities. Their incidental links may repeat a real resource.
            continue
        link = node.select_one(ACTIVITY_LINK_SELECTOR)
        if link is None:
            raise schema_error("ELC 部分活动缺少链接，保留原缓存。")
        url = urljoin(base, str(link["href"]))
        match = re.search(r"/mod/([^/]+)/", urlparse(url).path)
        category = match.group(1) if match else "resource"
        title_node = node.select_one(ACTIVITY_TITLE_SELECTOR) or link
        title = clean(title_node.get_text(" ", strip=True))
        if not title or url in seen:
            raise schema_error("ELC 活动缺少标题或标识重复，保留原缓存。")
        records.append({"activityTitle": title, "activityUrl": url,
                        "activityCategory": "assignment" if category in {"assign", "quiz"} else category,
                        "moodleType": category, "description": clean(node.get_text(" ", strip=True))[:4000]})
        seen.add(url)
    return records


def parse_assignment(html: str) -> dict:
    if is_login(html):
        raise AppError("needs_elc_login", "作业详情需要学校页面登录。", "mystu")
    soup = BeautifulSoup(html, "html.parser")
    intros = soup.select(DESCRIPTION_SELECTOR)
    # Moodle may wrap #intro in .activity-description. Nested candidates are
    # one description region; independent regions have no unambiguous owner.
    roots = [node for node in intros if not any(parent in intros for parent in node.parents)]
    if len(roots) > 1:
        raise schema_error("ELC 作业说明出现多个候选区域，保留原缓存。")
    intro = roots[0] if roots else None
    pairs = []
    for row in soup.select("tr"):
        if intro is not None and intro in row.parents:
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2 and not any(cell.find("table") for cell in cells):
            pairs.append((clean(cells[0].get_text(" ", strip=True)).lower(),
                          clean(cells[-1].get_text(" ", strip=True))))
    for term in soup.select("dt"):
        if intro is not None and intro in term.parents:
            continue
        sibling = term.find_next_sibling("dd")
        if sibling:
            pairs.append((clean(term.get_text(" ", strip=True)).lower(),
                          clean(sibling.get_text(" ", strip=True))))
    values, recognized_field = {}, False
    for field, pattern in DETAIL_LABELS.items():
        matches = [value for label, value in pairs if re.fullmatch(pattern, label)]
        if len(matches) > 1:
            raise schema_error("ELC 作业详情的关键字段重复，无法确认实际内容。")
        recognized_field |= bool(matches)
        values[field] = matches[0] if matches else None
    if not soup.select_one(ASSIGNMENT_PAGE_SELECTOR) and not recognized_field:
        raise schema_error("ELC 未返回可识别的作业详情；未把错误页面当作已读取。")
    return {"due_at": parse_date(values["due_at"]), "school_status": values["school_status"],
            "description": clean(intro.get_text(" ", strip=True))[:6000] if intro else ""}


def parse_schedule(payload: dict) -> tuple[list[dict], bool]:
    events = payload_records(payload)
    result = []
    for event in events[:EVENT_LIMIT]:
        if any(isinstance(event.get(SCHEDULE_FIELDS[field]), bool) for field in ("id", "start_at", "end_at")):
            raise schema_error("MySTU 日程标识或时间字段类型发生变化。")
        title = optional_text(next((event.get(key) for key in SCHEDULE_FIELDS["title"] if event.get(key)), None),
                              "日程标题")
        if title:
            result.append({"id": item_id("mystu", "event", event.get(SCHEDULE_FIELDS["id"]), title),
                           "kind": "event", "title": title,
                           "start_at": stamp(event.get(SCHEDULE_FIELDS["start_at"])),
                           "end_at": stamp(event.get(SCHEDULE_FIELDS["end_at"])),
                           "location": optional_text(event.get(SCHEDULE_FIELDS["location"]), "日程地点")})
    return result, len(events) > EVENT_LIMIT
