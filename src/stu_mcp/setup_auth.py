"""Private loopback-page interactions with the existing HTTP login core.

Nothing here is an MCP interface. Challenges and input live only in memory for a
single bounded task; snapshots never include submitted credentials or callbacks.
"""
from __future__ import annotations

import base64
import io
import math
import re
import threading
import time
import uuid
from collections.abc import Callable
from copy import deepcopy

from .auth_http import Credentials
from .auth_http.school import SCHOOL_SERVICES
from .runtime import AppError, key_lock, reject_symlinks

_PROFILES = frozenset({"school", "yuketang", "webvpn", "duifene", "smartcard"})
_SERVICES = _PROFILES | frozenset(SCHOOL_SERVICES) | {"oa"}
_MESSAGES = {
    "session_saved": "登录会话已加密保存；实际功能按业务分别读取核验。",
    "school_login_complete": "所选业务已分别处理；本地保留的会话尚未在线核验。",
    "school_login_partial": "部分业务未完成，请查看各业务结果。",
    "school_login_stopped": "认证已停止，已完成的业务结果分别保留。",
    "needs_login": "此业务尚未登录。", "login_expired": "此业务会话已过期。",
    "session_invalid": "此业务保存的会话无效。", "session_changed": "登录期间业务已退出或切换，结果未沿用。",
    "secure_storage_unavailable": "安全存储不可用，未接收认证信息。",
    "insecure_transport": "学校登录通道暂不支持。",
    "login_rejected": "账号或密码未通过验证，请检查后重新登录。",
    "interaction_required": "学校要求额外验证，请先到学校网站完成验证。",
    "authentication_identity_mismatch": "学校返回身份不一致，未保存会话。",
    "authentication_unconfirmed": "未取得此业务的明确认证证明。",
    "authentication_network_error": "暂时无法连接学校登录页面，请检查网络后重试。",
    "authentication_outcome_unknown": "暂时无法核实登录结果，请先查看配置状态。",
    "authentication_schema_changed": "学校登录方式有变化，当前版本暂不支持。",
    "authentication_budget": "登录等待超时，请查看配置状态后重试。",
    "authentication_response_limit": "认证响应超过大小或时间上限。",
    "schema_changed": "来源结构发生变化，未保存未经证明的会话。",
    "unsafe_cookie_scope": "认证会话范围异常，已停止。",
    "insecure_authentication_route": "认证跳转超出已核验范围，已停止。",
    "account_not_bound": "雨课堂尚未绑定学校；本工具未进行绑定。",
    "operation_cancelled": "本次登录已取消。", "login_timeout": "登录等待已结束，请重新开始。",
    "not_attempted": "请先解决上面的登录问题，再继续配置。",
    "invalid_callback": "回调链接无效，请重新完成原微信授权。",
    "invalid_authentication_input": "认证输入格式无效。", "local_state_busy": "本地状态正在变更，请稍后再试。",
    "captcha_display_unavailable": "验证码暂时无法显示，请重新配置。",
    "captcha_rejected": "验证码未通过验证，请重新配置。",
    "unsafe_path": "本地安全路径检查失败，已停止。",
    "invalid_totp": "令牌密钥无效，请填写已绑定令牌的密钥，不是当前六位动态口令。",
    "auto_login_config_invalid": "自动登录配置无法读取，请重新配置。",
    "auto_login_failed": "WebVPN 未接受账号或动态口令，请检查配置。",
    "auto_login_interaction_required": "WebVPN 要求额外验证，本次登录已停止。",
    "source_unavailable": "学校服务暂时无法访问，请稍后重试。",
    "operation_failed": "登录未完成，请查看当前配置后再试。",
    "paused": "微信连接状态已读取；没有创建新的监听计划。",
    "monitoring": "已有授权监听计划的状态已读取。",
    "not_logged_in": "对分易尚未登录。", "query_error": "无法核实对分易当前状态，请先只读检查。",
    "service_not_started": "对分易后台尚未启动。", "starting": "对分易后台正在启动。",
    "stopping": "对分易后台正在停止。",
}


