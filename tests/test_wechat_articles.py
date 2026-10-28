"""Synthetic public pages only: no WeChat accounts, cookies or copied articles."""
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from stu_mcp.features.wechat import adapter, service
from stu_mcp.features.wechat.parser import parse_article
from stu_mcp.runtime import AppError

URL = "https://mp.weixin.qq.com/s/synthetic_article"
BODY = "这是一段用于校验公开文章读取的合成正文，包含足够的文字，但不含任何真实业务数据。"
PAGE = (f'<h1 id="activity-name">合成文章</h1><a id="js_name">合成公众号</a>'
        f'<em id="publish_time">2026-10-28</em><div id="js_content"><p>{BODY}</p>'
        '<p>第二段 <strong>保留行文</strong> 与链接文字。</p><img src="https://invalid.test/a.png">'
        '<script>doNotIncludeThis()</script></div>')


def test_dom_body_identity_and_nontext_boundaries():
    result = parse_article(PAGE)
    assert result["title"] == "合成文章" and result["account"] == "合成公众号"
    assert result["published_at"] == "2026-10-28" and result["author"] is None
    assert result["text"] == BODY + "\n第二段 保留行文 与链接文字。"
    assert result["extraction"] == "dom" and result["image_count"] == 1
    assert not result["identity_verified"] and "doNotIncludeThis" not in result["text"]


@pytest.mark.parametrize("quoted", [
    json.dumps(f"<p>{BODY}</p><p>表情😀、引号\"和反斜杠\\都应保留。</p>", ensure_ascii=True),
    "'<p>" + BODY + r"</p><p>\x48\u0069\'\n第二行</p>'",
])
def test_safe_js_string_fallback_and_unicode(quoted):
    page = ('<script>var msg_title = "合成标题"; var nickname = htmlDecode("合成账号");'
            f'var ct = "1793145600"; var content_noencode = {quoted};</script>')
    result = parse_article(page)
    assert result["extraction"] == "content_noencode" and BODY in result["text"]
    assert "2026-10" in result["published_at"] and result["account"] == "合成账号"
    assert ("😀" in result["text"]) if quoted.startswith('"') else ("Hi'" in result["text"])


def test_js_expression_is_not_executed_or_accepted_as_complete_body():
    page = ('<h1 id="activity-name">标题</h1><a id="js_name">账号</a><script>'
            f'var content_noencode = "<p>{BODY}</p>" + getPrivateStuff();</script>')
    with pytest.raises(AppError) as exc:
        parse_article(page)
    assert exc.value.code == "insufficient_content"


@pytest.mark.parametrize("html,code", [
    ('<h1>环境异常</h1><p>请验证后继续</p>', "captcha_required"),
    ('<div class="weui-msg__text-area">访问过于频繁</div>', "rate_limited"),
    ('<div>该内容已被发布者删除</div>', "article_unavailable"),
    ('<div>参数错误</div>', "article_unavailable"),
    ('<title>合成搜索摘要</title><p>没有文章正文</p>', "schema_changed"),
    ('<div id="js_content">' + BODY + '</div>', "schema_changed"),
    ('<h1 id="activity-name">合成文章</h1><a id="js_name">合成公众号</a>'
     '<div id="js_content"><img alt="图片不当作正文"></div>', "insufficient_content"),
])
def test_http_200_is_not_proof_of_article(html, code):
    with pytest.raises(AppError) as exc:
        parse_article(html)
    assert exc.value.code == code


def test_article_about_verification_is_not_a_challenge():
    assert parse_article(PAGE.replace(BODY, BODY + "环境异常、安全验证、参数错误的分析。"))["title"] == "合成文章"


def test_source_epoch_takes_precedence_over_browser_localized_display():
    result = parse_article(PAGE + '<script>var ct = "1793145600";</script>')
    assert result["published_at"] == "2026-10-28T08:00:00+08:00"


