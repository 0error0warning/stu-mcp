"""Pure input and provider-response validation for anonymous Huyou reads."""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from ...parsing import clean, item_id
from ...runtime import AppError
from .schema import DEFAULT_CIRCLE, WEB_BASE


def integer(value) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None

def param_string(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AppError("invalid_parameters", "狐友参数不能包含非有限数值。", "huyou")
        if value.is_integer():
            return str(int(value))
    return str(value)

def numeric_id(value: str, label: str = "帖子") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,24}", value) or int(value) == 0:
        raise AppError("invalid_id", f"请提供有效的数字{label} ID。", "huyou")
    return value

def feed_id(target: str) -> str:
    if not isinstance(target, str):
        raise AppError("invalid_id", "请提供帖子 ID 或狐友公开帖子链接。", "huyou")
    target = target.strip()
    if target.isdigit():
        return numeric_id(target)
    try:
        parsed = urlparse(target)
    except ValueError:
        raise AppError("invalid_id", "请提供有效的狐友公开帖子链接。", "huyou") from None
    if (parsed.scheme == "https" and parsed.netloc == "hy.sns.sohu.com" and parsed.path in ("", "/")
            and not parsed.fragment and set(parse_qs(parsed.query)) == {"feedDetail"}):
        values = parse_qs(parsed.query)["feedDetail"]
        if len(values) == 1:
            return numeric_id(values[0])
    raise AppError("invalid_id", "请提供数字帖子 ID 或 https://hy.sns.sohu.com/?feedDetail=帖子ID 链接。", "huyou")

def search_plan(query: str, keywords: list[str] | None = None) -> dict:
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise AppError("invalid_query", "原问题或搜索词不能为空，最长 2000 字。", "huyou")
    if keywords is not None and (not isinstance(keywords, list) or not keywords):
        raise AppError("invalid_keywords", "关键词必须是 1–6 个非空字符串的列表。", "huyou")
    terms = []
    for keyword in [query] if keywords is None else keywords:
        if (not isinstance(keyword, str) or not keyword.strip() or len(keyword.strip()) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in keyword)):
            raise AppError("invalid_keywords", "每个字面关键词为 1–512 字，不能包含控制字符。", "huyou")
        if keyword.strip() not in terms:
            terms.append(keyword.strip())
    if len(terms) > 6:
        raise AppError("invalid_keywords", "最多 6 个关键词；请由当前 agent 精简，不会自动拆词或截断。", "huyou")
    return {"query": query.strip(), "keywords": terms, "strategy": "explicit" if keywords is not None else "literal",
            "match_mode": "literal", "combine": "union"}

def text(value, limit: int = 12000) -> str:
    return clean(re.sub(r"<[^>]+>", "", value))[:limit] if isinstance(value, str) else ""

