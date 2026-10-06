import json
import time

import httpx
import pytest

from stu_mcp import huyou
from stu_mcp.cli import main
from stu_mcp.huyou import (
    DEFAULT_CIRCLE,
    HuyouClient,
    comment_record,
    empty_discussion,
    feed_id,
    post_record,
    sign_params,
)
from stu_mcp.runtime import AppError


def post(fid="101", content="合成选课讨论", **extra):
    return {"feedId": fid, "circleId": DEFAULT_CIRCLE, "content": content, "userId": "ACCOUNT_ID_DO_NOT_STORE",
            "userName": "合成同学", "score": 1791158400000, "anonymous": True, "status": 1, **extra}


def comment(cid="501", content="合成回复内容", **extra):
    return {"commentId": cid, "content": content, "status": 1, "userId": "COMMENT_ACCOUNT_DO_NOT_STORE",
            "userName": "匿名合成同学", "anonymous": True, "timeId": 1791158400000, "replyCount": 0, **extra}


def payload(data, status=100000):
    return httpx.Response(200, json={"status": status, "data": data})


def search_page(rows, more=False, next_page=-1):
    return {"feedList": rows, "pageInfo": {"hasMore": more, "pageIndex": next_page}}


def discussion_page(rows, more=False, score=None, total=None):
    return {"list": rows, "pageInfo": {"hasMore": more, "score": score, "totalCount": total}}


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(huyou.time, "sleep", lambda _: None)


def install_client(monkeypatch, handler):
    requests = []

    def checked(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == "cs-ol.sns.sohu.com"
        assert not {"cookie", "authorization", "token", "s-pid", "s-ppid"}.intersection(request.headers)
        return handler(request)

    monkeypatch.setattr("stu_mcp.app.HuyouClient", lambda: HuyouClient(transport=httpx.MockTransport(checked)))
    return requests


def test_official_web_signature_known_vector_and_negative_cursor():
    signed = sign_params({"circle_id": DEFAULT_CIRCLE, "query": "选课 & 奖学金", "page_index": 1,
                          "size": 20, "search_type": 2, "optional": None}, 1791158400000)
    assert signed["sig"] == "41c07d5478daad472341762dd422eb03"
    assert signed["query"] == "选课 & 奖学金" and "optional" not in signed
    assert sign_params({"score": -1791047297796.0}, 1)["score"] == "-1791047297796"


def test_image_posts_keep_public_addresses_and_strip_raw_personal_fields():
    item = post_record(post(content="", picFeed={"pics": [{"url": "https://hy.cdn.sohucs.com/synthetic.png",
                                                         "userId": "EXTRA_ACCOUNT_ID"},
                                                        {"url": "javascript:alert(1)"}]}), detail=True)
    assert item["images"] == ["https://hy.cdn.sohucs.com/synthetic.png"]
    assert "EXTRA_ACCOUNT_ID" not in json.dumps(item) and "ACCOUNT_ID_DO_NOT_STORE" not in json.dumps(item)


@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "https://evil.example"}),
                                      httpx.Response(200, text="not JSON"),
                                      httpx.Response(200, json={"status": 100000, "data": []})])
def test_redirect_and_bad_response_are_not_followed_or_misreported(app, monkeypatch, response):
    requests = install_client(monkeypatch, lambda _: response)
    with pytest.raises(AppError):
        app.huyou_search("选课")
    assert len(requests) == 1


def test_oversized_response_stops_without_caching_or_leaking_error_content(app, monkeypatch):
    requests = install_client(monkeypatch, lambda _: httpx.Response(200, content=b"SYNTHETIC_SECRET" * 150000))
    with pytest.raises(AppError) as error:
        app.huyou_search("选课")
    assert error.value.code == "response_too_large" and len(requests) == 1
    assert "SYNTHETIC_SECRET" not in str(error.value)


@pytest.mark.parametrize("keywords", [[], "选课", {"q": "选课"}, [None], [""], [1], ["a\nb"],
                                       ["x" * 513], list("abcdefg")])
def test_bad_keyword_plan_fails_before_http(app, monkeypatch, keywords):
    monkeypatch.setattr("stu_mcp.app.HuyouClient", lambda: pytest.fail("invalid plan must not construct HTTP"))
    with pytest.raises(AppError):
        app.huyou_search("原问题", keywords)


