"""Opt-in, local WebVPN credentials and bounded renewal during protected OA reads."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import parse_qsl, urlparse

import httpx
import pyotp
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright

from .auth import prepare_browser
from .network import CampusHTTP, checked_url, scoped_state
from .parsers import is_login
from .runtime import AppError, key_lock, private_write, reject_symlinks
from .sources import SOURCES
from .store import Store
from .vault import Vault

KEYRING_SERVICE = "stu-mcp.webvpn-auto-login"
COOLDOWN_SECONDS = 60
T = TypeVar("T")
LOGIN_ERRORS = frozenset({"needs_login", "login_expired"})
PAUSE_ERRORS = frozenset({"auto_login_failed", "auto_login_interaction_required", "login_expired", "needs_login"})
TOTP_INPUT = ("[data-dialog-ctr='totp_signature']:visible input.input-txt:not([disabled]), "
              ".totp_signature-box:visible input.input-txt:not([disabled])")
CAPTCHA = ("input[name*='captcha' i]:visible, input[id*='captcha' i]:visible, "
           "img[src*='captcha' i]:visible, iframe[src*='recaptcha']:visible")


def parse_totp(value: str, encoding: str = "auto") -> pyotp.TOTP:
    """Accept a provisioning URI or a seed, never a single rotating code."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 2048:
            raise ValueError
        value = value.strip()
        if encoding not in {"auto", "base32", "base64", "hex"}:
            raise ValueError
        if value.startswith("otpauth://"):
            uri = urlparse(value)
            pairs = parse_qsl(uri.query)
            if uri.netloc != "totp" or uri.fragment or len(pairs) != len(dict(pairs)):
                raise ValueError
            if set(dict(pairs)) - {"secret", "issuer", "algorithm", "digits", "period"}:
                raise ValueError
            otp = pyotp.parse_uri(value)
            if not isinstance(otp, pyotp.TOTP):
                raise ValueError
        else:
            compact = "".join(value.split())
            normalized = compact.upper().replace("-", "").rstrip("=")
            raw = None
            if encoding in {"auto", "base32"} and re.fullmatch(r"[A-Z2-7]+", normalized):
                try:
                    raw = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
                except binascii.Error:
                    if encoding == "base32":
                        raise
            if raw is None and encoding in {"auto", "hex"} and re.fullmatch(r"[0-9a-fA-F]+", compact):
                raw = bytes.fromhex(compact)
            if raw is None and encoding in {"auto", "base64"}:
                raw = base64.b64decode(compact + "=" * (-len(compact) % 4), altchars=b"-_", validate=True)
            if raw is None or not 10 <= len(raw) <= 128:
                raise ValueError
            otp = pyotp.TOTP(base64.b32encode(raw).decode("ascii").rstrip("="))
        if otp.digits not in (6, 8) or not 15 <= otp.interval <= 120:
            raise ValueError
        if otp.digest().name not in {"sha1", "sha256", "sha512"} or not 10 <= len(otp.byte_secret()) <= 128:
            raise ValueError
        otp.at(0)  # Validate without returning or printing an authentication code.
        return otp
    except Exception:
        raise AppError("invalid_totp", "请填写已绑定令牌的密钥或完整 otpauth://totp/ 地址，不能填写当前六位验证码。", "oa") from None


@dataclass(frozen=True, repr=False)
class Credentials:
    username: str
    password: str
    totp: pyotp.TOTP


@dataclass(frozen=True, repr=False)
class Snapshot:
    state: dict | None
    version: bytes | None
    generation: str | None


@dataclass(frozen=True)
class Access:
    value: object
    session_version: bytes


