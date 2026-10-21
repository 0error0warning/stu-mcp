"""Direct HTTP WebForms session, with the same reviewed single-send workflow."""
from __future__ import annotations

import copy
import re
import time
from contextlib import contextmanager, nullcontext
from http.cookiejar import Cookie
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from ...auth_http.transport import HTTPFlow
from ...runtime import AppError, key_lock
from . import http_parser as html
from .parser import clean, detail_link, list_rows, match_detail, refresh_detail, school_time
from .schema import LIST_URL, REPAIR_FORM, SELECT_FIELDS, TEXT_FIELDS, TIME_EVENTS
from .submission import SubmissionGate, check_submission_result


def verify_login(flow: HTTPFlow, *, response=None) -> dict:
    """CAS repair proof: the actual unfiltered personal list, including explicit empty state."""
    response = response if response is not None else flow.get(LIST_URL)
    if response.status_code != 200:
        raise AppError("repair_login_required", "未能核验报修登录，请重新登录此来源。", "repair")
    parsed = urlsplit(str(response.url))
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (parsed.scheme != "https" or parsed.netloc != "repair.stu.edu.cn" or parsed.path != "/student.aspx"
            or parsed.fragment or set(query) - {"ticket"}
            or "ticket" in query and (len(query["ticket"]) != 1 or not 1 <= len(query["ticket"][0]) <= 8192)):
        raise html.changed()
    try:
        rows = list_rows(html.list_snapshot(response.text))
    except ValueError:
        raise html.changed() from None
    return {"authenticated": True, "list_verified": True, "orders": len(rows)}


class HttpReceiptVerifier:
    def __init__(self, session):
        self.session = session
        self.known_orders = self.capture = self.receipt = None
        self.last_check = "not_checked"

    def prepare(self, _page=None):
        self.session.budget(10)
        self.known_orders = None
        self.known_orders = frozenset(row["order_id"] for row in self.session.read_list())

    def verify(self, _page=None, *, timeout=10):
        if self.capture is None or self.known_orders is None:
            self.last_check = "baseline_missing"
            return None
        self.session.budget(timeout)
        try:
            row = self.receipt
            if row is None:
                self.last_check = "list_read"
                rows = self.session.read_list()
                values = {field["key"]: field["value"] for field in self.capture["fields"]}
                timestamp = school_time(values.get("tb_happentime", ""))
                if timestamp is None:
                    self.last_check = "form_timestamp_missing"
                    return None
                matches = [row for row in rows if row["order_id"] not in self.known_orders
                           and row["order_id"].startswith(timestamp.strftime("%Y%m%d"))
                           and school_time(row["time"]) == timestamp
                           and clean(values.get("tb_title", "")).startswith(
                               row["title"].removesuffix("...").removesuffix("…"))]
                if len(matches) != 1:
                    self.last_check = "no_unique_new_order"
                    return None
                row = matches[0]
            link = detail_link(row["detail_url"])
            if not link or link[0] != row["detail_url"]:
                self.last_check = "detail_identity_changed"
                return None
            self.last_check = "detail_read"
            raw = html.detail_snapshot(self.session.read(link[0]))
            receipt = refresh_detail(raw, self.receipt) if self.receipt else match_detail(raw, self.capture, row)
            if receipt:
                self.receipt = receipt
            self.last_check = "verified" if receipt else "detail_mismatch"
            return receipt
        except AppError as error:
            self.last_check = error.code
            return None
        except Exception:
            self.last_check = "verification_unavailable"
            return None