def test_explicit_terms_are_sent_unchanged_and_selected_fairly(app, monkeypatch):
    def handler(request):
        q = request.url.params["query"]
        rows = [post("101"), post("102"), post("103")] if q == "选课" else [post("101"), post("104", "合成给分讨论")]
        return payload(search_page(rows))
    requests = install_client(monkeypatch, handler)
    result = app.huyou_search("选课有哪些建议，哪些课程给分怎么样", [" 选课 ", "给分", "选课"], limit=2)
    assert [r.url.params["query"] for r in requests] == ["选课", "给分"]
    assert [i["feed_id"] for i in result["items"]] == ["101", "104"]
    assert result["plan"]["combine"] == "union" and result["limited"]
    assert len(result["items"][0]["search_hits"]) == 2
    assert result["official"] is False
    assert "ACCOUNT_ID_DO_NOT_STORE" not in json.dumps(result)


def test_literal_question_is_not_automatically_split(app, monkeypatch):
    requests = install_client(monkeypatch, lambda _: payload(search_page([])))
    result = app.huyou_search("请问思想政治理论这门课怎么样")
    assert result["plan"]["strategy"] == "literal"
    assert requests[0].url.params["query"] == "请问思想政治理论这门课怎么样"
    assert result["items"] == [] and result["errors"] == []


def test_numbered_search_pagination_uses_server_next_page_and_ignores_member_cards(app, monkeypatch):
    def handler(request):
        if request.url.params["page_index"] == "1":
            return payload(search_page([post()], True, 4))
        assert request.url.params["page_index"] == "4"
        return payload(search_page([post(), post("102"), {"userId": "9", "feedAttr": 8}]))
    requests = install_client(monkeypatch, handler)
    result = app.huyou_search("选课")
    assert len(requests) == 2 and len(result["items"]) == 2 and result["status"] == "ok"


@pytest.mark.parametrize("data", [{}, {"feedList": [], "pageInfo": {}}, {"feedList": None, "pageInfo": {}},
                                  {"feedList": [1], "pageInfo": {"hasMore": False}}])
def test_bad_search_schema_is_not_successfully_empty(app, monkeypatch, data):
    install_client(monkeypatch, lambda _: payload(data))
    with pytest.raises(AppError):
        app.huyou_search("选课")
    assert app.store.freshness()[0]["status"] == "schema_changed"


def test_partial_page_keeps_results_and_failed_search_does_not_clear_cache(app, monkeypatch):
    def handler(request):
        if request.url.params["page_index"] == "1":
            return payload(search_page([post()], True, 2))
        return httpx.Response(503)
    install_client(monkeypatch, handler)
    result = app.huyou_search("选课")
    assert result["status"] == "partial" and result["items"] and result["errors"]
    install_client(monkeypatch, lambda _: httpx.Response(403))
    with pytest.raises(AppError, match="要求登录"):
        app.huyou_search("选课")
    assert app.huyou_search("选课", local=True)["total_count"] == 1


