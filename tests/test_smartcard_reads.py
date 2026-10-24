"""Synthetic campus card contracts; no school credentials or personal fixtures."""
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from stu_mcp.features.smartcard.adapter import SmartcardAdapter
from stu_mcp.features.smartcard.parser import (
    continuation,
    decode,
    parse_profile,
    parse_transactions,
    profile_balance,
    query_form,
    read_url,
    transaction_type,
    validate_dates,
)
from stu_mcp.features.smartcard.schema import CARD_HISTORY_URL, CARD_OVERVIEW_URL
from stu_mcp.features.smartcard.service import card_overview, card_transactions
from stu_mcp.runtime import AppError

ACCOUNT = "synthetic-student-A"
START, END = date(2026, 10, 1), date(2026, 10, 7)
FIELDS = ["交易发生时间", "学号", "姓名", "交易类型", "子系统名称", "操作员", "类别",
          "交易额", "现有余额", "次数", "状态"]
RECORD = ["2026/10/03 12:34:56", ACCOUNT, "合成姓名", "扣款", "合成子系统", "不应输出的操作员", "合成类别",
          "-1.50", "18.50", "2", "成功"]


def profile(*, account=ACCOUNT):
    values = [("学工号", account), ("余额", "18.50 元"), ("卡状态", "正常"), ("冻结状态", "未冻结"),
              ("检查状态", "正常"), ("挂失状态", "未挂失"), ("身份证号码", "synthetic-private-id"),
              ("家庭住址", "不应返回的合成地址")]
    return "<table>" + "".join(f"<tr><td>{label}：</td><td>{value}</td></tr>" for label, value in values) + "</table>"


def history(*, rows=None, fields=None, pages=1, current=1, declared_count=None):
    fields = FIELDS if fields is None else fields
    rows = [RECORD] if rows is None else rows
    count = len(rows) * max(pages, 1) if declared_count is None else declared_count
    return ('<table id="tables"><tr>' + "".join(f"<th>{label}</th>" for label in fields) + "</tr>" +
            "".join("<tr>" + "".join(f"<td>{value}</td>" for value in record) + "</tr>" for record in rows) +
            f'<tr><td colspan="{len(fields)}">本次查询共涉及:{count}次交易 ; '
            f"总计交易额为:0.00（元） 共{pages}页 当前第{current}页</td></tr></table>")


def selection():
    return ('<form method="post" action="?__continue=synthetic-selection">'
            '<select name="account"><option value="synthetic-internal-card">本人卡</option></select>'
            '<select name="inputObject"><option value="all">全部</option>'
            '<option value="1A">支付宝转账</option><option value="15">消费</option></select></form>')


def dates():
    return ('<form method="post" action="?__continue=synthetic-dates">'
            '<input name="inputStartDate" value="20261001"><input name="inputEndDate" value="20261007">'
            '<input type="submit" name="submit" value="查询"></form>')


def proceeding():
    return ('<p>操作正进行</p><form id="form1" name="form1" method="post" '
            'action="?__continue=synthetic-next"></form>'
            '<script>setTimeout("document.form1.submit()",1000);</script>')


def test_profile_proves_own_identity_and_returns_only_minimal_fields():
    result = parse_profile(profile(), ACCOUNT)
    assert result == {"balance": "18.50", "currency": "CNY", "card_status": "正常",
                      "freeze_status": "未冻结", "check_status": "正常", "loss_status": "未挂失"}
    assert ACCOUNT not in str(result) and "synthetic-private-id" not in str(result)


def test_missing_optional_status_is_unknown():
    html = "<table><tr><td>学工号：</td><td>" + ACCOUNT + "</td></tr><tr><td>余额</td><td>1</td></tr></table>"
    assert parse_profile(html, ACCOUNT)["card_status"] is None