class WebVPNConfig:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.path = vault.runtime.home / "webvpn-auto.json"

    def marker(self) -> dict:
        reject_symlinks(self.path)
        if not self.path.exists():
            return {"id": None, "configured": False, "enabled": False, "cooldown_until": 0, "failure": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or not re.fullmatch(r"[a-f0-9]{32}", data.get("id", ""))
                    or type(data.get("configured")) is not bool or type(data.get("enabled")) is not bool
                    or not isinstance(data.get("cooldown_until"), (float, int))
                    or not math.isfinite(data["cooldown_until"])
                    or data.get("failure") not in PAUSE_ERRORS | {None, "secure_storage_unavailable"}):
                raise ValueError
            return data
        except (ValueError, TypeError, OSError):
            raise AppError("auto_login_config_invalid", "自动登录状态无效，请在本机重新配置或移除。", "oa") from None

    def _write(self, marker: dict):
        try:
            private_write(self.path, json.dumps(marker).encode())
        except OSError:
            raise AppError("local_state_unavailable", "本机自动登录状态无法保存；未将凭据写入文件。", "oa") from None

    def status(self) -> dict:
        try:
            marker = self.marker()
            return {"configured": marker["configured"], "enabled": marker["enabled"],
                    "status": "paused" if marker["failure"] else "enabled" if marker["enabled"]
                    else "disabled" if marker["configured"] else "not_configured",
                    "reason": marker["failure"],
                    "retry_after_seconds": max(0, math.ceil(marker["cooldown_until"] - time.time()))}
        except AppError as exc:
            return {"configured": False, "enabled": False, "status": exc.code}

    def _keyring(self, action: Callable):
        try:
            return action(self.vault.key_store())
        except AppError:
            raise
        except Exception:
            raise AppError("secure_storage_unavailable", "无法访问系统密钥库；未使用明文保存凭据。", "oa") from None

    def configure(self, fields: dict) -> dict:
        if (set(fields) - {"enabled", "username", "password", "totp", "encoding"}
                or fields.get("enabled") is not True):
            raise AppError("invalid_credentials", "请在本机明确勾选允许自动重新登录。", "oa")
        username, password = fields.get("username"), fields.get("password")
        if (not isinstance(username, str) or not 1 <= len(username.strip()) <= 128
                or not isinstance(password, str) or not 1 <= len(password) <= 1024
                or any(ord(c) < 32 for c in username)):
            raise AppError("invalid_credentials", "请填写有效的学校账号和密码。", "oa")
        otp = parse_totp(fields.get("totp"), fields.get("encoding", "auto"))
        marker = {"id": uuid.uuid4().hex, "configured": True, "enabled": True, "cooldown_until": 0, "failure": None}
        record = {"id": marker["id"], "username": username.strip(), "password": password,
                  "totp": {"secret": otp.secret, "digits": otp.digits, "period": otp.interval,
                           "algorithm": otp.digest().name.upper()}}
        with key_lock(self.vault.runtime.home, "webvpn"):
            # Record a disabled pending configuration first. An interrupted keyring write remains removable.
            self._write({**marker, "enabled": False})
            self.vault.logout("webvpn")
            Store(self.vault.runtime, self.vault).forget("oa")
            self._keyring(lambda store: store.set_password(KEYRING_SERVICE, self.vault.account,
                                                          json.dumps(record, ensure_ascii=False)))
            self._write(marker)
        return {"ok": True, "status": "auto_login_configured",
                "message": "凭据已保存到系统密钥库。需要受保护 OA 信息时，会在会话失效后自动重新登录。"}

    def remove_locked(self) -> None:
        """Caller owns the short webvpn mutation lock. Fence running logins before deletion."""
        try:
            configured = self.marker()["configured"]
        except AppError as exc:
            if exc.code != "auto_login_config_invalid":
                raise
            configured = True
        marker = {"id": uuid.uuid4().hex, "configured": configured, "enabled": False,
                  "cooldown_until": 0, "failure": None}
        self._write(marker)
        if configured:
            try:
                self._keyring(lambda store: store.delete_password(KEYRING_SERVICE, self.vault.account))
            except AppError:
                self._write({**marker, "failure": "secure_storage_unavailable"})
                raise AppError("secure_storage_unavailable", "自动重登已关闭，但系统密钥库暂时无法移除凭据；恢复后请再次移除。", "oa") from None
        self._write({**marker, "configured": False})

    def remove(self) -> dict:
        with key_lock(self.vault.runtime.home, "webvpn"):
            self.remove_locked()
        return {"ok": True, "status": "auto_login_removed", "message": "已关闭自动重新登录并移除保存的凭据。"}

    def credentials(self, marker: dict) -> Credentials:
        raw = self._keyring(lambda store: store.get_password(KEYRING_SERVICE, self.vault.account))
        try:
            record = json.loads(raw)
            if record["id"] != marker["id"]:
                raise ValueError
            otp = record["totp"]
            if not isinstance(record["username"], str) or not isinstance(record["password"], str):
                raise ValueError
            totp = pyotp.TOTP(otp["secret"], digits=otp["digits"], interval=otp["period"],
                             digest={"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}[otp["algorithm"]])
            totp.at(0)
            return Credentials(record["username"], record["password"], totp)
        except Exception:
            raise AppError("auto_login_config_invalid", "系统密钥库中的自动登录配置无效，请重新填写。", "oa") from None

    def snapshot(self) -> Snapshot:
        with key_lock(self.vault.runtime.home, "webvpn"):
            marker, version = self.marker(), self.vault.fingerprint("webvpn")
            try:
                state = self.vault.load("webvpn")
            except AppError as exc:
                if exc.code != "needs_login":
                    raise
                state = None
            return Snapshot(state, version, marker["id"])

    def check(self, snapshot: Snapshot):
        if self.marker()["id"] != snapshot.generation or self.vault.fingerprint("webvpn") != snapshot.version:
            raise AppError("session_changed", "WebVPN 配置或登录状态已改变，此次结果已丢弃，请重新请求。", "oa")

    def pause(self, generation: str | None, code: str):
        with key_lock(self.vault.runtime.home, "webvpn"):
            marker = self.marker()
            if marker["id"] == generation and marker["configured"]:
                self._write({**marker, "enabled": False, "failure": code})


def _official_page(page):
    parsed = urlparse(page.url)
    if parsed.scheme != "https" or parsed.hostname != "webvpn.stu.edu.cn" or parsed.port not in (None, 443):
        raise AppError("auto_login_interaction_required", "学校登录入口已变化，请在学校页面手动登录。", "oa")


def _visible(page, selector):
    matches = page.locator(selector)
    return matches.first if matches.count() else None


def automatic_login(credentials: Credentials, check: Callable[[], None], *, timeout: int = 50) -> dict:
    """No screenshots, traces, persistent browser profile, debug dumps, or automatic MFA binding."""
    submitted_password = submitted_totp = had_credentials = False
    blocked = [False]
    try:
        with sync_playwright() as p:
            prepare_browser(p)
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(ignore_https_errors=False)
                def guard(route):
                    parsed = urlparse(route.request.url)
                    if (parsed.scheme != "https" or parsed.hostname != "webvpn.stu.edu.cn"
                            or parsed.port not in (None, 443) or parsed.username or parsed.password):
                        if route.request.is_navigation_request() or route.request.method != "GET":
                            blocked[0] = True
                        route.abort()
                    else:
                        route.continue_()
                context.route("**/*", guard)
                page = context.new_page()
                check()
                page.goto(SOURCES["oa"].login_url, wait_until="domcontentloaded", timeout=30000)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    check()
                    _official_page(page)
                    if blocked[0]:
                        raise AppError("auto_login_interaction_required", "学校要求其他登录步骤，请在学校页面手动完成。", "oa")
                    if _visible(page, CAPTCHA):
                        raise AppError("auto_login_interaction_required", "学校要求人工验证码，请手动登录。", "oa")
                    # The login page's help links themselves mention "password error" and "login failed".
                    errors = page.locator(".error-content:visible, [data-dialog-ctr='common_message']:visible, "
                                          ".common_message:visible, .message-box:visible")
                    text = " ".join(errors.all_inner_texts())
                    if re.search(r"(?:密码|口令|验证码).{0,6}(?:错误|无效|不正确)|(?:账号|帐号).{0,6}(?:锁定|不存在)|认证失败|登录失败", text):
                        raise AppError("auto_login_failed", "学校未接受登录凭据，已暂停自动尝试。请检查账号、密码和令牌密钥。", "oa")
                    if _visible(page, "[data-dialog-ctr='totp_loading']:visible"):
                        raise AppError("auto_login_interaction_required", "请先在学校页面完成令牌绑定，再配置自动登录。", "oa")
                    password = _visible(page, "#loginPwd:visible")
                    if password and not submitted_password:
                        username = _visible(page, "#sangfor_main_auth_container_password input.input-txt[type='text']:visible, "
                                            ".auto-input-usr input.input-txt:visible")
                        if not username:
                            raise AppError("auto_login_interaction_required", "学校账号表单已变化，请手动登录。", "oa")
                        check()
                        had_credentials = True
                        username.fill(credentials.username, timeout=5000)
                        password.fill(credentials.password, timeout=5000)
                        checkbox = page.locator(".include-box__privacy .checkbox__input")
                        if checkbox.count() and not checkbox.first.is_checked():
                            page.locator(".include-box__privacy .checkbox__label:visible").click(timeout=5000)
                        check()
                        page.locator("button.button--normal:visible").filter(has_text="登录").click(timeout=5000)
                        submitted_password = True
                    else:
                        totp_input = _visible(page, TOTP_INPUT)
                        if totp_input and not submitted_totp:
                            remaining = credentials.totp.interval - time.time() % credentials.totp.interval
                            if remaining <= 5:
                                page.wait_for_timeout(int((remaining + 0.2) * 1000))
                            check()
                            _official_page(page)
                            totp_input.fill(credentials.totp.at(time.time()), timeout=5000)
                            check()
                            confirm = page.locator("[data-dialog-ctr='totp_signature']:visible button.button--normal, "
                                                   ".totp_signature-box:visible button.button--normal").filter(has_text="确定")
                            if confirm.count():
                                confirm.first.click(timeout=5000)
                            else:
                                totp_input.press("Enter", timeout=5000)
                            submitted_totp = True
                        elif not password and not totp_input:
                            current = urlparse(page.url)
                            if submitted_password and "portal" in current.path and "service" in current.fragment:
                                state = scoped_state(context.storage_state(), "oa")
                                if state["cookies"]:
                                    return state
                    page.wait_for_timeout(250)
                raise AppError("auto_login_interaction_required", "自动登录未完成，请手动登录或检查令牌配置。", "oa")
            finally:
                browser.close()
    except AppError:
        raise
    except BrowserError:
        if not had_credentials:
            raise AppError("network_error", "学校登录入口暂时无法连接，请稍后重试。", "oa") from None
        raise AppError("auto_login_failed", "学校登录页面未能完成认证，已暂停自动尝试；可改为手动登录。", "oa") from None
    except Exception:
        raise AppError("auto_login_failed", "自动登录未完成，已暂停自动尝试；没有输出任何凭据。", "oa") from None


def _request(state: dict, url: str, parse: Callable[[httpx.Response], T]) -> T:
    with CampusHTTP("oa", state) as http:
        response = http.request(url)
    html = "html" in response.headers.get("content-type", "").lower() or response.content.lstrip().startswith(b"<")
    if html and (is_login(response.text) or re.search(r"<title[^>]*>[^<]*WebVPN|"
                                                    r"<script[^>]+src=[\"'][^\"']*jssdk/common/errcode\.js", response.text, re.I)):
        raise AppError("login_expired", "WebVPN 会话已失效。", "oa")
    return parse(response)


def protected_access(vault: Vault, url: str, parse: Callable[[httpx.Response], T]) -> Access:
    # Reject the destination before reading credentials or contacting a login endpoint.
    checked_url("oa", url, authenticated=True)
    config = WebVPNConfig(vault)
    initial = config.snapshot()
    if initial.state is not None:
        try:
            return Access(_request(initial.state, url, parse), initial.version)
        except AppError as exc:
            if exc.code not in LOGIN_ERRORS:
                raise
    with key_lock(vault.runtime.home, "webvpn-login"):
        # A simultaneous MCP process may already have renewed this same account.
        current = config.snapshot()
        if current.generation != initial.generation:
            raise AppError("session_changed", "WebVPN 配置已改变，请重新请求。", "oa")
        if current.version != initial.version and current.state is not None:
            return Access(_request(current.state, url, parse), current.version)
        with key_lock(vault.runtime.home, "webvpn"):
            config.check(current)
            marker = config.marker()
            if not marker["enabled"]:
                code = "auto_login_paused" if marker["configured"] else "needs_login"
                raise AppError(code, "请在本机设置页登录，或更新 WebVPN 自动重登配置。", "oa")
            if marker["cooldown_until"] > time.time():
                raise AppError("auto_login_cooldown", "刚刚尝试过 WebVPN 登录，请稍后重试；不会反复提交凭据。", "oa")
            credentials = config.credentials(marker)
            config._write({**marker, "cooldown_until": time.time() + max(COOLDOWN_SECONDS, credentials.totp.interval + 5)})
        try:
            state = automatic_login(credentials, lambda: config.check(current))
            config.check(current)
            value = _request(state, url, parse)  # Verify access before saving a new session.
            version = vault.save("webvpn", state, guard=lambda: config.check(current),
                                 on_relogin=lambda: Store(vault.runtime, vault).forget("oa"))
            return Access(value, version)
        except AppError as exc:
            if exc.code in PAUSE_ERRORS:
                config.pause(current.generation, exc.code)
            raise
