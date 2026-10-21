"""Pure parsers adapted from the pinned School Hub source; never read credentials."""
from __future__ import annotations

import math
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .parsing import CST as CST
from .parsing import clean as clean
from .parsing import is_login as is_login
from .parsing import item_id as item_id
from .parsing import parse_date as parse_date
from .parsing import published as published
from .parsing import stamp as stamp
from .parsing import text_body as text_body
from .runtime import AppError

JW_SCHEMA_VERSION = 2


def jw_authenticated(html: str) -> bool:
    if is_login(html):
        return False
    soup = BeautifulSoup(html, "html.parser")
    if (soup.select_one("#NEW_XSD_XJCJ_WDCJ_KCCJCX")
            and soup.select_one("#NEW_XSD_KSBM_WDKS_KSAPCX")):
        return True
    raise AppError("schema_changed", "教务未返回可识别的学生主页；请检查学校页面，未保存未经验证的会话。", "jw")


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


JW_COLUMNS = {
    "grade": {
        "semester": ("开课学期", "学期"), "course_code": ("课程编号", "课程号", "课程代码"),
        "title": ("课程名称", "课程名"), "score": ("成绩", "总评成绩"),
        "score_marker": ("成绩标识",), "credits": ("学分",), "hours": ("总学时", "学时"),
        "gpa": ("绩点",), "retake_semester": ("补重学期",),
        "exam_method": ("考核方式", "考试方式"), "exam_type": ("考试性质", "考试类型"),
        "course_attribute": ("课程属性", "属性"), "course_nature": ("课程性质", "性质"),
        "category": ("通选课类别", "类别"), "group": ("分组名称",),
    },
    "exam": {
        "campus": ("校区",), "exam_campus": ("考试校区",), "exam_session": ("考试场次",),
        "course_code": ("课程编号", "课程号", "课程代码"), "title": ("课程名称", "课程名"),
        "teacher": ("授课教师", "教师"), "exam_time": ("考试时间",),
        "location": ("考场", "考试地点"), "seat_number": ("座位号",),
        "exam_id": ("准考证号", "考试编号"), "notes": ("备注",),
    },
}


def parse_jw(html: str, kind: str, semester: str = "") -> list[dict]:
    if is_login(html):
        raise AppError("login_expired", "教务登录已过期，请在本地设置页重新登录。", "jw")
    soup = BeautifulSoup(html, "html.parser")
    aliases = JW_COLUMNS[kind]
    required = ({"semester", "course_code", "title", "score", "credits", "gpa"} if kind == "grade"
                else {"course_code", "title", "exam_time", "location"})
    selected, columns, header = None, {}, None
    for table in soup.select("table"):
        for row in table.select("tr"):
            labels = [clean(cell.get_text(" ", strip=True)).replace(" ", "")
                      for cell in row.find_all(["th", "td"], recursive=False)]
            mapping = {field: next(i for i, label in enumerate(labels) if label in names)
                       for field, names in aliases.items() if any(label in names for label in labels)}
            if required.issubset(mapping):
                selected, columns, header = table, mapping, row
                break
        if selected is not None:
            break
    if selected is None:
        raise AppError("schema_changed", "教务表头缺少预期字段；未把此页面当作空结果。", "jw")
    records = []
    for row in selected.select("tr"):
        if row is header or row.find("th", recursive=False):
            continue
        cells = [clean(c.get_text(" ", strip=True)) for c in row.find_all("td", recursive=False)]
        if not cells:
            continue
        if len(cells) <= max(columns.values()):
            if re.search(r"未查询到|无数据|暂无|没有.*(?:记录|数据)|合计|总计|平均", " ".join(cells)):
                continue
            raise AppError("schema_changed", "教务记录与表头不匹配，保留原缓存。", "jw")
        record = {field: cells[index] for field, index in columns.items()}
        if not record["course_code"] or not record["title"]:
            raise AppError("schema_changed", "教务记录缺少课程编号或名称，保留原缓存。", "jw")
        record["jw_schema_version"] = JW_SCHEMA_VERSION
        if kind == "grade":
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
        else:
            record.update(id=item_id("jw", kind, semester, record["course_code"], record["exam_time"]),
                          kind=kind, semester=semester)
            records.append(record)
    return records


def jw_exam_semester(html: str) -> str:
    if is_login(html):
        raise AppError("login_expired", "教务登录已过期，请重新登录。", "jw")
    soup = BeautifulSoup(html, "html.parser")
    field = soup.select_one("select[name=xnxqid],select#xnxqid")
    if field is not None:
        options = field.select("option[value]")
        option = next((o for o in options if o.has_attr("selected")), options[0] if options else None)
        if option is not None and re.fullmatch(r"20\d{2}-20\d{2}-[123]", str(option["value"])):
            return str(option["value"])
    raise AppError("schema_changed", "教务未返回可识别的考试学期；请明确指定学期后重试。", "jw")


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
