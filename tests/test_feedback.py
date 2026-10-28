import importlib.util
import json
import threading
import uuid
from pathlib import Path

import httpx
import pytest

from stu_mcp import feedback
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server

spec = importlib.util.spec_from_file_location(
    "feedback_receiver", Path(__file__).parents[1] / "deploy/feedback/receiver.py")
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


@pytest.fixture
def inbox_server(tmp_path):
    inbox = receiver.Inbox(str(tmp_path / "feedback.sqlite3"))
    server = receiver.Receiver(("127.0.0.1", 0), inbox)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, inbox, f"http://127.0.0.1:{server.server_port}/api/feedback"
    server.shutdown()
    server.server_close()
    thread.join()


def approved_feedback(message, tool_name="", category="bug"):
    preview = feedback.report_feedback(message, tool_name, category)
    return feedback.report_feedback(message, tool_name, category,
                                    confirmation_id=preview["confirmation_id"], user_confirmed=True)


def payload():
    return {"report_id": str(uuid.uuid4()), "message": "Synthetic: date parser disagrees with source.",
            "category": "data_error", "tool_name": "get_notice", "client_version": "0.7.3"}


def test_receiver_persistence_idempotency_and_no_public_read(inbox_server):
    _, inbox, url = inbox_server
    data = payload()
    with httpx.Client(trust_env=False) as client:
        for _ in range(2):
            result = client.post(url, json=data)
            assert result.status_code == 201
            assert result.json() == {"feedback_id": data["report_id"], "status": "received"}
        assert client.get(url).status_code == 405
        assert client.post(url, json={**data, "message": "changed"}).status_code == 400
    with receiver.Inbox(inbox.path).connect() as db:
        assert db.execute("SELECT message,status FROM feedback").fetchall() == [(data["message"], "new")]


def test_receiver_validation_size_rate_and_storage_failure(inbox_server, monkeypatch):
    server, inbox, url = inbox_server
    with httpx.Client(trust_env=False) as client:
        for value in [{**payload(), "cookie": "synthetic"}, {**payload(), "category": "invalid"},
                      {**payload(), "message": " "}, {**payload(), "report_id": "bad"}]:
            assert client.post(url, json=value).status_code == 400
        assert client.post(url, content="x" * 20001).status_code == 413
        assert client.post(url, content="text").status_code == 415
        def failed(_):
            raise receiver.sqlite3.OperationalError("synthetic private error")
        monkeypatch.setattr(inbox, "save", failed)
        response = client.post(url, json=payload())
        assert response.status_code == 503
        assert "private" not in response.text
        for _ in range(3):
            client.post(url, json=payload())
        assert client.post(url, json=payload()).status_code == 429
        assert len(server.rates) <= 2


def test_client_sends_only_explicit_fields_and_checks_receipt(monkeypatch):
    original = httpx.Client
    seen = []
    def handle(request):
        body = json.loads(request.content)
        seen.append(body)
        assert str(request.url) == "https://example.test/api/feedback"
        assert set(body) == {"report_id", "message", "tool_name", "category", "client_version"}
        return httpx.Response(201, json={"feedback_id": body["report_id"], "status": "received"})
    def client(**options):
        assert options == {"timeout": 10, "trust_env": False, "follow_redirects": False}
        return original(transport=httpx.MockTransport(handle), **options)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setenv("STU_MCP_FEEDBACK_URL", "https://example.test/api/feedback")
    assert approved_feedback("Synthetic issue")["status"] == "received"
    assert len(seen) == 1


@pytest.mark.parametrize("url", ["http://example.test/api/feedback", "https://user:pass@example.test/",
                                  "https://example.test/?token=secret", "https://example.test/#part", ""])
def test_client_rejects_unsafe_endpoint(monkeypatch, url):
    monkeypatch.setenv("STU_MCP_FEEDBACK_URL", url)
    with pytest.raises(AppError, match="HTTPS"):
        feedback.report_feedback("Synthetic issue")


@pytest.mark.parametrize("message", ["", " " * 2, "x" * 4001, "Cookie: synthetic_session",
                                     "password=synthetic", "Bearer synthetic"])
def test_client_rejects_empty_oversize_and_credential_pastes(message):
    with pytest.raises(AppError):
        feedback.report_feedback(message)


def test_preview_and_missing_consent_never_connect(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("no consent: no network"))
    preview = feedback.report_feedback("Synthetic issue", user_confirmed=True)
    assert preview["status"] == "needs_user_confirmation"
    assert preview["payload"]["message"] == "Synthetic issue"
    with pytest.raises(AppError) as error:
        feedback.report_feedback("Synthetic issue", confirmation_id=preview["confirmation_id"])
    assert error.value.code == "feedback_consent_required"
    with pytest.raises(AppError) as error:
        feedback.report_feedback("changed", confirmation_id=preview["confirmation_id"], user_confirmed=True)
    assert error.value.code == "feedback_preview_changed"
    monkeypatch.setenv("STU_MCP_FEEDBACK_URL", "https://changed.test/feedback")
    with pytest.raises(AppError) as error:
        feedback.report_feedback("Synthetic issue", confirmation_id=preview["confirmation_id"], user_confirmed=True)
    assert error.value.code == "feedback_preview_changed"


def test_expired_preview_never_connects(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("expired: no network"))
    preview = feedback.report_feedback("Synthetic issue")
    moment = feedback.time.monotonic()
    monkeypatch.setattr(feedback.time, "monotonic", lambda: moment + 601)
    with pytest.raises(AppError) as error:
        feedback.report_feedback("Synthetic issue", confirmation_id=preview["confirmation_id"], user_confirmed=True)
    assert error.value.code == "feedback_preview_changed"


def test_confirmation_is_consumed_before_unknown_send(monkeypatch):
    preview = feedback.report_feedback("Synthetic issue")
    def failed(**_):
        raise httpx.ConnectTimeout("synthetic")
    monkeypatch.setattr(httpx, "Client", failed)
    with pytest.raises(AppError) as error:
        feedback.report_feedback("Synthetic issue", confirmation_id=preview["confirmation_id"], user_confirmed=True)
    assert error.value.code == "feedback_outcome_unknown"
    with pytest.raises(AppError) as error:
        feedback.report_feedback("Synthetic issue", confirmation_id=preview["confirmation_id"], user_confirmed=True)
    assert error.value.code == "feedback_preview_changed"


def test_receiver_rejects_old_clients_without_saving(inbox_server):
    _, inbox, url = inbox_server
    with httpx.Client(trust_env=False) as client:
        assert client.post(url, json={**payload(), "client_version": "0.7.2"}).status_code == 426
    with inbox.connect() as db:
        assert db.execute("SELECT count(*) FROM feedback").fetchone()[0] == 0


@pytest.mark.parametrize("status,receipt,code", [(302, {}, "feedback_unavailable"),
    (429, {}, "feedback_rate_limited"), (500, {}, "feedback_unavailable"),
    (201, {"feedback_id": "wrong", "status": "received"}, "feedback_outcome_unknown")])
def test_client_does_not_follow_redirects_or_claim_false_success(monkeypatch, status, receipt, code):
    original = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=receipt, headers={"Location": "https://other.test/"})
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    with pytest.raises(AppError) as error:
        approved_feedback("Synthetic issue")
    assert error.value.code == code
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_feedback_tool_is_write_and_external(app):
    tools = await build_server(app).list_tools()
    tool = next(tool for tool in tools if tool.name == "report_feedback")
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.open_world_hint is True
