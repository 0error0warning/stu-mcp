"""Synthetic repair data only; never log in or create a school work order."""
import io
import json
import os
import subprocess
import sys
import threading
from datetime import date, timedelta
from html import escape
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlencode

import pytest

from stu_mcp.cli import main
from stu_mcp.repair import (
    REPAIR_FORM,
    RepairDrafts,
    campus_today,
    field_plan,
    fill_form,
    read_form,
    request_allowed,
    select_calendar,
    validate_fields,
)
from stu_mcp.runtime import AppError


@pytest.fixture
def fields():
    return {"campus": "桑浦山", "name": "合成同学", "college": "工学院",
            "building": "桑浦山校区学生宿舍C栋", "location": "合成测试位置",
            "phone": "13800000000", "title": "合成空调故障", "device": "空调",
            "description": "空调外机不转。",
            "visit_date": (campus_today() + timedelta(days=1)).isoformat(),
            "visit_start": "14:00", "visit_end": "17:00"}


def test_incomplete_draft_is_offline_and_never_opens_login(monkeypatch):
    drafts = RepairDrafts()
    run = Mock(side_effect=AssertionError("incomplete drafts must not launch a browser"))
    monkeypatch.setattr(drafts, "_run", run)
    result = drafts.prepare(title="空调外机不转", building="B999")
    result = drafts.open(result["draft_id"])
    assert result["status"] == "needs_information"
    assert {p["field"] for p in result["problems"]} >= {"name", "phone", "building", "visit_date"}
    assert "桑浦山校区学生宿舍B栋" in result["building_options"]
    assert "修远书院B楼" in result["building_options"]
    run.assert_not_called()


def test_draft_update_snapshot_is_masked_and_copied(fields):
    drafts = RepairDrafts()
    first = drafts.prepare(title=fields["title"])
    result = drafts.prepare(first["draft_id"], **fields)
    assert result["status"] == "draft_ready" and result["problems"] == []
    assert fields["phone"] not in json.dumps(result)
    assert result["preview"]["phone"] == "138****0000"
    assert result["submitted_by_mcp"] is False and result["submission_supported"] is True
    assert result["confirmation_required"] is True
    result["preview"]["name"] = "MUTATED"
    assert drafts.snapshot(first["draft_id"])["preview"]["name"] == "合成同学"
    assert RepairDrafts().drafts == {}


@pytest.mark.parametrize("update,bad", [
    ({"visit_date": "2020-01-01"}, "visit_date"),
    ({"visit_date": "2026-02-30"}, "visit_date"),
    ({"visit_date": "明天下午"}, "visit_date"),
    ({"visit_start": "14:30"}, "visit_start"),
    ({"visit_end": "14:00"}, "visit_end"),
    ({"visit_end": "19:00"}, "visit_end"),
    ({"building": "B栋"}, "building"),
    ({"email": "invalid"}, "email"),
    ({"phone": "not-a-phone"}, "phone"),
    ({"description": "长" * 801}, "description"),
])
def test_validates_user_business_fields_without_guessing(fields, update, bad):
    assert any(p["field"] == bad for p in validate_fields(fields | update))


def test_other_campus_and_unknown_fields_do_not_reuse_dorm_adapter(fields):
    with pytest.raises(AppError, match="其他校区"):
        RepairDrafts().prepare(**(fields | {"campus": "东海岸"}))
    for key in ("password", "cookies", "ticket", "url", "submit"):
        with pytest.raises(AppError):
            RepairDrafts().prepare(**(fields | {key: "SYNTHETIC"}))


@pytest.mark.parametrize("url,method,allowed", [
    (REPAIR_FORM, "GET", True),
    (REPAIR_FORM, "POST", False),
    (REPAIR_FORM, "PUT", False),
    ("https://repair.stu.edu.cn/student.aspx", "POST", False),
    ("https://sso.stu.edu.cn/login", "POST", True),
    ("http://sso.stu.edu.cn/login", "POST", False),
    ("https://repair.stu.edu.cn.evil.example/", "GET", False),
    ("https://r.stu.edu.cn/", "GET", False),
    ("https://user:secret@repair.stu.edu.cn/", "GET", False),
    ("https://repair.stu.edu.cn:6443/", "GET", False),
    ("https://repair.stu.edu.cn:bad/", "GET", False),
])
def test_preview_transport_blocks_business_submission_and_wrong_systems(url, method, allowed):
    assert request_allowed(url, method) is allowed