def test_labelled_profile_balances_are_kept_separate_without_guessing_available_funds():
    compound = "12.34元（卡余额） -5.60 元(当前过渡余额) 7.89元(上次过渡余额)"
    result = parse_profile(profile().replace("18.50 元", compound), ACCOUNT)
    assert result["balance"] == "12.34"
    assert result["balance_breakdown"] == {"card_balance": "12.34", "current_transition_balance": "-5.60",
                                            "previous_transition_balance": "7.89"}
    assert profile_balance("7.89元(上次过渡余额)12.34元(卡余额)-5.60元(当前过渡余额)") == {
        "balance": "12.34", "balance_breakdown": result["balance_breakdown"]}


@pytest.mark.parametrize("compound", [
    "12.34元(卡余额)-5.60元(当前过渡余额)",
    "12.34元(卡余额)-5.60元(卡余额)7.89元(上次过渡余额)",
    "12.34元(卡余额)-5.60元(额外余额)7.89元(上次过渡余额)",
    "12.34元(卡余额)-5.60元(当前过渡余额)7.89元(上次过渡余额)合计14.63元",
    "12.34元(卡余额)未知元(当前过渡余额)7.89元(上次过渡余额)",
])
def test_labelled_balance_ambiguity_is_not_summed_or_ignored(compound):
    with pytest.raises(AppError) as error:
        profile_balance(compound)
    assert error.value.code == "schema_changed" and compound not in error.value.message


@pytest.mark.parametrize("mutate", [
    lambda h: h.replace("余额", "累计余额"),
    lambda h: h.replace("18.50 元", "未知"),
    lambda h: h.replace("18.50 元", "NaN"),
    lambda h: h + "<table><tr><td>余额</td><td>3</td></tr></table>",
    lambda h: h.replace("学工号", "账号摘要"),
    lambda h: h.replace(f"<td>{ACCOUNT}</td>", f"<td><table><tr><td>{ACCOUNT}</td></tr></table></td>"),
])
def test_ambiguous_or_changed_profile_is_not_balance_zero(mutate):
    with pytest.raises(AppError) as error:
        parse_profile(mutate(profile()), ACCOUNT)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("html", [profile(account="another-synthetic-student"), profile()])
def test_profile_identity_failure_is_safe(html):
    with pytest.raises(AppError) as error:
        parse_profile(html, "different-synthetic-student")
    assert error.value.code == "session_invalid"
    assert "another-synthetic" not in error.value.message


@pytest.mark.parametrize("html", [
    '<input name="passwd">', '<form action="loginstudent.action"></form>', '<frame src="homeLogin.action">',
])
def test_login_page_is_not_empty_data(html):
    with pytest.raises(AppError) as error:
        parse_profile(html, ACCOUNT)
    assert error.value.code == "login_expired"


def test_strict_mixed_encoding_helper():
    for encoding in ("utf-8", "gb18030"):
        assert decode(SimpleNamespace(content="卡余额".encode(encoding))) == "卡余额"
    with pytest.raises(AppError):
        decode(SimpleNamespace(content=b"\xff"))


def test_history_reordered_columns_preserve_source_category_and_money():
    order = [4, 0, 5, 2, 10, 8, 6, 1, 7, 9, 3]
    result = parse_transactions(history(fields=[FIELDS[i] for i in order], rows=[[
        RECORD[i] for i in order]]), ACCOUNT, START, END)
    assert result["items"] == [{"occurred_at": "2026-10-03T12:34:56+08:00", "type": "扣款",
                               "subsystem": "合成子系统", "category": "合成类别", "amount": "-1.50",
                               "balance": "18.50", "sequence": "2", "status": "成功"}]
    assert result["coverage"] == {"complete": True, "pages_read": 1, "total_pages": 1,
                                  "total_records": 1, "rows_read": 1}
    assert "合成姓名" not in str(result) and "操作员" not in str(result) and ACCOUNT not in str(result)


def test_normal_empty_history_requires_table_and_page_proof():
    result = parse_transactions(history(rows=[], pages=0), ACCOUNT, START, END)
    assert result["items"] == [] and result["coverage"]["complete"]
    for html in (history(rows=[]), "暂无数据", history(rows=[], pages=0).replace("共0页 当前第1页", "")):
        with pytest.raises(AppError):
            parse_transactions(html, ACCOUNT, START, END)