class HttpRepairSession:
    """Own one temporary in-memory school form; never accept arbitrary URL or credentials."""
    def __init__(self, flow: HTTPFlow, stop, update=lambda **_: None, *, lease=nullcontext, sso=None):
        self.flow, self.stop, self.update, self.lease = flow, stop, update, lease
        self.sso = sso
        self.form, self.closed = None, False
        self.verifier = HttpReceiptVerifier(self)
        self.gate = SubmissionGate(cancelled=stop.is_set, verifier=self.verifier)

    @property
    def request_sent(self):
        return self.gate.sent

    def budget(self, seconds=30):
        self.flow.deadline = time.monotonic() + max(.01, min(45, seconds))
        self.flow.requests = 0
        if self.sso is not None:
            self.sso.deadline, self.sso.requests = self.flow.deadline, 0

    def _check(self):
        if self.stop.is_set() or self.closed:
            raise AppError("repair_session_closed", "报修会话已关闭，未继续操作。", "repair")

    def read(self, url):
        detail = detail_link(url)
        if url not in {LIST_URL, REPAIR_FORM} and (not detail or detail[0] != url):
            raise AppError("unsafe_url", "报修读取地址超出此适配器范围。", "repair")
        with self.lease():
            current, target, base_query = url, urlsplit(url), parse_qs(urlsplit(url).query, keep_blank_values=True)
            callback_expected, seen_tickets = False, set()
            for _ in range(8):
                self._check()
                parsed = urlsplit(current)
                if parsed.hostname == "sso.stu.edu.cn":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if (callback_expected or self.sso is None or parsed.scheme != "https" or parsed.port not in {None, 443}
                            or parsed.username or parsed.password or parsed.fragment
                            or not re.fullmatch(r"/login(?:;jsessionid=[A-Za-z0-9.]+)?", parsed.path)
                            or query != {"service": [url]}):
                        raise AppError("repair_login_required", "报修需要重新登录或认证跳转发生变化；未提交密码。", "repair")
                    response = self.sso.get(current)
                    from ...auth_http.cas import _bridge_service_token
                    _bridge_service_token(self.sso, self.flow, "repair")
                    if not response.is_redirect:
                        raise AppError("repair_login_required", "报修统一认证已失效，请在本人终端重新登录 repair。", "repair")
                    callback_expected = True
                else:
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    ticket = query.pop("ticket", None)
                    if (parsed.scheme != target.scheme or parsed.netloc != target.netloc or parsed.path != target.path
                            or parsed.fragment or query != base_query or (ticket is not None) != callback_expected
                            or ticket is not None and (len(ticket) != 1 or not 1 <= len(ticket[0]) <= 8192
                                                       or ticket[0] in seen_tickets)):
                        raise AppError("unsafe_url", "报修认证未返回本次固定读取页面；已停止。", "repair")
                    if ticket:
                        seen_tickets.add(ticket[0])
                    callback_expected = False
                    response = self.flow.get(current)
                    if response.status_code == 200:
                        return response.text
                if response.status_code in {302, 303} and response.headers.get("location"):
                    current = urljoin(str(response.url), response.headers["location"])
                    continue
                raise AppError("repair_login_required" if response.is_redirect or response.status_code == 401
                               else "repair_source_error", "学校报修读取未成功；没有自动重登或重发。", "repair")
            raise AppError("repair_authentication_budget", "报修页面认证跳转超过上限；没有重发密码或提交。", "repair")

    def read_list(self):
        try:
            return list_rows(html.list_snapshot(self.read(LIST_URL)))
        except ValueError:
            raise html.changed() from None

    def _post(self, event, *, approved=None):
        if self.form is None or event not in TIME_EVENTS | {"btn_OK"}:
            raise html.changed()
        data = html.payload(self.form, event)
        # HTML form serialization normalizes successful values to CRLF.
        body = urlencode({key: [value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
                               for value in values] for key, values in data.items()}, doseq=True)
        if len(body) > 262144:
            raise AppError("unsupported_repair_fields", "学校表单超过已核验的大小上限，已停止发送。", "repair")
        with self.lease():
            self._check()
            if event == "btn_OK":
                if approved is None or html.capture(self.form)["fingerprint"] != approved["fingerprint"]:
                    raise AppError("repair_form_changed", "表单已改变，请重新预览和确认。", "repair")
                if not self.gate.allows(REPAIR_FORM, "POST", body):
                    raise AppError("repair_submission_blocked", "此次提交未通过单次授权核对。", "repair")
            elif self.request_sent:
                raise AppError("repair_already_sent", "请求已发出，不能再次填写或提交。", "repair")
            # HTTPFlow never follows redirects or retries; the send gate is
            # consumed before this call, including unknown transport outcomes.
            response = self.flow.post(REPAIR_FORM, content=body.encode("utf-8"),
                                      headers={"Content-Type": "application/x-www-form-urlencoded",
                                               "Origin": "https://repair.stu.edu.cn", "Referer": REPAIR_FORM})
        if event != "btn_OK":
            if response.status_code != 200:
                raise AppError("repair_time_validation_failed", "学校预约校验未成功，未发送正式报修。", "repair")
            self.form = html.form_document(response.text)

    def _apply(self, fields):
        for key, selector in TEXT_FIELDS.items():
            if fields.get(key):
                html.set_value(self.form, selector[1:], fields[key])
        if fields.get("email"):
            html.set_value(self.form, "tb_email", fields["email"])
        for key in ("college", "building"):
            if fields.get(key):
                html.set_value(self.form, SELECT_FIELDS[key][1:], fields[key], label=True)

    def open(self, fields):
        self.budget()
        self.update(status="opening_form")
        self.read_list()  # Actual source proof, never cached success or another system.
        self.form = html.form_document(self.read(REPAIR_FORM))
        self.update(status="filling")
        self._apply(fields)
        for key, event in (("visit_end", "DropDownList1"), ("visit_start", "ddl_time1")):
            label = f"{int(fields[key].split(':')[0])}:00"
            html.set_value(self.form, event, label, label=True)
            node = html.control(self.form, event)
            onchange = str(node.get("onchange", ""))
            if onchange:
                signature = onchange.replace("\\'", "'").replace('\\"', '"')
                if not re.search(r"__doPostBack\(['\"]" + event + r"['\"],\s*['\"]['\"]\)", signature):
                    raise html.changed()
                self._post(event)
                # Keep server-returned business values. Reapplying the full
                # draft here would hide a validation/reset from readback.
        if fields.get("visit_date"):
            html.set_value(self.form, "tb_bookingtime1", fields["visit_date"])
        captured = self.capture()
        display = {field["key"]: field["value"] for field in captured["fields"]}
        matches = {}
        for key, selector in TEXT_FIELDS.items():
            if fields.get(key):
                matches[key] = display.get(selector[1:]) == fields[key]
        for key, selector in SELECT_FIELDS.items():
            if fields.get(key):
                expected = f"{int(fields[key].split(':')[0])}:00" if key.startswith("visit_") else fields[key]
                matches[key] = display.get(selector[1:]) == expected
        if fields.get("visit_date"):
            matches["visit_date"] = display.get("tb_bookingtime1") == fields["visit_date"]
        if fields.get("email"):
            matches["email"] = display.get("tb_email") == fields["email"]
        return {"matches": matches, "missing_page_fields": sorted({p["field"] for p in captured["problems"]})}

    def capture(self):
        with self.lease():
            self._check()
            if self.form is None:
                raise html.changed()
            return html.capture(self.form)

    def prepare_receipt(self):
        self.verifier.prepare()

    def submit(self, capture):
        if self.request_sent:
            return self.check()
        if self.verifier.known_orders is None:
            return {"status": "submission_not_sent", "request_sent": False, "submitted_by_mcp": False}
        started = time.monotonic()
        self.budget(20)
        self.gate.approved_body = capture["body"]
        self.verifier.capture = copy.deepcopy(capture)
        try:
            self._post("btn_OK", approved=capture)
        except AppError:
            if not self.request_sent:
                raise
        finally:
            self.gate.approved_body = None
        return check_submission_result(None, self.gate, timeout=max(.01, min(10, 20 - (time.monotonic() - started))))

    def check(self):
        return check_submission_result(None, self.gate)

    def is_closed(self):
        return self.closed

    def on_form(self):
        return self.form is not None and not self.closed

    def wait(self, milliseconds):
        self.stop.wait(milliseconds / 1000)


