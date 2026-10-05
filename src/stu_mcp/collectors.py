"""On-demand campus adapters. No schedulers, model calls, or production dependencies."""
from __future__ import annotations

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

    def fail(self, part: str, exc: AppError):
        self.errors.append({"part": part, **exc.result()})

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
    base = JW_BASE.replace("https://", "http://") if legacy else JW_BASE
    result = Collection(private=True, coverage={"grade_scope": semester or "all_semesters",
                                                "exam_semester": semester or default_semester(),
                                                "transport": "school_legacy_http" if legacy else "https"})
    with CampusHTTP("jw", vault.load("jw"), allow_legacy_http=legacy) as http:
        html = http.text(base + "/kscj/cjcx_list",
                         data={"kksj": semester, "kcmc": "", "kcxz": "", "kspage": "1", "jspage": "200"})
        grades = parse_jw(html, "grade")
        result.items.extend(grades)
        result.limited = len(grades) >= 200
        term = semester or default_semester()
        try:
            exams = parse_jw(http.text(base + "/xsks/xsksap_list", data={"xnxqid": term, "kslcdm": ""}),
                             "exam", term)
            result.items.extend(exams[:limit])
            result.limited |= len(exams) > limit
        except AppError as exc:
            result.fail("考试安排", exc)
    return result


def default_semester() -> str:
    today = datetime.now(CST)
    year = today.year if today.month >= 8 else today.year - 1
    return f"{year}-{year + 1}-{'1' if today.month >= 8 or today.month == 1 else '2'}"


