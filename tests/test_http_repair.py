"""Synthetic WebForms only; no real login, form write or school submission."""
from __future__ import annotations

import copy
import threading
from datetime import timedelta
from html import escape
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from stu_mcp.auth_http.transport import HTTPFlow
from stu_mcp.features.repair import http_parser as html
from stu_mcp.features.repair.http_adapter import HttpRepairSession, open_http, verify_login
from stu_mcp.features.repair.models import campus_today
from stu_mcp.features.repair.parser import list_rows
from stu_mcp.features.repair.schema import LABELS, REPAIR_FORM
from stu_mcp.features.repair.service import RepairService
from stu_mcp.runtime import AppError


class School:
    def __init__(self, mode="success"):
        self.mode, self.version, self.created, self.posts = mode, 0, False, []
        self.status = "等待处理"
        self.day = (campus_today() + timedelta(days=1)).isoformat()
        self.stamp = campus_today().strftime("%Y/%m/%d") + " 12:00:00"
        self.order = campus_today().strftime("%Y%m%d") + "900001"
        self.data = {key: "" for key in LABELS}
        self.data.update(tb_name="合成同学", tb_stu_no="SYNTHETIC-STUDENT", tb_tel="13800000000",
                         tb_email="synthetic@stu.edu.cn", tb_happentime=self.stamp, ddl_sex="男",
                         ddl_department_name="工学院", ddl_floor="桑浦山校区学生宿舍C栋",
                         tb_title="合成故障", tb_happenarea="合成房间", Detail="合成故障",
                         tb_bookingtime1=self.day, ddl_time1="14:00", DropDownList1="17:00",
                         ddl3="8:00", ddl4="8:00", rbtn_list_agency="0")

    @property
    def fields(self):
        return {"campus": "桑浦山", "name": "合成同学", "college": "工学院",
                "building": "桑浦山校区学生宿舍C栋", "location": "合成房间", "phone": "13800000000",
                "title": "合成故障", "description": "合成故障", "visit_date": self.day,
                "visit_start": "14:00", "visit_end": "17:00"}

    def form(self):
        selects = {"ddl_department_name": ["工学院"], "ddl_floor": [self.data["ddl_floor"]],
                   "ddl_sex": ["男"], **{key: [f"{n}:00" for n in range(8, 19)]
                                        for key in ("ddl_time1", "DropDownList1", "ddl3", "ddl4")}}
        parts = []
        for key in LABELS:
            if key == "rbtn_list_agency":
                parts.extend(f'<input type="radio" name="{key}" value="{n}" {"checked" if self.data[key] == n else ""}>'
                             for n in ("0", "1"))
            elif key in selects:
                onchange = f' onchange="__doPostBack(\'{key}\',\'\')"' if key in {"ddl_time1", "DropDownList1"} else ""
                options = ''.join(f'<option value="v{self.version}-{index}" {"selected" if label == self.data[key] else ""}>'
                                  f'{escape(label)}</option>' for index, label in enumerate(selects[key]))
                parts.append(f'<select id="{key}" name="{key}"{onchange}>{options}</select>')
            elif key == "Detail":
                parts.append(f'<textarea name="Detail">{escape(self.data[key])}</textarea>')
            else:
                flags = " disabled" if key == "tb_happentime" else " readonly" if key.startswith("tb_booking") else ""
                parts.append(f'<input id="{key}" name="{key}" value="{escape(self.data[key], quote=True)}"{flags}>')
        parts += [f'<input type="hidden" name="{key}" value="{value}">' for key, value in (
            ("__VIEWSTATE", f"VS{self.version}"), ("__EVENTVALIDATION", f"EV{self.version}"),
            ("__EVENTTARGET", ""), ("__EVENTARGUMENT", ""))]
        return '<form action="student_applybill.aspx" method="post">' + ''.join(parts) + '</form>'

    def listing(self):
        filters = ''.join(f'<input id="{key}" value="">' for key in (
            "tb_AppBill_ID", "tb_AppBill_Title", "tb_Appbill_from_Date", "tb_Appbill_to_Date"))
        result = '<h1>我的报修单据列表</h1>' + filters + '<select id="ddl_Appbill_Status"><option>全部</option></select>'
        if not self.created:
            return result + '<p>没有任何数据!</p>'
        return result + ('<table id="DataGrid1"><tr><th>单据编号</th><th>报修标题</th><th>报修时间</th>'
                         '<th>处理状态</th><th>操作</th></tr><tr><td>' + self.order + '</td><td>'
                         '<a href="student_detail.aspx?ApplyBill_ID=900001">合成故障</a></td><td>' +
                         self.stamp + '</td><td>' + self.status + '</td><td></td></tr></table>')

    def detail(self):
        source = {key: self.data[value] for key, value in html.DETAIL_LABELS.items()
                  if value not in {"appointment", "processing_status"}}
        source.update({"我想预约时间:": f'{self.day}日-14:00~17:00', "处理状态:": self.status})
        rows = ''.join(f'<tr><td>{key}</td><td>{escape(value)}</td></tr>' for key, value in source.items())
        if self.mode == "wrong_detail":
            rows = rows.replace("合成房间", "不符的房间")
        return (f'<table><tr><td>报修单({self.order})</td></tr>{rows}</table>'
                f'<select id="ddl_floor" disabled><option selected>{self.data["ddl_floor"]}</option></select>'
                '<input id="chk_agency_common" type="checkbox" checked disabled>'
                '<input id="chk_agency_urgency" type="checkbox" disabled>')

    def handle(self, request):
        assert request.url.host == "repair.stu.edu.cn" and request.url.scheme == "https"
        if request.method == "GET":
            if request.url.path == "/student.aspx":
                return httpx.Response(200, text=self.listing())
            if request.url.path == "/student_detail.aspx":
                return httpx.Response(200, text=self.detail())
            assert str(request.url) == REPAIR_FORM
            return httpx.Response(200, text=self.form())
        assert request.method == "POST" and str(request.url) == REPAIR_FORM
        data = parse_qs(request.content.decode(), keep_blank_values=True)
        self.posts.append(data)
        assert data["__VIEWSTATE"] == [f"VS{self.version}"]
        assert data["__EVENTVALIDATION"] == [f"EV{self.version}"]
        assert len(data["__EVENTTARGET"]) == 1
        event = data["__EVENTTARGET"][0]
        if event == "btn_OK":
            self.created = self.mode not in {"not_created", "redirect"}
            if self.mode == "lost_response":
                raise httpx.ReadError("synthetic_private_response_lost", request=request)
            return httpx.Response(307 if self.mode == "redirect" else 302,
                                  headers={"Location": "https://r.stu.edu.cn/should-never-follow"})
        assert event in {"ddl_time1", "DropDownList1"}
        # Real WebForms keeps posted business values while hidden fields and
        # dropdown values can rotate. A server reset must remain observable.
        for key, posted in data.items():
            if key in self.data and key not in {"ddl_department_name", "ddl_floor", "ddl_sex", "ddl_time1",
                                                "DropDownList1", "ddl3", "ddl4"}:
                self.data[key] = posted[0]
        if self.mode == "server_reset":
            self.data["tb_tel"] = ""
        self.version += 1
        return httpx.Response(200, text=self.form())


