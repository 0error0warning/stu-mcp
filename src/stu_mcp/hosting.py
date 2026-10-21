"""One personal instance owns services; transports never own user sessions."""
from __future__ import annotations

import threading
from typing import Any

from .app import App
from .checkin import CheckinClient
from .connectivity import NetworkDiagnostics
from .credentials import backend_name
from .execution import execution_context
from .features.repair import RepairDrafts
from .interaction import interaction_mode, open_local_page, require_interaction
from .network_audit import NetworkAudit
from .runtime import AppError
from .setup_web import SetupServer


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
        self.repairs = RepairDrafts()
        self.network = NetworkDiagnostics()
        self.network_audit = NetworkAudit()
        self._setup: SetupServer | None = None
        self._lock = threading.Lock()
        self._closed = False

    def capabilities(self) -> dict[str, Any]:
        try:
            mode = require_interaction()
            interaction = {"mode": mode, "scope": "manual_browser", "available": True, "health_verified": False}
        except AppError as exc:
            interaction = {"mode": "invalid" if exc.code == "invalid_interaction_mode" else interaction_mode(),
                           "scope": "manual_browser", "available": False, "status": exc.code}
        return self.app.status() | {"checkin": self.checkin.status(), "execution": execution_context(),
            "hosting": {"transport": self.transport, "identity_scope": "single_user_instance",
                        "shared_between_clients": True, "multi_user": False, "workers": 1,
                        "authentication": "local_process" if self.transport == "stdio" else "private_bearer",
                        "oauth_discovery": False, "interaction": interaction,
                        "credential_backend": backend_name(), "credential_backend_verified": False,
                        "setup_on": "mcp_host", "setup_url_returned_to_agent": False,
                        "login_flows": {
                            "duifene": {"method": "wechat_callback", "input": "host_tty_or_loopback_page",
                                        "requires_display": False, "new_monitoring_plan": False,
                                        "existing_authorized_plan_may_resume": True},
                            "webvpn": {"manual_login": "official_browser", "configure": "host_tty_or_loopback_page",
                                       "automatic_renewal": "headless_totp", "human_challenges": "pause",
                                       "real_account_renewal_verified": False},
                            **{source: {"method": "official_browser", "new_login_requires_display": True,
                                        "saved_session_reads_require_display": False}
                               for source in ("jw", "mystu", "yuketang")},
                            "repair": {"method": "isolated_official_browser", "requires_display": True,
                                       "persistent_session": False}},
                        "repair_state": "process_memory", "repair_survives_restart": False,
                        "downloads_on": "mcp_host"}}

    def open_setup(self) -> dict[str, Any]:
        if self.transport != "stdio":
            return {"ok": False, "status": "host_setup_required", "execution": execution_context(),
                    "message": "对分易请由本人在 MCP 宿主终端运行 stu-mcp login duifene，使用原微信回调。"
                    "WebVPN 自动重登可在终端用 stu-mcp webvpn-auto configure 配置；不把凭据发给 agent。"
                    "其他来源的首次登录和报修仍需本人操作学校浏览器，当前尚未实现全 CLI。"
                    "可选设置页仍仅在宿主回环提供，私密地址不会通过 MCP 返回。"}
        with self._lock:
            if self._closed:
                raise AppError("host_closed", "此 MCP 实例已关闭，请重新连接。")
            if self._setup is None:
                ui = SetupServer(self.app)
                try:
                    opened = ui.start()
                except BaseException:
                    ui.close()
                    raise
                self._setup = ui
            else:
                opened = open_local_page(self._setup.url)
        return {"ok": opened, "status": "settings_opened" if opened else "local_browser_required",
                "message": "请在 MCP 宿主的浏览器完成设置；对分易和 WebVPN 的终端入口见 get_capabilities。"}

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