def _safe_result(raw: dict, *, nested: bool = False) -> dict:
    """Keep only known result shapes; adapter prose and opaque proof never escape."""
    status = raw.get("status")
    status = status if isinstance(status, str) and status in _MESSAGES else "operation_failed"
    result = {"ok": raw.get("ok") is True and status != "operation_failed", "status": status,
              "message": _MESSAGES[status]}
    for key in ("service", "source"):
        if isinstance(raw.get(key), str) and raw[key] in _SERVICES:
            result[key] = raw[key]
    for key in ("verified_live", "skipped", "kept_previous", "previous_identity_verified", "logged_in",
                "monitoring", "resume_enabled", "service_running", "cancellation_requested"):
        if type(raw.get(key)) is bool:
            result[key] = raw[key]
    if isinstance(raw.get("login_outcome"), str) and raw["login_outcome"] in {
            "confirmed", "not_sent", "unknown", "rejected"}:
        result["login_outcome"] = raw["login_outcome"]
    if raw.get("action_error") == "pause_required":
        result.update(ok=False, message="已有监听正在运行，请先暂停后再切换微信连接；未新建计划。")
    if not nested:
        if isinstance(raw.get("results"), list):
            result["results"] = [_safe_result(item, nested=True) for item in raw["results"][:len(SCHOOL_SERVICES)]
                                 if isinstance(item, dict)]
        if isinstance(raw.get("group_error"), dict):
            result["group_error"] = _safe_result(raw["group_error"], nested=True)
    return result


def checkin_storage_preflight(home=None):
    """Verify the worker's own credential scope without starting its process."""
    from stu_checkin.storage import SecureStore, StorageError, default_home
    try:
        store = SecureStore(default_home() if home is None else home)
        reject_symlinks(store.path)
        # Never replace a missing key for an existing encrypted state.
        store._cipher(create=not store.path.exists())
    except (StorageError, AppError, OSError):
        raise AppError("secure_storage_unavailable", _MESSAGES["secure_storage_unavailable"], "duifene") from None