def published(value) -> str | None:
    stamp = integer(value)
    if stamp is not None and stamp >= 1_000_000_000_000:
        try:
            return datetime.fromtimestamp(stamp / 1000, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return None

def image_urls(row: dict) -> list[str]:
    pic_feed = row.get("picFeed")
    pictures = pic_feed.get("pics", []) if isinstance(pic_feed, dict) else []
    candidates = [p.get("url") if isinstance(p, dict) else p for p in pictures[:9]] if isinstance(pictures, list) else []
    if row.get("picUrl"):
        candidates.append(row["picUrl"])
    urls = []
    for url in candidates:
        if isinstance(url, str) and len(url) <= 2000:
            try:
                parsed = urlparse(url)
            except ValueError:
                continue
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and url not in urls:
                urls.append(url)
    return urls[:9]

def schema_error(message: str = "狐友记录字段发生变化，未当作空结果。") -> AppError:
    return AppError("schema_changed", message, "huyou")


def provider_id(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise schema_error("狐友记录缺少有效的数字身份。")
    result = str(value)
    if not re.fullmatch(r"[0-9]{1,24}", result) or int(result) == 0:
        raise schema_error("狐友记录缺少有效的数字身份。")
    return result


def provider_integer(value, *, minimum: int | None = None) -> int:
    if (isinstance(value, bool) or not isinstance(value, (str, int))
            or len(str(value)) > 30 or not re.fullmatch(r"-?[0-9]+", str(value))):
        raise schema_error()
    result = int(value)
    if minimum is not None and result < minimum:
        raise schema_error()
    return result


def optional_integer(row: dict, key: str, *, minimum: int | None = None) -> int | None:
    value = row.get(key)
    return None if value is None else provider_integer(value, minimum=minimum)


def provider_flag(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if type(value) not in (bool, int) or value not in (0, 1):
        raise schema_error()
    return bool(value)


def provider_text(row: dict, key: str, *, required: bool = False) -> str:
    value = row.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise schema_error("狐友文本字段发生变化，未用空正文替换缓存。")
    return value


def validate_record(row: dict) -> None:
    if not isinstance(row, dict):
        raise schema_error()
    for key in ("content", "title", "userName", "circleName", "replyUserName"):
        if key in row:
            provider_text(row, key, required=key == "content")
    provider_text(row, "content", required=True)
    for key in ("anonymous", "contentIsSub", "ownerHidden", "isAuthor"):
        provider_flag(row.get(key))
    for key in ("status", "feedAttr", "score", "timeId", "commentCount", "likeCount", "replyCount"):
        optional_integer(row, key, minimum=0)
    if row.get("circle") is not None:
        if not isinstance(row["circle"], dict):
            raise schema_error()
        provider_text(row["circle"], "circleName")
    for value in (row.get("circleId"), (row.get("circle") or {}).get("circleId"),
                  row.get("commentId"), row.get("replyCommentId")):
        if value is not None:
            provider_id(value)
    if row.get("picFeed") is not None:
        pictures = row["picFeed"]
        if not isinstance(pictures, dict) or not isinstance(pictures.get("pics", []), list):
            raise schema_error()
        if any(not isinstance(p, (str, dict)) for p in pictures.get("pics", [])):
            raise schema_error()


def unique_records(rows: list[dict], identity: str) -> None:
    seen = set()
    for row in rows:
        value = provider_id(row[identity])
        if value in seen:
            raise schema_error("狐友同一响应出现重复记录身份，未合并冲突数据。")
        seen.add(value)


def search_records(rows: list[dict], circle_id: str, keyword: str) -> list[dict]:
    records = [record for row in rows if (record := post_record(row, circle_id, keyword)) is not None]
    unique_records(records, "feed_id")
    return records


def comment_records(rows: list[dict], root_id: str | None = None) -> list[dict]:
    records = [record for row in rows if (record := comment_record(row, root_id)) is not None]
    unique_records(records, "comment_id")
    return records


def reply_preview(row: dict, root_id: str, reply_count: int) -> tuple[list[dict], str, bool]:
    if row.get("replyCount") is None:
        raise schema_error("狐友评论缺少回复数量，无法确认讨论完整性。")
    preview = row.get("replies")
    if preview is None and "replies" not in row:
        preview = {}
    if not isinstance(preview, dict) or ("replies" in row and "list" not in preview):
        raise schema_error("狐友内嵌回复结构发生变化。")
    rows = preview.get("list", [])
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise schema_error("狐友内嵌回复结构发生变化。")
    replies = comment_records(rows, root_id)
    has_more = provider_flag(preview.get("hasMore"))
    has_up = provider_flag(preview.get("hasMoreUp"))
    more = has_more or has_up or reply_count > len(replies)
    score = cursor(preview.get("score") if has_more and not has_up else 0)
    return replies, score, more


def circle_records(data: dict) -> tuple[list[dict], bool, int | None]:
    rows = data.get("circleList")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise schema_error("狐友未返回可识别的圈子列表。")
    if "hasMore" not in data:
        raise schema_error("狐友圈子分页字段发生变化。")
    has_more = provider_flag(data["hasMore"])
    next_page = optional_integer(data, "pageIndex")
    if has_more and (next_page is None or next_page < 1):
        raise schema_error("狐友圈子搜索缺少下一页页码。")
    items = [{"circle_id": provider_id(row.get("circleId")), "name": text(provider_text(row, "circleName"), 100),
              "url": WEB_BASE + "circle/" + provider_id(row.get("circleId"))} for row in rows[:50]]
    unique_records(items, "circle_id")
    return items, has_more, next_page


def detail_record(data: dict, fid: str) -> dict:
    post = data.get("sourceFeed")
    if not isinstance(post, dict) or provider_id(post.get("feedId")) != fid:
        raise schema_error("狐友详情未返回对应的帖子。")
    if optional_integer(post, "status", minimum=0) == 0 or provider_flag(post.get("ownerHidden")):
        raise AppError("post_unavailable", "此帖子已删除或设为私密，不继续读取讨论。", "huyou")
    record = post_record(post, detail=True)
    if record is None:
        raise schema_error("狐友详情无法识别为公开帖子。")
    return record


def post_record(post: dict, circle_id: str = "", keyword: str = "", *, detail: bool = False) -> dict | None:
    if not isinstance(post, dict):
        raise schema_error()
    if optional_integer(post, "feedAttr", minimum=0) == 8:
        return None  # Explicit member cards are not posts; missing identities are errors.
    fid = provider_id(post.get("feedId"))
    if optional_integer(post, "status", minimum=0) == 0 or provider_flag(post.get("ownerHidden")):
        return None
    validate_record(post)
    circle = post.get("circle") if isinstance(post.get("circle"), dict) else {}
    cid = str(circle.get("circleId") or post.get("circleId") or circle_id)
    body = text(post.get("content"))
    result = {"id": item_id("huyou", "post", fid), "kind": "post", "source": "huyou",
              "feed_id": fid, "circle_id": cid,
              "circle_name": text(circle.get("circleName") or post.get("circleName"), 100)
              or ("汕大树洞" if cid == DEFAULT_CIRCLE else cid),
              "title": text(post.get("title"), 120) or body[:80] or f"狐友帖子 {fid}",
              "body": body, "url": WEB_BASE + "?feedDetail=" + fid, "published_at": published(post.get("score")),
              "source_type": "community", "official": False, "author_name": text(post.get("userName"), 100),
              "anonymous": bool(post.get("anonymous")), "detail_fetched": detail,
              "content_truncated": bool(post.get("contentIsSub")) or len(str(post.get("content") or "")) > 12000,
              "comment_count": integer(post.get("commentCount")), "search_hits": []}
    result["images"] = image_urls(post)
    # Public nicknames are useful context; account IDs, avatars and raw payloads are not stored.
    if detail:
        result["detail_fetched_at"] = datetime.now(UTC).isoformat()
    if keyword:
        result["search_hits"] = [{"keyword": keyword, "excerpt": body[:1200],
                                  "comment_id": str(post["commentId"]) if post.get("commentId") else None}]
    return result

def page_rows(data: dict, key: str, *, numbered: bool = False) -> tuple[list[dict], dict]:
    if not isinstance(data, dict):
        raise schema_error()
    rows, info = data.get(key), data.get("pageInfo")
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or not isinstance(info, dict)
            or type(info.get("hasMore")) not in (bool, int) or info["hasMore"] not in (0, 1)):
        raise AppError("schema_changed", "狐友列表或分页字段发生变化，未当作空结果。", "huyou")
    if numbered:
        next_page = optional_integer(info, "pageIndex")
        if info["hasMore"] and (next_page is None or next_page < 1):
            raise schema_error("狐友搜索缺少下一页页码。")
    else:
        optional_integer(info, "totalCount", minimum=0)
        if info["hasMore"]:
            cursor(info.get("score"))
    return rows, info

def cursor(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AppError("schema_changed", "狐友返回了无效的评论游标。", "huyou")
    try:
        result = param_string(value)
    except AppError:
        raise schema_error("狐友返回了无效的评论游标。") from None
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", result) or len(result) > 50:
        raise AppError("schema_changed", "狐友返回了无效的评论游标。", "huyou")
    return result[:-2] if result.endswith(".0") else result

def comment_record(row: dict, root_id: str | None = None) -> dict | None:
    if not isinstance(row, dict):
        raise schema_error()
    if optional_integer(row, "status", minimum=0) == 0:
        return None
    cid = provider_id(row.get("commentId"))
    validate_record(row)
    result = {"comment_id": cid, "content": text(row.get("content"), 3000),
              "content_truncated": bool(row.get("contentIsSub")) or len(str(row.get("content") or "")) > 3000,
              "author_name": text(row.get("userName"), 100), "anonymous": bool(row.get("anonymous")),
              "is_author": bool(row.get("isAuthor")), "published_at": published(row.get("timeId")),
              "like_count": integer(row.get("likeCount")) or 0,
              "reply_count": max(0, integer(row.get("replyCount")) or 0)}
    result["images"] = image_urls(row)
    if root_id:
        result.update(root_comment_id=root_id, reply_to_comment_id=str(row.get("replyCommentId") or root_id),
                      reply_to_name=text(row.get("replyUserName"), 100))
    else:
        result["replies"] = []
    return result


def response_data(payload) -> dict:
    if not isinstance(payload, dict):
        raise schema_error("狐友响应结构发生变化。")
    status = provider_integer(payload.get("status"))
    if status in (304023, 40110, 200004):
        raise AppError("huyou_login_required", "此狐友内容需要登录；本版仅支持公开读取。", "huyou")
    if status != 100000 or not isinstance(payload.get("data"), dict):
        raise AppError("source_rejected", "狐友未返回成功数据，未当作空结果。", "huyou")
    return payload["data"]