def test_multiple_pages_are_explicit_first_page_partial_without_guessing_next_request():
    result = parse_transactions(history(pages=3), ACCOUNT, START, END)
    assert not result["coverage"]["complete"] and result["coverage"]["total_pages"] == 3
    assert result["pending"] and result["coverage"]["pages_read"] == 1


def test_summary_footer_is_not_a_transaction_and_total_is_not_a_balance():
    html = history(rows=[RECORD] * 5).replace("总计交易额为:0.00", "总计交易额为:-123.45")
    result = parse_transactions(html, ACCOUNT, START, END)
    assert result["coverage"]["total_records"] == result["coverage"]["rows_read"] == 5
    assert len(result["items"]) == 5 and "-123.45" not in str(result)


@pytest.mark.parametrize("html", [
    history(declared_count=2), history(pages=3, declared_count=1), history(rows=[], pages=0, declared_count=1),
    history().replace('colspan="11"', 'colspan="10"'),
    history().replace("总计交易额为", "新汇总含义"),
    history().replace("</table>", "<tr><td>汇总后的未知数据</td></tr></table>"),
    history().replace("本次查询共涉及:1", "本次查询共涉及:未知"),
    history().replace("本次查询共涉及:1次交易", "本次查询共涉及:1次交易额"),
])
def test_summary_count_or_structure_changes_cannot_claim_complete_history(html):
    with pytest.raises(AppError) as error:
        parse_transactions(html, ACCOUNT, START, END)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("mutate", [
    lambda h: h.replace("交易发生时间", "发生信息"),
    lambda h: h.replace("交易额", "现有余额"),
    lambda h: h.replace("<th>状态</th>", "<th>状态</th><th>新字段</th>"),
    lambda h: h.replace("<td>-1.50</td>", "<td>-1.50</td><td>多一列</td>"),
    lambda h: h.replace("2026/10/03", "2026/09/03"),
    lambda h: h.replace("2026/10/03", "2026/13/03"),
    lambda h: h.replace("-1.50", "--"),
    lambda h: h.replace("<td>2</td>", "<td>两次</td>"),
    lambda h: h.replace("<td>18.50</td>", "<td colspan='2'>18.50</td>"),
    lambda h: h.replace("<td>成功</td>", "<td><table><tr><td>成功</td></tr></table></td>"),
    lambda h: h.replace("第1页", "第2页"),
    lambda h: h + "<span>共1页，第1页</span>",
    lambda h: h.replace("共1页", "共0页"),
    lambda h: h.replace("<table id=\"tables\">", '<table id="tables"><tr><td>数据在表头前</td></tr>'),
])
def test_history_ambiguity_never_silently_loses_records(mutate):
    with pytest.raises(AppError) as error:
        parse_transactions(mutate(history()), ACCOUNT, START, END)
    assert error.value.code == "schema_changed"


def test_each_nonempty_history_row_must_belong_to_self():
    other = list(RECORD)
    other[1] = "synthetic-other"
    with pytest.raises(AppError) as error:
        parse_transactions(history(rows=[RECORD, other]), ACCOUNT, START, END)
    assert error.value.code == "session_invalid" and "synthetic-other" not in error.value.message


def test_query_forms_use_current_relative_continuation_and_own_account_only():
    form = query_form(selection(), CARD_HISTORY_URL + "?__continue=synthetic-old", "selection")
    assert form.url == CARD_HISTORY_URL + "?__continue=synthetic-selection"
    assert form.account == "synthetic-internal-card"
    assert transaction_type(form, "") == "all" and transaction_type(form, "15") == "15"
    assert query_form(dates(), form.url, "dates").data == {"inputStartDate": "20261001", "inputEndDate": "20261007"}
    with pytest.raises(AppError) as error:
        transaction_type(form, "unobserved-option")
    assert error.value.code == "invalid_transaction_type"