class _LoginTask:
    def __init__(self, service: str, clock: Callable[[], float], ttl: float):
        self.id, self.service = uuid.uuid4().hex, service
        self.clock, self.deadline = clock, clock() + ttl
        self.condition = threading.Condition()
        self.cancelled = False
        self.cancel_status = "operation_cancelled"
        self.status, self.phase = "running", "starting"
        self.challenge: dict | None = None
        self.input: dict | None = None
        self.results: list[dict] = []
        self.result: dict | None = None
        self.finished_at: float | None = None
        self.callback_sent = False
        self.thread: threading.Thread | None = None

    def _check_locked(self):
        if self.clock() >= self.deadline and not self.cancelled:
            self._cancel_locked("login_timeout")
        if self.cancelled:
            raise AppError(self.cancel_status, _MESSAGES[self.cancel_status], self.service)

    def check(self):
        with self.condition:
            self._check_locked()

    def _cancel_locked(self, status: str):
        self.cancelled, self.cancel_status = True, status
        self.challenge = self.input = None
        self.phase = "cancelling"
        self.condition.notify_all()

    def cancel(self):
        with self.condition:
            if self.status == "running":
                self._cancel_locked("operation_cancelled")

    def set_phase(self, phase: str):
        with self.condition:
            self._check_locked()
            if isinstance(phase, str) and phase in {
                    "http_authentication", "initializing", "password", "totp", "verifying", "saving"}:
                self.phase = phase

    def add_result(self, result: dict):
        safe = _safe_result(result, nested=True)
        with self.condition:
            for index, item in enumerate(self.results):
                if item.get("service") == safe.get("service"):
                    self.results[index] = safe
                    break
            else:
                if len(self.results) < len(SCHOOL_SERVICES):
                    self.results.append(safe)

    def ask(self, kind: str, **public) -> dict:
        with self.condition:
            self._check_locked()
            self.challenge = {"id": uuid.uuid4().hex, "kind": kind, **public}
            self.phase = "waiting_for_" + kind
            while self.input is None:
                self._check_locked()
                self.condition.wait(timeout=max(.01, self.deadline - self.clock()))
            self._check_locked()
            value, self.input = self.input, None
            self.challenge = None
            self.phase = "http_authentication"
            return value

    def show_qr(self, content: str):
        if not isinstance(content, str) or not 1 <= len(content) <= 16384:
            raise AppError("operation_failed", _MESSAGES["operation_failed"], self.service)
        import qrcode
        import qrcode.image.svg
        output = io.BytesIO()
        qrcode.make(content, image_factory=qrcode.image.svg.SvgPathImage).save(output)
        image = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        with self.condition:
            self._check_locked()
            self.challenge = {"id": uuid.uuid4().hex, "kind": "qr", "image": image}
            self.phase = "waiting_for_qr"

    def submit(self, challenge_id: str, values: dict):
        with self.condition:
            self._check_locked()
            if (self.status != "running" or not self.challenge or self.challenge["id"] != challenge_id
                    or self.input is not None):
                raise AppError("invalid_challenge", "该输入请求已失效或已使用。")
            kind = self.challenge["kind"]
            expected = {"credentials": {"username", "password"}, "code": {"code"}, "captcha": {"code"}, "callback": {"callback"},
                        "webvpn_credentials": {"username", "password", "totp"}}
            if kind not in expected or set(values) != expected[kind]:
                raise AppError("invalid_request", "输入字段与当前验证步骤不匹配。")
            if kind in {"credentials", "webvpn_credentials"}:
                if (not isinstance(values["username"], str) or not 1 <= len(values["username"].strip()) <= 128
                        or not isinstance(values["password"], str) or not 1 <= len(values["password"]) <= 1024):
                    raise AppError("invalid_authentication_input", _MESSAGES["invalid_authentication_input"])
                if kind == "webvpn_credentials":
                    from .webvpn import parse_totp
                    if not isinstance(values["totp"], str) or len(values["totp"]) > 2048:
                        raise AppError("invalid_totp", _MESSAGES["invalid_totp"])
                    if values["totp"].strip():
                        parse_totp(values["totp"])
            elif kind == "code":
                if not isinstance(values["code"], str) or re.fullmatch(r"[0-9]{6}", values["code"]) is None:
                    raise AppError("invalid_authentication_input", "动态码须为六位数字。")
            elif kind == "captcha":
                if not isinstance(values["code"], str) or re.fullmatch(r"[0-9]{4}", values["code"]) is None:
                    raise AppError("invalid_authentication_input", "验证码须为四位数字。")
            elif not isinstance(values["callback"], str) or not 1 <= len(values["callback"]) <= 8192:
                raise AppError("invalid_callback", _MESSAGES["invalid_callback"])
            self.input = dict(values)
            self.challenge = None  # Consume the private prompt exactly once.
            self.condition.notify_all()

    def begin_callback(self):
        with self.condition:
            self._check_locked()
            self.callback_sent = True
            self.phase = "callback_submitted"

    def finish(self, raw: dict):
        with self.condition:
            if not isinstance(raw, dict):
                raw = {"ok": False, "service": self.service, "status": "operation_failed"}
            if self.cancelled and not self.callback_sent:
                raw = {"ok": False, "service": self.service, "status": self.cancel_status}
            safe = _safe_result(raw)
            if self.cancelled and self.callback_sent:
                safe["cancellation_requested"] = True
                if safe.get("login_outcome") != "confirmed":
                    safe.update(ok=False, status="authentication_outcome_unknown", login_outcome="unknown",
                                message="回调已发送一次，取消等待不能撤回登录；请先只读核对，不要重发。")
            self.result, self.status, self.phase = safe, "finished", "finished"
            self.challenge = self.input = None
            self.finished_at = self.clock()
            self.condition.notify_all()

    def snapshot(self) -> dict:
        with self.condition:
            if self.status == "running" and not self.cancelled and self.clock() >= self.deadline:
                self._cancel_locked("login_timeout")
            view = {"id": self.id, "service": self.service, "status": self.status, "phase": self.phase}
            if self.challenge:
                view["challenge"] = deepcopy(self.challenge)
            if self.results:
                view["results"] = deepcopy(self.results)
            if self.result is not None:
                view["result"] = deepcopy(self.result)
            return view