@pytest.fixture
def school():
    return School()


def session(school):
    flow = HTTPFlow("repair", ("repair.stu.edu.cn",), transport=httpx.MockTransport(school.handle))
    return HttpRepairSession(flow, threading.Event())


def test_http_form_dynamic_hidden_state_and_dropdown_values(school):
    school.data.update(tb_name="原名", tb_title="旧标题", Detail="旧描述")
    current = session(school)
    try:
        result = current.open(school.fields)
        assert all(result["matches"].values()) and not result["missing_page_fields"]
        assert [post["__EVENTTARGET"] for post in school.posts] == [["DropDownList1"], ["ddl_time1"]]
        assert school.posts[1]["__VIEWSTATE"] == ["VS1"]
        assert school.posts[0]["ddl_time1"] != school.posts[1]["ddl_time1"]
        captured = current.capture()
        assert not captured["problems"] and "__VIEWSTATE" not in captured["body"]
        assert html.control(current.form, "tb_bookingtime1").has_attr("readonly")
    finally:
        current.flow.client.close()


@pytest.mark.parametrize("mode,expected", [("success", "submitted"), ("lost_response", "submitted"),
                                           ("not_created", "submission_unknown"), ("wrong_detail", "submission_unknown"),
                                           ("redirect", "submission_unknown")])