def test_current_query_all_label_is_recognized_for_default_and_explicit_all():
    html = selection().replace(">全部</option>", ">查询全部</option>")
    form = query_form(html, CARD_HISTORY_URL, "selection")
    assert transaction_type(form, "") == transaction_type(form, "all") == "all"
    fake = FakeHTTP([profile(), html, dates(), history()])
    with SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT}, http_factory=lambda *_: fake) as adapter:
        assert adapter.transactions(START, END, "all")["items"][0]["type"] == "扣款"


@pytest.mark.parametrize("mutate", [
    lambda h: h.replace('method="post"', 'method="get"'),
    lambda h: h.replace('action="?', 'action="https://outside.invalid/?'),
    lambda h: h.replace('action="?', 'action="/accountloss.action?'),
    lambda h: h.replace('name="account"', 'name="otherAccount"'),
    lambda h: h.replace('name="inputObject"', 'name="password"'),
    lambda h: h.replace('</form>', '<input type="hidden" name="writeAction" value="yes"></form>'),
    lambda h: h.replace('本人卡</option>', '本人卡</option><option value="second-synthetic-card">旧卡</option>'),
    lambda h: h + h,
])
def test_query_form_changes_cannot_expand_scope_or_send_unknown_fields(mutate):
    with pytest.raises(AppError):
        query_form(mutate(selection()), CARD_HISTORY_URL, "selection")


@pytest.mark.parametrize("url", [
    "http://outside.invalid/accounthisTrjn.action", "//sso.stu.edu.cn/accounthisTrjn.action",
    "/accountloss.action", "/accounthisTrjn.action?password=secret", "/accounthisTrjn.action?__continue=a&__continue=b",
    "/accounthisTrjn.action#fragment", "http://user:pass@smartcard.stu.edu.cn/accounthisTrjn.action",
])
def test_read_urls_reject_noncanonical_or_sensitive_routes(url):
    with pytest.raises(AppError):
        read_url(url, CARD_HISTORY_URL)


def test_continuation_is_only_observed_readonly_proceeding_form():
    assert continuation(proceeding(), CARD_HISTORY_URL) == CARD_HISTORY_URL + "?__continue=synthetic-next"
    assert continuation(history(), CARD_HISTORY_URL) is None
    for html in (proceeding().replace("1000", "60000"), proceeding().replace("submit()", "write()"),
                 proceeding().replace("</form>", '<input name="passwd"></form>'),
                 proceeding().replace("form1", "otherForm")):
        with pytest.raises(AppError):
            continuation(html, CARD_HISTORY_URL)


@pytest.mark.parametrize("start,end", [("2026-10-01", "2026-10-01"), ("2026-10-01", "2026-10-30")])
def test_date_range_includes_both_ends(start, end):
    assert validate_dates(start, end) == (date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("start,end", [("2026-10-01", "2026-10-31"), ("2026-10-07", "2026-10-01"),
                                        ("20261001", "20261007"), ("2026-02-30", "2026-03-01"),
                                        (None, "2026-10-01")])
def test_bad_dates_fail_before_network(start, end):
    with pytest.raises(AppError) as error:
        validate_dates(start, end)
    assert error.value.code == "invalid_date_range"


class FakeHTTP:
    def __init__(self, responses, on_request=None):
        self.responses = iter(responses)
        self.calls = []
        self.on_request = on_request

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def request(self, url, *, data=None):
        self.calls.append((url, data))
        if self.on_request:
            self.on_request()
        html = next(self.responses)
        return httpx.Response(200, content=html.encode("utf-8"), request=httpx.Request("GET", url))


class FakeVault:
    def __init__(self, tmp_path):
        self.runtime = SimpleNamespace(home=tmp_path)
        self.revision = b"synthetic-session-A"

    def login_revision(self, source):
        assert source == "smartcard"
        return self.revision

    def load(self, source):
        assert source == "smartcard"
        return {"cookies": [], "smartcard_account": ACCOUNT}


def test_adapter_uses_real_forms_and_only_official_read_continuation():
    row = RECORD.copy()
    row[3] = "消费"
    fake = FakeHTTP([profile(), selection(), dates(), proceeding(), history(rows=[row])])
    sleeps = []
    with SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT},
                          http_factory=lambda *_: fake, sleep=sleeps.append) as adapter:
        result = adapter.transactions(START, END, "15")
    assert len(fake.calls) == 5 and sleeps == [1]
    assert fake.calls[0] == (CARD_OVERVIEW_URL, None)
    assert fake.calls[2][1] == {"account": "synthetic-internal-card", "inputObject": "15"}
    assert fake.calls[3][1] == {"inputStartDate": "20261001", "inputEndDate": "20261007"}
    assert fake.calls[4] == (CARD_HISTORY_URL + "?__continue=synthetic-next", {})
    assert result["query"]["transaction_type"] == "15"


