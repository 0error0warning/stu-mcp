"""One status contract for the local page and all control clients."""
from __future__ import annotations

LABELS = {
    "not_logged_in": "未登录", "paused": "已暂停", "monitoring": "监听中",
    "query_error": "查询异常", "starting": "正在启动", "stopping": "正在暂停",
}


def describe(*, busy, auth_state, monitoring, stopping, requested, error, course_statuses):
    failures = [key for key, value in course_statuses.items() if value.get("error")]
    if busy:
        status, reason = "starting", "restoring_session"
    elif auth_state == "not_logged_in":
        status, reason = "not_logged_in", "login_required"
    elif error or auth_state == "unknown":
        status, reason = "query_error", "connection_unverified" if auth_state == "unknown" else "local_error"
    elif stopping:
        status, reason = "stopping", "request_finishing"
    elif monitoring and failures:
        status, reason = "query_error", "course_query_failed"
    elif monitoring:
        status, reason = "monitoring", "polling"
    elif requested:
        status, reason = "query_error", "worker_stopped_unexpectedly"
    else:
        status, reason = "paused", "paused"
    return {"status": status, "status_label": LABELS[status], "status_reason": reason,
            "failed_courses": failures if monitoring else [], "auth_state": auth_state,
            "needs_login": auth_state == "not_logged_in" and not busy}
