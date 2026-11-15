"""Agent workflows use synthetic records, sessions and upstream responses only."""
import io
import json

import httpx
import pytest
from pypdf import PdfWriter

from stu_mcp import collectors
from stu_mcp.checkin import CheckinClient
from stu_mcp.hosting import HostRuntime
from stu_mcp.network import CampusHTTP
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server

URL = "https://www.stu.edu.cn/info/1001/12345.htm"
NOTICE = {"id": "public:notice:synthetic", "kind": "notice", "title": "合成通知", "url": URL}


@pytest.fixture
def host(app, tmp_path):
    instance = HostRuntime(app, checkin=CheckinClient(tmp_path / "checkin"))
    yield instance
    instance.close()


def structured(result):
    return result.model_dump(by_alias=True)["structuredContent"]


@pytest.mark.asyncio
async def test_profile_patch_keeps_unmentioned_fields_and_explicit_clear_is_targeted(host):
    host.app.runtime.save_profile({"college": "合成学院", "major": "合成专业", "interests": "旧兴趣"})
    server = build_server(host=host)
    result = structured(await server.call_tool("set_student_profile", {"interests": "新兴趣"}))
    assert result["profile"] == {"college": "合成学院", "major": "合成专业", "interests": "新兴趣"}
    cleared = structured(await server.call_tool("set_student_profile", {"clear_fields": ["major"]}))
    assert cleared["profile"] == {"college": "合成学院", "major": "", "interests": "新兴趣"}
    unchanged = structured(await server.call_tool("set_student_profile", {}))
    assert unchanged["profile"] == cleared["profile"]


def test_missing_notice_body_tells_the_agent_the_exact_read_call(app, monkeypatch):
    app.store.save_batch("public", [NOTICE])
    monkeypatch.setattr(collectors, "article", lambda *_: pytest.fail("cached reads must not start network I/O"))
    result = app.notice(NOTICE["id"])
    assert result["ok"] is True and result["status"] == "metadata_only"
    assert result["content_ready"] is False and result["detail_available"] is False
    assert result["next_call"] == {"tool": "get_notice", "arguments": {"item_id": NOTICE["id"], "refresh": True}}


def test_notice_body_pages_do_not_lose_the_full_cache_and_do_not_refetch(app, monkeypatch):
    body = "合成正文。" * 6000
    app.store.save_batch("public", [{**NOTICE, "body": body, "attachments": [{"name": "材料.pdf", "url": "/test.pdf"}]}])
    monkeypatch.setattr(collectors, "article", lambda *_: pytest.fail("body continuation must use the cache"))
    first = app.notice(NOTICE["id"])
    assert first["item"]["body"] == body[:8000] and first["next_offset"] == 8000
    assert first["total_chars"] == len(body) and first["has_more"] is True
    assert first["attachment_options"][0] == {"index": 0, "name": "材料.pdf"}
    next_call = first["next_call"]
    assert next_call["tool"] == "get_notice" and next_call["arguments"]["refresh"] is False
    second = app.notice(**next_call["arguments"])
    assert second["item"]["body"] == body[8000:16000]
    assert app.store.get(NOTICE["id"])["body"] == body


def test_notice_search_returns_bounded_previews_and_a_working_next_offset(app):
    body = "合成正文。" * 6000
    app.store.save_batch("public", [{**NOTICE, "body": body}, {**NOTICE, "id": "public:notice:second"}])
    result = app.query("notice", source="public", limit=1)
    assert result["has_more"] is True and result["next_offset"] == 1
    assert result["status"] == "ok"
    second = app.query("notice", source="public", limit=1, offset=result["next_offset"])
    assert second["next_offset"] is None
    preview = next(item for item in [*result["items"], *second["items"]] if "body" in item)
    assert len(preview["body"]) == 1200 and preview["body_truncated"] is True


def test_empty_cache_gives_source_refresh_guidance_without_authenticating(app, monkeypatch):
    monkeypatch.setattr(app.vault, "load", lambda *_: pytest.fail("query guidance must remain passive"))
    result = app.query("notice", source="public")
    assert result["empty_reason"] == "not_refreshed"
    assert result["next_calls"] == [{"tool": "refresh_source", "arguments": {"source": "public"}}]
    assert result["content_trust"] == "untrusted_source_data"


