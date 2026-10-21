"""Owned direct browser and school form interaction; workflow is in service.py."""
from __future__ import annotations

import re
import time
from contextlib import contextmanager, suppress
from datetime import date
from urllib.parse import parse_qs, urlparse

from ...runtime import AppError
from . import submission
from .parser import on_page, parse_form
from .schema import (
    DIRECT_BROWSER_ARGS,
    FORM_SCRIPT,
    PAGE_PROBLEM_SCRIPT,
    POSTBACK_FIELDS,
    REPAIR_FORM,
    REPAIR_HOME,
    SELECT_FIELDS,
    TEXT_FIELDS,
    TIME_EVENTS,
)


def direct_preflight() -> dict:
    """Fresh, parallel, bounded direct checks before starting a login window."""
    from ...connectivity import direct_checks
    checks = direct_checks("sangpushan_repair")
    if not all(result.get("reachable") is True for result in checks.values()):
        raise AppError("repair_direct_unavailable", "报修站或统一认证直连暂不可用。请调用 diagnose_campus_network "
                       "区分服务、DNS和本机代理情况；校外普通代理不等于校内接入，不会自动切换或重发报修。", "repair")
    return {"transport": "direct", "checks": checks}

def field_plan(fields: dict) -> list[dict]:
    """Only observed form controls; never return selectors for submit/upload."""
    plan = [{"field": key, "selector": selector, "action": "fill", "value": fields[key]}
            for key, selector in TEXT_FIELDS.items() if fields.get(key)]
    if fields.get("email"):
        plan.append({"field": "email", "selector": "#tb_email", "action": "fill", "value": fields["email"]})
    # The legacy form immediately checks start <= end on change. End goes first.
    for key, selector in SELECT_FIELDS.items():
        if fields.get(key):
            value = fields[key]
            plan.append({"field": key, "selector": selector, "action": "select_label",
                         "value": f"{int(value.split(':')[0])}:00" if key.startswith("visit_") else value})
    if fields.get("visit_date"):
        plan.append({"field": "visit_date", "selector": "#tb_bookingtime1", "action": "calendar",
                     "value": fields["visit_date"]})
    return plan

def request_allowed(url: str, method: str, post_data: str | None = None) -> bool:
    """Allow SSO and the two observed time-validation events, never btn_OK.

    WebForms posts the whole form on a time change. Inspect bounded data only in
    memory; never include ViewState, body text or callback URLs in diagnostics.
    """
    try:
        p = urlparse(url)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return False
        if p.hostname == "sso.stu.edu.cn":
            return method in {"GET", "HEAD", "POST"}
        if p.hostname != "repair.stu.edu.cn":
            return False
        if method in {"GET", "HEAD"}:
            return True
        if method != "POST" or p.path != "/student_applybill.aspx" or p.query or not post_data:
            return False
        if len(post_data) > 262144:
            return False
        data = parse_qs(post_data, keep_blank_values=True, max_num_fields=64)
        return (set(data).issubset(POSTBACK_FIELDS) and
                len(data.get("__EVENTTARGET", [])) == 1 and data["__EVENTTARGET"][0] in TIME_EVENTS and
                data.get("__EVENTARGUMENT", [""]) == [""])
    except ValueError:
        return False

def select_calendar(page, value: str) -> bool:
    target = date.fromisoformat(value)
    page.locator("#tb_bookingtime1").click()
    day_selector = f'td[onclick="day_Click({target.year},{target.month},{target.day});"]'
    # My97 renders an anonymous iframe with visible year/month controls.
    for frame in page.frames:
        if frame == page.main_frame or not frame.locator("#dpOkInput").count():
            continue
        day = frame.locator(day_selector)
        if day.count() == 1 and day.is_visible():
            day.click()
            return True
    # Keep the window available for a human; never alter the readonly property.
    page.locator("#tb_title").click()
    return False

def read_form(page, plan: list[dict]) -> dict:
    """Read only explicitly filled controls and required email, never SSO fields."""
    actual = {}
    for step in plan:
        locator = page.locator(step["selector"])
        if step["action"] == "select_label":
            actual[step["field"]] = locator.locator("option:checked").inner_text().strip()
        else:
            actual[step["field"]] = locator.input_value()
    email = page.locator("#tb_email").input_value().strip()
    missing = [] if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else ["email"]
    if "visit_date" in actual and not actual["visit_date"]:
        missing.append("visit_date")
    return {"matches": {step["field"]: actual[step["field"]] == step["value"] for step in plan},
            "missing_page_fields": missing}

