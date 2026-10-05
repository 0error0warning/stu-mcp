"""Pure parsers adapted from the pinned School Hub source; never read credentials."""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .runtime import AppError

CST = timezone(timedelta(hours=8))


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def item_id(source: str, kind: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:24]
    return f"{source}:{kind}:{digest}"


def stamp(value: object) -> str | None:
    try:
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, CST).isoformat() if seconds > 0 else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?.*?(\d{1,2}):(\d{2})", value)
    if match:
        try:
            return datetime(*map(int, match.groups()), tzinfo=CST).isoformat()
        except ValueError:
            return None
    for fmt in ("%A, %d %B %Y, %I:%M %p", "%A, %d %B %Y, %H:%M",
                "%d %B %Y, %I:%M %p", "%d %B %Y, %H:%M"):
        try:
            return datetime.strptime(clean(value), fmt).replace(tzinfo=CST).isoformat()
        except ValueError:
            pass
    return clean(value)


def is_login(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(soup.select_one("input[type=password]")) or bool(
        re.search(r"<title[^>]*>[^<]*(?:统一身份认证|用户登录|SSO Login)", html, re.I))


def text_body(html: str, limit: int = 60000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, nav, header, footer, form"):
        node.decompose()
    node = soup.select_one("#docContent, #content, #vsb_content, .v_news_content, article, main")
    return clean((node or soup).get_text(" ", strip=True))[:limit]


def published(text: str) -> str | None:
    m = re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", text)
    return m.group(0) if m else None


def parse_public(html: str, base: str, category: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records, seen = [], set()
    for link in soup.select("a[href]"):
        url = urljoin(base, str(link["href"]))
        path = urlparse(url).path.lower()
        if not ("/info/" in path or re.search(r"/(?:news|activity|notice)(?:detail|view)?\.aspx$", path, re.IGNORECASE)):
            continue
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if len(title) < 3 or title.lower() in {"more", "更多", "查看详情", "了解更多"} or url in seen:
            continue
        parent = link.find_parent("li") or link.parent
        records.append({"id": item_id("public", "notice", url), "kind": "notice", "title": title,
                        "url": url, "category": category,
                        "published_at": published(clean(parent.get_text(" ", strip=True)))})
        seen.add(url)
        if len(records) >= limit:
            break
    return records


def parse_links(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    return [{"id": item_id("public", "service", urljoin(base, str(a["href"]))), "kind": "service",
             "title": clean(a.get_text(" ", strip=True)), "url": urljoin(base, str(a["href"]))}
            for a in soup.select("section.n_kuaisu .box a[href]")
            if clean(a.get_text(" ", strip=True))][:80]


def parse_oa(html: str, base: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records, seen = [], set()
    for link in soup.select('a[href*="newstemplateprotal.jsp"]'):
        url = urljoin(base, str(link["href"]))
        docid = parse_qs(urlparse(url).query).get("docid", [url])[0]
        if docid in seen:
            continue
        row = link.find_parent("tr")
        cells = [clean(c.get_text(" ", strip=True)) for c in row.select("td")] if row else []
        records.append({"id": item_id("oa", "notice", docid), "kind": "notice", "docid": docid,
                        "title": clean(link.get("title") or link.get_text(" ", strip=True)),
                        "url": url, "department": cells[1] if len(cells) > 1 else "",
                        "published_at": published(" ".join(cells))})
        seen.add(docid)
        if len(records) >= limit:
            break
    if not records and not soup.select_one("#searchForm"):
        raise AppError("oa_unavailable", "此网络无法读取 OA 列表；请查看本地设置中的 OA 状态。", "oa")
    return records


def parse_oa_article(html: str, base: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    attachments = []
    for row in soup.select('tr[id^="accessory_dsp_tr"]'):
        field = row.select_one('input[name="accessory"]')
        if field and str(field.get("value", "")).isdigit():
            file_id = str(field["value"])
            label = re.sub(r"附件\d+|下载", "", clean(row.get_text(" ", strip=True))).strip(" :：")
            attachments.append({"name": label or f"附件 {file_id}", "url": base +
                                f"/weaver/weaver.file.FileDownload?fileid={file_id}&download=1&requestid=0"})
    return {"body": text_body(html), "attachments": attachments[:30]}


def parse_jw(html: str, kind: str, semester: str = "") -> list[dict]:
    if is_login(html):
        raise AppError("login_expired", "教务登录已过期，请在本地设置页重新登录。", "jw")
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select("table"):
        raise AppError("schema_changed", "教务页面没有预期的表格；未把此页面当作空结果。", "jw")
    records = []
    for row in soup.select("table tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all("td", recursive=False)]
        if not cells or not cells[0].isdigit():
            continue
        if kind == "grade" and len(cells) >= 10:
            keys = ("semester", "course_code", "title", "score", "credits", "hours", "gpa",
                    "exam_method", "exam_type", "course_attribute", "course_nature", "category", "group")
            record = dict(zip(keys, cells[1:], strict=False))
            for key in ("credits", "gpa"):
                try:
                    record[key] = float(record[key])
                    if not math.isfinite(record[key]):
                        record[key] = None
                except (ValueError, TypeError):
                    record[key] = None
            record.update(id=item_id("jw", kind, record["semester"], record["course_code"],
                                     record.get("exam_type", ""), record.get("group", "")), kind=kind)
            records.append(record)
        elif kind == "exam" and len(cells) >= 8:
            keys = ("campus", "unused", "exam_session", "course_code", "title", "teacher", "exam_time",
                    "location", "seat_number", "exam_id", "notes")
            record = dict(zip(keys, cells[1:], strict=False))
            record.pop("unused", None)
            record.update(id=item_id("jw", kind, semester, record["course_code"], record["exam_time"]),
                          kind=kind, semester=semester)
            records.append(record)
    if not records and not re.search(r"成绩|考试|未查询到|无数据|暂无", html):
        raise AppError("schema_changed", "教务表格结构发生变化；未把解析失败当作空结果。", "jw")
    return records


def payload_records(payload: dict) -> list[dict]:
    fields = [f.strip() for f in str(payload.get("fields") or "").split(",") if f]
    return [r if isinstance(r, dict) else dict(zip(fields, r, strict=False))
            for r in payload.get("items") or [] if isinstance(r, (dict, list))]


def current_courses(courses: list[dict]) -> list[dict]:
    dated = [c for c in courses if isinstance(c.get("attendanceYear"), int)
             and isinstance(c.get("attendanceSemester"), int)]
    if not dated:
        return courses
    term = max((c["attendanceYear"], c["attendanceSemester"]) for c in dated)
    return [c for c in dated if (c["attendanceYear"], c["attendanceSemester"]) == term]


def parse_elc(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for node in soup.select(".course-content li.activity, .course-content .activity[class*='modtype_']"):
        link = node.select_one(".activityinstance a[href], a[href]")
        if not link:
            continue
        url = urljoin(base, str(link["href"]))
        match = re.search(r"/mod/([^/]+)/", urlparse(url).path)
        category = match.group(1) if match else "resource"
        title_node = node.select_one(".instancename") or link
        records.append({"activityTitle": clean(title_node.get_text(" ", strip=True)), "activityUrl": url,
                        "activityCategory": "assignment" if category in {"assign", "quiz"} else category,
                        "moodleType": category, "description": clean(node.get_text(" ", strip=True))[:4000]})
    return records


def parse_assignment(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    values = {}
    for row in soup.select("tr"):
        cells = row.select("th, td")
        if len(cells) >= 2:
            values[clean(cells[0].get_text(" ", strip=True)).lower()] = clean(cells[-1].get_text(" ", strip=True))
    for term in soup.select("dt"):
        sibling = term.find_next_sibling("dd")
        if sibling:
            values[clean(term.get_text(" ", strip=True)).lower()] = clean(sibling.get_text(" ", strip=True))
    def field(pattern: str) -> str | None:
        return next((v for k, v in values.items() if re.search(pattern, k)), None)
    intro = soup.select_one("#intro, .activity-description")
    due = field("due date|截止|到期|closes|关闭")
    status = field("submission status|提交状态|completion status|完成状态")
    return {"due_at": parse_date(due), "school_status": status,
            "description": clean(intro.get_text(" ", strip=True))[:6000] if intro else ""}
