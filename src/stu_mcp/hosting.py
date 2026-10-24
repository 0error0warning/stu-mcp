"""One personal instance owns services; transports never own user sessions."""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any

from .app import App
from .capability_catalog import build_capability_catalog
from .checkin import CheckinClient
from .connectivity import NetworkDiagnostics
from .credentials import backend_name
from .execution import execution_context
from .features.repair import RepairDrafts
from .interaction import interaction_mode, open_local_page, require_interaction
from .network_audit import NetworkAudit
from .runtime import AppError
from .setup_web import SetupServer
from .update_guard import exclusive_update
from .updates import UpdateService


class HostRuntime:
    """Composition and lifecycle for a single user's state, shared by clients.

    Repair reviews deliberately survive client disconnection, but never a process
    restart. The independent, explicitly started check-in worker is not stopped
    when the MCP instance exits.
    """

    def __init__(self, app: App | None = None, *, checkin: CheckinClient | None = None,
                 transport: str = "stdio"):
        if transport not in {"stdio", "streamable-http"}:
            raise ValueError("unsupported transport")
        self.app = app if app is not None else App()
        self.transport = transport
        self.checkin = checkin if checkin is not None else CheckinClient(
            opener=open_local_page if transport == "stdio" else lambda _: False)
        self.repairs = RepairDrafts(vault=self.app.vault)
        self.network = NetworkDiagnostics()
        self.network_audit = NetworkAudit()
        self._setup: SetupServer | None = None
        self._lock = threading.Lock()
        self._closed = False
        self.updates = UpdateService()
        self._operations = threading.Lock()
        self._active_operations = 0
        self._updating = False

    @contextmanager
    def tool_operation(self, name: str):
        with self._operations:
            if self.updates.restart_required and name not in {"get_capabilities", "check_updates"}:
                raise AppError("update_restart_required", "软件安装已变更；" + self._restart_message())
            if self._updating or (name == "update_self" and self._active_operations):
                raise AppError("update_busy", "当前有工具请求正在执行，请稍后再升级。")
            self._active_operations += 1
            self._updating = name == "update_self"
        try:
            yield
        finally:
            with self._operations:
                self._active_operations -= 1
                if name == "update_self":
                    self._updating = False

    def _before_update(self):
        with self._lock:
            if self._setup is not None:
                raise AppError("update_setup_active", "本进程设置页仍在运行，请先重启 MCP 关闭设置页，再升级。")
        with self.repairs.lock:
            unfinished = any(draft["status"] not in {"closed", "submitted"} or (
                draft["status"] == "submitted" and (not draft.get("submitted_by_mcp") or not draft.get("receipt")
                                                      or draft.get("window_status") != "closed"))
                for draft in self.repairs.drafts.values())
            if unfinished or any(worker.is_alive() for worker in self.repairs.threads.values()):
                raise AppError("update_repair_active", "存在未完成的报修流程；未发送草稿请关闭，已发送请求请先核实回执并关闭会话，再升级。")
        check_worker_before_update(self.checkin)

    def update_self(self) -> dict:
        result = self.updates.run(before_install=self._before_update,
                                  guard=lambda: exclusive_update(exclude_pid=os.getpid()))
        if result.get("restart_required"):
            result["next_action"] = "restart_host_service" if self.transport == "streamable-http" else "reload_mcp"
            result["message"] = result.get("message", "") + " " + self._restart_message()
        return result

    def _restart_message(self) -> str:
        if self.transport == "streamable-http":
            return "请重启宿主上的 MCP 服务；仅重新连接 HTTP 客户端不会加载新版。"
        return "请在客户端重新加载 MCP，以新进程使用已安装版本。"

    def capabilities(self) -> dict[str, Any]:
        if self.updates.restart_required:
            return {"ok": True, "version": self.updates.capabilities()["running_version"],
                    "updates": self.updates.capabilities(), "message": self._restart_message()}
        try:
            mode = require_interaction()
            interaction = {"mode": mode, "scope": "manual_browser", "available": True, "health_verified": False}
        except AppError as exc:
            interaction = {"mode": "invalid" if exc.code == "invalid_interaction_mode" else interaction_mode(),
                           "scope": "manual_browser", "available": False, "status": exc.code}
        local = self.app.status()
        checkin = self.checkin.status()
        catalog = build_capability_catalog(
            local["sources"], repair_status=local["repair"]["auth"], checkin_status=checkin,
            takeout_status=local["takeout"], freshness=local["freshness"])
        return local | {"checkin": checkin, "execution": execution_context(), "capability_catalog": catalog,
            "updates": self.updates.capabilities(),
            "hosting": {"transport": self.transport, "identity_scope": "single_user_instance",
                        "shared_between_clients": True, "multi_user": False, "workers": 1,
                        "authentication": "local_process" if self.transport == "stdio" else "private_bearer",
                        "oauth_discovery": False, "interaction": interaction,
                        "default_authentication": "http", "browser_backend": "optional_explicit",
                        "credential_backend": backend_name(), "credential_backend_verified": False,
                        "setup_on": "mcp_host", "setup_url_returned_to_agent": False,
                        "setup_authentication": {"backend": "http", "interfaces": ["cli", "private_setup_page"],
                                                 "server_browser_required": False, "secrets_through_mcp": False},
                        "login_flows": {
                            "school": {"method": "isolated_cas_http", "input": "host_tty_once",
                                       "services": ["jw", "mystu", "repair"], "sessions_shared": False,
                                       "credentials_persisted": False, "requires_display": False,
                                       "input_options": ["host_tty_once", "private_setup_page"]},
                            "duifene": {"method": "wechat_callback", "input": "host_tty_or_loopback_page",
                                        "requires_display": False, "new_monitoring_plan": False,
                                        "existing_authorized_plan_may_resume": True},
                            "webvpn": {"manual_login": "http_cli", "configure": "host_tty_or_loopback_page",
                                       "input_options": ["host_tty", "private_setup_page"],
                                       "automatic_renewal": "http_totp", "human_challenges": "pause",
                                       "real_account_renewal_verified": False},
                            **{source: {"method": "http_qr" if source == "yuketang" else "cas_http",
                                        "new_login_requires_display": False, "input": "host_tty",
                                        "input_options": ["host_tty", "private_setup_page"],
                                        "saved_session_reads_require_display": False}
                               for source in ("jw", "mystu", "yuketang")},
                            "repair": {"method": "isolated_cas_http", "requires_display": False,
                                       "persistent_session": True, "draft_storage": "process_memory",
                                       "input_options": ["host_tty", "private_setup_page"],
                                       "input": "host_tty"},
                            "smartcard": {"method": "http_image_captcha", "requires_display": False,
                                          "input_options": ["host_tty", "private_setup_page"],
                                          "independent_query_password": True, "credentials_persisted": False}},
                        "repair_state": "process_memory", "repair_survives_restart": False,
                        "downloads_on": "mcp_host"}}

    def open_setup(self) -> dict[str, Any]:
        if self.transport != "stdio":
            return {"ok": False, "status": "host_setup_required", "execution": execution_context(),
                    "message": "请本人在 MCP 宿主选择 CLI 配置，或运行 stu-mcp setup --no-browser 查看私密设置链接。"
                    "网页可直接输入账号、扫码或完成回调，CLI 也提供完整认证；两者共用 HTTP 核心和独立业务会话。"
                    "设置页仅监听宿主回环，不需要服务端浏览器；认证信息和私密链接不通过 MCP 返回。"}
        with self._lock:
            if self._closed:
                raise AppError("host_closed", "此 MCP 实例已关闭，请重新连接。")
            if self._setup is None:
                ui = SetupServer(self.app, checkin=self.checkin)
                try:
                    opened = ui.start()
                except BaseException:
                    ui.close()
                    raise
                self._setup = ui
            else:
                opened = open_local_page(self._setup.url)
        return {"ok": opened, "status": "settings_opened" if opened else "local_browser_required",
                "message": "已在你的浏览器打开设置页，可直接输入账号、扫码或完成授权，也可选择 CLI。"
                "配置后返回 Agent 即可使用，各业务会话独立保存。" if opened else
                "设置页已启动，但未能自动打开浏览器。请本人运行 stu-mcp setup --no-browser 查看私密链接，"
                "或选择完整 CLI 认证；无需向 Agent 提供凭据。"}

    def checkin_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.transport != "stdio" and (result.get("needs_login") or result.get("next_action") == "open_local_browser"):
            return result | {"next_action": "login_on_host_cli" if result.get("needs_login") else "open_host_checkin_page",
                             "execution": execution_context(),
                             "login_message": "对分易登录沿用微信回调；请本人在 MCP 宿主终端运行 stu-mcp login duifene，"
                             "在隐藏输入中粘贴回调，不通过 MCP 或聊天传递。查看网页可另行转发宿主回环端口。"
                             "原已授权持续计划按既有规则恢复，不会新建监听计划。"}
        return result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            ui, self._setup = self._setup, None
        try:
            self.repairs.shutdown()
        finally:
            if ui is not None:
                ui.close()


def check_worker_before_update(checkin: CheckinClient | None = None) -> None:
    # Also recognize a previous-version worker that predates installation leases.
    state = (checkin if checkin is not None else CheckinClient()).status()
    if state.get("service_running") is not False:
        raise AppError("update_worker_active", "签到后台正在运行或无法确认已停止；请先停止后台，再升级软件。")
