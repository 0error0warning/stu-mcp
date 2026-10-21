"""One password submission to school HTTPS CAS, with isolated service sessions."""
from __future__ import annotations

import re
from collections.abc import Callable
from copy import copy
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from ..features.jw.parser import jw_authenticated
from ..features.mystu.parser import parse_inventory
from ..features.mystu.schema import COURSES_URL, VALIDATE_URL
from ..parsing import is_login
from ..runtime import AppError
from ..sources import JW_HOME, JW_LOGIN_URL, MYSTU_BASE
from .transport import HTTPFlow
from .types import Candidate

SSO = "https://sso.stu.edu.cn/login"
REPAIR = "https://repair.stu.edu.cn/"
ENTRIES = {"jw": JW_LOGIN_URL, "mystu": MYSTU_BASE + "/discussion/my-courses", "repair": REPAIR}
SERVICES = {"jw": JW_LOGIN_URL, "mystu": ENTRIES["mystu"], "repair": REPAIR + "default.aspx"}
ELC_SERVICE = MYSTU_BASE + "/courses/elc/login/index.php"
MOODLE_SERVICES = {"elc": ELC_SERVICE, "campus": MYSTU_BASE + "/courses/campus/login/index.php"}
MOODLE_PATHS = {name: {f"/courses/{name}{tail}" for tail in ("", "/", "/index.php", "/login/index.php", "/my/")}
                for name in MOODLE_SERVICES}
MOODLE_ALIASES = {f"/courses/{name}" for name in MOODLE_SERVICES}
MOODLE_TEST_PATHS = {f"/courses/{name}/{tail}" for name in MOODLE_SERVICES
                     for tail in ("index.php", "login/index.php")}
JW_PATHS = {"", "/", "/jwglxt/xtgl/login_slogin.html", "/jsxsd", "/jsxsd/",
            "/jsxsd/xk/LoginToXk", "/jsxsd/framework/xsMainV.htmlx", "/jsxsd/framework/xsMainV_new.htmlx"}
SERVICE_PATHS = {"mystu": {"/discussion/my-courses"} | set.union(*MOODLE_PATHS.values()),
                 "repair": {"/", "/default.aspx", "/student.aspx"}, "jw": JW_PATHS}


def account(value: object) -> str:
    return str(value).strip().lower().removesuffix("@stu.edu.cn")


def _changed(source: str) -> AppError:
    return AppError("authentication_schema_changed", "学校认证页面或跳转结构发生变化；未猜测字段或重发密码。", source)


def _bridge_service_token(sso: HTTPFlow, school: HTTPFlow, source: str) -> None:
    """The school Web SSO token is required by these HTTPS service gateways.

    Keep CAS's ticket-granting and host-only cookies in its separate jar. Only
    the observed parent-domain _UT_ token is narrowed to this exact service
    host; it never crosses the explicitly insecure legacy JW callback.
    """
    if source not in {"mystu", "repair"}:
        return
    tokens = [cookie for cookie in sso.client.cookies.jar if cookie.name == "_UT_"]
    if not tokens:
        return  # Services may instead establish their own normal session.
    if len(tokens) != 1:
        raise AppError("unsafe_cookie_scope", "学校服务令牌存在歧义；未混用中央认证会话。", source)
    token = tokens[0]
    if (token.domain.lower() not in {"stu.edu.cn", ".stu.edu.cn"} or not token.domain_specified
            or token.path != "/" or not token.value or len(token.value) > 8192
            or any(ord(char) < 32 or ord(char) == 127 for char in token.value)):
        raise AppError("unsafe_cookie_scope", "学校服务令牌范围发生变化；未扩大认证 Cookie 权限。", source)
    if token.is_expired():
        return
    scoped = copy(token)
    scoped.domain = urlsplit(ENTRIES[source]).hostname
    scoped.domain_specified, scoped.domain_initial_dot, scoped.secure = False, False, True
    school.client.cookies.jar.set_cookie(scoped)


