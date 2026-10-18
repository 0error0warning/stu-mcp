"""On-demand campus adapters. No schedulers, model calls, or production dependencies."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from bs4 import BeautifulSoup

from .network import CampusHTTP, checked_url
from .parsers import (
    CST,
    clean,
    current_courses,
    is_login,
    item_id,
    jw_exam_semester,
    parse_assignment,
    parse_elc,
    parse_jw,
    parse_links,
    parse_oa,
    parse_oa_article,
    parse_public,
    payload_records,
    stamp,
    text_body,
)
from .runtime import AppError
from .sources import (
    JW_BASE,
    MYSTU_API,
    OA_DIRECT,
    OA_SECURE_PROXY,
    PUBLIC_LISTINGS,
    YUKETANG_BASE,
)
from .sync import CourseSync
from .vault import Vault
from .webvpn import protected_access


@dataclass
class Collection:
    items: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    private: bool = False
    limited: bool = False
    coverage: dict = field(default_factory=dict)
    session_version: bytes | None = None
    sync: CourseSync | None = None

    def fail(self, part: str, exc: AppError, *, stage: str | None = None,
             course_id: str | None = None, item_id: str | None = None):
        context = {k: v for k, v in {"stage": stage, "course_id": course_id, "item_id": item_id}.items()
                   if v is not None}
        if course_id is not None and not re.fullmatch(r"[A-Za-z0-9._:-]{1,120}", course_id):
            context.pop("course_id")  # Some legacy course IDs are URLs; don't echo an unsafe URL on failure.
        self.errors.append({"part": part, **context, **exc.result()})

    @property
    def status(self) -> str:
        return "partial" if self.errors or self.limited else "ok"


def public(limit: int) -> Collection:
    result = Collection(limited=True, coverage={"scope": "recent_listing_pages", "per_listing": limit})
    with CampusHTTP("public") as http:
        for category, url in PUBLIC_LISTINGS:
            try:
                html = http.text(url)
                records = parse_public(html, url, category, limit)
                if not records:
                    raise AppError("schema_changed", "此公开栏目未找到预期文章链接。", "public")
                for record in records:
                    checked_url("public", record["url"])
                result.items.extend(records)
            except AppError as exc:
                result.fail(category, exc)
        url = "https://www.stu.edu.cn/kstd.htm"
        try:
            result.items.extend(parse_links(http.text(url), url))
        except AppError as exc:
            result.fail("校园服务入口", exc)
    if not result.items:
        raise AppError("source_unavailable", "公开来源暂时无法读取；这不表示没有通知。", "public")
    return result


def oa(vault: Vault, limit: int) -> Collection:
    # The published OA board currently works anonymously. Never send a session to its HTTP endpoint.
    base, private, session_version = OA_DIRECT, False, None
    http = CampusHTTP("oa")
    url = base + "/login/Login.jsp?logintype=1"
    try:
        html = http.text(url)
        records = parse_oa(html, base, limit)
    except AppError:
        http.client.close()
        base, private = OA_SECURE_PROXY, True
        accessed = protected_access(vault, base + "/login/Login.jsp?logintype=1",
                                    lambda response: parse_oa(response.text, base, limit))
        records, session_version = accessed.value, accessed.session_version
    finally:
        http.client.close()
    return Collection(records, private=private, limited=True, session_version=session_version,
                      coverage={"scope": "first_listing_page", "limit": limit,
                                "access": "authenticated_https" if private else "anonymous_http"})


def jw(vault: Vault, limit: int, semester: str) -> Collection:
    legacy = vault.runtime.preferences()["jw_http_compat"]
    base = JW_BASE
    result = Collection(private=True, limited=True, coverage={"grade_scope": semester or "available_table",
                                                             "max_grade_rows": 200,
                                                             "exam_semester": semester or None,
                                                             "transport": "https", "login_entry": "jwglxt"})
    with CampusHTTP("jw", vault.load("jw"), allow_legacy_http=legacy) as http:
        response = http.request(base + "/kscj/cjcx_list",
                                data={"kksj": semester, "kcmc": "", "kcxz": "", "kspage": "1", "jspage": "200"})
        html = response.text
        grades = parse_jw(html, "grade")
        result.coverage["grade_rows_read"] = len(grades)
        result.items.extend(g for g in grades[:200] if not semester or g["semester"] == semester)
        try:
            term = semester or jw_exam_semester(http.text(base + "/xsks/xsksap_query"))
            result.coverage["exam_semester"] = term
            response = http.request(base + "/xsks/xsksap_list", data={"xnxqid": term, "xqlb": "", "xqlbmc": ""})
            exams = parse_jw(response.text, "exam", term)
            result.items.extend(exams[:limit])
            result.coverage["exam_rows_read"] = len(exams)
        except AppError as exc:
            result.fail("考试安排", exc)
        result.coverage["transport"] = "school_legacy_http" if http.used_legacy_http else "https"
    return result


def default_semester() -> str:
    today = datetime.now(CST)
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-{year + 1}-{'1' if today.month >= 8 or today.month == 1 else '2'}"


def complete_list(payload: dict, size: int, capacity: int | None = None) -> bool:
    """A full page or explicit remaining results is never a replacement snapshot."""
    if capacity is not None and size >= capacity:
        return False
    for key in ("has_more", "hasMore", "has_next", "hasNext", "has_next_page", "next", "nextPage"):
        if payload.get(key):
            return False
    for key in ("total", "total_count", "totalCount", "count"):
        value = payload.get(key)
        if value is not None:
            try:
                if int(value) > size or int(value) < 0:
                    return False
            except (TypeError, ValueError):
                return False
    for key in ("total_pages", "totalPages", "page_count", "pageCount"):
        if payload.get(key, 1) != 1:
            return False
    pagination = payload.get("pagination")
    return not isinstance(pagination, dict) or complete_list(pagination, size)


def mystu(vault: Vault, limit: int) -> Collection:
    result = Collection(private=True, coverage={"scope": "latest_term", "max_courses": limit,
                                                "activities_per_course": 50, "detail_limit": 20})
    detail_count = 0
    with CampusHTTP("mystu", vault.load("mystu")) as http:
        http.json(MYSTU_API + "/user/validate?ver=1.1")
        payload = http.json(MYSTU_API + "/course/query")
        raw_courses = payload.get("items")
        if not isinstance(raw_courses, list):
            raise AppError("schema_changed", "MySTU 的课程字段发生变化。", "mystu")
        courses = payload_records(payload)
        if len(courses) != len(raw_courses) or any(not (c.get("id") or c.get("url")) for c in courses):
            raise AppError("schema_changed", "MySTU 课程缺少可识别的记录。", "mystu")
        selected = current_courses(courses)
        dated = [c for c in courses if isinstance(c.get("attendanceYear"), int)
                 and isinstance(c.get("attendanceSemester"), int)]
        inventory_complete = complete_list(payload, len(courses)) and len(dated) == len(courses)
        semester = (f"{selected[0]['attendanceYear']}-{selected[0]['attendanceSemester']}"
                    if selected and dated else None)
        result.sync = CourseSync(
            course_ids=frozenset(str(c.get("id") or c["url"]) for c in selected) if inventory_complete else None,
            semester=semester)
        result.coverage.update(semester=semester, inventory_complete=inventory_complete,
                               selected_courses=len(selected))
        result.limited = len(selected) > limit or not inventory_complete
        for course in selected[:limit]:
            name = clean(course.get("name") or course.get("groupName"))
            url = str(course.get("url") or "")
            cid = str(course.get("id") or url)
            try:
                if url:
                    checked_url("mystu", url)
                provenance = {"course_id": cid, "semester": semester,
                              "year": course.get("attendanceYear"), "term": course.get("attendanceSemester")}
                result.items.append({"id": item_id("mystu", "course", cid), "kind": "course", "title": name,
                                     "url": url or None, **provenance, "teacher": clean(course.get("teacher"))})
                if "/courses/elc/" in url:
                    html = http.text(url)
                    if is_login(html):
                        raise AppError("needs_elc_login", "ELC 还需在学校页面完成登录；请重新打开 MySTU 登录。", "mystu")
                    soup = BeautifulSoup(html, "html.parser")
                    if not soup.select_one(".course-content"):
                        raise AppError("schema_changed", "ELC 未返回可识别的课程内容。", "mystu")
                    activities = parse_elc(html, url)
                    nodes = soup.select(".course-content li.activity, .course-content .activity[class*='modtype_']")
                    if len(nodes) != len(activities):
                        raise AppError("schema_changed", "ELC 部分活动未能解析，保留其旧缓存。", "mystu")
                    # HTML may contain just one section or lazily loaded activities.
                    # Recognizing a page is not proof of a complete course snapshot.
                    activity_complete = False
                else:
                    moodle_id = parse_qs(urlparse(url).query).get("id", [""])[0]
                    if not moodle_id:
                        result.limited = True
                        continue
                    activity_payload = http.json(MYSTU_API + "/courseactivity/query?" +
                                                 urlencode({"moodleCourseId": moodle_id, "category": "undefined",
                                                            "lang": "zh-CN"}))
                    activities = activity_payload.get("courseActivities")
                    activity_complete = isinstance(activities, list) and complete_list(
                        activity_payload, len(activities), 50)
                if not isinstance(activities, list) or any(not isinstance(a, dict) for a in activities):
                    raise AppError("schema_changed", "MySTU 活动字段发生变化。", "mystu")
                result.limited |= not activity_complete
                for activity in activities[:50]:
                    title = clean(activity.get("activityTitle"))
                    if not title:
                        raise AppError("schema_changed", "MySTU 活动缺少标题，未把解析失败当作空列表。", "mystu")
                    link = str(activity.get("activityUrl") or "")
                    category = str(activity.get("activityCategory") or "resource")
                    kind = "task" if category in {"assignment", "assign", "quiz"} else "resource"
                    detail = {}
                    aid = item_id("mystu", kind, cid, link or title)
                    detail_state = {"detail_status": "not_read"} if kind == "task" else {}
                    if link:
                        checked_url("mystu", link)
                    if kind == "task" and link and detail_count < 20:
                        detail_count += 1
                        try:
                            detail_html = http.text(link)
                            if is_login(detail_html):
                                raise AppError("needs_elc_login", "作业详情需要学校页面登录。", "mystu")
                            detail = parse_assignment(detail_html)
                            detail_state = {"detail_status": "read"}
                        except AppError as exc:
                            if exc.code in {"login_expired", "needs_login", "needs_elc_login"}:
                                exc = AppError("resource_login_required",
                                               "此活动返回登录页；不能据此判断整个 MySTU 会话失效，请先核对该活动原页面。",
                                               "mystu", http_status=exc.http_status)
                            detail_state = {"detail_status": "unavailable", "detail_error": exc.result()}
                            result.fail("作业详情", exc, stage="task_detail", course_id=cid, item_id=aid)
                    elif kind == "task" and link:
                        result.limited = True
                        detail_state = {"detail_status": "limit_reached"}
                    due = detail.get("due_at") or stamp(activity.get("additionalDueDate"))
                    if kind == "task":
                        detail_state["due_at_status"] = ("available" if due else "not_found_in_detail"
                                                         if detail_state["detail_status"] == "read"
                                                         else "detail_" + detail_state["detail_status"])
                    result.items.append({"id": aid, "kind": kind, **detail_state,
                                         "title": title, "course": name, **provenance, "url": link or None,
                                         "category": category, "due_at": due,
                                         "school_status": detail.get("school_status"), "status": "todo",
                                         "body": detail.get("description") or clean(activity.get("description"))[:6000]})
                if activity_complete:
                    result.sync.complete_courses.add(cid)
            except AppError as exc:
                result.fail("课程活动", exc, stage="course_activities", course_id=cid)
        # Calendar data is optional and independent of successful course collection.
        start, end = datetime.now(CST) - timedelta(days=7), datetime.now(CST) + timedelta(days=31)
        try:
            schedule = http.json(MYSTU_API + "/userschedule/query?" +
                                 urlencode({"startTime": int(start.timestamp() * 1000),
                                            "endTime": int(end.timestamp() * 1000), "category": "all"}))
            events = payload_records(schedule)
            result.limited |= len(events) > 50
            for event in events[:50]:
                title = clean(event.get("title") or event.get("name"))
                if title:
                    result.items.append({"id": item_id("mystu", "event", event.get("id"), title),
                                         "kind": "event", "title": title,
                                         "start_at": stamp(event.get("startTime")),
                                         "end_at": stamp(event.get("endTime")),
                                         "location": clean(event.get("location"))})
        except AppError as exc:
            result.fail("个人日程", exc, stage="schedule")
    result.coverage.update(complete_activity_courses=len(result.sync.complete_courses),
                           course_snapshot_complete=result.sync.complete)
    return result


def yuketang(vault: Vault, limit: int) -> Collection:
    result = Collection(private=True, limited=True, coverage={"scope": "latest_available_term",
                                                             "courses": limit, "activities_per_course": 50})
    with CampusHTTP("yuketang", vault.load("yuketang")) as http:
        payload = http.json(YUKETANG_BASE + "/v2/api/web/courses/list?identity=2")
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise AppError("schema_changed", "雨课堂未返回课程列表。", "yuketang")
        courses = data["list"]
        if any(not isinstance(c, dict) or not str(c.get("classroom_id") or "").isdigit() for c in courses):
            raise AppError("schema_changed", "雨课堂课程缺少可识别的记录。", "yuketang")
        terms = [c.get("term") for c in courses if isinstance(c.get("term"), int)]
        inventory_complete = complete_list(data, len(courses)) and complete_list(payload, len(courses))
        inventory_complete &= len(terms) == len(courses)
        semester = str(max(terms)) if terms else None
        if terms:
            latest = max(terms)
            courses = [c for c in courses if c.get("term") == latest]
        result.sync = CourseSync(
            course_ids=frozenset(str(c["classroom_id"]) for c in courses) if inventory_complete else None,
            semester=semester)
        result.coverage.update(semester=semester, inventory_complete=inventory_complete,
                               selected_courses=len(courses))
        for c in courses[:limit]:
            cid = str(c.get("classroom_id") or "")
            if not cid.isdigit():
                continue
            name = clean((c.get("course") or {}).get("name") or c.get("name"))
            course_url = YUKETANG_BASE + f"/v2/web/studentLog/{cid}"
            result.items.append({"id": item_id("yuketang", "course", cid), "kind": "course", "title": name,
                                 "url": course_url, "term": c.get("term"), "semester": semester, "course_id": cid,
                                 "teacher": clean((c.get("teacher") or {}).get("name"))})
            try:
                feed = http.json(YUKETANG_BASE + f"/v2/api/web/logs/learn/{cid}?actype=-1&page=0&offset=50&sort=-1")
                feed_data = feed.get("data")
                if not isinstance(feed_data, dict) or not isinstance(feed_data.get("activities"), list):
                    raise AppError("schema_changed", "雨课堂未返回可识别的课程活动列表。", "yuketang")
                activities = feed_data["activities"]
                activity_complete = complete_list(feed_data, len(activities), 50) and complete_list(
                    feed, len(activities))
                for activity in activities[:50]:
                    if not isinstance(activity, dict):
                        raise AppError("schema_changed", "雨课堂活动记录结构发生变化。", "yuketang")
                    title = clean(activity.get("title"))
                    if not title:
                        raise AppError("schema_changed", "雨课堂活动缺少标题，未把解析失败当作空列表。", "yuketang")
                    content = activity.get("content") or {}
                    if not isinstance(content, dict):
                        raise AppError("schema_changed", "雨课堂活动内容字段发生变化。", "yuketang")
                    kind = "task" if activity.get("type") in (19, 3) else "resource"
                    leaf = str(content.get("leaf_id") or "")
                    url = YUKETANG_BASE + f"/ai-workspace/lms-graph/{cid}/exercise/{leaf}?is_chapter=1" if leaf.isdigit() else course_url
                    result.items.append({"id": item_id("yuketang", kind, cid, activity.get("id") or title),
                                         "kind": kind, "title": title, "course": name, "url": url,
                                         "course_id": cid, "semester": semester, "term": c.get("term"),
                                         "activity_type": activity.get("type"), "leaf_id": leaf or None,
                                         "due_at": stamp(content.get("score_d")), "status": "todo",
                                         "published_at": stamp(activity.get("create_time"))})
                if activity_complete:
                    result.sync.complete_courses.add(cid)
            except AppError as exc:
                result.fail("课程活动", exc, stage="course_activities", course_id=cid)
            # An activity failure must not suppress this course's independent announcements.
            try:
                announcement = http.json(YUKETANG_BASE +
                                         f"/v/discussion/v2/announcements/?cid={cid}&limit=20&offset=0&type=9")
                ann_data = announcement.get("data")
                if not isinstance(ann_data, dict) or not isinstance(ann_data.get("data"), list):
                    raise AppError("schema_changed", "雨课堂未返回可识别的课程公告列表。", "yuketang")
                for ann in ann_data["data"][:20]:
                    if not isinstance(ann, dict):
                        raise AppError("schema_changed", "雨课堂公告记录结构发生变化。", "yuketang")
                    body = text_body(str(ann.get("content") or ""), 10000)
                    result.items.append({"id": item_id("yuketang", "notice", cid, ann.get("id")),
                                         "kind": "notice", "title": clean(ann.get("title") or body)[:200],
                                         "course": name, "body": body, "url": course_url,
                                         "published_at": stamp(ann.get("publish_time") or ann.get("create_time"))})
            except AppError as exc:
                result.fail("课程公告", exc, stage="course_announcements", course_id=cid)
    result.coverage.update(complete_activity_courses=len(result.sync.complete_courses),
                           course_snapshot_complete=result.sync.complete)
    return result


@dataclass
class Article:
    item: dict
    session_version: bytes | None = None


def article(record: dict, vault: Vault) -> Article:
    source, url = record["source"], record.get("url")
    if source not in {"public", "oa"} or not url:
        raise AppError("unsupported_article", "请通过对应课程工具读取此来源。", source)
    session_version = None
    if source == "oa" and urlparse(url).scheme == "https":
        accessed = protected_access(vault, url, lambda response: response.text)
        html, session_version = accessed.value, accessed.session_version
    else:
        with CampusHTTP(source) as http:
            html = http.text(url)
    if is_login(html):
        raise AppError("needs_login", "正文需要在学校页面登录。", source)
    if source == "oa":
        parsed = urlparse(url)
        return Article(parse_oa_article(html, f"{parsed.scheme}://{parsed.netloc}"), session_version)
    soup = BeautifulSoup(html, "html.parser")
    return Article({"body": text_body(html), "attachments": [
        {"name": clean(a.get_text(" ", strip=True)) or "附件", "url": str(a["href"])}
        for a in soup.select('a[href*="download"], a[href$=".pdf"], a[href$=".docx"]')][:30]})