def test_adapter_rejects_a_filter_ignored_by_the_source():
    fake = FakeHTTP([profile(), selection(), dates(), history()])
    with (SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT}, http_factory=lambda *_: fake) as adapter,
          pytest.raises(AppError) as error):
        adapter.transactions(START, END, "15")
    assert error.value.code == "schema_changed"


def test_adapter_does_not_guess_pagination():
    fake = FakeHTTP([profile(), selection(), dates(), history(pages=4)])
    with SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT}, http_factory=lambda *_: fake) as adapter:
        result = adapter.transactions(START, END, "")
    assert len(fake.calls) == 4 and result["pending"]


def test_adapter_stops_bounded_processing_and_does_not_retry_queries():
    fake = FakeHTTP([profile(), selection(), dates()] + [proceeding()] * 5)
    sleeps = []
    with (SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT},
                          http_factory=lambda *_: fake, sleep=sleeps.append) as adapter,
          pytest.raises(AppError) as error):
        adapter.transactions(START, END, "")
    assert error.value.code == "request_limit" and len(fake.calls) == 7 and sleeps == [1, 1, 1]


def test_adapter_does_not_renew_or_submit_after_login_expiry():
    fake = FakeHTTP([profile(), selection(), dates(), '<input type="password">'])
    with (SmartcardAdapter({"cookies": [], "smartcard_account": ACCOUNT}, http_factory=lambda *_: fake) as adapter,
          pytest.raises(AppError) as error):
        adapter.transactions(START, END, "")
    assert error.value.code == "login_expired" and len(fake.calls) == 4


def test_service_returns_safe_envelope_and_no_private_continuation(tmp_path):
    vault = FakeVault(tmp_path)
    result = card_overview(vault, http_factory=lambda *_: FakeHTTP([profile()]))
    assert result["ok"] and result["source"] == "smartcard" and result["cached"] is False
    assert result["source_url"] == CARD_OVERVIEW_URL and result["transport"] == "school_http"
    assert result["content_trust"] == "untrusted_source_data" and result["checked_at"]
    result = card_transactions(vault, "2026-10-01", "2026-10-07", http_factory=lambda *_: FakeHTTP([
        profile(), selection(), dates(), history(rows=[], pages=0)]))
    assert result["status"] == "ok" and result["source_url"] == CARD_HISTORY_URL
    assert "__continue" not in str(result) and ACCOUNT not in str(result)


@pytest.mark.parametrize("replacement", [b"synthetic-relogin", b"synthetic-logout", b"synthetic-other-account"])
def test_generation_changes_discard_even_successful_results(tmp_path, replacement):
    vault = FakeVault(tmp_path)

    def mutate():
        vault.revision = replacement

    with pytest.raises(AppError) as error:
        card_overview(vault, http_factory=lambda *_: FakeHTTP([profile()], mutate))
    assert error.value.code == "session_changed"


def test_invalid_input_and_missing_encrypted_identity_do_not_open_network(tmp_path):
    def fail_factory(*_):
        raise AssertionError("network must not initialize")

    with pytest.raises(AppError):
        card_transactions(FakeVault(tmp_path), "wrong", "wrong", http_factory=fail_factory)
    with pytest.raises(AppError) as error:
        SmartcardAdapter({"cookies": []}, http_factory=fail_factory)
    assert error.value.code == "session_invalid"