def _cas_service(url: str, source: str, services: set[str]) -> str:
    p = urlsplit(url)
    query = parse_qs(p.query, keep_blank_values=True)
    if (p.scheme != "https" or p.hostname != "sso.stu.edu.cn" or p.port not in {None, 443}
            or p.username or p.password or p.fragment or not re.fullmatch(r"/login(?:;jsessionid=[A-Za-z0-9.]+)?", p.path)
            or set(query) - {"service", "gateway"} or len(query.get("service", [])) != 1
            or query["service"][0] not in services or "gateway" in query and query["gateway"] != ["true"]):
        raise _changed(source)
    return query["service"][0]


def parse_form(response: httpx.Response, source: str, service: str) -> tuple[str, dict]:
    soup = BeautifulSoup(response.content, "html.parser")
    if response.status_code != 200:
        raise AppError("authentication_unconfirmed", "统一认证没有返回可验证的登录表单。", source)
    if soup.select('input[name*="captcha" i], input[id*="captcha" i], input[autocomplete="one-time-code"], '
                   'iframe[src*="captcha" i], input[name*="sms" i], input[name*="otp" i], '
                   '[class*="slider" i], [class*="geetest" i], [class*="recaptcha" i]'):
        raise AppError("interaction_required", "统一认证要求额外人工挑战；HTTP 登录已停止，可显式选择浏览器兼容。", source)
    forms = [form for form in soup.select("form") if form.select('input[name="username"]')
             and form.select('input[name="password"]')]
    if len(forms) != 1:
        raise _changed(source)
    form = forms[0]
    if (form.get("method", "get").lower() != "post" or len(form.select('input[name="username"]')) != 1
            or len(form.select('input[name="password"]')) != 1):
        raise _changed(source)
    action = urljoin(str(response.url), form.get("action", ""))
    if _cas_service(action, source, {service}) != service:
        raise _changed(source)
    hidden = form.select('input[type="hidden"][name]')
    names = [field["name"] for field in hidden]
    if len(names) != len(set(names)) or set(names) != {"lt", "execution", "_eventId"}:
        raise _changed(source)
    fields = {field["name"]: field.get("value", "") for field in hidden}
    if any(not isinstance(value, str) or not 1 <= len(value) <= 4096 for value in fields.values()):
        raise _changed(source)
    return action, fields


def validate_identity(payload: object, username: str | None = None) -> dict:
    if (not isinstance(payload, dict) or not isinstance(payload.get("username"), str)
            or not payload["username"].strip() or isinstance(payload.get("id"), bool)
            or not isinstance(payload.get("id"), (str, int)) or not str(payload["id"]).strip()
            or any(key in payload and payload[key] is not True for key in ("success", "authenticated"))):
        raise AppError("authentication_unconfirmed", "MySTU 没有返回已核验的身份资料。", "mystu")
    if username is not None and account(payload["username"]) != account(username):
        raise AppError("authentication_identity_mismatch", "MySTU 返回身份与本次登录账号不一致；未保存会话。", "mystu")
    return {"authenticated": True, "identity_verified": True}


def _moodle_instances(inventory) -> list[str]:
    needed = set()
    for course in inventory.courses:
        try:
            parsed = urlsplit(course.url)
            if (parsed.scheme == "https" and parsed.hostname == "my.stu.edu.cn" and parsed.port in {None, 443}
                    and not parsed.username and not parsed.password):
                needed.update(name for name in MOODLE_SERVICES if parsed.path.startswith(f"/courses/{name}/"))
        except ValueError:
            continue  # Unknown course links never expand the authentication route.
    return sorted(needed if inventory.courses else {"elc"})  # Preserve the original empty-inventory ELC login.