def test_http_single_submit_and_readonly_recovery(mode, expected):
    school = School(mode)
    current = session(school)
    try:
        current.open(school.fields)
        captured = current.capture()
        current.prepare_receipt()
        result = current.submit(captured)
        assert result["status"] == expected and current.request_sent
        assert sum(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts) == 1
        current.submit(captured)
        current.check()
        assert sum(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts) == 1
        if expected == "submitted":
            assert result["receipt"]["order_id"] == school.order
            school.status = "已派人维修"
            assert current.check()["receipt"]["processing_status"] == "已派人维修"
    finally:
        current.flow.client.close()


def test_http_review_change_and_missing_baseline_cannot_send(school):
    current = session(school)
    try:
        current.open(school.fields)
        captured = current.capture()
        assert current.submit(captured)["status"] == "submission_not_sent"
        current.prepare_receipt()
        html.set_value(current.form, "tb_tel", "13900000000")
        with pytest.raises(AppError) as error:
            current.submit(captured)
        assert error.value.code == "repair_form_changed" and not current.request_sent
        assert not any(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts)
    finally:
        current.flow.client.close()


def test_http_auth_proof_accepts_only_actual_unfiltered_list(school):
    with HTTPFlow("repair", ("repair.stu.edu.cn",), transport=httpx.MockTransport(school.handle)) as flow:
        assert verify_login(flow) == {"authenticated": True, "list_verified": True, "orders": 0}
    forged = school.listing().replace('<input id="tb_AppBill_ID" value="">', '<span id="tb_AppBill_ID"></span>')
    with pytest.raises(ValueError):
        list_rows(html.list_snapshot(forged))


def test_http_server_validation_reset_is_not_hidden_by_reapplying_draft():
    school = School("server_reset")
    current = session(school)
    try:
        result = current.open(school.fields)
        assert result["matches"]["phone"] is False
        assert "phone" in result["missing_page_fields"]
        assert not current.request_sent
    finally:
        current.flow.client.close()


def test_http_textarea_serializes_like_html_forms_and_readback_normalizes_crlf(school):
    school.data["Detail"] = "合成第一行\n合成第二行"
    fields = school.fields | {"description": school.data["Detail"]}
    current = session(school)
    try:
        assert current.open(fields)["matches"]["description"]
        assert school.posts[0]["Detail"] == ["合成第一行\r\n合成第二行"]
        assert dict((item["key"], item["value"]) for item in current.capture()["fields"])["Detail"] == fields["description"]
    finally:
        current.flow.client.close()


def test_http_unsupported_forms_stop_before_post(school):
    for mutation in (lambda value: value.replace('action="student_applybill.aspx"', 'action="https://r.stu.edu.cn/"'),
                     lambda value: value.replace('</form>', '<input name="unknown" value="private"></form>'),
                     lambda value: value.replace('</form>', '<input name="tb_tel" value="private"></form>')):
        with pytest.raises(AppError):
            html.capture(html.form_document(mutation(school.form())))


def test_http_logout_revision_invalidates_ram_review_before_submission(tmp_path, school):
    class Vault:
        runtime = SimpleNamespace(home=tmp_path)
        revision = b"synthetic-before"
        def login_revision(self, _service):
            return self.revision
        def load(self, _service):
            return {"cookies": [], "origins": []}
    vault = Vault()
    with open_http(threading.Event(), lambda **_: None, vault=vault, transport=httpx.MockTransport(school.handle)) as current:
        current.open(school.fields)
        captured = current.capture()
        current.prepare_receipt()
        vault.revision = b"synthetic-logout"
        with pytest.raises(AppError) as error:
            current.submit(captured)
        assert error.value.code == "session_changed" and not current.request_sent
        assert not any(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts)


def test_http_service_requires_confirmed_review_and_deduplicates(school):
    current = session(school)
    try:
        current.open(school.fields)
        service = RepairService(lambda *_: None)
        draft_id = service.prepare(**school.fields)["draft_id"]
        with pytest.raises(AppError) as error:
            service.submit(draft_id, "not-a-review")
        assert error.value.code == "repair_confirmation_required"
        assert not current.request_sent
        raw = copy.deepcopy(current.capture())
        current.prepare_receipt()
        current.submit(raw)
        assert current.submit(raw)["status"] == "submitted"
        assert len([post for post in school.posts if post["__EVENTTARGET"] == ["btn_OK"]]) == 1
    finally:
        current.flow.client.close()