def test_only_observed_time_postbacks_pass_never_real_submit_or_extra_controls():
    time_body = {"__EVENTTARGET": "DropDownList1", "__EVENTARGUMENT": "", "__VIEWSTATE": "SYNTHETIC",
                 "tb_name": "合成同学", "ddl_time1": "1", "DropDownList1": "10"}
    assert request_allowed(REPAIR_FORM, "POST", urlencode(time_body))
    assert request_allowed(REPAIR_FORM, "POST", urlencode(time_body | {"__EVENTTARGET": "ddl_time1"}))
    for changed in ({"__EVENTTARGET": "btn_OK"}, {"__EVENTTARGET": "Button2"}, {"btn_OK": "提交报修单"},
                    {"submit": "1"}, {"__EVENTARGUMENT": "btn_OK"}, {"__EVENTTARGET": "ddl3"}):
        assert not request_allowed(REPAIR_FORM, "POST", urlencode(time_body | changed))
    assert not request_allowed(REPAIR_FORM, "POST", urlencode(time_body) + "&__EVENTTARGET=btn_OK")
    assert not request_allowed(REPAIR_FORM + "?submit=1", "POST", urlencode(time_body))
    assert not request_allowed(REPAIR_FORM, "POST", "x=" + "a" * 262144)


def test_plan_orders_end_before_start_and_has_no_submit_or_account_mutations(fields):
    plan = field_plan(fields)
    keys = [p["field"] for p in plan]
    assert keys.index("visit_end") < keys.index("visit_start")
    assert not {"#btn_OK", "#Button1", "#Button2", "#tb_stu_no", "#ddl_sex"} & {p["selector"] for p in plan}
    assert {p["action"] for p in plan} <= {"fill", "select_label", "calendar"}


class FormPage:
    """Small DOM fixture implementing the locator methods used by the adapter."""
    def __init__(self, fields):
        self.url = REPAIR_FORM
        self.events = []
        self.values = {p["selector"]: "" for p in field_plan(fields)} | {"#tb_email": "synthetic@stu.edu.cn"}
        self.options = {p["selector"]: [p["value"]] for p in field_plan(fields) if p["action"] == "select_label"}
        self.missing = set()
        self.main_frame = object()
        self.frames = [self.main_frame]

    def locator(self, selector):
        return FormLocator(self, selector)


class FormLocator:
    def __init__(self, page, selector, sub=""):
        self.page, self.selector, self.sub = page, selector, sub

    def count(self):
        return 0 if self.selector in self.page.missing else 1

    def is_visible(self):
        return True

    def locator(self, selector):
        return FormLocator(self.page, self.selector, selector)

    def all_text_contents(self):
        return self.page.options.get(self.selector, [])

    def fill(self, value):
        self.page.events.append(("fill", self.selector))
        self.page.values[self.selector] = value

    def select_option(self, *, label):
        self.page.events.append(("select", self.selector))
        self.page.values[self.selector] = label

    def click(self):
        self.page.events.append(("click", self.selector))

    def input_value(self):
        return self.page.values[self.selector]

    def inner_text(self):
        return self.input_value()

    def get_attribute(self, name):
        return None


def test_adapter_roundtrip_preserves_school_email_and_detects_user_changes(fields, monkeypatch):
    page = FormPage(fields)
    monkeypatch.setattr("stu_mcp.features.repair.adapter.select_calendar", lambda p, d: p.values.update({"#tb_bookingtime1": d}))
    result = fill_form(page, fields)
    assert all(result["matches"].values()) and not result["missing_page_fields"]
    assert page.values["#tb_email"] == "synthetic@stu.edu.cn"
    assert not any(selector == "#btn_OK" for _, selector in page.events)
    page.values["#tb_tel"] = "CHANGED"
    assert read_form(page, field_plan(fields))["matches"]["phone"] is False
    page.values["#tb_email"] = ""
    assert "email" in read_form(page, field_plan(fields))["missing_page_fields"]