def acquire_state(service: str, username: str, password: str, *, check: Callable[[], None] = lambda: None,
                  transport=None, timeout: float = 60, legacy_jw: bool = False) -> Candidate:
    if service not in ENTRIES:
        raise AppError("unknown_service", "请选择教务、MySTU 或宿舍报修。")
    username = account(username)
    if (not username or len(username) > 128 or any(c.isspace() for c in username)
            or not isinstance(password, str) or not 1 <= len(password) <= 1024):
        raise AppError("invalid_authentication_input", "账号或密码为空或超出长度范围。", service)
    host = urlsplit(ENTRIES[service]).hostname
    actual_service = SERVICES[service]
    if service == "jw":
        if not legacy_jw:
            raise AppError("insecure_transport", "当前教务官方回调使用 HTTP；请明确使用 --allow-http-callback，"
                           "或在本地设置中启用教务兼容。密码仍只发送至 HTTPS 统一认证。", "jw")
        actual_service = actual_service.replace("https:", "http:", 1)
    allow_http = (lambda url: urlsplit(url).hostname == "jw.stu.edu.cn"
                  and urlsplit(url).path in JW_PATHS) if service == "jw" and legacy_jw else None
    with (HTTPFlow(service, ("sso.stu.edu.cn",), transport=transport, timeout=timeout) as sso,
          HTTPFlow(service, (host,), transport=transport, timeout=timeout, allow_http=allow_http) as school):
        cas_services = {actual_service}
        if service == "mystu":
            cas_services.update(MOODLE_SERVICES.values())
        elif service == "repair":
            # The community gateway authenticates default.aspx, then asks CAS
            # for a separate student.aspx service ticket through normal GETs.
            cas_services.add(REPAIR + "student.aspx")

        def guard_budget():
            check()
            if sso.requests + school.requests >= 32:
                raise AppError("authentication_budget", "学校认证请求总数超过上限；没有重发密码。", service)

        def follow(url: str, *, allow_cas: bool = False, max_hops: int = 8, moodle: str | None = None) -> httpx.Response:
            for _ in range(max_hops):
                guard_budget()
                p = urlsplit(url)
                if p.hostname == "sso.stu.edu.cn":
                    _cas_service(url, service, {MOODLE_SERVICES[moodle]} if moodle else cas_services)
                    if not allow_cas:
                        raise AppError("login_rejected", "服务返回统一认证；本次会话未验证。", service)
                    flow = sso
                else:
                    if p.hostname != host or p.path not in (MOODLE_PATHS[moodle] if moodle else SERVICE_PATHS[service]):
                        raise _changed(service)
                    query = parse_qs(p.query, keep_blank_values=True)
                    if service == "mystu" and p.path in MOODLE_ALIASES and query:
                        raise _changed(service)
                    moodle_test = (service == "mystu" and p.path in MOODLE_TEST_PATHS
                                   and set(query) == {"testsession"})
                    allowed_keys = {"method", "ticket1"} if service == "jw" and p.path == "/jsxsd/xk/LoginToXk" else {"ticket"}
                    if (moodle_test and (len(query["testsession"]) != 1
                                         or not re.fullmatch(r"[0-9]{1,20}", query["testsession"][0]))
                            or not moodle_test and (set(query) - allowed_keys or any(
                                len(values) != 1 or not values[0] or len(values[0]) > 8192 for values in query.values()))):
                        raise _changed(service)
                    flow = school
                    if service == "jw" and any(cookie.domain.lstrip(".") != host for cookie in school.client.cookies.jar):
                        raise AppError("unsafe_cookie_scope", "教务会话包含其他域 Cookie；已停止 HTTP 回调。", service)
                page = flow.get(url)
                if flow is sso:
                    _bridge_service_token(sso, school, service)
                if page.is_redirect and page.headers.get("location"):
                    url = urljoin(str(page.url), page.headers["location"])
                    continue
                return page
            raise AppError("authentication_budget", "学校认证跳转超过上限；没有重发密码。", service)

        guard_budget()
        # Prime isolated service state; only the school's explicit HTTPS Web
        # token may later bridge CAS into MySTU/repair, never CAS credentials.
        if service == "jw":
            initial = school.get(ENTRIES[service])
            if initial.status_code != 200:
                raise _changed(service)
            login_url = SSO + "?" + str(httpx.QueryParams({"service": actual_service}))
            guard_budget()
            page = sso.get(login_url)
        else:
            page = follow(ENTRIES[service], allow_cas=True)
            login_url = str(page.url)
            if _cas_service(login_url, service, {actual_service}) != actual_service:
                raise _changed(service)
        action, data = parse_form(page, service, actual_service)
        data.update(username=username, password=password)
        guard_budget()
        try:
            reply = sso.post(action, data=data, credential=True)
        finally:
            data.clear()
            password = ""
        if not reply.is_redirect or not reply.headers.get("location"):
            raise AppError("login_rejected", "统一认证未确认登录；没有再次提交密码。", service)
        target = urljoin(str(reply.url), reply.headers["location"])
        destination, expected = urlsplit(target), urlsplit(actual_service)
        tickets = parse_qs(destination.query, keep_blank_values=True)
        if (destination.scheme != expected.scheme or destination.netloc != expected.netloc
                or destination.path != expected.path or destination.fragment or set(tickets) != {"ticket"}
                or len(tickets["ticket"]) != 1 or not tickets["ticket"][0]):
            raise _changed(service)
        _bridge_service_token(sso, school, service)
        landing = follow(target, allow_cas=service == "repair")
        check()
        if service == "jw":
            guard_budget()
            home = school.get(JW_HOME)
            if home.status_code != 200 or not jw_authenticated(home.text):
                raise AppError("authentication_unconfirmed", "教务没有返回可验证的学生主页。", "jw")
            proof = {"authenticated": True, "student_home_verified": True, "http_callback_used": True}
        elif service == "mystu":
            headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/plain, */*",
                       "Referer": ENTRIES["mystu"]}
            guard_budget()
            identity = school.get(VALIDATE_URL, headers=headers)
            if identity.status_code != 200:
                raise AppError("authentication_unconfirmed", "MySTU 身份校验未通过。", service)
            try:
                proof = validate_identity(identity.json(), username)
                guard_budget()
                courses = school.get(COURSES_URL, headers=headers)
                if courses.status_code != 200:
                    raise _changed(service)
                inventory = parse_inventory(courses.json())
            except (ValueError, UnicodeError):
                raise _changed(service) from None
            proof.update(courses_verified=True, course_count=len(inventory.courses),
                         course_inventory_complete=inventory.complete)
            bootstrap = {}
            for name in _moodle_instances(inventory):
                try:
                    page = follow(MYSTU_BASE + f"/courses/{name}/", allow_cas=True, max_hops=12, moodle=name)
                    soup = BeautifulSoup(page.content, "html.parser")
                    final_url = urlsplit(str(page.url))
                    verified = (page.status_code == 200 and final_url.hostname == "my.stu.edu.cn"
                                and final_url.path in MOODLE_PATHS[name] and not is_login(page.text)
                                and not soup.select('input[type="password"]')
                                and bool(soup.select('a[href*="/login/logout.php"]')))
                    status = "verified" if verified else "moodle_session_unconfirmed"
                except AppError as error:
                    if error.code == "session_changed":
                        raise
                    verified = False
                    status = error.code if error.code in {
                        "authentication_budget", "authentication_network_error", "authentication_response_limit",
                        "authentication_schema_changed", "insecure_authentication_route", "login_rejected",
                        "unsafe_cookie_scope"} else "moodle_verification_unavailable"
                bootstrap[name] = {"bootstrapped": verified, "status": status}
                proof[name + "_bootstrapped"] = verified
            proof["moodle_bootstrap"] = bootstrap
        else:
            from ..features.repair.http_adapter import verify_login
            proof = verify_login(school, response=landing)
        check()
        state = school.state((host,))
        if service == "repair":
            # This legacy site asks CAS for a fresh ticket on each page. Keep
            # central cookies encrypted under repair only, in a separate jar.
            state["repair_sso_state"] = sso.state(("sso.stu.edu.cn",))
        return Candidate(state, proof)
