"""One human credential entry, separate CAS proofs and encrypted source sessions."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from copy import deepcopy

from ..runtime import AppError, key_lock
from ..terminal import require_terminal
from ..vault import Vault
from .types import Credentials

SCHOOL_SERVICES = ("jw", "mystu", "repair")
_CONTINUE_ERRORS = {"insecure_transport", "authentication_network_error", "authentication_schema_changed",
                    "authentication_unconfirmed"}


def school_account_fingerprint(username: str) -> str:
    """Only store this association inside an encrypted business session."""
    from .cas import account
    value = account(username)
    if not value or len(value) > 128 or any(char.isspace() for char in value):
        raise AppError("invalid_authentication_input", "账号为空或超出长度范围。", "school")
    return hashlib.sha256(b"stu-mcp/school-account/v1\0" + value.encode("utf-8")).hexdigest()


def login_school(vault: Vault, *, services: Sequence[str] | None = None, interaction=None,
                 allow_http_callback: bool = False, transport=None, reauthenticate: bool = False,
                 check_cancelled: Callable[[], None] | None = None,
                 on_result: Callable[[dict], None] | None = None) -> dict:
    """Migrate selected sessions independently; never persist the shared password.

    Saved sessions are skipped only when their encrypted account association
    matches the credentials just entered. That is a local check, not online proof.
    Old sessions without this metadata are reauthenticated rather than guessed.
    An explicit human interaction can be a private setup-page bridge; the
    default terminal interaction still requires a real TTY. Cancellation raises
    at checkpoints. Progress callbacks receive safe copies outside source locks.
    """
    from . import TerminalInteraction, login_http

    selected = tuple(SCHOOL_SERVICES if services is None else services)
    if not selected or len(set(selected)) != len(selected) or any(name not in SCHOOL_SERVICES for name in selected):
        raise AppError("invalid_school_services", "请选择不重复的 jw、mystu、repair 业务。", "school")
    if allow_http_callback and "jw" not in selected:
        raise AppError("invalid_login_options", "HTTP 票据回调选项只适用于本次所选教务业务。", "school")
    if interaction is None:
        require_terminal()
    if check_cancelled is not None:
        check_cancelled()
    vault._key(create=True)  # Fail before credential input or school requests.
    expected = {}
    previous = {}
    for source in selected:
        with key_lock(vault.runtime.home, source):
            expected[source] = vault.login_revision(source)
            previous[source] = vault.fingerprint(source)

    def kept_previous(source):
        return previous[source] is not None and vault.fingerprint(source) == previous[source]

    def check_group():
        if check_cancelled is not None:
            check_cancelled()
        for source in selected:
            with key_lock(vault.runtime.home, source):
                if vault.login_revision(source) != expected[source]:
                    raise AppError("session_changed", "所选业务在登录期间已退出或切换账号；后续认证已停止。", source)

    results = []
    stopped = False
    group_error = None
    credentials: Credentials | None = None

    def publish(item):
        if on_result is not None:
            on_result(deepcopy(item))

    def record(item):
        results.append(item)
        publish(item)

    def changed_result(error):
        for item in results:
            if item["service"] == error.source:
                item.update(ok=False, status="session_changed", verified_live=False,
                            next_step="此业务的登录状态在本次认证后又被改变；请查看当前配置状态。")
                publish(item)

    try:
        credentials = (TerminalInteraction() if interaction is None else interaction).credentials()
        if check_cancelled is not None:
            check_cancelled()
        if not isinstance(credentials, Credentials) or not isinstance(credentials.password, str) or not 1 <= len(credentials.password) <= 1024:
            raise AppError("invalid_authentication_input", "账号或密码为空或超出长度范围。", "school")
        fingerprint = school_account_fingerprint(credentials.username)
        for index, source in enumerate(selected):
            try:
                check_group()
                with key_lock(vault.runtime.home, source):
                    if vault.login_revision(source) != expected[source]:
                        raise AppError("session_changed", "此业务的登录状态已改变；后续认证已停止。", source)
                    try:
                        saved = vault.load(source) if previous[source] else None
                    except AppError as error:
                        if error.code != "session_invalid":
                            raise
                        saved = None  # A legacy/unreadable session still needs fresh proof.
                    locally_saved = vault.status(source)["status"] == "session_saved" if saved else False
                route_ready = source != "jw" or not allow_http_callback or saved and saved.get("jw_http_compat") is True
                if not reauthenticate and locally_saved and route_ready and saved.get("school_account_fingerprint") == fingerprint:
                    record({"ok": True, "service": source, "status": "session_saved",
                                    "method": "http", "skipped": True, "verified_live": False,
                                    "next_step": "已保留同账号的本地加密会话，尚未在线核验；读取提示失效时可运行 "
                                    f"stu-mcp login school --services {source} --reauthenticate。"})
                    continue
                committed = {}
                result = login_http(vault, source, credentials=credentials,
                                    expected_revision=expected[source], check_group=check_group,
                                    allow_http_callback=allow_http_callback if source == "jw" else False,
                                    transport=transport, commit_receipt=committed,
                                    check_cancelled=check_cancelled)
                with key_lock(vault.runtime.home, source):
                    # A concurrent logout/account switch after saving must not
                    # become the baseline for later password submissions.
                    if vault.fingerprint(source) != committed.get("fingerprint"):
                        raise AppError("session_changed", "保存后此业务会话已被改变；后续认证已停止。", source)
                    try:
                        saved = vault.load(source)
                    except AppError as error:
                        if error.code not in {"needs_login", "session_invalid"}:
                            raise
                        raise AppError("session_changed", "保存后此业务已退出或切换账号；后续认证已停止。", source) from None
                    if saved.get("school_account_fingerprint") != fingerprint:
                        raise AppError("session_changed", "此业务的登录状态已改变；后续认证已停止。", source)
                    expected[source] = vault.login_revision(source)
                record(result)
            except Exception as caught:
                error = caught if isinstance(caught, AppError) else AppError(
                    "operation_failed", "此业务认证未完成；后续认证已停止，未输出认证信息。", source)
                if error.code == "session_changed":
                    changed_result(error)
                item = {**error.result(), "service": source, "verified_live": False,
                        "kept_previous": kept_previous(source)}
                if item["kept_previous"]:
                    item["previous_identity_verified"] = False
                    item["next_step"] = "保留原有会话和缓存；未确认它属于本次账号或仍可在线使用。"
                record(item)
                if error.code not in _CONTINUE_ERRORS:
                    stopped = True
                    for remaining in selected[index + 1:]:
                        record({"ok": False, "service": remaining, "status": "not_attempted",
                                        "verified_live": False, "kept_previous": kept_previous(remaining),
                                        "next_step": "前一业务认证需先处理，本次没有继续发送共享密码。"})
                    break
        if not stopped:
            try:
                check_group()
            except AppError as error:
                stopped = True
                group_error = error.result()
                changed_result(error)
    finally:
        credentials = None
    complete = not stopped and all(item["ok"] for item in results)
    result = {"ok": complete, "service": "school", "status": "school_login_complete" if complete else
            "school_login_stopped" if stopped else "school_login_partial", "method": "http",
            "results": results, "untouched_services": [source for source in SCHOOL_SERVICES if source not in selected],
            "next_step": "各业务独立保存会话；普通学校账号密码未保存。未接入的学校服务不会因此自动启用。"}
    if group_error:
        result["group_error"] = group_error
        result["next_step"] = "各业务认证结果已分别保留，但最终本地状态核对未完成；请检查状态后再使用。"
    return result
