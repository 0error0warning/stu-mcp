"""Anonymous bounded Huyou integration with synthetic HTTP only."""
from copy import deepcopy

import httpx
import pytest

from stu_mcp import huyou
from stu_mcp.features.huyou.cache import merge_discussion
from stu_mcp.runtime import AppError


def post(**fields):
    return {"feedId": "101", "content": "合成正文", "status": 1, **fields}


def comment(cid="501", **fields):
    return {"commentId": cid, "content": "合成评论", "replyCount": 0, "status": 1, **fields}


def page(rows, **info):
    return {"list": rows, "pageInfo": {"hasMore": False, **info}}


def response(data):
    return httpx.Response(200, json={"status": 100000, "data": data})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(huyou.time, "sleep", lambda _: None)


def old_discussion():
    root = huyou.comment_record(comment(replyCount=1))
    root.update(replies=[huyou.comment_record(comment("502", content="合成旧回复"), "501")], replies_complete=True)
    return {**huyou.empty_discussion(), "comments": [root], "comment_count": 1, "reply_count": 1}


@pytest.mark.parametrize("fields", [
    {"replies": None}, {"replies": {}}, {"replies": {"renamed": []}}, {"replies": []}, {"replies": "renamed"}, {"replies": {"list": None}},
    {"replyCount": None}, {"replies": {"list": [comment("502", content={})]}},
])
def test_invalid_reply_preview_retains_known_root_and_cached_replies(fields):
    row = comment(replyCount=1, **fields) if "replyCount" not in fields else comment(**fields)
    with huyou.HuyouClient(transport=httpx.MockTransport(lambda _: response(page([row])))) as client:
        current = client.discussion("101")
    assert current["comment_count"] == 1 and current["errors"] and not current["complete"]
    result = merge_discussion(old_discussion(), current)
    assert result["comments"][0]["replies"][0]["content"] == "合成旧回复"
    assert result["retained_from_cache"]


@pytest.mark.parametrize("bad", [comment(content={}), comment(replyCount=True), comment(commentId=True)])
def test_invalid_comment_page_does_not_replace_previous_discussion(bad):
    old = old_discussion()
    before = deepcopy(old)
    with huyou.HuyouClient(transport=httpx.MockTransport(lambda _: response(page([bad])))) as client:
        current = client.discussion("101")
    assert current["errors"] and not current["comments_complete"] and current["comments"] == []
    merged = merge_discussion(old, current)
    assert merged["comments"][0]["replies"][0]["content"] == "合成旧回复"
    assert old == before


def test_later_bad_comment_page_retains_prior_page_and_other_reply_thread():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/v8/comment/list":
            if request.url.params["score"] == "0":
                return response(page([comment(replyCount=1), comment("601", replyCount=1)], hasMore=True, score=-1))
            return response(page([comment("701", content={})]))
        if request.url.params["comment_id"] == "501":
            return response(page([comment("502", content={})]))
        return response(page([comment("602", content="合成另一楼中楼")]))
    with huyou.HuyouClient(transport=httpx.MockTransport(handler)) as client:
        result = client.discussion("101")
    assert len(seen) == 4 and result["comment_count"] == 2 and len(result["errors"]) == 2
    assert not result["complete"] and not result["comments_complete"]
    assert result["comments"][1]["replies"][0]["comment_id"] == "602"


def test_bad_search_keyword_does_not_block_independent_keyword():
    def handler(request):
        row = post(content={}) if request.url.params["query"] == "坏结构" else post()
        return response({"feedList": [row], "pageInfo": {"hasMore": False}})
    with huyou.HuyouClient(transport=httpx.MockTransport(handler)) as client:
        result = client.search(huyou.search_plan("合成", ["坏结构", "有效结构"]))
    assert result["status"] == "partial" and len(result["items"]) == 1
    assert [run["status"] for run in result["keyword_runs"]] == ["failed", "ok"]
    assert result["request_count"] == 2