@pytest.mark.parametrize("url", [
    "http://mp.weixin.qq.com/s/synthetic_article", "https://evil.test/s/synthetic_article",
    "https://mp.weixin.qq.com.evil.test/s/synthetic_article", "https://127.0.0.1/s/synthetic_article",
    "https://mp.weixin.qq.com@127.0.0.1/s/synthetic_article", "https://mp.weixin.qq.com:444/s/synthetic_article",
    URL + "?pass_ticket=synthetic_private", URL + "?uin=synthetic_private", URL + "?%74oken=synthetic_private",
    "https://mp.weixin.qq.com/mp/profile_ext?action=home", "https://mp.weixin.qq.com/s?__biz=abc",
    URL + "\n", "https://mp.weixin.qq.com\\@127.0.0.1/s/synthetic_article",
])
def test_rejects_nonarticle_urls_and_credentials(url):
    result = service.read_article(url)
    assert result["status"] == "invalid_article_url" and not result["content_ready"]
    assert "synthetic_private" not in json.dumps(result) and "source_url" not in result


def test_public_long_link_preserves_identity_and_drops_tracking():
    url = "https://mp.weixin.qq.com/s?__biz=synthetic&mid=123&idx=1&sn=public_signature&scene=1#wechat_redirect"
    assert adapter.article_url(url) == url.split("&scene")[0]
    assert adapter.article_url(URL + "?scene=1&from=share#rd") == URL


def factory(handler):
    return lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs)


def test_http_follows_only_validated_redirects_and_never_sends_cookies(monkeypatch):
    seen = []
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic.invalid:9999")

    def handler(request):
        seen.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        assert "Chrome/" in request.headers["user-agent"]
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "/s/other_synthetic?scene=1",
                                               "set-cookie": "synthetic_private=never_forward; Path=/"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)

    html, final = adapter.fetch_http(URL, client_factory=factory(handler))
    assert final == "https://mp.weixin.qq.com/s/other_synthetic" and html == PAGE and len(seen) == 2


@pytest.mark.parametrize("location,code", [
    ("https://127.0.0.1/s/synthetic_article", "unsafe_redirect"),
    ("http://mp.weixin.qq.com/s/synthetic_article", "unsafe_redirect"),
    ("https://evil.test/s/synthetic_article", "unsafe_redirect"),
    ("/mp/wappoc_appmsgcaptcha?target_url=synthetic", "captcha_required"),
    ("/s/synthetic_article?token=synthetic_private", "unsafe_redirect"),
])
def test_unsafe_redirect_is_stopped_before_a_second_request(location, code):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": location})

    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(handler))
    assert exc.value.code == code and len(seen) == 1


@pytest.mark.parametrize("status,code", [(429, "rate_limited"), (403, "access_denied"),
                                       (404, "article_unavailable"), (503, "source_unavailable")])
def test_http_failure_statuses(status, code):
    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(lambda _: httpx.Response(status)))
    assert exc.value.code == code and exc.value.http_status == status


def test_bounded_response_redirect_loop_and_network_error(monkeypatch):
    monkeypatch.setattr(adapter, "MAX_HTML_BYTES", 100)
    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(lambda _: httpx.Response(
            200, headers={"content-type": "text/html"}, text=PAGE)))
    assert exc.value.code == "response_too_large"
    calls = []

    def loop(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": URL})

    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(loop))
    assert exc.value.code == "unsafe_redirect" and len(calls) == adapter.MAX_REDIRECTS + 1

    def fail(request):
        raise httpx.ConnectError("synthetic_private_do_not_echo", request=request)

    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(fail))
    assert exc.value.code == "network_error" and "synthetic_private" not in str(exc.value)


