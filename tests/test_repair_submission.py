"""Review/confirmation tests use synthetic forms; never create a school ticket."""
import copy
import json
import threading
import time
from concurrent.futures import Future
from datetime import timedelta
from html import escape
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from queue import Queue
from urllib.parse import urlencode

import pytest

from stu_checkin.http_server import LoopbackHTTPServer
from stu_mcp.features.repair.adapter import BrowserSession
from stu_mcp.features.repair.parser import list_rows
from stu_mcp.repair import REPAIR_FORM, RepairDrafts, campus_today
from stu_mcp.repair_receipt import DETAIL_SCRIPT, LIST_SCRIPT, LIST_URL, ROOT
from stu_mcp.repair_submission import (
    SubmissionGate,
    capture_form,
    check_review,
    check_submission_result,
    forward_submission,
    normalize_body,
    review_result,
    submit_reviewed_form,
)
from stu_mcp.runtime import AppError


@pytest.fixture
def captured():
    return {"body": {"tb_tel": ["13800000000"], "Detail": ["合成故障\n第二行"]},
            "fields": [{"key": "tb_tel", "label": "联系电话", "value": "13800000000"},
                       {"key": "Detail", "label": "详细描述", "value": "<script>合成|故障</script>\n第二行"}],
            "fingerprint": "SYNTHETIC_FINGERPRINT", "problems": []}


@pytest.fixture
def review(captured):
    return {"review_id": "synthetic-review-id", "expires_at": time.time() + 300, "capture": captured}


def test_review_displays_full_business_information_without_hidden_state(review):
    result = review_result(review)
    assert result["requires_user_confirmation"] is True
    assert "13800000000" in result["preview_markdown"]
    assert "repair.stu.edu.cn" in result["preview_markdown"]
    assert "<script>" not in result["preview_markdown"] and "&lt;script&gt;" in result["preview_markdown"]
    assert "合成\\|故障" in result["preview_markdown"]
    assert "body" not in result and "__VIEWSTATE" not in json.dumps(result)
    result["form_fields"][0]["value"] = "changed"
    assert review["capture"]["fields"][0]["value"] == "13800000000"


@pytest.mark.parametrize("change", ["missing", "wrong_id", "expired", "fields_changed", "incomplete"])
def test_confirmation_is_bound_to_recent_complete_exact_review(review, captured, change):
    review_id = review["review_id"]
    if change == "missing":
        review = None
    elif change == "wrong_id":
        review_id = "some-other-review"
    elif change == "expired":
        review["expires_at"] = time.time() - 1
    elif change == "fields_changed":
        captured = captured | {"fingerprint": "changed"}
    else:
        captured = captured | {"problems": [{"field": "phone"}]}
    with pytest.raises(AppError):
        check_review(review, review_id, captured)


def submit_body(captured):
    return urlencode({"__EVENTTARGET": "btn_OK", "__EVENTARGUMENT": "", "__VIEWSTATE": "SYNTHETIC",
                      **{k: v[0] for k, v in captured["body"].items()}})


def test_gate_requires_arming_and_allows_exactly_one_matching_post(captured):
    gate = SubmissionGate()
    payload = submit_body(captured)
    assert not gate.allows(REPAIR_FORM, "POST", payload)
    gate.approved_body = captured["body"]
    assert not gate.allows(REPAIR_FORM, "POST", payload.replace("13800000000", "13900000000"))
    assert not gate.allows(REPAIR_FORM, "POST", payload + "&__EVENTTARGET=btn_OK")
    assert not gate.allows(REPAIR_FORM + "?id=1", "POST", payload)
    assert not gate.allows("https://r.stu.edu.cn/", "POST", payload)
    assert not gate.allows(REPAIR_FORM, "GET", payload)
    assert not gate.allows(REPAIR_FORM, "POST", payload + "&btn_OK=1")
    assert gate.allows(REPAIR_FORM, "POST", payload)
    assert gate.sent is True
    assert not gate.allows(REPAIR_FORM, "POST", payload)


def test_gate_normalizes_form_line_endings_and_observes_cancellation(captured):
    gate = SubmissionGate(approved_body=captured["body"])
    payload = submit_body(captured).replace("%0A", "%0D%0A")
    assert gate.allows(REPAIR_FORM, "POST", payload)
    cancelled = threading.Event()
    second = SubmissionGate(approved_body=captured["body"], cancelled=cancelled.is_set)
    cancelled.set()
    assert not second.allows(REPAIR_FORM, "POST", payload) and not second.sent
    assert normalize_body({"x": ["a\r\nb\rc"]}) == {"x": ["a\nb\nc"]}


