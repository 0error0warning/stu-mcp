"""HTTP authentication with replaceable human interaction and isolated sessions."""
from __future__ import annotations

import sys
from collections.abc import Callable

from ..network import scoped_state
from ..runtime import AppError, key_lock
from ..store import Store
from ..terminal import require_terminal, secret_input
from ..vault import Vault
from .school import login_school
from .types import Candidate, Credentials


class TerminalInteraction:
    """Only the person at the local TTY receives authentication challenges."""

    def credentials(self) -> Credentials:
        require_terminal()
        return Credentials(secret_input("学校账号（隐藏输入）：").strip(), secret_input("学校密码（隐藏输入）："))

    def code(self) -> str:
        return secret_input("学校要求已绑定令牌的当前动态码（隐藏输入）：").strip()

    def show_qr(self, content: str) -> None:
        require_terminal()
        try:
            import qrcode
            qr = qrcode.QRCode(box_size=1, border=2)
            qr.add_data(content)
            qr.make(fit=True)
            print("请本人使用手机扫描二维码并确认。二维码不写入文件。", file=sys.stderr)
            qr.print_ascii(out=sys.stderr, invert=True)
            sys.stderr.flush()
        except Exception:
            raise AppError("qr_display_unavailable", "当前终端无法显示二维码；本次扫码未继续。", "yuketang") from None


def _next_step(source: str, proof: dict) -> str:
    default = "登录会话已加密保存，现在可读取此来源。"
    bootstrap = proof.get("moodle_bootstrap")
    if source != "mystu" or not isinstance(bootstrap, dict):
        return default
    safe_codes = {"moodle_session_unconfirmed", "authentication_budget", "authentication_network_error",
                  "authentication_response_limit", "authentication_schema_changed", "insecure_authentication_route",
                  "login_rejected", "unsafe_cookie_scope", "moodle_verification_unavailable"}
    pending = []
    for name, label in (("elc", "ELC"), ("campus", "Campus")):
        item = bootstrap.get(name)
        if isinstance(item, dict) and item.get("bootstrapped") is False:
            code = item.get("status")
            code = code if isinstance(code, str) and code in safe_codes else "moodle_verification_unavailable"
            pending.append(f"{label}（{code}）")
    if not pending:
        return default
    return ("MySTU 身份及课程会话已加密保存；" + "、".join(pending) +
            "初始化未完成。课程查询可用，相关 Moodle 业务仍需单独验证。")


def login_http(vault: Vault, service: str, *, credentials: Credentials | None = None,
               interaction=None, on_phase: Callable[[str], None] | None = None,
               expected_revision: bytes | None = None, allow_http_callback: bool = False,
               transport=None, check_group: Callable[[], None] | None = None,
               commit_receipt: dict | None = None,
               check_cancelled: Callable[[], None] | None = None,
               use_saved_credentials: bool = True) -> dict:
    source = "oa" if service in {"oa", "webvpn"} else service
    session = "webvpn" if source == "oa" else source
    if source not in {"jw", "mystu", "repair", "yuketang", "oa"}:
        raise AppError("unknown_service", "请选择教务、MySTU、雨课堂、WebVPN 或宿舍报修。")
    interaction = TerminalInteraction() if interaction is None else interaction
    if expected_revision is None:
        with key_lock(vault.runtime.home, session):
            expected_revision = vault.login_revision(session)
    vault._key(create=True)  # Secure storage must work before asking for credentials.
    config = snapshot = None
    used_configured_credentials = False
    if source == "oa":
        from ..webvpn import WebVPNConfig
        config = WebVPNConfig(vault)
        snapshot = config.snapshot()

    def check_locked():
        if check_cancelled is not None:
            check_cancelled()
        if vault.login_revision(session) != expected_revision:
            raise AppError("session_changed", "登录期间已退出或切换账号；本次认证结果未保存。", source)
        if config is not None:
            config.check(snapshot)

    def check():
        if check_group is not None:
            check_group()
        with key_lock(vault.runtime.home, session):
            check_locked()

    check()
    if on_phase:
        on_phase("http_authentication")
    if source == "yuketang":
        from .yuketang import acquire_state
        candidate = acquire_state(show_qr=interaction.show_qr, check=check, transport=transport)
    elif source == "oa":
        from .webvpn import acquire_state
        code = interaction.code
        if credentials is None and use_saved_credentials and config.marker()["configured"]:
            import time
            saved = config.credentials(config.marker())
            credentials = Credentials(saved.username, saved.password)
            used_configured_credentials = True
            def current_code():
                remaining = saved.totp.interval - time.time() % saved.totp.interval
                if remaining <= 5:
                    time.sleep(remaining + .2)
                check()
                return saved.totp.now()
            code = current_code
        credentials = credentials or interaction.credentials()
        check()
        state, metadata = acquire_state(username=credentials.username, password=credentials.password,
                                        totp_code=code, check=check, on_phase=on_phase, transport=transport)
        candidate = Candidate(state, metadata)
    else:
        from .cas import acquire_state
        credentials = credentials or interaction.credentials()
        check()
        legacy = bool(allow_http_callback or vault.runtime.preferences()["jw_http_compat"])
        candidate = acquire_state(source, credentials.username, credentials.password, check=check,
                                  transport=transport, legacy_jw=legacy)
    account_fingerprint = None
    if source in {"jw", "mystu", "repair"}:
        from .school import school_account_fingerprint
        account_fingerprint = school_account_fingerprint(credentials.username)
    credentials = None
    check()
    if (not isinstance(candidate, Candidate) or not isinstance(candidate.proof, dict)
            or not (candidate.proof.get("authenticated") is True
                    or candidate.proof.get("authentication_verified") is True)
            or not isinstance(candidate.state, dict) or not isinstance(candidate.state.get("cookies"), list)):
        raise AppError("authentication_unconfirmed", "来源没有提供明确认证证明；本次会话未保存。", source)
    state = dict(candidate.state) if source == "repair" else scoped_state(candidate.state, source)
    if source == "jw" and legacy and candidate.proof.get("http_callback_used") is True:
        # Keep the verified official route with this encrypted JW session. It
        # neither changes global transport preferences nor applies to SSO.
        state["jw_http_compat"] = True
    if account_fingerprint is not None:
        # Account association is encrypted metadata, never a cookie or result.
        state["school_account_fingerprint"] = account_fingerprint

    def forget_previous():
        Store(vault.runtime, vault).forget(source)
        if config is not None and not used_configured_credentials:
            config.remove_locked()

    saved_fingerprint = vault.save(session, state, on_relogin=forget_previous, guard=check_locked)
    if commit_receipt is not None:
        # Internal receipt for group fencing; never included in CLI/MCP results.
        commit_receipt["fingerprint"] = saved_fingerprint
    return {"ok": True, "service": session, "status": "session_saved", "method": "http",
            "verified_live": True, "proof": candidate.proof,
            "next_step": _next_step(source, candidate.proof)}


__all__ = ["Candidate", "Credentials", "TerminalInteraction", "login_http", "login_school"]
