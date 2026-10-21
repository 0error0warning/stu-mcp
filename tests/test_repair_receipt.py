"""Synthetic receipt contracts, with no real accounts, identifiers or school requests."""
import copy
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from stu_checkin.http_server import LoopbackHTTPServer
from stu_mcp.connectivity import ENDPOINTS
from stu_mcp.features.repair.parser import refresh_detail
from stu_mcp.repair import direct_preflight
from stu_mcp.repair_receipt import ROOT, detail_link, expected_fields, list_rows, match_detail


@pytest.mark.parametrize("href", ["https://evil.example/student_detail.aspx?ApplyBill_ID=900001",
    "//repair.stu.edu.cn.evil.example/student_detail.aspx?ApplyBill_ID=900001",
    "https://u:p@repair.stu.edu.cn/student_detail.aspx?ApplyBill_ID=900001",
    "https://repair.stu.edu.cn:8443/student_detail.aspx?ApplyBill_ID=900001",
    "http://repair.stu.edu.cn/student_detail.aspx?ApplyBill_ID=900001",
    "student_detail.aspx?ApplyBill_ID=900001&ApplyBill_ID=900002",
    "student_detail.aspx?ApplyBill_ID=900001&delete=1", "student_detail.aspx?ApplyBill_ID=900001#x",
    "student_detail.aspx?ApplyBill_ID=../secret", "student_delete.aspx?ApplyBill_ID=900001",
    "javascript:alert(1)"])
def test_only_observed_read_only_detail_links_are_accepted(href):
    assert detail_link(href) is None


@pytest.fixture
def receipt_capture():
    values = {"tb_name": "合成同学", "ddl_department_name": "工学院", "tb_stu_no": "",
        "ddl_sex": "男", "ddl_floor": "桑浦山校区学生宿舍C栋", "tb_tel": "13800000000",
        "tb_address": "", "tb_mobil": "", "tb_email": "synthetic@stu.edu.cn", "tb_title": "合成故障",
        "tb_happenarea": "合成位置", "tb_happentime": "2026/01/02 12:00:00",
        "tb_Repair_device_name": "空调", "tb_Repair_device_no": "", "Detail": "合成现象",
        "tb_bookingtime1": "2026-01-03", "ddl_time1": "14:00", "DropDownList1": "17:00",
        "tb_bookingtime2": "", "ddl3": "8:00", "ddl4": "8:00", "rbtn_list_agency": "一般"}
    return {"fields": [{"key": k, "value": v} for k, v in values.items()]}


@pytest.fixture
def receipt_row():
    return {"order_id": "20260102900001", "detail_url": ROOT + "student_detail.aspx?ApplyBill_ID=900001"}


def test_detail_requires_every_reviewed_value_and_matching_order_identity(receipt_capture, receipt_row):
    fields = {k: [v or "未知"] for k, v in expected_fields(receipt_capture).items()}
    fields["processing_status"] = ["等待处理"]
    raw = {"orders": [receipt_row["order_id"]], "fields": fields}
    result = match_detail(raw, receipt_capture, receipt_row)
    assert result["processing_status"] == "等待处理" and result["detail_url"] == receipt_row["detail_url"]
    assert not {"phone", "fields", "capture"} & result.keys()
    for key in fields:
        changed = copy.deepcopy(raw)
        changed["fields"][key] = ["错误内容"]
        assert match_detail(changed, receipt_capture, receipt_row) is None, key
        changed["fields"][key] = fields[key] * 2
        assert match_detail(changed, receipt_capture, receipt_row) is None, key
    assert match_detail(raw | {"orders": ["20260102900002"]}, receipt_capture, receipt_row) is None
    # A legitimate status transition while checking must use the latest detail state.
    raw["fields"]["processing_status"] = ["已派人维修"]
    assert match_detail(raw, receipt_capture, receipt_row)["processing_status"] == "已派人维修"


def test_list_schema_filters_and_ids_are_verified():
    empty = {"heading": True, "filtersClear": True, "empty": True, "rows": []}
    assert list_rows(empty) == []
    for change in ({"heading": False}, {"filtersClear": False}, {"empty": False}):
        with pytest.raises(ValueError):
            list_rows(empty | change)
    header = [{"text": h, "links": []} for h in ("单据编号", "报修标题", "报修时间", "处理状态", "操作")]
    row = [{"text": "20260102900001", "links": []}, {"text": "合成...", "links": [
        "student_detail.aspx?ApplyBill_ID=900001"]}, {"text": "2026/01/02 12:00:00", "links": []},
        {"text": "等待处理", "links": []}, {"text": "", "links": []}]
    base = empty | {"rows": [header, row], "empty": False}
    assert list_rows(base)[0]["order_id"] == "20260102900001"
    for broken in (base | {"rows": [header, row, row]}, base | {"rows": [header, row[:4]]}):
        with pytest.raises(ValueError):
            list_rows(broken)
    changed = copy.deepcopy(base)
    changed["rows"][1][1]["links"] = ["student_detail.aspx?ApplyBill_ID=900002"]
    with pytest.raises(ValueError):
        list_rows(changed)


def test_verified_receipt_refresh_allows_school_edits_but_still_checks_identity(receipt_capture, receipt_row):
    fields = {k: [v] for k, v in expected_fields(receipt_capture).items()}
    fields["processing_status"] = ["等待处理"]
    raw = {"orders": [receipt_row["order_id"]], "fields": fields}
    receipt = match_detail(raw, receipt_capture, receipt_row)
    changed = copy.deepcopy(raw)
    changed["fields"]["appointment"] = ["2026-01-04日-15:00~18:00"]
    changed["fields"]["processing_status"] = ["等待第三方配件"]
    assert match_detail(changed, receipt_capture, receipt_row) is None
    result = refresh_detail(changed, receipt)
    assert result["processing_status"] == "等待第三方配件"
    assert result["checked_at"] >= receipt["checked_at"]
    assert result["order_id"] == receipt["order_id"]
    for mutation in ({"orders": ["20260102900002"]}, {"orders": raw["orders"] * 2},
                     {"problem": "login_required"}, {"problem": "source_error"}):
        assert refresh_detail(changed | mutation, receipt) is None
    changed["fields"]["processing_status"] *= 2
    assert refresh_detail(changed, receipt) is None


def test_direct_preflight_ignores_proxy_environment_without_exporting_auth(monkeypatch):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(dict(self.headers))
            self.send_response(302)
            self.send_header("Location", "https://sso.stu.edu.cn/login?service=SYNTHETIC")
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *_):
            pass
    server = LoopbackHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setitem(ENDPOINTS, "sangpushan_repair", f"http://127.0.0.1:{server.server_port}/")
        monkeypatch.setitem(ENDPOINTS, "school_sso", f"http://127.0.0.1:{server.server_port}/")
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(key, "http://127.0.0.1:1")
        monkeypatch.setenv("NO_PROXY", "")
        direct_preflight()
        assert len(received) == 2
        assert all("Cookie" not in headers and "Authorization" not in headers for headers in received)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)