def test_schema_or_option_change_stops_before_pii_entry(fields):
    for broken in ("schema", "option", "duplicate"):
        page = FormPage(fields)
        if broken == "schema":
            page.missing.add("#Detail")
        elif broken == "option":
            page.options["#ddl_floor"] = ["OTHER_BUILDING"]
        else:
            page.options["#ddl_floor"] *= 2
        with pytest.raises(AppError):
            fill_form(page, fields)
        assert not page.events
    page.url = "https://r.stu.edu.cn/WorkOrder.do?woMode=newWO"
    with pytest.raises(AppError):
        fill_form(page, fields)


def test_calendar_outside_visible_months_keeps_readonly_field_for_user(fields):
    page = FormPage(fields)
    assert select_calendar(page, fields["visit_date"]) is False
    assert page.values["#tb_bookingtime1"] == ""
    assert page.events == [("click", "#tb_bookingtime1"), ("click", "#tb_title")]


def test_open_is_idempotent_and_cancel_is_owned_and_nonblocking(fields, monkeypatch):
    drafts = RepairDrafts()
    entered = threading.Event()
    def run(draft_id, values, stop):
        entered.set()
        stop.wait(5)
        drafts._update(draft_id, status="closed")
    monkeypatch.setattr(drafts, "_run", run)
    one = drafts.prepare(**fields)["draft_id"]
    two = drafts.prepare(**fields)["draft_id"]
    try:
        drafts.open(one)
        assert entered.wait(1)
        thread = drafts.threads[one]
        drafts.open(one)
        assert drafts.threads[one] is thread
        with pytest.raises(AppError):
            drafts.open(two)
        with pytest.raises(AppError):
            drafts.prepare(one, title="changed while browser open")
        assert drafts.close(one)["status"] == "closing"
        thread.join(1)
        assert drafts.snapshot(one)["status"] == "closed"
        assert drafts.prepare(one, title="changed after close")["preview"]["title"] == "changed after close"
    finally:
        drafts.shutdown()


def test_readback_status_never_means_submitted(fields):
    drafts = RepairDrafts()
    draft_id = drafts.prepare(**fields)["draft_id"]
    for matches, missing, expected in (({"phone": True}, [], "filled_unsubmitted"),
                                       ({"phone": False}, [], "form_changed"),
                                       ({"visit_date": False}, ["visit_date"], "needs_manual_fields")):
        drafts._record_readback(draft_id, {"matches": matches, "missing_page_fields": missing})
        result = drafts.snapshot(draft_id)
        assert result["status"] == expected and result["checked_at"]
        assert result["submitted_by_mcp"] is False


def test_closed_drafts_are_evicted_at_bounded_capacity():
    drafts = RepairDrafts()
    oldest = drafts.prepare()["draft_id"]
    for _ in range(19):
        drafts.prepare()
    with pytest.raises(AppError):
        drafts.prepare()
    drafts.close(oldest)
    drafts.prepare()
    assert len(drafts.drafts) == 20 and oldest not in drafts.drafts


