"""User-operated school login, with secrets staying outside the agent conversation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .network import PASSWORD_KEYS, CampusHTTP, scoped_state
from .parsers import is_login, parse_jw
from .runtime import AppError
from .sources import JW_BASE, MYSTU_API, MYSTU_BASE, SOURCES, YUKETANG_BASE
from .store import Store
from .vault import Vault


def login_service(service: str) -> str:
    if service == "webvpn":
        return "oa"
    if service not in {"jw", "mystu", "yuketang", "oa"}:
        raise AppError("unknown_service", "请选择教务、MySTU、雨课堂或 WebVPN。")
    return service


def proof(source: str, state: dict, *, legacy_jw: bool = False) -> bool:
    """A cookie's existence is not proof of a working authenticated school endpoint."""
    try:
        with CampusHTTP(source, state, allow_legacy_http=legacy_jw) as http:
            if source == "jw":
                base = JW_BASE.replace("https://", "http://") if legacy_jw else JW_BASE
                parse_jw(http.text(base + "/kscj/cjcx_list", data={"kksj": "", "kcmc": "", "kcxz": ""}), "grade")
            elif source == "mystu":
                data = http.json(MYSTU_API + "/user/validate?ver=1.1")
                if data.get("authenticated") is False or data.get("success") is False:
                    return False
            elif source == "yuketang":
                data = http.json(YUKETANG_BASE + "/v2/api/web/courses/list?identity=2")
                return isinstance(data.get("data"), dict) and isinstance(data["data"].get("list"), list)
            else:
                # WebVPN is only stored provisionally; OA refresh must validate access over HTTPS.
                return bool(state.get("cookies"))
        return True
    except AppError:
        return False


def browser_http_allowed(url: str, post_data: str | None, *, legacy_jw: bool) -> bool:
    """The JW exception never authorizes HTTP password submissions or other hosts."""
    parsed = urlparse(url)
    if not legacy_jw or parsed.scheme != "http" or parsed.hostname != "jw.stu.edu.cn" or parsed.port not in (None, 80):
        return False
    pairs = parse_qsl(parsed.query) + parse_qsl(post_data or "")
    if any(k.lower() in PASSWORD_KEYS for k, _ in pairs):
        return False
    try:
        payload = json.loads(post_data or "null")
    except ValueError:
        payload = None
    return not (isinstance(payload, dict) and any(k.lower() in PASSWORD_KEYS for k in payload))


def prepare_browser(playwright, on_phase: Callable[[str], None] | None = None):
    if not Path(playwright.chromium.executable_path).is_file():
        if on_phase:
            on_phase("preparing_browser")
        try:
            installed = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=300, check=False,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise AppError("browser_install_failed", "登录浏览器准备失败，请检查下载网络后重新登录。") from None
        if installed.returncode:
            raise AppError("browser_install_failed", "登录浏览器下载失败；可执行 stu-mcp browser install 检查。")