def test_empty_default_notice_search_does_not_require_unconfigured_private_sources(app):
    for source in ("public", "oa"):
        app.store.record_status(source, "ok", 0)
    result = app.query("notice", "合成关键词")
    assert result["empty_reason"] == "no_matching_cached_records" and result["next_action"] == "refine_query"
    assert "next_calls" not in result
    with pytest.raises(AppError) as error:
        app.query("notice", source="yuketang")
    assert error.value.code == "needs_login" and error.value.source == "yuketang"


@pytest.mark.parametrize("configured", ["mystu", "yuketang"])
def test_empty_course_search_only_uses_configured_sources(app, monkeypatch, configured):
    monkeypatch.setattr(app.vault, "status", lambda source: {
        "status": "session_saved" if source == configured else "needs_login"})
    pending = app.query("course", "合成关键词")
    assert pending["next_calls"] == [{"tool": "refresh_source", "arguments": {"source": configured}}]
    app.store.record_status(configured, "ok", 0)
    result = app.query("course", "合成关键词")
    assert result["empty_reason"] == "no_matching_cached_records" and result["next_action"] == "refine_query"
    assert "next_calls" not in result


def test_course_notice_preview_reads_existing_body_without_refreshing_every_course(app, monkeypatch):
    record = {"id": "yuketang:notice:synthetic", "kind": "notice", "title": "合成课程公告", "body": "合成公告正文" * 500}
    app.store.save_batch("yuketang", [record], private=True)
    monkeypatch.setattr(collectors, "yuketang", lambda *_: pytest.fail("cached notice reads must not refresh courses"))
    preview = app.query("notice", source="yuketang")["items"][0]
    assert preview["detail_call"] == {"tool": "get_notice", "arguments": {"item_id": record["id"], "refresh": False}}
    result = app.notice(record["id"], refresh=True)
    assert result["next_call"] == {"tool": "refresh_source", "arguments": {"source": "yuketang"}}


def test_unreadable_private_attachment_honors_logout_generation_before_sharing_metadata(app, monkeypatch):
    from types import SimpleNamespace

    app.vault.save("webvpn", {"cookies": []})
    version = app.vault.fingerprint("webvpn")
    record = {**NOTICE, "id": "oa:notice:synthetic", "url": "https://oa-stu-edu-cn.webvpn.stu.edu.cn/newstemplateprotal.jsp?docid=SYNTHETIC",
              "attachments": [{"name": "合成私人附件", "url": "/file.docx"}]}
    app.store.save_batch("oa", [record], private=True)

    def access(*_):
        app.vault.logout("webvpn")
        return SimpleNamespace(value=httpx.Response(200, content=b"PK synthetic"), session_version=version)

    monkeypatch.setattr("stu_mcp.app.protected_access", access)
    with pytest.raises(AppError) as error:
        app.attachment(record["id"])
    assert error.value.code == "session_changed"


def test_attachment_not_fetched_empty_list_and_bad_index_have_distinct_next_steps(app):
    app.store.save_batch("public", [NOTICE])
    missing = app.attachment(NOTICE["id"])
    assert missing["status"] == "attachment_not_cached"
    assert missing["next_call"] == {"tool": "get_notice", "arguments": {"item_id": NOTICE["id"], "refresh": True}}
    app.store.save_batch("public", [{**NOTICE, "body": "合成正文", "attachments": []}])
    empty = app.attachment(NOTICE["id"])
    assert empty["status"] == "no_attachments" and empty["next_action"] == "none"
    assert "next_call" not in empty
    app.store.save_batch("public", [{**NOTICE, "attachments": [{"name": "材料.pdf", "url": "/test.pdf"}]}])
    with pytest.raises(AppError) as error:
        app.attachment(NOTICE["id"], index=5)
    assert error.value.code == "invalid_attachment_index"


