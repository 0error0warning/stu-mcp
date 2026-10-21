"""Pure HTML snapshots for the existing school form/list/detail validators."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ...runtime import AppError
from .parser import parse_form
from .schema import BUSINESS_FIELDS, POSTBACK_FIELDS, REPAIR_FORM, SYSTEM_FIELDS

DETAIL_LABELS = {"报修人姓名:": "tb_name", "所属单位:": "ddl_department_name", "学号:": "tb_stu_no",
                 "性别:": "ddl_sex", "电话:": "tb_tel", "住址:": "tb_address", "手机:": "tb_mobil",
                 "E-MAIL:": "tb_email", "报修标题:": "tb_title", "发生地址:": "tb_happenarea",
                 "发生时间:": "tb_happentime", "故障设备名称:": "tb_Repair_device_name",
                 "资产编号:": "tb_Repair_device_no", "详细描述:": "Detail", "我想预约时间:": "appointment",
                 "处理状态:": "processing_status"}


def changed() -> AppError:
    return AppError("schema_changed", "学校报修页面结构变化，已停止操作。", "repair")


def document(markup: str) -> BeautifulSoup:
    if len(markup) > 2_000_000:
        raise changed()
    soup = BeautifulSoup(markup, "html.parser")
    if soup.select('input[type="password"]'):
        raise AppError("repair_login_required", "报修登录已失效，请重新登录 repair。", "repair")
    if any(re.search(r"应用程序中的服务器错误|Server Error in .*Application", node.get_text(), re.I)
           for node in soup.select("h1,h2")):
        raise AppError("repair_source_error", "学校报修服务返回错误，未继续操作。", "repair")
    return soup


def selected(node: Tag) -> list[Tag]:
    options = node.find_all("option")
    values = [option for option in options if option.has_attr("selected")]
    return values or ([] if node.has_attr("multiple") else options[:1])


def disabled(node: Tag) -> bool:
    """HTML disabled inheritance, including the first-legend exception."""
    if node.has_attr("disabled"):
        return True
    if node.name == "option" and any(parent.name == "optgroup" and parent.has_attr("disabled")
                                      for parent in node.parents):
        return True
    ancestors = list(node.parents)
    for parent in ancestors:
        if parent.name == "fieldset" and parent.has_attr("disabled"):
            legend = parent.find("legend", recursive=False)
            if legend is None or not any(ancestor is legend for ancestor in ancestors):
                return True
    return False


def form_document(markup: str) -> Tag:
    soup = document(markup)
    forms = soup.find_all("form")
    if len(forms) != 1:
        raise changed()
    form = forms[0]
    if (urljoin(REPAIR_FORM, str(form.get("action", ""))) != REPAIR_FORM
            or str(form.get("method", "get")).lower() != "post"):
        raise changed()
    return form


def control(form: Tag, name: str) -> Tag:
    nodes = form.find_all(["input", "select", "textarea"], attrs={"name": name})
    if len(nodes) != 1 or disabled(nodes[0]):
        raise changed()
    return nodes[0]


def set_value(form: Tag, name: str, value: str, *, label: bool = False) -> None:
    node = control(form, name)
    if node.has_attr("readonly") and name != "tb_bookingtime1":
        raise changed()
    if node.name == "select":
        matches = [option for option in node.find_all("option")
                   if (option.get_text().strip() if label else str(option.get("value", option.get_text()))) == value
                   and not disabled(option)]
        if len(matches) != 1:
            raise AppError("repair_option_missing", "学校下拉选项没有唯一匹配，已停止填写。", "repair")
        for option in node.find_all("option"):
            option.attrs.pop("selected", None)
        matches[0]["selected"] = "selected"
    elif node.name == "textarea":
        node.string = value
    elif str(node.get("type", "text")).lower() not in {"hidden", "file", "password", "radio", "checkbox"}:
        # A readonly date is serialized by the official form. This changes only
        # the local draft value; the readonly control attribute remains intact.
        node["value"] = value
    else:
        raise changed()


def values(node: Tag) -> list[str]:
    if node.name == "select":
        return [str(option.get("value", option.get_text())) for option in selected(node) if not disabled(option)]
    if node.name == "textarea":
        return [node.get_text().replace("\r\n", "\n").replace("\r", "\n")]
    return [str(node.get("value", "on" if node.get("type") in {"radio", "checkbox"} else ""))]


def snapshot(form: Tag) -> dict:
    body, display, controls, unknown = {}, {}, {}, []
    attachments = False
    for node in form.find_all(["input", "textarea", "select", "button"]):
        name = str(node.get("name", ""))
        kind = str(node.get("type", "text")).lower()
        if name in POSTBACK_FIELDS:
            controls[name] = controls.get(name, 0) + 1
        # Never manufacture a business payload that a normal HTML form could
        # not send. School-generated disabled timestamp is display-only.
        if name in BUSINESS_FIELDS - {"tb_happentime"} and (disabled(node) or
                node.name == "select" and any(disabled(option) for option in selected(node))):
            raise changed()
        if kind == "file":
            attachments |= bool(node.get("value"))
            continue
        if name == "tb_happentime":
            display[name] = values(node)[0]
            if not disabled(node):
                body.setdefault(name, []).extend(values(node))
            continue
        if (not name or disabled(node) or node.name == "button"
                or kind in {"button", "submit", "reset"}):
            continue
        if name not in POSTBACK_FIELDS:
            unknown.append(name)
            continue
        if name in SYSTEM_FIELDS or kind in {"radio", "checkbox"} and not node.has_attr("checked"):
            continue
        body.setdefault(name, []).extend(values(node))
        display[name] = ("、".join(option.get_text().strip() for option in selected(node))
                         if node.name == "select" else values(node)[0])
    return {"action": str(form.get("action", "")), "method": str(form.get("method", "get")),
            "body": body, "display": display, "controls": controls, "unknown": unknown,
            "attachments": attachments}


def capture(form: Tag) -> dict:
    return parse_form(snapshot(form))


def payload(form: Tag, event: str) -> dict[str, list[str]]:
    raw = snapshot(form)
    parse_form(raw)  # Full schema validation precedes sending hidden state/PII.
    result = {key: list(value) for key, value in raw["body"].items()}
    for node in form.find_all(["input", "textarea", "select"]):
        name = str(node.get("name", ""))
        if name not in SYSTEM_FIELDS or disabled(node):
            continue
        if name in result:
            raise changed()
        result[name] = values(node)
    if not result.get("__VIEWSTATE") or len(result["__VIEWSTATE"]) != 1:
        raise changed()
    result["__EVENTTARGET"], result["__EVENTARGUMENT"] = [event], [""]
    return result


def list_snapshot(markup: str) -> dict:
    soup = document(markup)
    ids = ("tb_AppBill_ID", "tb_AppBill_Title", "tb_Appbill_from_Date", "tb_Appbill_to_Date")
    clear = True
    for key in ids:
        nodes = soup.select("#" + key)
        clear &= len(nodes) == 1 and nodes[0].name == "input" and not nodes[0].get("value", "")
    status = soup.select("#ddl_Appbill_Status")
    clear &= (len(status) == 1 and status[0].name == "select" and len(selected(status[0])) == 1
              and selected(status[0])[0].get_text().strip() == "全部")
    grids = soup.select("#DataGrid1")
    empty = any(not node.find(["table", "input", "select"]) and not node.find_parent(id="DataGrid1")
                and node.get("id") != "DataGrid1" and re.fullmatch(r"没有任何数据[!！]?", node.get_text().strip())
                for node in soup.find_all(["span", "p", "td", "div"]))
    rows = []
    if len(grids) == 1 and grids[0].name == "table":
        for row in grids[0].find_all("tr")[:101]:
            rows.append([{"text": cell.get_text(" ", strip=True),
                          "links": [link.get("href") for link in cell.find_all("a")]}
                         for cell in row.find_all(["td", "th"], recursive=False)])
    return {"problem": None, "schemaValid": len(grids) <= 1 and all(g.name == "table" for g in grids),
            "heading": "我的报修单据列表" in soup.get_text(), "filtersClear": bool(clear), "empty": empty, "rows": rows}


def detail_snapshot(markup: str) -> dict:
    soup = document(markup)
    fields, orders = {}, []
    for row in soup.select("table tr"):
        cells = row.find_all(["td", "th"], recursive=False)
        if any(cell.find("table") for cell in cells):
            continue
        if len(cells) == 1:
            match = re.fullmatch(r"报修单\s*[(（]\s*(\d+)\s*[)）]", cells[0].get_text().strip())
            if match:
                orders.append(match[1])
        index = 0
        while index < len(cells):
            source = cells[index].get_text(" ", strip=True)
            parts = re.split("[:：]", source, maxsplit=1)
            key = DETAIL_LABELS.get(re.sub(r"\s", "", parts[0]) + ":") if len(parts) == 2 else None
            if key:
                value = parts[1].strip()
                if not value and index + 1 < len(cells):
                    index += 1
                    value = cells[index].get_text(" ", strip=True)
                fields.setdefault(key, []).append(value)
            index += 1
    floors = soup.select("#ddl_floor")
    if len(floors) == 1 and floors[0].name == "select" and len(selected(floors[0])) == 1:
        fields["ddl_floor"] = [selected(floors[0])[0].get_text().strip()]
    common, urgent = soup.select("#chk_agency_common"), soup.select("#chk_agency_urgency")
    if len(common) == len(urgent) == 1 and common[0].has_attr("checked") != urgent[0].has_attr("checked"):
        fields["rbtn_list_agency"] = ["紧急" if urgent[0].has_attr("checked") else "一般"]
    return {"problem": None, "orders": orders, "fields": fields}