@contextmanager
def open_http(stop, update, *, vault=None, transport=None):
    if vault is None:
        raise AppError("needs_login", "请先在本人终端运行 stu-mcp login repair。", "repair")
    with key_lock(vault.runtime.home, "repair"):
        revision = vault.login_revision("repair")
        state = vault.load("repair")
    update(login_session_saved=True)

    @contextmanager
    def lease():
        with key_lock(vault.runtime.home, "repair"):
            if vault.login_revision("repair") != revision:
                raise AppError("session_changed", "报修登录已退出或切换，原预览不能继续提交。", "repair")
            yield

    def restore(flow, saved, host):
        if not isinstance(saved, dict) or not isinstance(saved.get("cookies"), list) or len(saved["cookies"]) > 128:
            raise AppError("session_invalid", "报修登录态格式无效，请重新登录此来源。", "repair")
        for item in saved["cookies"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("value"), str):
                raise AppError("session_invalid", "报修登录态格式无效，请重新登录此来源。", "repair")
            domain = str(item.get("domain", ""))
            cookie_host = domain.lstrip(".").lower()
            expiry = item.get("expires", -1)
            allowed = cookie_host == host or host == "sso.stu.edu.cn" and domain.lower() in {"stu.edu.cn", ".stu.edu.cn"}
            if (not allowed or host == "repair.stu.edu.cn" and item["name"].lower() == "castgc"
                    or not isinstance(expiry, (int, float)) or 0 < expiry <= time.time()):
                continue
            flow.client.cookies.jar.set_cookie(Cookie(
                0, str(item["name"]), str(item["value"]), None, False, domain, bool(domain), domain.startswith("."),
                str(item.get("path", "/")), True, bool(item.get("secure", False)), None if expiry <= 0 else int(expiry),
                expiry <= 0, None, None, {}, False))
    with (HTTPFlow("repair", ("repair.stu.edu.cn",), transport=transport, timeout=45, max_requests=24) as flow,
          HTTPFlow("repair", ("sso.stu.edu.cn",), transport=transport, timeout=45, max_requests=16) as sso):
        restore(flow, state, "repair.stu.edu.cn")
        restore(sso, state.get("repair_sso_state", {"cookies": []}), "sso.stu.edu.cn")
        session = HttpRepairSession(flow, stop, update, lease=lease, sso=sso)
        try:
            yield session
        finally:
            session.closed = True
