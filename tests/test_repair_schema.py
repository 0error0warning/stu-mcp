"""Mutation contracts for school schema changes, using synthetic snapshots only."""
import copy

import pytest

from stu_mcp.features.repair.parser import list_rows, parse_form
from stu_mcp.features.repair.schema import LABELS, LIST_COLUMNS
from stu_mcp.runtime import AppError


@pytest.fixture
def listing():
    header = [{"text": name, "links": []} for name in LIST_COLUMNS]
    row = [{"text": text, "links": []} for text in
           ("20260102900001", "合成故障", "2026/01/02 12:00:00", "等待处理", "")]
    row[1]["links"] = ["student_detail.aspx?ApplyBill_ID=900001"]
    return {"heading": True, "filtersClear": True, "empty": False, "rows": [header, row]}


@pytest.mark.parametrize("order", [(4, 3, 2, 1, 0), (1, 0, 3, 4, 2), (0, 1, 2, 3, 4)])
def test_list_uses_named_columns_and_tolerates_extra_columns(listing, order):
    expected = list_rows(listing)
    listing["rows"] = [[row[i] for i in order] for row in listing["rows"]]
    listing["rows"][0].insert(2, {"text": "新增负责部门", "links": []})
    listing["rows"][1].insert(2, {"text": "合成部门", "links": []})
    listing["rows"][0][0]["text"] = " \n" + listing["rows"][0][0]["text"] + " \n"
    assert list_rows(listing) == expected


@pytest.mark.parametrize("column", LIST_COLUMNS)
@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_critical_list_headers_must_be_unique(listing, column, change):
    index = LIST_COLUMNS.index(column)
    for row in listing["rows"]:
        if change == "missing":
            row.pop(index)
        else:
            row.append(copy.deepcopy(row[index]))
    with pytest.raises(ValueError):
        list_rows(listing)


@pytest.mark.parametrize("change", [
    {"problem": "login_required"}, {"problem": "source_error"},
    {"schemaValid": False}, {"filtersClear": False},
])
def test_login_errors_and_ambiguous_grids_cannot_be_empty_results(listing, change):
    with pytest.raises(ValueError):
        list_rows(listing | {"rows": [], "empty": True} | change)


def test_header_only_is_not_evidence_of_zero_orders(listing):
    with pytest.raises(ValueError):
        list_rows(listing | {"rows": listing["rows"][:1]})
    assert list_rows(listing | {"rows": listing["rows"][:1], "empty": True}) == []


def test_unknown_school_status_remains_raw_text(listing):
    listing["rows"][1][3]["text"] = "等待第三方配件"
    assert list_rows(listing)[0]["processing_status"] == "等待第三方配件"
    listing["rows"][1][1]["links"].append("student_detail.aspx?ApplyBill_ID=900002")
    with pytest.raises(ValueError):
        list_rows(listing)


@pytest.fixture
def form():
    return {
        "action": "student_applybill.aspx", "method": "post",
        "controls": dict.fromkeys(LABELS, 1) | {"rbtn_list_agency": 2},
        "body": {"tb_tel": ["13800000000"]}, "display": {},
        "unknown": [], "attachments": False,
    }


@pytest.mark.parametrize("key", ["tb_tel", "tb_happentime", "tb_stu_no", "rbtn_list_agency"])
@pytest.mark.parametrize("count", [0, 3])
def test_missing_or_duplicate_controls_stop_review(form, key, count):
    form["controls"][key] = count
    with pytest.raises(AppError) as error:
        parse_form(form)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("change,code", [
    ({"action": "https://r.stu.edu.cn/"}, "schema_changed"),
    ({"action": "student_applybill.aspx?new_version=2"}, "schema_changed"),
    ({"method": "get"}, "schema_changed"),
    ({"unknown": ["new_required_field"]}, "unsupported_repair_fields"),
    ({"attachments": True}, "unsupported_repair_fields"),
    ({"body": {"tb_tel": ["13800000000", "13900000000"]}}, "unsupported_repair_fields"),
])
def test_unreviewable_payload_cannot_reach_submission(form, change, code):
    with pytest.raises(AppError) as error:
        parse_form(form | change)
    assert error.value.code == code
