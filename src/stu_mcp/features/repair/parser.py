"""Pure parsing/validation of bounded DOM snapshots; never performs I/O."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

from ...runtime import AppError
from .models import FormCapture, validate_fields
from .schema import LABELS, LIST_COLUMNS, LIST_URL, RAW_TO_DRAFT, REPAIR_FORM, ROOT, STATUSES


def normalize_body(body: dict[str, list[str]]) -> dict[str, list[str]]:
    return {k: [v.replace("\r\n", "\n").replace("\r", "\n") for v in values]
            for k, values in sorted(body.items())}

def parse_form(raw: dict) -> FormCapture:
    if urljoin(REPAIR_FORM, raw["action"] or "") != REPAIR_FORM or raw["method"].lower() != "post":
        raise AppError("schema_changed", "学校表单提交目标发生变化，停止提交。", "repair")
    controls = raw.get("controls", {})
    if (any(controls.get(key) != 1 for key in LABELS if key != "rbtn_list_agency") or
            controls.get("rbtn_list_agency") != 2):
        raise AppError("schema_changed", "学校表单字段缺失、重名或控件结构变化，停止提交。", "repair")
    if (raw["unknown"] or raw["attachments"] or set(raw["body"]) - LABELS.keys() or
            any(len(v) != 1 for v in raw["body"].values())):
        raise AppError("unsupported_repair_fields", "表单包含未知字段、附件或重复值，请在学校页面人工核对。", "repair")
    display = raw["display"]
    required = {"campus": "桑浦山"} | {dst: display.get(src, "") for src, dst in RAW_TO_DRAFT.items()}
    problems = validate_fields(required)
    if not required["email"]:
        problems.append({"field": "email", "reason": "required"})
    if display.get("tb_bookingtime2"):
        second = validate_fields(required | {"visit_date": display["tb_bookingtime2"],
                                            "visit_start": display.get("ddl3", ""),
                                            "visit_end": display.get("ddl4", "")})
        problems.extend({**p, "field": p["field"] + "_2"} for p in second
                        if p["field"] in {"visit_date", "visit_start", "visit_end"})
    if display.get("rbtn_list_agency") not in {"0", "1"}:
        problems.append({"field": "urgency", "reason": "choose_one"})
    entries = [{"key": key, "label": label, "value":
                {"0": "一般", "1": "紧急"}.get(display.get(key), "未选择")
                if key == "rbtn_list_agency" else display.get(key, "")}
               for key, label in LABELS.items()]
    result = {"fields": entries, "body": normalize_body(raw["body"]), "problems": problems}
    result["fingerprint"] = hashlib.sha256(json.dumps(
        {"fields": entries, "body": result["body"]}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    result["submission_fingerprint"] = hashlib.sha256(json.dumps(
        {k: v for k, v in result["body"].items() if k != "tb_happentime"},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return result

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

def school_time(value: str) -> datetime | None:
    for pattern in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(clean(value), pattern)
        except ValueError:
            continue
    return None

def on_page(url: str, path: str) -> bool:
    try:
        p = urlparse(url)
        return (p.scheme == "https" and p.hostname == "repair.stu.edu.cn" and
                not p.username and not p.password and p.port in (None, 443) and p.path == path)
    except ValueError:
        return False

def detail_link(href: str) -> tuple[str, str] | None:
    url = urljoin(LIST_URL, href)
    if not on_page(url, "/student_detail.aspx"):
        return None
    p = urlparse(url)
    query = parse_qs(p.query, keep_blank_values=True)
    ids = query.get("ApplyBill_ID", [])
    if p.fragment or set(query) != {"ApplyBill_ID"} or len(ids) != 1 or not re.fullmatch(r"[1-9]\d{0,15}", ids[0]):
        return None
    return ROOT + "student_detail.aspx?ApplyBill_ID=" + ids[0], ids[0]

def list_rows(raw: dict) -> list[dict]:
    if (raw.get("problem") or raw.get("schemaValid") is False or
            not raw.get("heading") or not raw.get("filtersClear")):
        raise ValueError("unverified list")
    rows = raw.get("rows", [])
    if not rows and raw.get("empty"):
        return []
    if not rows or len(rows) > 100:
        raise ValueError("changed list schema")
    headers = [re.sub(r"\s+", "", c["text"]) for c in rows[0]]
    if any(headers.count(name) != 1 for name in LIST_COLUMNS):
        raise ValueError("changed list schema")
    columns = {name: headers.index(name) for name in LIST_COLUMNS}
    result = []
    for cells in rows[1:]:
        if len(cells) != len(headers):
            raise ValueError("changed row schema")
        values = {name: cells[index] for name, index in columns.items()}
        title = values["报修标题"]
        if len(title["links"]) != 1:
            raise ValueError("ambiguous detail link")
        link = detail_link(title["links"][0] or "")
        order_id = clean(values["单据编号"]["text"])
        status = clean(values["处理状态"]["text"])
        timestamp = clean(values["报修时间"]["text"])
        if (not link or not re.fullmatch(r"\d{9,24}", order_id) or
                order_id != order_id[:8] + link[1] or not 0 < len(status) <= 120 or
                not school_time(timestamp) or not clean(title["text"])):
            raise ValueError("unverified order identity")
        result.append({"order_id": order_id, "detail_url": link[0], "title": clean(title["text"]),
                       "time": timestamp, "processing_status": status})
    if not result and not raw.get("empty"):
        raise ValueError("unverified empty list")
    if len({r["order_id"] for r in result}) != len(result):
        raise ValueError("duplicate order identity")
    return result

def expected_fields(capture: dict) -> dict[str, str]:
    values = {f["key"]: f["value"] for f in capture["fields"]}
    appointment = []
    for date_key, start_key, end_key in (("tb_bookingtime1", "ddl_time1", "DropDownList1"),
                                         ("tb_bookingtime2", "ddl3", "ddl4")):
        if values.get(date_key):
            appointment.append(f'{values[date_key]}日-{values[start_key]}~{values[end_key]}')
    keys = {"tb_name", "ddl_department_name", "tb_stu_no", "ddl_sex", "tb_tel", "tb_address",
            "tb_mobil", "tb_email", "tb_title", "tb_happenarea", "tb_happentime",
            "tb_Repair_device_name", "tb_Repair_device_no", "Detail", "ddl_floor", "rbtn_list_agency"}
    if not keys <= values.keys() or not appointment:
        raise ValueError("incomplete reviewed capture")
    return {k: values[k] for k in keys} | {"appointment": "或".join(appointment)}

def match_detail(raw: dict, capture: dict, row: dict) -> dict | None:
    """Prove initial creation using every reviewed business field."""
    if raw.get("problem") or raw.get("orders") != [row["order_id"]]:
        return None
    fields = raw.get("fields", {})
    expected = expected_fields(capture)
    for key, wanted in expected.items():
        values = fields.get(key, [])
        if len(values) != 1:
            return None
        actual = clean(values[0])
        if key == "tb_happentime":
            if not school_time(wanted) or school_time(actual) != school_time(wanted):
                return None
        elif key == "appointment":
            if re.sub(r"\s+", "", actual) != re.sub(r"\s+", "", wanted):
                return None
        elif actual != clean(wanted) and not (not wanted and actual == "未知"):
            return None
    status = fields.get("processing_status", [])
    if len(status) != 1 or clean(status[0]) not in STATUSES:
        return None
    return {"order_id": row["order_id"], "detail_url": row["detail_url"],
            "processing_status": clean(status[0]), "checked_at": time.time(),
            "evidence": "new_list_row_and_matching_detail"}


def refresh_detail(raw: dict, receipt: dict) -> dict | None:
    """Refresh an already proven order; school-side edits are legitimate changes.

    Unknown status text is returned verbatim, without guessing its meaning.
    Identity and a unique status are still required. The original creation proof
    remains valid; an unavailable refresh must not erase it.
    """
    link = detail_link(receipt["detail_url"])
    if (not link or receipt["detail_url"] != link[0] or
            receipt["order_id"] != receipt["order_id"][:8] + link[1] or
            raw.get("problem") or raw.get("orders") != [receipt["order_id"]]):
        return None
    status = raw.get("fields", {}).get("processing_status", [])
    if len(status) != 1 or not 0 < len(clean(status[0])) <= 120:
        return None
    return {**receipt, "processing_status": clean(status[0]), "checked_at": time.time()}
