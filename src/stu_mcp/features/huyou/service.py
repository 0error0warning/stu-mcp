"""Bounded search and discussion orchestration, independent of transport and cache."""
from __future__ import annotations

from ...runtime import AppError
from .adapter import HuyouHTTP
from .cache import empty_discussion, merge_post
from .parser import (
    circle_records,
    comment_records,
    cursor,
    detail_record,
    feed_id,
    integer,
    numeric_id,
    page_rows,
    reply_preview,
    search_plan,
    search_records,
)
from .schema import CIRCLES_PATH, COMMENTS_PATH, DEFAULT_CIRCLE, DETAIL_PATH, REPLIES_PATH, SEARCH_PATH


class HuyouClient(HuyouHTTP):
    def circles(self, query: str, page: int = 1) -> dict:
        search_plan(query)
        if type(page) is not int or not 1 <= page <= 5:
            raise AppError("invalid_limit", "圈子搜索页码为 1–5。", "huyou")
        data = self.get(CIRCLES_PATH, {"query": query.strip(), "page_index": page})
        items, has_more, next_page = circle_records(data)
        return {"ok": True, "source": "huyou", "items": items, "has_more": has_more,
                "next_page": next_page, "cached": False,
                "content_trust": "untrusted_source_data", "official": False}

    def detail(self, target: str) -> dict:
        fid = feed_id(target)
        return detail_record(self.get(DETAIL_PATH, {"feed_id": fid}), fid)

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
                    data = self.get(SEARCH_PATH, {"circle_id": circle_id, "query": keyword,
                                                              "page_index": page, "size": min(20, limit), "search_type": 2})
                    rows, info = page_rows(data, "feedList", numbered=True)
                    records = search_records(rows, circle_id, keyword)
                    fetched += 1
                    has_more = bool(info["hasMore"])
                    for item in records:
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
        reported_totals = set() if reported_total is None else {reported_total}
        for _ in range(3):
            try:
                data = self.get(COMMENTS_PATH, {"feed_id": fid, "stpl": "1,2,4,7,8,9,16",
                                                     "score": score, "count": min(20, comment_limit - len(roots))})
                rows, info = page_rows(data, "list")
                comments = comment_records(rows)
                result["pages_fetched"] += 1
                if integer(info.get("totalCount")) is not None:
                    result["reported_total"] = integer(info["totalCount"])
                    reported_totals.add(result["reported_total"])
                result["has_more"] = bool(info["hasMore"])
                added = 0
                row_by_id = {str(row.get("commentId")): row for row in rows}
                for comment in comments:
                    if comment["comment_id"] not in roots:
                        if len(roots) >= comment_limit:
                            result["truncated"] = True
                            break
                        roots[comment["comment_id"]], originals[comment["comment_id"]] = comment, row_by_id[comment["comment_id"]]
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
        # totalCount includes replies. A shortfall explained by a known root's
        # replyCount does not imply missing roots; an unexplained excess does.
        known_total = len(roots) + sum(root["reply_count"] for root in roots.values())
        unexplained_total = result["reported_total"] is not None and result["reported_total"] > known_total
        changed_total = len(reported_totals) > 1
        result["comments_complete"] = (not result["errors"] and not result["has_more"]
                                       and not result["truncated"] and not unexplained_total and not changed_total)
        result["truncated"] |= result["has_more"] or unexplained_total or changed_total
        threads = []
        for cid, root in roots.items():
            replies, errors = [], []
            try:
                replies, reply_score, more = reply_preview(originals[cid], cid, root["reply_count"])
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
                    data = self.get(REPLIES_PATH, {"feed_id": fid, "comment_id": root["comment_id"],
                                                            "stpl": "1,2,3,4,7,9,11,12,13,16",
                                                            "score": thread["score"], "count": min(5, reply_limit - reply_count)})
                    rows, info = page_rows(data, "list")
                    replies = comment_records(rows, root_id=root["comment_id"])
                    thread["pages"] += 1
                    result["reply_pages_fetched"] += 1
                    thread["more"] = bool(info["hasMore"])
                    added, seen = 0, {r["comment_id"] for r in root["replies"]}
                    for reply in replies:
                        if reply["comment_id"] not in seen:
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
