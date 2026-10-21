"""One personal instance owns services; transports never own user sessions."""
from __future__ import annotations

import os
import threading
from typing import Any

from .app import App
from .checkin import CheckinClient
from .connectivity import NetworkDiagnostics
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
            interaction = {"mode": mode, "available": True, "health_verified": False}
        except AppError as exc:
            interaction = {"mode": "invalid" if exc.code == "invalid_interaction_mode" else interaction_mode(),
                           "available": False, "status": exc.code}
        return self.app.status() | {"checkin": self.checkin.status(), "execution": execution_context(),
            "hosting": {"transport": self.transport, "identity_scope": "single_user_instance",
                        "shared_between_clients": True, "multi_user": False, "workers": 1,
                        "authentication": "local_process" if self.transport == "stdio" else "private_bearer",
                        "oauth_discovery": False, "interaction": interaction,
                        "credential_backend": "encrypted_file" if os.environ.get("STU_MCP_KEY_FILE") is not None
                        else "os_keyring", "credential_backend_verified": False,
                        "setup_on": "mcp_host", "setup_url_returned_to_agent": False,
                        "repair_state": "process_memory", "repair_survives_restart": False,
                        "downloads_on": "mcp_host"}}

    def open_setup(self) -> dict[str, Any]:
        if self.transport != "stdio":
            return {"ok": False, "status": "host_setup_required", "execution": execution_context(),
                    "message": "请在 MCP 宿主终端运行 stu-mcp setup --port 8766 --no-browser，"
                    "通过受保护的端口转发访问设置页；学校登录还需宿主桌面或虚拟桌面。"
                    "设置页的私密地址只显示在该终端，不会发给 agent。"}
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
                "message": "请在 MCP 宿主的浏览器完成设置；无桌面环境请按服务器部署说明配置登录界面。"}

    def checkin_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.transport != "stdio" and result.get("next_action") == "open_local_browser":
            return result | {"next_action": "forward_host_checkin_page", "execution": execution_context(),
                             "message": "对分易网页运行在 MCP 宿主的回环地址；请在宿主终端启动 stu-checkin "
                             "--no-browser，并按服务器说明转发网页端口后由本人登录。"}
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
