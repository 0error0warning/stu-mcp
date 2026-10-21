"""Pure cache reconciliation and bounded response views."""
from copy import deepcopy
from datetime import UTC, datetime


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