class _WebInteraction:
    def __init__(self, task: _LoginTask):
        self.task = task

    def credentials(self) -> Credentials:
        value = self.task.ask("credentials")
        try:
            return Credentials(value["username"].strip(), value["password"])
        finally:
            value.clear()

    def code(self) -> str:
        value = self.task.ask("code")
        try:
            return value["code"]
        finally:
            value.clear()

    def show_qr(self, content: str):
        self.task.show_qr(content)

    def captcha(self, image: bytes, *, media_type: str = "image/jpeg") -> str:
        if (not isinstance(image, bytes) or not 1 <= len(image) <= 65536
                or media_type not in {"image/png", "image/jpeg"}):
            raise AppError("captcha_display_unavailable", _MESSAGES["captcha_display_unavailable"], self.task.service)
        encoded = "data:" + media_type + ";base64," + base64.b64encode(image).decode("ascii")
        value = self.task.ask("captcha", image=encoded)
        try:
            return value["code"]
        finally:
            value.clear()


class SetupAuthJobs:
    """One bounded HTTP authentication job per private setup page."""

    def __init__(self, vault, *, clock=time.monotonic, ttl: float = 300, history: int = 2,
                 checkin_factory=None, checkin_preflight=None):
        if (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl)
                or not 0 < ttl <= 600 or type(history) is not int or not 1 <= history <= 3):
            raise ValueError("invalid setup authentication limits")
        self.vault, self.clock, self.ttl, self.history = vault, clock, ttl, history
        self.lock = threading.Lock()
        self.tasks: list[_LoginTask] = []
        self.closed = False
        self.checkin_factory = checkin_factory
        self.checkin_preflight = checkin_preflight

    def _prune_locked(self):
        self.tasks = [task for task in self.tasks if task.finished_at is None
                      or self.clock() - task.finished_at < self.ttl][-self.history:]

    def start(self, service: str, *, reauthenticate: bool = False) -> dict:
        if not isinstance(service, str) or service not in _PROFILES:
            raise AppError("unknown_service", "请选择已适配的登录配置。")
        if (type(reauthenticate) is not bool
                or reauthenticate and service not in {"school", "webvpn"}):
            raise AppError("invalid_login_options", "登录选项无效。")
        with self.lock:
            self._prune_locked()
            if self.closed:
                raise AppError("setup_closed", "设置页已关闭，请重新打开。")
            if any(task.status == "running" for task in self.tasks):
                raise AppError("login_running", "已有认证正在进行，请先完成或取消。")
            task = _LoginTask(service, self.clock, self.ttl)
            self.tasks.append(task)
            self.tasks = self.tasks[-self.history:]

            def run():
                try:
                    result = self._run(task, reauthenticate)
                except AppError as error:
                    result = error.result()
                except Exception:
                    result = {"ok": False, "service": service, "status": "operation_failed"}
                task.finish(result)

            task.thread = threading.Thread(target=run, daemon=True, name="stu-setup-login")
            try:
                task.thread.start()
            except BaseException:
                task.finish({"ok": False, "service": service, "status": "operation_failed"})
                raise
            return {"ok": True, "id": task.id, "service": service, "status": "running"}

    def _run(self, task: _LoginTask, reauthenticate):
        from .auth_http import login_http, login_school
        task.check()
        interaction = _WebInteraction(task)
        if task.service == "school":
            # JW's verified official route is an adapter detail, not a page option.
            # login_school scopes this permission to JW's fixed callback paths only.
            return login_school(self.vault, interaction=interaction, reauthenticate=reauthenticate,
                                allow_http_callback=True,
                                check_cancelled=task.check, on_result=task.add_result)
        if task.service == "webvpn":
            return self._webvpn(task, interaction, reauthenticate)
        if task.service == "duifene":
            from stu_checkin.auth import AUTH_URL, callback_code

            from .checkin import CheckinClient
            if self.checkin_preflight is not None:
                self.checkin_preflight()
            else:
                checkin_storage_preflight()
            task.check()
            # No worker is launched before valid, explicitly supplied callback input.
            value = task.ask("callback", authorization_url=AUTH_URL)
            link = value.pop("callback")
            value.clear()
            try:
                try:
                    callback_code(link)
                except ValueError:
                    raise AppError("invalid_callback", _MESSAGES["invalid_callback"], "duifene") from None
                control = self.checkin_factory() if self.checkin_factory else CheckinClient(opener=lambda _: False)
                task.begin_callback()
                return control.connect_callback(link)
            finally:
                link = ""
        return login_http(self.vault, task.service, interaction=interaction, on_phase=task.set_phase,
                          check_cancelled=task.check, use_saved_credentials=False)

    def _webvpn(self, task, interaction, reauthenticate):
        from .auth_http import login_http
        from .webvpn import PAUSE_ERRORS, WebVPNConfig
        config = WebVPNConfig(self.vault)
        self.vault._key(create=True)
        with key_lock(self.vault.runtime.home, "webvpn"):
            marker = config.marker()
            baseline = {"revision": self.vault.login_revision("webvpn"), "generation": marker["id"]}
            saved = marker["configured"] and marker["enabled"] and not reauthenticate

        def check():
            task.check()
            if (self.vault.login_revision("webvpn") != baseline["revision"]
                    or config.marker()["id"] != baseline["generation"]):
                raise AppError("session_changed", _MESSAGES["session_changed"], "webvpn")

        credentials = None
        if not saved:
            values = task.ask("webvpn_credentials")
            try:
                if values["totp"].strip():
                    # This explicit save uses the existing credential backend. The receipt
                    # fences both the following login and concurrent logout/config changes.
                    config.configure({**values, "enabled": True}, guard=check, commit_receipt=baseline)
                    saved = True
                else:
                    credentials = Credentials(values["username"].strip(), values["password"])
            finally:
                values.clear()
        try:
            return login_http(self.vault, "webvpn", credentials=credentials, interaction=interaction,
                              on_phase=task.set_phase, expected_revision=baseline["revision"],
                              check_cancelled=check, use_saved_credentials=saved)
        except AppError as error:
            pause = error.code if error.code in PAUSE_ERRORS else "auto_login_failed" if error.code in {
                "authentication_outcome_unknown", "authentication_response_limit", "authentication_budget",
                "schema_changed"} else None
            if saved and pause:
                config.pause(baseline["generation"], pause)
            raise

    def _task(self, task_id: str) -> _LoginTask:
        if not isinstance(task_id, str) or re.fullmatch(r"[a-f0-9]{32}", task_id) is None:
            raise AppError("invalid_login_job", "登录任务已失效。")
        with self.lock:
            self._prune_locked()
            for task in self.tasks:
                if task.id == task_id:
                    return task
        raise AppError("invalid_login_job", "登录任务已失效。")

    def submit_input(self, id: str, challenge_id: str, **values) -> dict:
        self._task(id).submit(challenge_id, values)
        return {"ok": True, "status": "input_received"}

    def cancel(self, id: str) -> dict:
        task = self._task(id)
        task.cancel()
        return {"ok": True, "id": task.id, "status": "cancelling" if task.status == "running" else "finished"}

    def snapshot(self) -> list[dict]:
        with self.lock:
            self._prune_locked()
            return [task.snapshot() for task in self.tasks]

    def close(self):
        with self.lock:
            self.closed = True
            for task in self.tasks:
                task.cancel()
            threads = [task.thread for task in self.tasks if task.thread]
        # Source HTTP calls are bounded and consult cancellation before saving.
        # Do not wait for a long QR poll or change an authorized check-in plan.
        for thread in threads:
            thread.join(timeout=.05)