def manager_with_window():
    drafts = RepairDrafts()
    draft_id = drafts.prepare(title="合成故障")["draft_id"]
    drafts._update(draft_id, status="filled_unsubmitted")
    drafts.commands[draft_id] = Queue()
    drafts.stops[draft_id] = threading.Event()
    return drafts, draft_id


def command(drafts, draft_id, operation, gate, page=None, **values):
    if page is None:
        gate.verifier.prepare = lambda _: None
    future = Future()
    drafts.commands[draft_id].put((operation, values, future))
    drafts._process_command(draft_id, BrowserSession(page, gate, drafts.stops[draft_id], lambda **_: None))
    return future.result(timeout=1)


def test_manager_never_treats_fill_or_review_as_user_confirmation(captured, monkeypatch):
    drafts, draft_id = manager_with_window()
    monkeypatch.setattr("stu_mcp.features.repair.adapter.capture_form", lambda _: copy.deepcopy(captured))
    attempts = []
    monkeypatch.setattr("stu_mcp.features.repair.submission.submit_reviewed_form", lambda *args: attempts.append(args))
    result = command(drafts, draft_id, "review", SubmissionGate())
    assert result["status"] == "awaiting_confirmation" and not attempts
    with pytest.raises(AppError, match="用户明确确认"):
        drafts.submit(draft_id, result["review_id"])
    assert not attempts


def test_changed_form_rejects_confirmation_before_click(captured, monkeypatch):
    drafts, draft_id = manager_with_window()
    current = copy.deepcopy(captured)
    monkeypatch.setattr("stu_mcp.features.repair.adapter.capture_form", lambda _: copy.deepcopy(current))
    result = command(drafts, draft_id, "review", SubmissionGate())
    current["fingerprint"] = "CHANGED_AFTER_USER_REVIEW"
    with pytest.raises(AppError, match="已改变"):
        command(drafts, draft_id, "submit", SubmissionGate(), review_id=result["review_id"])
    assert drafts.snapshot(draft_id)["request_sent"] is False


def test_unknown_result_is_not_retried_even_with_repeated_commands(captured, monkeypatch):
    drafts, draft_id = manager_with_window()
    monkeypatch.setattr("stu_mcp.features.repair.adapter.capture_form", lambda _: copy.deepcopy(captured))
    attempts = []
    def unknown(*_):
        attempts.append(True)
        return {"status": "submission_unknown", "request_sent": True, "submitted_by_mcp": False}
    monkeypatch.setattr("stu_mcp.features.repair.submission.submit_reviewed_form", unknown)
    result = command(drafts, draft_id, "review", SubmissionGate())
    sent = command(drafts, draft_id, "submit", SubmissionGate(), review_id=result["review_id"])
    assert sent["status"] == "submission_unknown" and not sent["submitted_by_mcp"]
    command(drafts, draft_id, "submit", SubmissionGate(), review_id=result["review_id"])
    assert attempts == [True]
    assert drafts.open(draft_id)["request_sent"] is True
    with pytest.raises(AppError):
        drafts.prepare(draft_id, title="try again")
    assert drafts.close(draft_id)["status"] == "submission_unknown"


def test_cancelled_queued_command_cannot_later_submit(captured, monkeypatch):
    drafts, draft_id = manager_with_window()
    calls = []
    monkeypatch.setattr("stu_mcp.features.repair.adapter.capture_form", lambda _: calls.append(True))
    future = Future()
    drafts.commands[draft_id].put(("submit", {"review_id": "unused"}, future))
    future.cancel()
    drafts._process_command(draft_id, None)
    assert not calls