def fill_form(page, fields: dict) -> dict:
    if page.url != REPAIR_FORM:
        raise AppError("wrong_repair_page", "当前页面不是已核验的学生社区报修表，停止填写。", "repair")
    plan = field_plan(fields)
    # Check the complete schema and exact dropdown labels before touching PII.
    if page.locator("#tb_email").count() != 1 or not page.locator("#tb_email").is_visible():
        raise AppError("schema_changed", "学校表单缺少必填邮箱，停止自动填写。", "repair")
    for step in plan:
        locator = page.locator(step["selector"])
        if locator.count() != 1 or not locator.is_visible():
            raise AppError("schema_changed", "学校表单字段发生变化，停止自动填写，请检查学校窗口。", "repair")
        if step["action"] == "select_label":
            labels = locator.locator("option").all_text_contents()
            if labels.count(step["value"]) != 1:
                raise AppError("repair_option_missing", "学校表单没有唯一匹配的学院、楼座或预约时间；"
                               "请在窗口核对选项。", "repair")
    for step in plan:
        locator = page.locator(step["selector"])
        if step["action"] == "fill":
            locator.fill(step["value"])
        elif step["action"] == "select_label":
            if step["selector"].removeprefix("#") in TIME_EVENTS and "__doPostBack" in (
                    locator.get_attribute("onchange") or ""):
                with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                    locator.select_option(label=step["value"])
            else:
                locator.select_option(label=step["value"])
        else:
            select_calendar(page, step["value"])
    return read_form(page, plan)

def capture_form(page) -> dict:
    """Extract business fields only; parser verifies target, cardinality and values."""
    if page.url != REPAIR_FORM:
        raise AppError("wrong_repair_page", "当前不是学生社区报修表，请重新打开表单。", "repair")
    check_page(page)
    if page.locator("form").count() != 1:
        raise AppError("schema_changed", "学校页面未包含唯一报修表单，停止提交。", "repair")
    return parse_form(page.locator("form").evaluate(FORM_SCRIPT, sorted(POSTBACK_FIELDS)))


def check_page(page) -> None:
    problem = page.locator("body").evaluate(PAGE_PROBLEM_SCRIPT)
    if problem == "login_required":
        raise AppError("repair_login_required", "学校登录已失效，请在报修窗口重新登录。", "repair")
    if problem == "source_error":
        raise AppError("repair_source_error", "学校报修表返回服务器错误，请稍后再试。", "repair")


class BrowserSession:
    def __init__(self, page, gate, stop, update):
        self.page, self.gate, self.stop, self.update = page, gate, stop, update

    @property
    def request_sent(self) -> bool:
        return self.gate.sent

    def open(self, fields: dict) -> dict | None:
        page = self.page
        page.goto(REPAIR_HOME, wait_until="domcontentloaded", timeout=45000)
        self.update(status="waiting_for_login")
        deadline = time.monotonic() + 300
        while not self.stop.is_set() and time.monotonic() < deadline:
            if page.is_closed():
                self.update(status="closed")
                return None
            if on_page(page.url, "/student.aspx"):
                break
            page.wait_for_timeout(500)
        else:
            self.update(status="closed" if self.stop.is_set() else "login_timeout")
            return None
        if self.stop.is_set():
            return None
        self.update(status="opening_form")
        page.goto(REPAIR_FORM, wait_until="domcontentloaded", timeout=45000)
        check_page(page)
        self.update(status="filling")
        return fill_form(page, fields)

    def capture(self):
        return capture_form(self.page)

    def prepare_receipt(self):
        self.gate.verifier.prepare(self.page)

    def submit(self, capture):
        return submission.submit_reviewed_form(self.page, self.gate, capture)

    def check(self):
        return submission.check_submission_result(self.page, self.gate)

    def is_closed(self):
        return self.page.is_closed()

    def on_form(self):
        return self.page.url == REPAIR_FORM

    def wait(self, milliseconds):
        self.page.wait_for_timeout(milliseconds)


@contextmanager
def open_browser(stop, update):
    """Own and close the entire temporary session, including partial startup failure."""
    from playwright.sync_api import sync_playwright

    from ...auth import prepare_browser

    update(network=direct_preflight())
    if stop.is_set():
        raise AppError("repair_window_required", "报修窗口已取消打开。", "repair")
    with sync_playwright() as p:
        prepare_browser(p, lambda phase: update(status=phase))
        if stop.is_set():
            raise AppError("repair_window_required", "报修窗口已取消打开。", "repair")
        browser = p.chromium.launch(headless=False, args=DIRECT_BROWSER_ARGS)
        try:
            context = browser.new_context(ignore_https_errors=False, service_workers="block")
            gate = submission.SubmissionGate(cancelled=stop.is_set)

            def guard(route):
                try:
                    request = route.request
                    allowed = request_allowed(request.url, request.method)
                    if not allowed and request.url == REPAIR_FORM and request.method == "POST":
                        body = request.post_data
                        allowed = request_allowed(request.url, request.method, body)
                        if not allowed and gate.allows(request.url, request.method, body):
                            submission.forward_submission(route)
                            return
                    route.continue_() if allowed else route.abort()
                except Exception:
                    with suppress(Exception):
                        route.abort()

            context.route("**/*", guard)
            page = context.new_page()
            page.set_default_timeout(5000)
            yield BrowserSession(page, gate, stop, update)
        finally:
            browser.close()
