"""Pure parsers adapted from the pinned School Hub source; never read credentials."""
from __future__ import annotations

import math
import re

from bs4 import BeautifulSoup

from .features.mystu.parser import current_courses as current_courses
from .features.mystu.parser import parse_assignment as parse_assignment
from .features.mystu.parser import parse_elc as parse_elc
from .features.mystu.parser import payload_records as payload_records
from .features.notices.parser import parse_links as parse_links
from .features.notices.parser import parse_oa as parse_oa
from .features.notices.parser import parse_oa_article as parse_oa_article
from .features.notices.parser import parse_public as parse_public
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
