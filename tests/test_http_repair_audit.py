"""Independent offline checks for repair UI constraints and receipt evidence."""
from __future__ import annotations

from copy import deepcopy

import pytest
from bs4 import BeautifulSoup
from test_http_repair import School, session

from stu_mcp.features.repair import http_parser as html
from stu_mcp.features.repair.parser import expected_fields, list_rows, match_detail
from stu_mcp.runtime import AppError


@pytest.mark.parametrize("name", ["tb_name", "tb_tel"])
def test_http_cannot_overwrite_school_readonly_business_fields(name):
    school = School()
    form = html.form_document(school.form())
    html.control(form, name)["readonly"] = "readonly"
    with pytest.raises(AppError):
        html.set_value(form, name, "SYNTHETIC_CHANGED_LOCKED_VALUE")


def test_http_rejects_form_disabled_by_an_ancestor_fieldset_before_any_post():
    school = School()
    markup = school.form().replace('method="post">', 'method="post"><fieldset disabled>')
    markup = markup.replace("</form>", "</fieldset></form>")
    form = html.form_document(markup)
    with pytest.raises(AppError):
        html.payload(form, "DropDownList1")


@pytest.mark.parametrize("legend_index", [0, 1], ids=["first-legend-enabled", "second-legend-disabled"])
def test_disabled_fieldset_honors_only_the_first_direct_legend_exception(legend_index):
    school = School()
    form = html.form_document(school.form())
    fieldset = BeautifulSoup("<fieldset disabled><legend></legend><legend></legend></fieldset>",
                             "html.parser").fieldset
    fieldset.find_all("legend")[legend_index].append(html.control(form, "tb_tel").extract())
    form.append(fieldset)
    if legend_index == 0:
        html.set_value(form, "tb_tel", "13900000000")
        assert html.payload(form, "ddl_time1")["tb_tel"] == ["13900000000"]
    else:
        with pytest.raises(AppError):
            html.set_value(form, "tb_tel", "13900000000")
        with pytest.raises(AppError):
            html.payload(form, "ddl_time1")


def test_selected_option_inside_disabled_optgroup_cannot_be_manufactured_into_a_post():
    school = School()
    form = html.form_document(school.form())
    select = html.control(form, "ddl_department_name")
    group = BeautifulSoup("<optgroup disabled></optgroup>", "html.parser").optgroup
    group.append(select.find("option").extract())
    select.append(group)
    with pytest.raises(AppError):
        html.set_value(form, "ddl_department_name", "工学院", label=True)
    with pytest.raises(AppError):
        html.payload(form, "ddl_time1")


def test_date_readonly_exception_remains_limited_to_the_known_calendar_control():
    school = School()
    form = html.form_document(school.form())
    date = html.control(form, "tb_bookingtime1")
    assert date.has_attr("readonly")
    html.set_value(form, "tb_bookingtime1", school.day)
    assert date["value"] == school.day and date.has_attr("readonly")


def test_hidden_previous_submit_target_cannot_turn_a_time_postback_into_submission():
    school = School()
    form = html.form_document(school.form())
    html.control(form, "__EVENTTARGET")["value"] = "btn_OK"
    data = html.payload(form, "ddl_time1")
    assert data["__EVENTTARGET"] == ["ddl_time1"]
    assert "btn_OK" not in data


def test_initial_receipt_requires_all_reviewed_business_fields_not_only_title_and_room():
    school = School()
    current = session(school)
    try:
        current.open(school.fields)
        capture = current.capture()
        school.created = True
        row = list_rows(html.list_snapshot(school.listing()))[0]
        raw = html.detail_snapshot(school.detail())
        assert match_detail(raw, capture, row)
        for key in expected_fields(capture):
            changed = deepcopy(raw)
            changed["fields"][key] = ["SYNTHETIC_MISMATCH"]
            assert match_detail(changed, capture, row) is None, key
    finally:
        current.flow.client.close()