def mystu(vault: Vault, limit: int) -> Collection:
    result = Collection(private=True, coverage={"scope": "latest_term", "max_courses": limit,
                                                "activities_per_course": 50, "detail_limit": 20})
    detail_count = 0
    with CampusHTTP("mystu", vault.load("mystu")) as http:
        http.json(MYSTU_API + "/user/validate?ver=1.1")
        payload = http.json(MYSTU_API + "/course/query")
        if "items" not in payload:
            raise AppError("schema_changed", "MySTU 的课程字段发生变化。", "mystu")
        selected = current_courses(payload_records(payload))
        result.limited = len(selected) > limit
        for course in selected[:limit]:
            name = clean(course.get("name") or course.get("groupName"))
            url = str(course.get("url") or "")
            try:
                if url:
                    checked_url("mystu", url)
                cid = str(course.get("id") or url)
                result.items.append({"id": item_id("mystu", "course", cid), "kind": "course", "title": name,
                                     "url": url or None, "year": course.get("attendanceYear"),
                                     "term": course.get("attendanceSemester"), "teacher": clean(course.get("teacher"))})
                if "/courses/elc/" in url:
                    html = http.text(url)
                    if is_login(html):
                        raise AppError("needs_elc_login", "ELC 还需在学校页面完成登录；请重新打开 MySTU 登录。", "mystu")
                    activities = parse_elc(html, url)
                else:
                    moodle_id = parse_qs(urlparse(url).query).get("id", [""])[0]
                    if not moodle_id:
                        continue
                    activities = http.json(MYSTU_API + "/courseactivity/query?" +
                                           urlencode({"moodleCourseId": moodle_id, "category": "undefined",
                                                      "lang": "zh-CN"})).get("courseActivities", [])
                if not isinstance(activities, list):
                    raise AppError("schema_changed", "MySTU 活动字段发生变化。", "mystu")
                result.limited |= len(activities) > 50
                for activity in activities[:50]:
                    title = clean(activity.get("activityTitle"))
                    if not title:
                        continue
                    link = str(activity.get("activityUrl") or "")
                    category = str(activity.get("activityCategory") or "resource")
                    kind = "task" if category in {"assignment", "assign", "quiz"} else "resource"
                    detail = {}
                    if link:
                        checked_url("mystu", link)
                    if kind == "task" and link and detail_count < 20:
                        detail_count += 1
                        try:
                            detail_html = http.text(link)
                            if is_login(detail_html):
                                raise AppError("needs_elc_login", "作业详情需要学校页面登录。", "mystu")
                            detail = parse_assignment(detail_html)
                        except AppError as exc:
                            result.fail("作业详情", exc)
                    elif kind == "task" and link:
                        result.limited = True
                    result.items.append({"id": item_id("mystu", kind, cid, link or title), "kind": kind,
                                         "title": title, "course": name, "url": link or None,
                                         "category": category, "due_at": detail.get("due_at") or
                                         stamp(activity.get("additionalDueDate")),
                                         "school_status": detail.get("school_status"), "status": "todo",
                                         "body": detail.get("description") or clean(activity.get("description"))[:6000]})
            except AppError as exc:
                result.fail("课程活动", exc)
        # Calendar data is optional and independent of successful course collection.
        start, end = datetime.now(CST) - timedelta(days=7), datetime.now(CST) + timedelta(days=31)
        try:
            schedule = http.json(MYSTU_API + "/userschedule/query?" +
                                 urlencode({"startTime": int(start.timestamp() * 1000),
                                            "endTime": int(end.timestamp() * 1000), "category": "all"}))
            for event in payload_records(schedule)[:50]:
                title = clean(event.get("title") or event.get("name"))
                if title:
                    result.items.append({"id": item_id("mystu", "event", event.get("id"), title),
                                         "kind": "event", "title": title,
                                         "start_at": stamp(event.get("startTime")),
                                         "end_at": stamp(event.get("endTime")),
                                         "location": clean(event.get("location"))})
        except AppError as exc:
            result.fail("个人日程", exc)
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
        terms = [c.get("term") for c in courses if isinstance(c.get("term"), int)]
        if terms:
            latest = max(terms)
            courses = [c for c in courses if c.get("term") == latest]
        for c in courses[:limit]:
            cid = str(c.get("classroom_id") or "")
            if not cid.isdigit():
                continue
            name = clean((c.get("course") or {}).get("name") or c.get("name"))
            course_url = YUKETANG_BASE + f"/v2/web/studentLog/{cid}"
            result.items.append({"id": item_id("yuketang", "course", cid), "kind": "course", "title": name,
                                 "url": course_url, "term": c.get("term"),
                                 "teacher": clean((c.get("teacher") or {}).get("name"))})
            try:
                feed = http.json(YUKETANG_BASE + f"/v2/api/web/logs/learn/{cid}?actype=-1&page=0&offset=50&sort=-1")
                for activity in (feed.get("data") or {}).get("activities", [])[:50]:
                    title = clean(activity.get("title"))
                    if not title:
                        continue
                    content = activity.get("content") or {}
                    kind = "task" if activity.get("type") in (19, 3) else "resource"
                    leaf = str(content.get("leaf_id") or "")
                    url = YUKETANG_BASE + f"/ai-workspace/lms-graph/{cid}/exercise/{leaf}?is_chapter=1" if leaf.isdigit() else course_url
                    result.items.append({"id": item_id("yuketang", kind, cid, activity.get("id") or title),
                                         "kind": kind, "title": title, "course": name, "url": url,
                                         "due_at": stamp(content.get("score_d")), "status": "todo",
                                         "published_at": stamp(activity.get("create_time"))})
                announcement = http.json(YUKETANG_BASE +
                                         f"/v/discussion/v2/announcements/?cid={cid}&limit=20&offset=0&type=9")
                for ann in (announcement.get("data") or {}).get("data", [])[:20]:
                    body = text_body(str(ann.get("content") or ""), 10000)
                    result.items.append({"id": item_id("yuketang", "notice", cid, ann.get("id")),
                                         "kind": "notice", "title": clean(ann.get("title") or body)[:200],
                                         "course": name, "body": body, "url": course_url,
                                         "published_at": stamp(ann.get("publish_time") or ann.get("create_time"))})
            except AppError as exc:
                result.fail("课程内容", exc)
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
