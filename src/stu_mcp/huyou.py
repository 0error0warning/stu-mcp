"""Anonymous, bounded reads of the official Huyou web client's public interfaces.

Adapted from School Hub 3986c4ae49d2ffed4e41582a4f40a2fdd8ef31fa.
No account cookies, private content, browser, model calls or background collection.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .parsers import clean, item_id
from .runtime import AppError

API_BASE = "https://cs-ol.sns.sohu.com"
WEB_BASE = "https://hy.sns.sohu.com/"
DEFAULT_CIRCLE = "905956136904237440"
APP_VERSION = "6.22.0"
PUBLIC_SIGNING_CONSTANT = "30lh2d011v20d362"
API_PATHS = frozenset({"/circle/search/v20", "/circle/search/feed/v22", "/v7/feeds/show",
                       "/v8/comment/list", "/v8/comment/replylist"})
STOP_CODES = frozenset({"huyou_login_required", "rate_limited", "request_limit", "request_deadline"})


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


def sign_params(params: dict, timestamp_ms: int | None = None) -> dict[str, str]:
    values = {k: param_string(v) for k, v in params.items() if v is not None and k != "sig"}
    values.update(appid="330012", app_key_vs=APP_VERSION,
                  flyer=str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)))
    basis = "".join(sorted(f"{k}={v}" for k, v in values.items())) + PUBLIC_SIGNING_CONSTANT
    values["sig"] = hashlib.md5(basis.encode()).hexdigest()
    return values


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
    parsed = urlparse(target)
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
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and url not in urls:
                urls.append(url)
    return urls[:9]


def post_record(post: dict, circle_id: str = "", keyword: str = "", *, detail: bool = False) -> dict | None:
    fid = str(post.get("feedId") or "")
    if not re.fullmatch(r"[0-9]{1,24}", fid) or post.get("feedAttr") == 8:
        return None  # Member cards are not posts.
    if post.get("status") == 0 or post.get("ownerHidden"):
        return None
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
    rows, info = data.get(key), data.get("pageInfo")
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or not isinstance(info, dict)
            or type(info.get("hasMore")) not in (bool, int) or info["hasMore"] not in (0, 1)):
        raise AppError("schema_changed", "狐友列表或分页字段发生变化，未当作空结果。", "huyou")
    if numbered and info["hasMore"] and integer(info.get("pageIndex")) is None:
        raise AppError("schema_changed", "狐友搜索缺少下一页页码。", "huyou")
    return rows, info


def cursor(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise AppError("schema_changed", "狐友返回了无效的评论游标。", "huyou")
    result = param_string(value)
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", result) or len(result) > 50:
        raise AppError("schema_changed", "狐友返回了无效的评论游标。", "huyou")
    return result[:-2] if result.endswith(".0") else result


def comment_record(row: dict, root_id: str | None = None) -> dict | None:
    if row.get("status") == 0:
        return None
    cid = numeric_id(str(row.get("commentId") or ""), "评论")
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


class HuyouClient:
    def __init__(self, *, transport=None):
        self.client = httpx.Client(verify=True, trust_env=False, follow_redirects=False, transport=transport,
                                   timeout=httpx.Timeout(15, connect=8), headers={
                                       "User-Agent": "STU-MCP (+https://github.com/0error0warning/stu-mcp)",
                                       "Referer": WEB_BASE, "Origin": WEB_BASE.rstrip("/"),
                                       "S-VS": APP_VERSION, "P-APPID": "110503"})
        self.requests, self.retries, self._sign_ms = 0, 0, 0
        self.deadline, self.last_request = time.monotonic() + 45, 0.0
        self.stopped: AppError | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.client.close()

    def get(self, path: str, params: dict) -> dict:
        if path not in API_PATHS:
            raise AppError("unsafe_url", "狐友只允许指定的公开读取接口。", "huyou")
        for attempt in range(2):
            if self.stopped:
                raise self.stopped
            if self.requests >= 40 or time.monotonic() >= self.deadline:
                code = "request_limit" if self.requests >= 40 else "request_deadline"
                self.stopped = AppError(code, "此轮狐友读取已达 40 次请求或 45 秒上限，保留已获取结果。", "huyou")
                raise self.stopped
            delay = max(0, 0.25 - (time.monotonic() - self.last_request))
            if delay:
                time.sleep(delay)
            if time.monotonic() >= self.deadline:
                self.stopped = AppError("request_deadline", "此轮狐友读取已达时间上限，保留已获取结果。", "huyou")
                raise self.stopped
            self.last_request, self.requests = time.monotonic(), self.requests + 1
            self._sign_ms = max(int(time.time() * 1000), self._sign_ms + 1)
            self.client.cookies.clear()  # Never adopt Set-Cookie as an account session.
            url = API_BASE + path + "?" + urlencode(sign_params(params, self._sign_ms))
            try:
                with self.client.stream("GET", url, timeout=min(15, max(0.1, self.deadline - time.monotonic()))) as r:
                    if r.status_code in (401, 403):
                        self.stopped = AppError("huyou_login_required", "狐友要求登录或拒绝访问；本版仅支持公开读取。", "huyou")
                        raise self.stopped
                    if r.is_redirect:
                        raise AppError("unsafe_redirect", "狐友返回跳转，未转发请求或认证数据。", "huyou")
                    if r.status_code in (429, 500, 502, 503, 504):
                        retry_after = r.headers.get("Retry-After", "0.5")
                        try:
                            retry_delay = float(retry_after)
                        except ValueError:
                            try:
                                retry_delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                            except (TypeError, ValueError, OverflowError):
                                retry_delay = 0.5
                        if (r.status_code == 429 and attempt or not math.isfinite(retry_delay) or retry_delay > 2
                                or time.monotonic() + max(0, retry_delay) >= self.deadline):
                            self.stopped = AppError("rate_limited", "狐友要求稍后重试，已停止本轮读取。", "huyou")
                            raise self.stopped
                        if attempt == 0:
                            self.retries += 1
                            time.sleep(max(0, retry_delay))
                            continue
                    r.raise_for_status()
                    parts, size = [], 0
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            raise AppError("response_too_large", "狐友响应超过 2 MiB 上限。", "huyou")
                        if time.monotonic() > self.deadline:
                            self.stopped = AppError("request_deadline", "此轮狐友读取已达时间上限。", "huyou")
                            raise self.stopped
                        parts.append(chunk)
                payload = json.loads(b"".join(parts))
                break
            except httpx.TransportError:
                if attempt == 0:
                    self.retries += 1
                    continue
                raise AppError("network_error", "狐友暂时无法连接，请稍后重试。", "huyou") from None
            except httpx.HTTPError:
                raise AppError("network_error", "狐友 HTTP 读取失败，未当作空结果。", "huyou") from None
            except (ValueError, UnicodeError):
                raise AppError("schema_changed", "狐友未返回有效 JSON，未当作空结果。", "huyou") from None
        if not isinstance(payload, dict):
            raise AppError("schema_changed", "狐友响应结构发生变化。", "huyou")
        if integer(payload.get("status")) in (304023, 40110, 200004):
            self.stopped = AppError("huyou_login_required", "此狐友内容需要登录；本版仅支持公开读取。", "huyou")
            raise self.stopped
        if integer(payload.get("status")) != 100000 or not isinstance(payload.get("data"), dict):
            raise AppError("source_rejected", "狐友未返回成功数据，未当作空结果。", "huyou")
        return payload["data"]

    def circles(self, query: str, page: int = 1) -> dict:
        search_plan(query)
        if type(page) is not int or not 1 <= page <= 5:
            raise AppError("invalid_limit", "圈子搜索页码为 1–5。", "huyou")
        data = self.get("/circle/search/v20", {"query": query.strip(), "page_index": page})
        rows = data.get("circleList")
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise AppError("schema_changed", "狐友未返回可识别的圈子列表。", "huyou")
        items = []
        for row in rows[:50]:
            cid = numeric_id(str(row.get("circleId") or ""), "圈子")
            items.append({"circle_id": cid, "name": text(row.get("circleName"), 100),
                          "url": WEB_BASE + "circle/" + cid})
        return {"ok": True, "source": "huyou", "items": items, "has_more": bool(data.get("hasMore")),
                "next_page": integer(data.get("pageIndex")), "cached": False,
                "content_trust": "untrusted_source_data", "official": False}

    def detail(self, target: str) -> dict:
        fid = feed_id(target)
        post = self.get("/v7/feeds/show", {"feed_id": fid}).get("sourceFeed")
        if not isinstance(post, dict) or str(post.get("feedId")) != fid:
            raise AppError("schema_changed", "狐友详情未返回对应的帖子。", "huyou")
        if post.get("status") == 0 or post.get("ownerHidden"):
            raise AppError("post_unavailable", "此帖子已删除或设为私密，不继续读取讨论。", "huyou")
        record = post_record(post, detail=True)
        if record is None:
            raise AppError("schema_changed", "狐友详情无法识别为公开帖子。", "huyou")
        return record

    def search(self, plan: dict, circle_id: str = DEFAULT_CIRCLE, *, limit: int = 10, pages: int = 2) -> dict:
        numeric_id(circle_id, "圈子")
        if type(limit) is not int or not 1 <= limit <= 20 or type(pages) is not int or not 1 <= pages <= 3:
            raise AppError("invalid_limit", "狐友搜索每次 1–20 帖，每词最多 1–3 页。", "huyou")
        runs, buckets, merged, errors, limited = [], [], {}, [], False
        for keyword in plan["keywords"]:
            if self.stopped:
                runs.append({"keyword": keyword, "status": "skipped", "count": 0})
                continue
            found, page, fetched, has_more = {}, 1, 0, False
            run_errors = []
            for _ in range(pages):
                try:
                    data = self.get("/circle/search/feed/v22", {"circle_id": circle_id, "query": keyword,
                                                              "page_index": page, "size": min(20, limit), "search_type": 2})
                    rows, info = page_rows(data, "feedList", numbered=True)
                    fetched += 1
                    has_more = bool(info["hasMore"])
                    for row in rows:
                        item = post_record(row, circle_id, keyword)
                        if item:
                            fid = item["feed_id"]
                            if fid not in found and len(found) < limit:
                                found[fid] = item
                            if fid in merged:
                                merged[fid] = merge_post(merged[fid], item)
                            else:
                                merged[fid] = item
                    if len(found) >= limit and len(rows) > len(found):
                        limited = True
                    if len(found) >= limit or not has_more:
                        break
                    next_page = integer(info.get("pageIndex"))
                    if next_page is None or next_page <= page:
                        raise AppError("schema_changed", "狐友搜索下一页页码无效，已停止分页。", "huyou")
                    page = next_page
                except AppError as exc:
                    run_errors.append(exc.result())
                    break
            limited |= has_more
            errors.extend(run_errors)
            buckets.append(list(found))
            runs.append({"keyword": keyword, "count": len(found), "pages_fetched": fetched,
                         "has_more": has_more, "status": "partial" if run_errors and fetched else
                         "failed" if run_errors else "ok", "errors": run_errors})
        selected, positions = [], [0] * len(buckets)
        while len(selected) < limit:
            progressed = False
            for index, bucket in enumerate(buckets):
                while positions[index] < len(bucket) and bucket[positions[index]] in selected:
                    positions[index] += 1
                if positions[index] < len(bucket) and len(selected) < limit:
                    selected.append(bucket[positions[index]])
                    positions[index] += 1
                    progressed = True
            if not progressed:
                break
        limited |= len(merged) > len(selected)
        if errors and not selected and not any(r.get("pages_fetched") for r in runs):
            error = errors[0]
            raise AppError(error["status"], error["message"], "huyou")
        return {"ok": True, "source": "huyou", "items": [merged[fid] for fid in selected], "plan": plan,
                "circle_id": circle_id, "keyword_runs": runs, "errors": errors, "limited": limited,
                "status": "partial" if errors or limited else "ok", "cached": False,
                "coverage": {"scope": "circle_keyword_search", "posts": limit, "pages_per_keyword": pages},
                "request_count": self.requests, "retry_count": self.retries,
                "content_trust": "untrusted_source_data", "official": False}

    def discussion(self, target: str, *, comment_limit: int = 20, reply_limit: int = 10,
                   reported_total: int | None = None) -> dict:
        fid = feed_id(target)
        if (type(comment_limit) is not int or not 1 <= comment_limit <= 40
                or type(reply_limit) is not int or not 0 <= reply_limit <= 20):
            raise AppError("invalid_limit", "每帖主评论上限 1–40，楼中楼回复总上限 0–20。", "huyou")
        result = empty_discussion(comment_limit, reply_limit)
        result["reported_total"] = reported_total
        if reported_total == 0:
            return result
        roots, originals, score, cursors = {}, {}, "0", {"0"}
        for _ in range(3):
            try:
                data = self.get("/v8/comment/list", {"feed_id": fid, "stpl": "1,2,4,7,8,9,16",
                                                     "score": score, "count": min(20, comment_limit - len(roots))})
                rows, info = page_rows(data, "list")
                result["pages_fetched"] += 1
                if integer(info.get("totalCount")) is not None:
                    result["reported_total"] = integer(info["totalCount"])
                result["has_more"] = bool(info["hasMore"])
                added = 0
                for row in rows:
                    comment = comment_record(row)
                    if comment and comment["comment_id"] not in roots:
                        if len(roots) >= comment_limit:
                            result["truncated"] = True
                            break
                        roots[comment["comment_id"]], originals[comment["comment_id"]] = comment, row
                        added += 1
                if not result["has_more"]:
                    break
                next_score = cursor(info.get("score"))
                result["next_score"] = next_score
                if len(roots) >= comment_limit:
                    break
                if next_score in cursors or added == 0:
                    raise AppError("schema_changed", "狐友评论游标重复或未返回新评论，已停止分页。", "huyou")
                score = next_score
                cursors.add(score)
            except AppError as exc:
                result["errors"].append(exc.result())
                break
        result["comments_complete"] = not result["errors"] and not result["has_more"] and not result["truncated"]
        result["truncated"] |= result["has_more"]
        threads = []
        for cid, root in roots.items():
            preview = originals[cid].get("replies")
            preview = preview if isinstance(preview, dict) else {}
            rows = preview.get("list", [])
            replies, errors = [], []
            try:
                if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                    raise AppError("schema_changed", "狐友内嵌回复结构发生变化。", "huyou")
                for row in rows:
                    reply = comment_record(row, root_id=cid)
                    if reply and reply["comment_id"] not in {r["comment_id"] for r in replies}:
                        replies.append(reply)
                more = bool(preview.get("hasMore") or preview.get("hasMoreUp") or root["reply_count"] > len(replies))
                initial = preview.get("score") if preview.get("hasMore") and not preview.get("hasMoreUp") else 0
                reply_score = cursor(initial)
            except AppError as exc:
                errors.append(exc.result())
                result["errors"].append(exc.result())
                reply_score, more = "0", False
            threads.append({"root": root, "preview": replies, "score": reply_score, "more": more,
                            "cursors": {reply_score}, "pages": 0, "errors": errors})
        reply_count = 0
        for index in range(max((len(t["preview"]) for t in threads), default=0)):
            for thread in threads:
                if index < len(thread["preview"]) and reply_count < reply_limit:
                    thread["root"]["replies"].append(thread["preview"][index])
                    reply_count += 1
        for _ in range(2):
            for thread in threads:
                if reply_count >= reply_limit or self.stopped:
                    break
                if not thread["more"]:
                    continue
                root = thread["root"]
                try:
                    data = self.get("/v8/comment/replylist", {"feed_id": fid, "comment_id": root["comment_id"],
                                                            "stpl": "1,2,3,4,7,9,11,12,13,16",
                                                            "score": thread["score"], "count": min(5, reply_limit - reply_count)})
                    rows, info = page_rows(data, "list")
                    thread["pages"] += 1
                    result["reply_pages_fetched"] += 1
                    thread["more"] = bool(info["hasMore"])
                    added, seen = 0, {r["comment_id"] for r in root["replies"]}
                    for row in rows:
                        reply = comment_record(row, root_id=root["comment_id"])
                        if reply and reply["comment_id"] not in seen:
                            if reply_count >= reply_limit:
                                thread["more"] = True
                                break
                            root["replies"].append(reply)
                            seen.add(reply["comment_id"])
                            reply_count, added = reply_count + 1, added + 1
                    if thread["more"]:
                        next_score = cursor(info.get("score"))
                        if next_score in thread["cursors"] or added == 0:
                            raise AppError("schema_changed", "狐友回复游标重复或未返回新回复，已停止分页。", "huyou")
                        thread["score"] = next_score
                        thread["cursors"].add(next_score)
                except AppError as exc:
                    result["errors"].append(exc.result())
                    thread["errors"].append(exc.result())
                    thread["more"] = False
            if reply_count >= reply_limit or self.stopped:
                break
        for thread in threads:
            root = thread["root"]
            root["replies_truncated"] = (thread["more"] or len(root["replies"]) < root["reply_count"]
                                         or len(root["replies"]) < len(thread["preview"])
                                         or any(r["content_truncated"] for r in root["replies"]))
            root["replies_complete"] = not root["replies_truncated"] and not thread["errors"]
            root["reply_errors"] = thread["errors"]
            result["truncated"] |= root["replies_truncated"] or root["content_truncated"]
        result.update(comments=list(roots.values()), comment_count=len(roots), reply_count=reply_count)
        if result["reported_total"] is not None and result["reported_total"] > len(roots) + reply_count:
            result["truncated"] = True
        result["complete"] = not result["errors"] and not result["truncated"]
        return result


def empty_discussion(comment_limit: int = 20, reply_limit: int = 10) -> dict:
    return {"comments": [], "comment_count": 0, "reply_count": 0, "reported_total": None,
            "comment_limit": comment_limit, "reply_limit": reply_limit, "has_more": False,
            "pages_fetched": 0, "reply_pages_fetched": 0, "truncated": False, "errors": [],
            "complete": True, "comments_complete": True, "fetched_at": datetime.now(UTC).isoformat()}


def merge_discussion(old: dict, new: dict) -> dict:
    if new.get("complete"):
        return deepcopy(new)
    previous = {r["comment_id"]: {**deepcopy(r), "retained_from_cache": True,
                                  "replies": [{**deepcopy(p), "retained_from_cache": True} for p in r["replies"]]}
                for r in old.get("comments", [])}
    roots = {} if new.get("comments_complete") else dict(previous)
    for row in new.get("comments", []):
        prev = previous.get(row["comment_id"], {})
        replies = {} if row.get("replies_complete") else {r["comment_id"]: r for r in prev.get("replies", [])}
        for reply in row["replies"]:
            previous_reply = replies.get(reply["comment_id"], {})
            refreshed_reply = deepcopy(reply)
            if reply.get("content_truncated") and previous_reply and not previous_reply.get("content_truncated"):
                refreshed_reply.update(content=previous_reply["content"], retained_from_cache=True)
            replies[reply["comment_id"]] = refreshed_reply
        refreshed = {**deepcopy(row), "replies": list(replies.values())}
        if row.get("content_truncated") and prev and not prev.get("content_truncated"):
            refreshed.update(content=prev["content"], retained_from_cache=True)
        roots[row["comment_id"]] = refreshed
    result = {**deepcopy(new), "comments": list(roots.values()), "complete": False,
              "comment_count": len(roots), "reply_count": sum(len(r["replies"]) for r in roots.values())}
    if any(r.get("retained_from_cache") or any(p.get("retained_from_cache") for p in r["replies"])
           for r in roots.values()):
        result.update(retained_from_cache=True, previous_fetched_at=old.get("fetched_at"))
    return result


def merge_post(old: dict, new: dict) -> dict:
    result = {**deepcopy(old), **deepcopy(new)}
    for key in ("circle_id", "circle_name"):
        if not result.get(key) and old.get(key):
            result[key] = old[key]
    if old.get("detail_fetched") and (not new.get("detail_fetched") or
                                     new.get("content_truncated") and not old.get("content_truncated")):
        for key in ("body", "title", "detail_fetched", "detail_fetched_at", "content_truncated"):
            if key in old:
                result[key] = old[key]
        result["body_retained_from_cache"] = True
    elif new.get("detail_fetched"):
        result.pop("body_retained_from_cache", None)
    if new.get("detail_fetched"):
        result.pop("detail_error", None)
    hits = {(h.get("keyword"), h.get("comment_id"), h.get("excerpt")): h
            for h in old.get("search_hits", []) + new.get("search_hits", [])}
    result["search_hits"] = list(hits.values())[-30:]
    if new.get("discussion"):
        result["discussion"] = merge_discussion(old.get("discussion", {}), new["discussion"])
    elif old.get("discussion"):
        result["discussion"] = {**deepcopy(old["discussion"]), "retained_from_cache": True}
    return result


def searchable_text(item: dict) -> str:
    discussion = item.get("discussion", {})
    return "\n".join([item.get("title", ""), item.get("body", ""),
                      *(h.get("excerpt", "") for h in item.get("search_hits", [])),
                      *(r.get("content", "") for r in discussion.get("comments", [])),
                      *(p.get("content", "") for r in discussion.get("comments", []) for p in r.get("replies", []))])


def post_preview(item: dict, with_discussion: bool = False) -> dict:
    """Bound discovery results even when their cache contains a much larger discussion."""
    result = deepcopy(item)
    result["body_preview_truncated"] = len(result.get("body", "")) > 1200
    result["body"] = result.get("body", "")[:1200]
    result["search_hits"] = [{**h, "excerpt": h.get("excerpt", "")[:400]}
                             for h in result.get("search_hits", [])[-6:]]
    discussion = result.pop("discussion", None)
    if discussion:
        result["discussion_coverage"] = {k: discussion.get(k) for k in (
            "complete", "comment_count", "reply_count", "truncated", "fetched_at", "retained_from_cache")}
        if with_discussion:
            shown = {**discussion, "comments": deepcopy(discussion["comments"][:5])}
            shown["response_truncated"] = len(discussion["comments"]) > 5
            replies_left = 5
            for root in shown["comments"]:
                shown["response_truncated"] |= len(root["content"]) > 500 or len(root["replies"]) > replies_left
                root["content"] = root["content"][:500]
                root["replies"] = root["replies"][:replies_left]
                replies_left -= len(root["replies"])
                for reply in root["replies"]:
                    shown["response_truncated"] |= len(reply["content"]) > 500
                    reply["content"] = reply["content"][:500]
            result["discussion"] = shown
    return result