def test_bad_detail_keeps_existing_full_body_without_following_discussion(app, monkeypatch):
    old = huyou.post_record(post(content="合成完整旧正文"), detail=True)
    old["discussion"] = old_discussion()
    app.store.save_community([old])
    requests = []
    def handler(request):
        requests.append(request)
        return response({"sourceFeed": post(content={"text": "new field"})})
    monkeypatch.setattr("stu_mcp.app.HuyouClient", lambda: huyou.HuyouClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(AppError) as error:
        app.huyou_post("101")
    assert error.value.code == "schema_changed" and len(requests) == 1
    cached = app.huyou_post("101", refresh=False)["item"]
    assert cached["body"] == "合成完整旧正文"
    assert cached["discussion"]["comments"][0]["replies"]


def test_duplicate_search_page_is_atomic_and_keeps_previous_cache(app, monkeypatch):
    old = huyou.post_record(post(content="合成旧正文"))
    app.store.save_community([old])
    def handler(_):
        return response({"feedList": [post(content="新正文"), post(content="冲突正文")], "pageInfo": {"hasMore": False}})
    monkeypatch.setattr("stu_mcp.app.HuyouClient", lambda: huyou.HuyouClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(AppError, match="重复"):
        app.huyou_search("合成")
    assert app.huyou_post("101", refresh=False)["item"]["body"] == "合成旧正文"


def test_empty_confirmed_discussion_clears_but_deleted_rows_have_no_identity_requirement():
    with huyou.HuyouClient(transport=httpx.MockTransport(lambda _: response(page([{"status": "0"}])))) as client:
        current = client.discussion("101")
    assert current["complete"] and current["comments_complete"]
    assert merge_discussion(old_discussion(), current)["comments"] == []


def test_feature_dependencies_do_not_point_back_to_compatibility_module():
    import ast
    from pathlib import Path

    from stu_mcp.features import huyou as feature
    for path in Path(feature.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(node.module == "huyou" and node.level >= 2 for node in imports)
    parser_imports = ast.parse((Path(feature.__file__).parent / "parser.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.ImportFrom) and node.module in {"adapter", "service", "cache"}
                   for node in ast.walk(parser_imports))


@pytest.mark.parametrize("rows,total", [([], 1), ([comment()], 2)])
def test_unexplained_reported_total_cannot_clear_unconfirmed_roots(rows, total):
    old = old_discussion()
    extra = huyou.comment_record(comment("601", content="合成未确认旧评论"))
    extra.update(replies_complete=True, replies=[])
    old["comments"].append(extra)
    old["comment_count"] = 2
    with huyou.HuyouClient(transport=httpx.MockTransport(lambda _: response(page(rows, totalCount=total)))) as client:
        current = client.discussion("101")
    assert not current["comments_complete"] and not current["complete"] and current["truncated"]
    merged = merge_discussion(old, current)
    assert {row["comment_id"] for row in merged["comments"]} == {"501", "601"}
    assert merged["retained_from_cache"]


def test_missing_reply_reads_do_not_make_verified_root_list_incomplete():
    def handler(request):
        if request.url.path == "/v8/comment/list":
            return response(page([comment(replyCount=1)], totalCount=2))
        return httpx.Response(503)
    with huyou.HuyouClient(transport=httpx.MockTransport(handler)) as client:
        current = client.discussion("101")
    assert current["comments_complete"] and not current["complete"]
    assert current["comments"][0]["reply_errors"]
    merged = merge_discussion(old_discussion(), current)
    assert merged["comments"][0]["replies"][0]["comment_id"] == "502"


def test_changed_page_totals_do_not_authorize_removing_unconfirmed_old_root():
    def handler(request):
        if request.url.params["score"] == "0":
            return response(page([comment()], hasMore=True, score=-1, totalCount=3))
        return response(page([comment("502")], totalCount=2))
    with huyou.HuyouClient(transport=httpx.MockTransport(handler)) as client:
        current = client.discussion("101")
    assert current["reported_total"] == 2  # Keep the existing displayed last-page value.
    assert not current["comments_complete"] and not current["complete"] and current["truncated"]
    old = old_discussion()
    old["comments"][0]["comment_id"] = "599"
    merged = merge_discussion(old, current)
    assert {row["comment_id"] for row in merged["comments"]} == {"501", "502", "599"}
    assert merged["retained_from_cache"]