@pytest.fixture
def synthetic_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).is_file():
            pytest.skip("optional local Chromium contract")
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def synthetic_page(browser, mode="success", *, change_on_click=False):
    next_day = (campus_today() + timedelta(days=1)).isoformat()
    values = {"tb_name": "合成同学", "tb_tel": "13800000000", "tb_mobil": "13900000000",
              "tb_stu_no": "SYNTHETIC-STUDENT", "tb_address": "合成住址", "tb_email": "synthetic@stu.edu.cn",
              "tb_title": "合成故障", "tb_happenarea": "合成房间", "tb_Repair_device_name": "空调",
              "tb_Repair_device_no": "SYNTHETIC-ASSET", "tb_bookingtime1": next_day, "tb_bookingtime2": ""}
    controls = ''.join(f'<input id="{k}" name="{k}" value="{escape(v)}">' for k, v in values.items())
    application_time = campus_today().strftime("%Y/%m/%d") + " 12:00:00"
    controls += f'<input id="tb_happentime" name="tb_happentime" value="{application_time}" disabled>'
    controls += '<textarea id="Detail" name="Detail">合成故障\n合成第二行</textarea>'
    for key, label, value in (("ddl_department_name", "工学院", "30"),
                               ("ddl_floor", "桑浦山校区学生宿舍C栋", "70001"),
                               ("ddl_sex", "男", "男"), ("ddl_time1", "14:00", "7"),
                               ("DropDownList1", "17:00", "10"), ("ddl3", "8:00", "1"), ("ddl4", "8:00", "1")):
        controls += f'<select id="{key}" name="{key}"><option value="{value}">{label}</option></select>'
    controls += '<input type="radio" name="rbtn_list_agency" value="0" checked>'
    controls += '<input type="radio" name="rbtn_list_agency" value="1">'
    controls += '<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="">'
    controls += '<input type="hidden" name="__EVENTARGUMENT" value="">'
    controls += '<input type="hidden" name="__VIEWSTATE" value="SYNTHETIC_NEVER_RETURN_THIS">'
    changing = 'document.getElementById("tb_tel").value="13700000000";' if change_on_click else ""
    markup = ('<form method="post" action="student_applybill.aspx">' + controls +
              '<button id="btn_OK" type="button" onclick="send()">提交报修单</button></form>' +
              '<script>function send(){' + changing + 'document.getElementById("__EVENTTARGET").value="btn_OK";'
              'document.querySelector("form").submit();}</script>')
    context = browser.new_context(service_workers="block", offline=True)
    gate, allowed, blocked = SubmissionGate(), [], []
    state = {"created": mode == "old_record", "status": "等待处理", "reads": [], "offline": False}
    order_id = campus_today().strftime("%Y%m%d") + "900001"

    def listing():
        filters = ''.join(f'<input id="{key}" value="">' for key in (
            "tb_AppBill_ID", "tb_AppBill_Title", "tb_Appbill_from_Date", "tb_Appbill_to_Date"))
        filters += '<select id="ddl_Appbill_Status"><option>全部</option></select>'
        if not state["created"]:
            return '<h1>我的报修单据列表</h1>' + filters + '<p>没有任何数据!</p>'
        headers = ''.join(f'<th>{h}</th>' for h in ("单据编号", "报修标题", "报修时间", "处理状态", "操作"))
        row = (f'<tr><td>{order_id}</td><td><a href="student_detail.aspx?ApplyBill_ID=900001">'
               f'合成故障...</a></td><td>{application_time}</td><td>{state["status"]}</td><td></td></tr>')
        if mode == "ambiguous":
            row += row.replace("900001", "900002")
        return '<h1>我的报修单据列表</h1>' + filters + f'<table id="DataGrid1"><tr>{headers}</tr>{row}</table>'

    def detail():
        data = {"报修人姓名:": values["tb_name"], "所属单位:": "工学院", "学号:": values["tb_stu_no"],
                "性别:": "男", "电话:": values["tb_tel"], "住址:": values["tb_address"],
                "手机:": values["tb_mobil"], "E-MAIL:": values["tb_email"], "报修标题:": values["tb_title"],
                "发生地址:": values["tb_happenarea"], "发生时间:": application_time,
                "故障设备名称:": values["tb_Repair_device_name"], "资产编号:": values["tb_Repair_device_no"],
                "详细描述:": "别的故障" if mode == "wrong_detail" else "合成故障 合成第二行",
                "我想预约时间:": state.get("appointment", f'{next_day}日-14:00~17:00'),
                "处理状态:": state["status"]}
        rows = ''.join(f'<tr><td>{label}</td><td>{escape(value)}</td></tr>' for label, value in data.items())
        return (f'<table><tr><td>报修单({state.get("detail_order", order_id)})</td></tr>{rows}</table>'
                '<select id="ddl_floor" disabled><option selected>桑浦山校区学生宿舍C栋</option></select>'
                '<input type="checkbox" id="chk_agency_common" checked disabled>'
                '<input type="checkbox" id="chk_agency_urgency" disabled>')

    def route_request(route):
        request = route.request
        if state["offline"]:
            route.abort()
            return
        if request.url == REPAIR_FORM and request.method == "GET":
            route.fulfill(content_type="text/html; charset=utf-8", body=markup)
        elif request.url == LIST_URL and request.method == "GET":
            state["reads"].append("list")
            route.fulfill(content_type="text/html; charset=utf-8", body=listing())
        elif request.url == ROOT + "student_detail.aspx?ApplyBill_ID=900001" and request.method == "GET":
            state["reads"].append("detail")
            route.fulfill(content_type="text/html; charset=utf-8", body=detail())
        elif gate.allows(request.url, request.method, request.post_data):
            allowed.append(True)
            state["created"] = mode in {"success", "lost_response", "old_record", "wrong_detail", "ambiguous"}
            if mode in {"network_error", "lost_response"}:
                route.abort()
            elif mode in {"success", "old_record", "wrong_detail", "ambiguous"}:
                # Browser redirects are not routed again by Playwright. A script
                # navigation exercises the landing page while remaining fully offline.
                route.fulfill(content_type="text/html; charset=utf-8", body=
                              '<script>location.replace("' + LIST_URL + '")</script>')
            else:
                body = '<p>提交成功，报修单号：SYN-10001</p>' if mode == "explicit_only" else markup
                route.fulfill(content_type="text/html; charset=utf-8", body=body)
        else:
            # All requests are handled locally, even ones the test accidentally introduces.
            blocked.append(True)
            route.abort()
    context.route("**/*", route_request)
    page = context.new_page()
    page.set_default_timeout(3000)
    page.goto(REPAIR_FORM)
    return page, gate, allowed, blocked, context, state


