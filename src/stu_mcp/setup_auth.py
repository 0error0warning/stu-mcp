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

from .auth import LoginJobs
from .auth_http import Credentials
from .runtime import AppError, reject_symlinks

_SERVICES = frozenset({"school", "jw", "mystu", "repair", "yuketang", "webvpn", "oa", "duifene"})
_MESSAGES = {
    "session_saved": "登录会话已加密保存；实际功能按业务分别读取核验。",
    "school_login_complete": "所选业务已分别处理；本地保留的会话尚未在线核验。",
    "school_login_partial": "部分业务未完成，请查看各业务结果。",
    "school_login_stopped": "认证已停止，已完成的业务结果分别保留。",
    "needs_login": "此业务尚未登录。", "login_expired": "此业务会话已过期。",
    "session_invalid": "此业务保存的会话无效。", "session_changed": "登录期间业务已退出或切换，结果未沿用。",
    "secure_storage_unavailable": "安全存储不可用，未接收认证信息。",
    "insecure_transport": "教务 HTTP 回调需要本人明确选择，此业务尚未完成。",
    "login_rejected": "学校没有确认认证，已停止后续密码尝试。",
    "interaction_required": "学校要求额外验证，已停止自动认证。",
    "authentication_identity_mismatch": "学校返回身份不一致，未保存会话。",
    "authentication_unconfirmed": "未取得此业务的明确认证证明。",
    "authentication_network_error": "认证网络不可达，未更改代理、DNS 或证书校验。",
    "authentication_outcome_unknown": "认证发送结果未知，未重发；请先核对状态。",
    "authentication_schema_changed": "学校认证结构发生变化，未猜测字段。",
    "authentication_budget": "本次认证达到等待或请求上限，未重发密码。",
    "authentication_response_limit": "认证响应超过大小或时间上限。",
    "schema_changed": "来源结构发生变化，未保存未经证明的会话。",
    "unsafe_cookie_scope": "认证会话范围异常，已停止。",
    "insecure_authentication_route": "认证跳转超出已核验范围，已停止。",
    "account_not_bound": "雨课堂尚未绑定学校；本工具未进行绑定。",
    "operation_cancelled": "本次登录已取消。", "login_timeout": "登录等待已结束，请重新开始。",
    "not_attempted": "前一业务需要先处理，本次未继续发送共享密码。",
    "invalid_callback": "回调链接无效，请重新完成原微信授权。",
    "invalid_authentication_input": "认证输入格式无效。", "local_state_busy": "本地状态正在变更，请稍后再试。",
    "unsafe_path": "本地安全路径检查失败，已停止。",
    "browser_unavailable": "浏览器兼容后端无法启动，请使用 HTTP 登录或检查可选依赖。",
    "operation_failed": "登录未完成，未输出认证信息。",
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
            result["results"] = [_safe_result(item, nested=True) for item in raw["results"][:3]
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
                if len(self.results) < 3:
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
            expected = {"credentials": {"username", "password"}, "code": {"code"}, "callback": {"callback"}}
            if kind not in expected or set(values) != expected[kind]:
                raise AppError("invalid_request", "输入字段与当前验证步骤不匹配。")
            if kind == "credentials":
                if (not isinstance(values["username"], str) or not 1 <= len(values["username"].strip()) <= 128
                        or not isinstance(values["password"], str) or not 1 <= len(values["password"]) <= 1024):
                    raise AppError("invalid_authentication_input", _MESSAGES["invalid_authentication_input"])
            elif kind == "code":
                if not isinstance(values["code"], str) or re.fullmatch(r"[0-9]{6}", values["code"]) is None:
                    raise AppError("invalid_authentication_input", "动态码须为六位数字。")
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


class SetupAuthJobs:
    """One HTTP or explicitly selected legacy browser job per private setup page."""

    def __init__(self, vault, *, clock=time.monotonic, ttl: float = 300, history: int = 2,
                 checkin_factory=None, checkin_preflight=None):
        if (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl)
                or not 0 < ttl <= 600 or type(history) is not int or not 1 <= history <= 3):
            raise ValueError("invalid setup authentication limits")
        self.vault, self.clock, self.ttl, self.history = vault, clock, ttl, history
        self.browser = LoginJobs(vault)
        self.lock = threading.Lock()
        self.tasks: list[_LoginTask] = []
        self.closed = False
        self.checkin_factory = checkin_factory
        self.checkin_preflight = checkin_preflight

    def _prune_locked(self):
        self.tasks = [task for task in self.tasks if task.finished_at is None
                      or self.clock() - task.finished_at < self.ttl][-self.history:]

    def start(self, service: str, *, backend: str = "http", services: list[str] | None = None,
              allow_http_callback: bool = False, reauthenticate: bool = False) -> dict:
        if not isinstance(service, str) or service not in _SERVICES:
            raise AppError("unknown_service", "请选择已适配的登录配置。")
        if (not isinstance(backend, str) or backend not in {"http", "browser"}
                or type(allow_http_callback) is not bool or type(reauthenticate) is not bool):
            raise AppError("invalid_login_options", "登录选项无效。")
        if services is not None and (service != "school" or not isinstance(services, list) or not services
                                     or any(not isinstance(item, str) or item not in {"jw", "mystu", "repair"}
                                            for item in services) or len(services) != len(set(services))):
            raise AppError("invalid_login_options", "业务选择仅用于学校账号，且不能重复。")
        if (reauthenticate and service != "school" or allow_http_callback and service not in {"school", "jw"}
                or allow_http_callback and services is not None and "jw" not in services
                or backend == "browser" and (service in {"school", "repair", "duifene"}
                                               or allow_http_callback or reauthenticate or services is not None)):
            raise AppError("invalid_login_options", "所选登录方式不支持这些选项。")
        with self.lock:
            self._prune_locked()
            if self.closed:
                raise AppError("setup_closed", "设置页已关闭，请重新打开。")
            if any(task.status == "running" for task in self.tasks) or any(
                    job["status"] == "running" for job in self.browser.snapshot()):
                raise AppError("login_running", "已有认证正在进行，请先完成或取消。")
            if backend == "browser":
                return self.browser.start(service, backend="browser")
            task = _LoginTask(service, self.clock, self.ttl)
            self.tasks.append(task)
            self.tasks = self.tasks[-self.history:]

            def run():
                try:
                    result = self._run(task, services, allow_http_callback, reauthenticate)
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

    def _run(self, task: _LoginTask, services, allow_http_callback, reauthenticate):
        from .auth_http import login_http, login_school
        task.check()
        interaction = _WebInteraction(task)
        if task.service == "school":
            return login_school(self.vault, services=services, interaction=interaction,
                                allow_http_callback=allow_http_callback, reauthenticate=reauthenticate,
                                check_cancelled=task.check, on_result=task.add_result)
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
                          allow_http_callback=allow_http_callback, check_cancelled=task.check,
                          use_saved_credentials=False)

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
            current = [task.snapshot() for task in self.tasks]
            for job in self.browser.snapshot()[-self.history:]:
                view = {key: job[key] for key in ("id", "service", "status", "phase") if key in job}
                if isinstance(job.get("result"), dict):
                    view["result"] = _safe_result(job["result"])
                current.append(view)
            return current

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