def test_nonhtml_and_timeout_are_explicit_failures():
    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(lambda _: httpx.Response(
            200, headers={"content-type": "application/json"}, json={"title": "Not an article"})))
    assert exc.value.code == "schema_changed"

    def timeout(request):
        raise httpx.ReadTimeout("synthetic_private_never_echo", request=request)

    with pytest.raises(AppError) as exc:
        adapter.fetch_http(URL, client_factory=factory(timeout))
    assert exc.value.code == "request_timeout" and "synthetic_private" not in str(exc.value)


def test_pagination_and_failure_never_auto_launch_browser(monkeypatch):
    from stu_mcp.features.wechat import browser

    monkeypatch.setattr(service, "fetch_http", lambda url: (PAGE, url))
    monkeypatch.setattr(browser, "fetch_browser", lambda *_: pytest.fail("No automatic browser fallback"))
    first = service.read_article(URL, max_chars=12)
    second = service.read_article(URL, offset=first["next_offset"], max_chars=20000)
    assert first["ok"] and first["content_ready"] and first["has_more"] and not first["cached"]
    assert first["text"] + second["text"] == parse_article(PAGE)["text"]
    assert not second["has_more"] and second["next_offset"] is None
    end = service.read_article(URL, offset=first["total_chars"] + 100)
    assert end["ok"] and end["text"] == "" and not end["has_more"]
    monkeypatch.setattr(service, "fetch_http", lambda url: ("<p>环境异常</p>", url))
    blocked = service.read_article(URL)
    assert not blocked["ok"] and not blocked["content_ready"] and "text" not in blocked
    assert blocked["status"] == "captcha_required" and blocked["next_action"] == "open_source_page"


@pytest.mark.parametrize("kwargs,code", [
    ({"backend": "auto"}, "invalid_backend"), ({"offset": -1}, "invalid_offset"),
    ({"offset": True}, "invalid_offset"), ({"max_chars": 20001}, "invalid_limit"),
    ({"max_chars": False}, "invalid_limit"),
])
def test_invalid_scope_does_not_fetch(monkeypatch, kwargs, code):
    monkeypatch.setattr(service, "fetch_http", lambda *_: pytest.fail("Invalid input must not fetch"))
    assert service.read_article(URL, **kwargs)["status"] == code


@pytest.mark.asyncio
async def test_tool_contract_and_catalog_are_additive_and_anonymous(app, monkeypatch):
    from stu_mcp.capability_catalog import build_capability_catalog
    from stu_mcp.server import build_server
    from stu_mcp.sources import SOURCES

    monkeypatch.setattr(service, "fetch_http", lambda url: (PAGE, url))
    server = build_server(app)
    tools = await server.list_tools()
    tool = next(tool for tool in tools if tool.name == "get_wechat_article")
    assert tool.input_schema["required"] == ["url"]
    assert tool.input_schema["properties"]["backend"]["default"] == "http"
    assert tool.annotations.read_only_hint and tool.annotations.open_world_hint
    response = await server.call_tool("get_wechat_article", {"url": URL, "max_chars": 20})
    result = response.model_dump(by_alias=True)["structuredContent"]
    assert result["content_ready"] and len(result["text"]) == 20 and result["execution_scope"] == "mcp_host"
    catalog = build_capability_catalog()
    entry = next(row for row in catalog["services"] if row["service_id"] == "wechat_articles")
    assert entry["configuration_id"] == "anonymous" and entry["login_id"] is None
    assert entry["source_id"] is None and "wechat" not in SOURCES


def test_all_51_existing_tool_definitions_stay_identical():
    contract = json.loads((Path(__file__).parents[1] / "scripts/mcp-tool-contract.json").read_text(encoding="utf-8"))
    previous = sorted((tool for tool in contract["tools"] if tool["name"] != "get_wechat_article"),
                      key=lambda tool: tool["name"])
    encoded = json.dumps(previous, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert len(previous) == 51
    assert hashlib.sha256(encoded).hexdigest() == "4a75a79ab8e073d187d5b2ae63b39da228e749a131d1c7d7798d7e92455df426"