def interactive_login(vault: Vault, service: str, *, timeout: int = 300,
                      on_phase: Callable[[str], None] | None = None) -> dict:
    source = login_service(service)
    spec = SOURCES[source]
    legacy_jw = source == "jw" and vault.runtime.preferences()["jw_http_compat"]
    login_url = ("https://sso.stu.edu.cn/login?" + urlencode({"service": "http://jw.stu.edu.cn/jsxsd/"})
                 if legacy_jw else spec.login_url)
    vault._key(create=True)  # Verify secure storage before asking the user to log in.
    webvpn_config = webvpn_snapshot = None
    if source == "oa":
        from .webvpn import WebVPNConfig
        webvpn_config = WebVPNConfig(vault)
        webvpn_snapshot = webvpn_config.snapshot()
    insecure_navigation = [False]
    try:
        with sync_playwright() as p:
            prepare_browser(p, on_phase)
            if on_phase:
                on_phase("waiting_for_login")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(ignore_https_errors=False)
            # Passwords stay on HTTPS; an explicit local option permits only the school's legacy JW service.
            def guard(route):
                parsed = urlparse(route.request.url)
                if parsed.scheme == "http" and not browser_http_allowed(route.request.url, route.request.post_data,
                                                                       legacy_jw=legacy_jw):
                    if route.request.is_navigation_request():
                        insecure_navigation[0] = True
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", guard)
            page = context.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
            deadline = time.monotonic() + timeout
            last_probe = 0.0
            while time.monotonic() < deadline:
                if insecure_navigation[0]:
                    raise AppError("insecure_transport", "HTTP 跳转被拦截。学校旧教务接口需先在本地设置页开启教务兼容。", source)
                if not browser.is_connected() or page.is_closed():
                    raise AppError("login_cancelled", "登录窗口已关闭；尚未保存会话。", source)
                page.wait_for_timeout(1000)
                current = urlparse(page.url)
                if current.hostname not in spec.hosts or current.hostname == "sso.stu.edu.cn":
                    continue
                html = page.content()
                if current.scheme == "http" and is_login(html):
                    raise AppError("insecure_password_form", "教务返回了 HTTP 登录表单，请关闭窗口并改用学校 HTTPS 统一认证。", source)
                if is_login(html) or page.locator('input[autocomplete="one-time-code"]').count():
                    continue
                if time.monotonic() - last_probe < 4:
                    continue
                last_probe = time.monotonic()
                state = scoped_state(context.storage_state(), source)
                if not state["cookies"] or not proof(source, state, legacy_jw=legacy_jw):
                    continue
                if source == "oa" and ("portal" not in current.path or "service" not in current.fragment):
                    continue
                if source == "mystu":
                    # Bootstrap the Moodle session in the same user-operated browser.
                    page.goto(MYSTU_BASE + "/courses/elc/", wait_until="domcontentloaded", timeout=45000)
                    if is_login(page.content()) or urlparse(page.url).hostname == "sso.stu.edu.cn":
                        continue
                    state = scoped_state(context.storage_state(), source)
                def forget_previous():
                    Store(vault.runtime, vault).forget(source)
                    if webvpn_config:
                        webvpn_config.remove_locked()
                vault.save(spec.session, state, on_relogin=forget_previous,
                           guard=(lambda: webvpn_config.check(webvpn_snapshot)) if webvpn_config else None)
                browser.close()
                return {"ok": True, "service": spec.session, "status": "session_saved",
                        "verified_live": source != "oa", "next_step": "现在可刷新此来源。"}
            browser.close()
    except AppError:
        raise
    except BrowserError:
        if insecure_navigation[0]:
            raise AppError("insecure_transport", "HTTP 跳转被拦截；教务旧接口可在本地设置页单独开启兼容。", source) from None
        raise AppError("browser_unavailable", "登录浏览器无法启动或学校页面无法访问。请运行 stu-mcp browser install 并检查网络。",
                       source) from None
    raise AppError("login_timeout", "登录等待超时；未保存未验证的登录会话。", source)


class LoginJobs:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def start(self, service: str) -> dict:
        source = login_service(service)
        with self.lock:
            if any(j["status"] == "running" for j in self.jobs.values()):
                raise AppError("login_running", "已有登录窗口，请先完成或关闭它。")
            self.jobs = {k: v for k, v in self.jobs.items() if v["status"] == "running"}
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"id": job_id, "service": source, "status": "running", "phase": "starting"}
        def run():
            def progress(phase):
                with self.lock:
                    self.jobs[job_id]["phase"] = phase
            try:
                result = interactive_login(self.vault, service, on_phase=progress)
            except AppError as exc:
                result = exc.result()
            except Exception:
                result = {"ok": False, "status": "login_failed", "message": "登录未完成；没有输出认证信息。"}
            with self.lock:
                self.jobs[job_id] = {"id": job_id, "service": source, "status": "finished", "result": result}
        threading.Thread(target=run, daemon=True, name="stu-login").start()
        return {"ok": True, "id": job_id, "status": "running"}

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.jobs.values())