def test_browser_review_reads_every_successful_field_and_preserves_full_phone(synthetic_browser):
    page, gate, allowed, blocked, context, _ = synthetic_page(synthetic_browser)
    try:
        captured = capture_form(page)
        assert captured["problems"] == []
        assert not any(k.startswith("__") for k in captured["body"])
        result = review_result({"review_id": "synthetic", "expires_at": time.time() + 300, "capture": captured})
        assert "13800000000" in result["preview_markdown"] and "synthetic@stu.edu.cn" in result["preview_markdown"]
        assert "SYNTHETIC_NEVER_RETURN_THIS" not in json.dumps(result)
        assert "SYNTHETIC-STUDENT" in result["preview_markdown"]
        assert not allowed and not gate.sent
        page.locator("#btn_OK").click()
        assert blocked and not gate.sent
    finally:
        context.close()


def test_generated_school_time_does_not_bypass_duplicate_submission_guard(synthetic_browser):
    page, _, _, _, context, _ = synthetic_page(synthetic_browser)
    try:
        original = capture_form(page)
        page.locator("#tb_happentime").evaluate("el => el.value = '2026/01/02 13:00:00'")
        changed = capture_form(page)
        assert original["fingerprint"] != changed["fingerprint"]
        assert original["submission_fingerprint"] == changed["submission_fingerprint"]
    finally:
        context.close()


@pytest.mark.parametrize("mutation,code", [
    ("document.querySelector('form').action='https://r.stu.edu.cn/'", "schema_changed"),
    ("document.querySelector('form').method='get'", "schema_changed"),
    ("document.querySelector('#tb_tel').remove()", "schema_changed"),
    ("document.querySelector('#tb_stu_no').remove()", "schema_changed"),
    ("document.querySelector('#tb_tel').name='new_phone_name'", "schema_changed"),
    ("document.querySelector('form').append(document.querySelector('#tb_happentime').cloneNode(true))",
     "schema_changed"),
    ("document.querySelector('form').insertAdjacentHTML('beforeend', '<input name=new_required value=test>')",
     "unsupported_repair_fields"),
    ("document.body.insertAdjacentHTML('beforeend', '<input type=password>')", "repair_login_required"),
    ("document.body.insertAdjacentHTML('beforeend', '<h1>应用程序中的服务器错误</h1>')", "repair_source_error"),
])
def test_changed_school_forms_stop_before_any_submission(synthetic_browser, mutation, code):
    page, gate, allowed, _, context, _ = synthetic_page(synthetic_browser)
    try:
        page.evaluate(mutation)
        with pytest.raises(AppError) as error:
            capture_form(page)
        assert error.value.code == code
        assert not gate.sent and not allowed
    finally:
        context.close()


