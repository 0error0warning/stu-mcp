"""Bounded notice responses and explicit continuations for the caller's agent."""
from __future__ import annotations

from ...network import checked_url
from ...runtime import AppError

BODY_PAGE_CHARS = 8000
PREVIEW_CHARS = 1200
PUBLIC_SOURCE_ACCESS = {"login_required": False, "user_network_checked": False}


def validate_body_page(offset: int, max_chars: int) -> None:
    if type(offset) is not int or not 0 <= offset <= 60000:
        raise AppError("invalid_offset", "正文偏移必须是 0–60000 的整数。")
    if type(max_chars) is not int or not 1 <= max_chars <= 20000:
        raise AppError("invalid_limit", "每次正文返回 1–20000 字符。")


def detail_call(record: dict, *, refresh: bool) -> dict | None:
    if not refresh or record.get("source") in {"public", "oa"}:
        return {"tool": "get_notice", "arguments": {"item_id": record["id"], "refresh": refresh}}
    if record.get("source") in {"mystu", "yuketang"}:
        return {"tool": "refresh_source", "arguments": {"source": record["source"]}}
    return None


def notice_preview(record: dict) -> dict:
    item = dict(record)
    item["detail_available"] = "body" in record or "attachments" in record
    if "body" in item:
        body = str(item["body"] or "")
        item.update(body=body[:PREVIEW_CHARS], body_chars=len(body), body_truncated=len(body) > PREVIEW_CHARS)
    item["content_ready"] = bool(item.get("body"))
    call = detail_call(record, refresh=not item["detail_available"])
    if call:
        item["detail_call"] = call
    return item


def notice_page(record: dict, *, cached: bool, offset: int, max_chars: int) -> dict:
    body = str(record.get("body") or "")
    available = "body" in record or "attachments" in record
    end = min(len(body), offset + max_chars)
    item = dict(record)
    if "body" in item:
        item["body"] = body[offset:end]
    result = {"ok": True, "status": "ok" if available else "metadata_only", "item": item,
              "cached": cached, "detail_available": available, "content_ready": bool(body),
              "offset": offset, "total_chars": len(body), "has_more": end < len(body),
              "next_offset": end if end < len(body) else None, "content_trust": "untrusted_source_data"}
    if record.get("source") == "public":
        result["source_access"] = dict(PUBLIC_SOURCE_ACCESS)
    if "attachments" in item:
        result["attachment_options"] = [{"index": index, "name": attachment["name"]}
                                        for index, attachment in enumerate(item["attachments"])]
    if not available:
        result["message"] = "当前只有列表记录，尚未读取正文和附件列表。"
        call = detail_call(record, refresh=True)
        if call:
            result.update(next_action=call["tool"], next_call=call)
    elif end < len(body):
        result["next_call"] = {"tool": "get_notice", "arguments": {
            "item_id": record["id"], "refresh": False, "offset": end, "max_chars": max_chars}}
    return result


def source_link_result(record: dict, error: AppError, *, attachment: dict | None = None) -> dict:
    """Share only the validated notice URL, never an authentication/download challenge URL."""
    result = {**error.result(), "next_action": "show_source_link", "handoff_required": True, "content_ready": False,
              "source_url": checked_url(record["source"], record["url"]), "title": record["title"],
              "user_message": error.message,
              "content_trust": "untrusted_source_data"}
    result["message"] += (" 当前附件的全文自动获取已经结束。立即用 title、source_url 和 user_message 交接给用户；"
                          "不得为补齐此附件继续调用工具，包括重试下载、刷新 OA、遍历缓存、换来源或借其他工具取全文。"
                          "尚未整理出完整条款不是继续调用的理由；用户要求总结条款不等于授权寻找替代版本。"
                          "只有用户已明确要求找替代公开版本时，才按该授权继续检索。")
    if record["source"] == "public":
        result["source_access"] = dict(PUBLIC_SOURCE_ACCESS)
    if attachment:
        result["name"] = attachment["name"]
    return result