@pytest.mark.parametrize("content_type,data,status", [
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK synthetic", "unsupported_attachment"),
    ("text/html", b'<title>Login</title><form><input type="password"></form>', "attachment_unreadable"),
    ("text/html", b'<title>503 Service Unavailable</title>', "attachment_unreadable"),
])
def test_unreadable_attachment_returns_the_article_link_without_fabricating_text(app, monkeypatch, content_type, data, status):
    app.store.save_batch("public", [{**NOTICE, "attachments": [{"name": "合成附件", "url": "/file.docx"}]}])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=data, headers={"content-type": content_type}))
    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=transport))
    result = app.attachment(NOTICE["id"])
    assert result["ok"] is False and result["status"] == status
    assert result["source_url"] == URL and result["next_action"] == "show_source_link"
    assert result["content_ready"] is False and "text" not in result


def test_pdf_without_extractable_text_is_not_a_successful_empty_attachment(app, monkeypatch):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    app.store.save_batch("public", [{**NOTICE, "attachments": [{"name": "合成扫描件.pdf", "url": "/scan.pdf"}]}])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=buffer.getvalue(),
                                                           headers={"content-type": "application/pdf"}))
    monkeypatch.setattr("stu_mcp.app.CampusHTTP", lambda source: CampusHTTP(source, transport=transport))
    result = app.attachment(NOTICE["id"])
    assert result["status"] == "attachment_unreadable" and result["content_ready"] is False
    assert result["source_url"] == URL and result["next_action"] == "show_source_link"


@pytest.mark.asyncio
async def test_compact_scoped_capabilities_are_small_passive_and_keep_default_contract(host, monkeypatch):
    monkeypatch.setattr(host.network, "diagnose", lambda *_: pytest.fail("capabilities must not probe"))
    monkeypatch.setattr(CampusHTTP, "request", lambda *_: pytest.fail("capabilities must not authenticate or read online"))
    original = host.capabilities()
    compact = host.capabilities(source="public", compact=True)
    assert len(json.dumps(compact)) < len(json.dumps(original)) / 2
    assert [source["source"] for source in compact["sources"]] == ["public"]
    assert [item["service_id"] for item in compact["capability_catalog"]["services"]] == ["public_notices"]
    assert compact["capability_catalog"]["state_scope"] == original["capability_catalog"]["state_scope"]
    assert compact["hosting"]["default_authentication"] == "http"
    assert len(host.capabilities()["capability_catalog"]["services"]) == len(original["capability_catalog"]["services"])
    host.app.runtime.save_profile({"interests": "合成兴趣"})
    assert host.capabilities(source="local", compact=True)["profile"] == {"interests": "合成兴趣"}


def test_remote_setup_and_login_errors_give_host_commands_without_loopback_links(app, tmp_path):
    remote = HostRuntime(app, checkin=CheckinClient(tmp_path / "checkin"), transport="streamable-http")
    try:
        setup = remote.open_setup()
        assert setup["next_action"] == "login_on_host_cli" and setup["host_command"] == "stu-mcp setup --no-browser"
        result = remote.tool_error(AppError("needs_login", "合成未登录", "mystu"))
        assert result["next_action"] == "login_on_host_cli"
        assert result["host_command"] == "stu-mcp login school --services mystu"
        assert "http://127.0.0.1" not in json.dumps(result)
        assert remote.tool_error(AppError("needs_login", "合成 OA 访问通道", "oa"))["host_command"] == "stu-mcp login webvpn"
        assert remote.tool_error(AppError("update_restart_required", "合成待重启"))["next_action"] == "restart_host_service"
    finally:
        remote.close()


@pytest.mark.asyncio
async def test_machine_readable_source_backend_and_status_choices(host):
    tools = {tool.name: tool for tool in await build_server(host=host).list_tools()}
    assert len(tools) == 53
    assert tools["refresh_source"].input_schema["properties"]["source"]["enum"] == ["public", "oa", "jw", "mystu", "yuketang"]
    assert set(tools["search_notices"].input_schema["properties"]["source"]["enum"]) == {"all", "public", "oa", "yuketang"}
    assert set(tools["get_courses"].input_schema["properties"]["source"]["enum"]) == {"all", "mystu", "yuketang"}
    assert set(tools["set_task_status"].input_schema["properties"]["status"]["enum"]) == {"todo", "done", "ignored"}
    assert set(tools["get_wechat_article"].input_schema["properties"]["backend"]["enum"]) == {"http", "browser"}