def test_auth_and_long_rate_limit_stop_all_remaining_keywords(app, monkeypatch):
    requests = install_client(monkeypatch, lambda _: httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(AppError) as error:
        app.huyou_search("合成问题", ["选课", "奖学金"])
    assert error.value.code == "rate_limited" and len(requests) == 1


def test_one_retry_uses_fresh_signature_and_drops_tracking_cookie(app, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1", "Set-Cookie": "tracking=do-not-send"})
        assert "cookie" not in request.headers
        return payload(search_page([]))
    install_client(monkeypatch, handler)
    result = app.huyou_search("选课")
    assert result["retry_count"] == 1
    assert calls[0].url.params["flyer"] != calls[1].url.params["flyer"]


def test_budget_and_deadline_are_terminal():
    with HuyouClient(transport=httpx.MockTransport(lambda _: pytest.fail("budget must prevent HTTP"))) as client:
        client.requests = 40
        with pytest.raises(AppError) as error:
            client.get("/v7/feeds/show", {"feed_id": "101"})
        assert error.value.code == "request_limit"
    with HuyouClient(transport=httpx.MockTransport(lambda _: pytest.fail("deadline must prevent HTTP"))) as client:
        client.deadline = time.monotonic() - 1
        with pytest.raises(AppError) as error:
            client.get("/v7/feeds/show", {"feed_id": "101"})
        assert error.value.code == "request_deadline"


def test_request_pacing_does_not_cross_deadline(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(huyou.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(huyou.time, "sleep", lambda delay: now.__setitem__(0, now[0] + delay))
    with HuyouClient(transport=httpx.MockTransport(lambda _: pytest.fail("expired pacing must prevent HTTP"))) as client:
        client.deadline, client.last_request = 100.1, 100.0
        with pytest.raises(AppError) as error:
            client.get("/v7/feeds/show", {"feed_id": "101"})
        assert error.value.code == "request_deadline" and client.requests == 0


@pytest.mark.parametrize("target", ["https://evil.example/?feedDetail=101", "http://hy.sns.sohu.com/?feedDetail=101",
                                    "https://hy.sns.sohu.com:444/?feedDetail=101", "0", "101; echo unsafe",
                                    "https://hy.sns.sohu.com/?feedDetail=101&token=secret"])
def test_untrusted_targets_are_rejected_before_http(app, monkeypatch, target):
    monkeypatch.setattr("stu_mcp.app.HuyouClient", lambda: pytest.fail("bad URL must not construct HTTP"))
    with pytest.raises(AppError):
        app.huyou_post(target)


def test_public_detail_deleted_or_private_never_fetches_discussion(app, monkeypatch):
    for extra in ({"status": 0}, {"ownerHidden": True, "bilateral": 4}):
        requests = install_client(monkeypatch, lambda _, extra=extra: payload({"sourceFeed": post(**extra)}))
        with pytest.raises(AppError) as error:
            app.huyou_post("101")
        assert error.value.code == "post_unavailable" and len(requests) == 1


def test_discussion_cursors_replies_and_public_identity_fields(app, monkeypatch):
    def handler(request):
        path = request.url.path
        if path == "/v7/feeds/show":
            return payload({"sourceFeed": post(commentCount=4)})
        if path == "/v8/comment/list":
            if request.url.params["score"] == "0":
                return payload(discussion_page([comment(replyCount=2, replies={
                    "list": [comment("502", replyCommentId="501")], "score": -2.0, "hasMore": True})], True, -1.0, 4))
            assert request.url.params["score"] == "-1"
            return payload(discussion_page([comment("504")], total=4))
        assert path == "/v8/comment/replylist" and request.url.params["score"] == "-2"
        return payload(discussion_page([comment("503", "合成关键回答", replyCommentId="502", isAuthor=True)], total=2))
    requests = install_client(monkeypatch, handler)
    result = app.huyou_post("https://hy.sns.sohu.com/?feedDetail=101")
    discussion = result["item"]["discussion"]
    assert discussion["complete"] and discussion["reply_count"] == 2 and len(requests) == 4
    reply = discussion["comments"][0]["replies"][1]
    assert reply["root_comment_id"] == "501" and reply["reply_to_comment_id"] == "502" and reply["is_author"]
    assert "COMMENT_ACCOUNT_DO_NOT_STORE" not in json.dumps(result)


def test_embedded_replies_shared_budget_and_zero_count_avoid_requests():
    roots = [comment(replyCount=2, replies={"list": [comment("502"), comment("503")]}),
             comment("601", replyCount=1, replies={"list": [comment("602")]})]
    with HuyouClient(transport=httpx.MockTransport(lambda _: payload(discussion_page(roots, total=5)))) as client:
        result = client.discussion("101", reply_limit=2)
        assert [len(r["replies"]) for r in result["comments"]] == [1, 1]
        assert result["truncated"] and not result["complete"] and client.requests == 1
        assert client.discussion("101", reported_total=0)["complete"] and client.requests == 1


def test_repeated_cursor_is_partial_with_previous_pages_preserved():
    def handler(request):
        cid = "501" if request.url.params["score"] == "0" else "502"
        return payload(discussion_page([comment(cid)], True, -1))
    with HuyouClient(transport=httpx.MockTransport(handler)) as client:
        result = client.discussion("101")
        assert result["comment_count"] == 2 and not result["complete"] and result["errors"]
        assert client.requests == 2


def full_item():
    item = post_record(post(content="合成完整正文"), detail=True)
    root = comment_record(comment(content="只有评论里的闭卷信息", replyCount=1))
    root.update(replies_complete=True, replies=[comment_record(comment("502", "合成原回复"), "501")])
    item["discussion"] = {**empty_discussion(), "comments": [root], "comment_count": 1, "reply_count": 1}
    return item


def test_light_search_preserves_full_body_and_threads_without_returning_them_in_preview(app, monkeypatch):
    full = full_item()
    app.store.save_community([full])
    requests = install_client(monkeypatch, lambda _: payload(search_page([post(content="合成搜索片段")])))
    result = app.huyou_search("仅在历史关键词里")
    assert len(requests) == 1 and "discussion" not in result["items"][0]
    assert result["items"][0]["body_retained_from_cache"]
    cached = app.huyou_post("101", refresh=False)["item"]
    assert cached["body"] == "合成完整正文" and cached["discussion"]["comments"]
    assert app.huyou_search("闭卷", local=True)["total_count"] == 1
    assert app.huyou_search("仅在历史关键词里", local=True)["total_count"] == 0
    assert app.query("post", "仅在历史关键词里", source="huyou")["total_count"] == 0


def test_search_previews_are_bounded_without_clipping_saved_discussions(app, monkeypatch):
    full = full_item()
    full["body"] = "合成完整正文" * 500
    root = full["discussion"]["comments"][0]
    root["content"] = "合成评论" * 300
    full["discussion"]["comments"] = [{**root, "comment_id": str(501 + i)} for i in range(8)]
    app.store.save_community([full])
    preview = app.huyou_search("合成", local=True, with_discussion=True)["items"][0]
    assert len(preview["body"]) == 1200 and preview["body_preview_truncated"]
    assert len(preview["discussion"]["comments"]) == 5 and preview["discussion"]["response_truncated"]
    assert len(preview["discussion"]["comments"][0]["content"]) == 500
    assert len(app.huyou_post("101", refresh=False)["item"]["discussion"]["comments"]) == 8


@pytest.mark.parametrize("previous_truncated", [True, False])
def test_fresh_detail_clears_old_error_and_updates_incomplete_body(app, monkeypatch, previous_truncated):
    previous = post_record(post(content="合成先前正文", contentIsSub=previous_truncated), detail=True)
    previous["detail_error"] = AppError("network_error", "合成暂时失败", "huyou").result()
    app.store.save_community([previous])
    install_client(monkeypatch, lambda _: payload({"sourceFeed": post(content="合成新截断正文", contentIsSub=True)}))
    result = app.huyou_post("101", with_discussion=False)
    assert result["status"] == "partial" and result["limited"] and "detail_error" not in result["item"]
    assert result["item"]["body"] == ("合成新截断正文" if previous_truncated else "合成先前正文")
    install_client(monkeypatch, lambda _: payload({"sourceFeed": post(content="合成最新完整正文")}))
    result = app.huyou_post("101", with_discussion=False)
    assert result["status"] == "ok" and result["item"]["body"] == "合成最新完整正文"
    assert "body_retained_from_cache" not in result["item"]


def test_partial_reply_refresh_retains_prior_reply_and_complete_empty_snapshot_clears(app, monkeypatch):
    full = full_item()
    app.store.save_community([full])
    state = {"empty": False}
    def handler(request):
        if request.url.path == "/v7/feeds/show":
            return payload({"sourceFeed": post(commentCount=0 if state["empty"] else 2)})
        if request.url.path == "/v8/comment/list":
            return payload(discussion_page([comment(replyCount=1)], total=2))
        return httpx.Response(503)
    install_client(monkeypatch, handler)
    result = app.huyou_post("101")
    discussion = result["item"]["discussion"]
    assert result["status"] == "partial" and discussion["retained_from_cache"]
    assert discussion["comments"][0]["replies"][0]["content"] == "合成原回复"
    state["empty"] = True
    result = app.huyou_post("101")
    assert result["item"]["discussion"]["comments"] == [] and result["item"]["discussion"]["complete"]


def test_public_reads_never_access_keyring_and_do_not_mix_into_oa(app, monkeypatch):
    class Unavailable:
        def get_password(self, *_):
            pytest.fail("anonymous Huyou must not read keyring")
    app.vault._store = Unavailable()
    install_client(monkeypatch, lambda _: payload(search_page([post()])))
    assert app.huyou_search("选课")["items"]
    assert app.query("notice")["items"] == []
    assert app.huyou_post("101", refresh=False)["item"]["official"] is False
    source = next(s for s in app.status()["sources"] if s["source"] == "huyou")
    assert source["auth"]["status"] == "not_required" and not source["login_available"]
    with pytest.raises(AppError) as error:
        app.refresh("huyou")
    assert error.value.code == "query_required"


def test_circles_cli_and_search_context_missing_detail_circle(app, monkeypatch, capsys):
    def handler(request):
        if request.url.path == "/circle/search/v20":
            return payload({"circleList": [{"circleId": DEFAULT_CIRCLE, "circleName": "合成汕大树洞"}], "hasMore": False})
        if request.url.path == "/circle/search/feed/v22":
            return payload(search_page([post()]))
        detailed = post(commentCount=0)
        detailed.pop("circleId")
        return payload({"sourceFeed": detailed})
    install_client(monkeypatch, handler)
    monkeypatch.setattr("stu_mcp.cli.App", lambda: app)
    assert main(["huyou", "circles"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["circle_id"] == DEFAULT_CIRCLE
    assert main(["huyou", "search", "合成问题", "--keyword", "选课", "--with-discussion"]) == 0
    item = json.loads(capsys.readouterr().out)["items"][0]
    assert item["circle_id"] == DEFAULT_CIRCLE and item["discussion"]["complete"]
    assert main(["huyou", "detail", "101", "--local"]) == 0
    assert json.loads(capsys.readouterr().out)["item"]["detail_fetched"]
    assert feed_id(item["url"]) == "101"