def test_list_dom_changes_are_mapped_and_duplicate_grids_are_rejected(synthetic_browser):
    page, _, _, _, context, state = synthetic_page(synthetic_browser)
    try:
        state["created"] = True
        page.goto(LIST_URL)
        expected = list_rows(page.locator("body").evaluate(LIST_SCRIPT))
        page.evaluate("""() => {
          for (const [index, row] of Array.from(document.querySelector('#DataGrid1').rows).entries()) {
            row.append(row.cells[0]);
            row.insertAdjacentHTML('afterbegin', index ? '<td>合成部门</td>' : '<th>新增部门</th>');
          }
        }""")
        assert list_rows(page.locator("body").evaluate(LIST_SCRIPT)) == expected
        page.evaluate("document.body.append(document.querySelector('#DataGrid1').cloneNode(true))")
        with pytest.raises(ValueError):
            list_rows(page.locator("body").evaluate(LIST_SCRIPT))
    finally:
        context.close()


def test_nested_layout_tables_do_not_duplicate_detail_fields(synthetic_browser):
    context = synthetic_browser.new_context(offline=True)
    page = context.new_page()
    try:
        page.set_content('<table><tr><td><div><table><tr><td><span>报修单(20260102900001)</span></td></tr>'
                         '<tr><td><b>电话：</b></td><td><span>13800000000</span></td></tr>'
                         '<tr><td>处理状态:</td><td>等待处理</td></tr>'
                         '<tr><td>新增字段:</td><td>新值</td></tr></table></div></td></tr></table>')
        raw = page.locator("body").evaluate(DETAIL_SCRIPT)
        assert raw["orders"] == ["20260102900001"]
        assert raw["fields"] == {"tb_tel": ["13800000000"], "processing_status": ["等待处理"]}
    finally:
        context.close()


def test_verified_order_can_change_appointment_and_status_without_resubmission(synthetic_browser):
    page, gate, allowed, _, context, state = synthetic_page(synthetic_browser)
    try:
        capture = capture_form(page)
        gate.verifier.prepare(page)
        first = submit_reviewed_form(page, gate, capture)
        assert first["receipt_fresh"]
        state.update(appointment="2026-01-04日-15:00~18:00", status="等待第三方配件")
        refreshed = check_submission_result(page, gate)
        assert refreshed["receipt_fresh"]
        assert refreshed["receipt"]["processing_status"] == "等待第三方配件"
        # Even direct reuse of the adapter's submit method is read-only once sent.
        assert submit_reviewed_form(page, gate, capture)["receipt_fresh"]
        assert allowed == [True]
        state["detail_order"] = "20260102900002"
        mismatch = check_submission_result(page, gate)
        assert mismatch["status"] == "submitted" and not mismatch["receipt_fresh"]
        assert mismatch["receipt"] == gate.verifier.receipt
        assert mismatch["verification_issue"] == "detail_mismatch"
        assert allowed == [True]
    finally:
        context.close()


def test_observed_inline_blank_asset_and_description_cannot_spoof_labels(synthetic_browser):
    context = synthetic_browser.new_context(offline=True)
    page = context.new_page()
    try:
        page.set_content('<table><tr><td>报修单(20260102900001)</td></tr>'
            '<tr><td>电话:</td><td>13800000000</td><td>手机:13900000000</td></tr>'
            '<tr><td>故障设备名称:</td><td>空调</td><td>资产编号:</td></tr>'
            '<tr><td>详细描述:</td><td>电话: 不是报修人电话字段</td></tr></table>')
        raw = page.locator("body").evaluate(DETAIL_SCRIPT)
        assert raw["orders"] == ["20260102900001"]
        assert raw["fields"]["tb_tel"] == ["13800000000"]
        assert raw["fields"]["tb_mobil"] == ["13900000000"]
        assert raw["fields"]["tb_Repair_device_no"] == [""]
        assert raw["fields"]["Detail"] == ["电话: 不是报修人电话字段"]
    finally:
        context.close()


def test_manager_read_only_check_dispatches_without_form_capture_or_submit(monkeypatch):
    drafts, draft_id = manager_with_window()
    drafts._update(draft_id, request_sent=True, status="submission_unknown")
    monkeypatch.setattr("stu_mcp.features.repair.adapter.capture_form", lambda _: pytest.fail("not a form operation"))
    monkeypatch.setattr("stu_mcp.features.repair.submission.submit_reviewed_form", lambda *_: pytest.fail("no resubmission"))
    monkeypatch.setattr("stu_mcp.features.repair.submission.check_submission_result", lambda *_: {
        "status": "submitted", "request_sent": True, "submitted_by_mcp": True,
        "receipt": {"order_id": "20260102900001", "processing_status": "等待处理"}})
    result = command(drafts, draft_id, "check", SubmissionGate())
    assert result["receipt"]["processing_status"] == "等待处理"