def test_cli_plan_uses_stdin_without_persistent_data(fields, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("STU_MCP_HOME", str(tmp_path / "no-data"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(fields)))
    assert main(["repair", "plan"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "draft_ready"
    assert fields["phone"] not in json.dumps(result)
    assert not (tmp_path / "no-data").exists()


def test_cli_reads_utf8_even_when_windows_default_pipe_encoding_differs(fields, tmp_path):
    completed = subprocess.run([sys.executable, "-m", "stu_mcp", "repair", "plan"],
                               input=json.dumps(fields, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, timeout=20,
                               env={**os.environ, "PYTHONIOENCODING": "cp1252",
                                    "STU_MCP_HOME": str(tmp_path / "unused")})
    assert completed.returncode == 0
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["preview"]["name"] == "合成同学" and result["status"] == "draft_ready"
    assert not (tmp_path / "unused").exists()


def test_fixed_reference_date_is_not_runtime_date(fields):
    assert validate_fields(fields | {"visit_date": "2026-10-19"}, today=date(2026, 10, 20))


def test_real_browser_synthetic_form_readback_and_blocked_submit(fields):
    """Exercise Playwright itself against fulfilled synthetic HTML, never STU."""
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    y, m, d = map(int, fields["visit_date"].split("-"))
    calendar = (f'<table><tr><td onclick="day_Click({y},{m},{d});">{d}</td></tr></table>'
                '<input id="dpOkInput" type="button" value="确定">'
                '<script>function day_Click(y,m,d){parent.document.getElementById("tb_bookingtime1").value='
                '`${y}-${String(m).padStart(2,"0")}-${String(d).padStart(2,"0")}`;}</script>')
    controls = ''.join(f'<input id="{s}" name="{s}" value="">' for s in (
        "tb_name", "tb_tel", "tb_title", "tb_happenarea", "tb_Repair_device_name"))
    controls += ('<input id="tb_email" name="tb_email" value="synthetic@stu.edu.cn">'
                 '<textarea id="Detail" name="Detail"></textarea>')
    controls += '<input readonly id="tb_bookingtime1" name="tb_bookingtime1">'
    controls += '<input type="hidden" id="__EVENTTARGET" name="__EVENTTARGET" value="">'
    controls += '<input type="hidden" name="__EVENTARGUMENT" value="">'
    for selector, options in (
        ("ddl_department_name", ["", "工学院"]),
        ("ddl_floor", ["德馨书院楼", "桑浦山校区学生宿舍C栋"]),
        ("ddl_time1", [f"{h}:00" for h in range(8, 19)]),
        ("DropDownList1", [f"{h}:00" for h in range(8, 19)]),
    ):
        onchange = f"__doPostBack('{selector}','')" if selector in {"ddl_time1", "DropDownList1"} else ""
        controls += f'<select id="{selector}" name="{selector}" onchange="{onchange}">' + ''.join(
            f'<option>{escape(label)}</option>' for label in options) + '</select>'
    html = ('<form method="post" action="student_applybill.aspx">' + controls +
            '<button id="btn_OK" type="button" onclick="__doPostBack(\'btn_OK\',\'\')">提交报修单</button></form>' +
            '<iframe srcdoc="' + escape(calendar, quote=True) + '"></iframe>' +
            '<script>function __doPostBack(k,a){document.getElementById("__EVENTTARGET").value=k;'
            'document.querySelector("form").submit();}'
            'document.getElementById("ddl_time1").onchange=()=>{'
            'if(parseInt(document.getElementById("ddl_time1").value)>'
            'parseInt(document.getElementById("DropDownList1").value))alert("invalid slot");'
            '__doPostBack("ddl_time1", "");};</script>')
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).is_file():
            pytest.skip("optional local browser contract requires installed Chromium")
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")
            blocked, dialogs, time_events = [], [], []
            def route_request(route):
                if not request_allowed(route.request.url, route.request.method, route.request.post_data):
                    blocked.append(route.request.method)
                    route.abort()
                else:
                    document = BeautifulSoup(html, "html.parser")
                    if route.request.method == "POST":
                        posted = parse_qs(route.request.post_data or "", keep_blank_values=True)
                        time_events.append(posted["__EVENTTARGET"][0])
                        for control in document.select("input, textarea, select"):
                            name = control.get("name", "")
                            if name not in posted or name.startswith("__"):
                                continue
                            value = posted[name][0]
                            if control.name == "textarea":
                                control.string = value
                            elif control.name == "select":
                                for option in control.select("option"):
                                    if option.text == value:
                                        option["selected"] = "selected"
                            else:
                                control["value"] = value
                    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=str(document))
            context.route("**/*", route_request)
            page = context.new_page()
            page.set_default_timeout(3000)
            def dismiss(dialog):
                dialogs.append(dialog.message)
                dialog.dismiss()
            page.on("dialog", dismiss)
            page.goto(REPAIR_FORM)
            result = fill_form(page, fields)
            assert all(result["matches"].values()) and not result["missing_page_fields"]
            assert page.locator("#tb_bookingtime1").get_attribute("readonly") is not None
            assert not blocked and not dialogs
            assert time_events == ["DropDownList1", "ddl_time1"]
            # Negative contract: even a human click in this preview cannot POST a work order.
            page.locator("#btn_OK").click()
            page.wait_for_timeout(200)
            assert blocked == ["POST"]
        finally:
            browser.close()