@pytest.mark.parametrize("mode,expected", [("success", "submitted"), ("lost_response", "submitted"),
    ("unknown", "submission_unknown"), ("network_error", "submission_unknown"),
    ("explicit_only", "submission_unknown"), ("old_record", "submission_unknown"),
    ("wrong_detail", "submission_unknown"), ("ambiguous", "submission_unknown")])
def test_browser_confirmed_submit_once_and_reports_only_evidenced_outcome(synthetic_browser, mode, expected):
    page, gate, allowed, blocked, context, state = synthetic_page(synthetic_browser, mode)
    try:
        captured = capture_form(page)
        gate.verifier.prepare(page)
        original_wait = page.wait_for_timeout
        page.wait_for_timeout = lambda _: pytest.fail("submission must wait for navigation, not sleep")
        result = submit_reviewed_form(page, gate, captured)
        page.wait_for_timeout = original_wait
        assert result["status"] == expected and result["request_sent"] is True, (state, result)
        assert result["submitted_by_mcp"] is (expected == "submitted")
        assert allowed == [True] and not blocked
        assert state["reads"].count("list") <= 2 and state["reads"].count("detail") <= 1
        if expected == "submitted":
            assert result["receipt"]["processing_status"] == "等待处理"
            assert "ticket=" not in result["receipt"]["detail_url"]
            assert not {"tb_tel", "fields", "body"} & result["receipt"].keys()
        assert gate.approved_body is None
        assert not gate.allows(REPAIR_FORM, "POST", submit_body(captured))
    finally:
        context.close()


def test_browser_race_after_confirmation_cannot_send_changed_contact(synthetic_browser):
    page, gate, allowed, blocked, context, _ = synthetic_page(synthetic_browser, change_on_click=True)
    try:
        gate.verifier.prepare(page)
        result = submit_reviewed_form(page, gate, capture_form(page))
        assert result["status"] == "submission_not_sent" and result["request_sent"] is False
        assert blocked and not allowed
    finally:
        context.close()


def test_read_only_recovery_and_status_refresh_never_send_a_second_request(synthetic_browser):
    page, gate, allowed, blocked, context, state = synthetic_page(synthetic_browser, "network_error")
    try:
        gate.verifier.prepare(page)
        result = submit_reviewed_form(page, gate, capture_form(page))
        assert result["status"] == "submission_unknown"
        # School committed after the response was lost; recovery only reads the record.
        state["created"] = True
        recovered = check_submission_result(page, gate)
        assert recovered["status"] == "submitted" and recovered["receipt_fresh"]
        state["status"] = "已派人维修"
        before = state["reads"].count("list")
        refreshed = check_submission_result(page, gate)
        assert refreshed["receipt"]["processing_status"] == "已派人维修"
        assert state["reads"].count("list") == before  # Known receipt needs just one detail GET.
        state["offline"] = True
        unavailable = check_submission_result(page, gate)
        assert unavailable["status"] == "submitted" and unavailable["receipt_fresh"] is False
        assert unavailable["receipt"] == refreshed["receipt"]
        assert allowed == [True] and not blocked
    finally:
        context.close()


@pytest.mark.parametrize("redirect_status", [302, 307, 308])
def test_transport_is_direct_and_never_replays_redirected_post(synthetic_browser, monkeypatch, redirect_status):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            received.append(self.path)
            self.send_response(redirect_status)
            self.send_header("Location", "/replayed-post")
            self.send_header("Set-Cookie", "synthetic-repair=SYNTHETIC; Path=/")
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *_):
            pass
    server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    entry = f"http://127.0.0.1:{server.server_port}"
    context = synthetic_browser.new_context(service_workers="block")
    try:
        def handler(route):
            if route.request.method == "POST":
                forward_submission(route)
            else:
                route.fulfill(content_type="text/html", body=
                    '<form method="post" action="/submit"><input name="Detail" value="SYNTHETIC">'
                    '<button>Send</button></form>')
        context.route(entry + "/**", handler)
        page = context.new_page()
        page.goto(entry + "/form")
        page.locator("button").click()
        assert received == ["/submit"]
        assert page.url == entry + "/submit"
        assert "正在核对" in page.locator("body").inner_text()
        # Cookies stay in Playwright's own context, never copied into tool fields.
        assert any(c["name"] == "synthetic-repair" for c in context.cookies(entry))
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
