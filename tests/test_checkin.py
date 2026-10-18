import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest

from stu_mcp.checkin import CheckinClient, _lock, default_home, worker_locked
from stu_mcp.checkin_process import worker_environment


@pytest.fixture
def local(tmp_path):
    info = {"url": "http://127.0.0.1:54321/", "pid": 101, "service": "stu-checkin",
            "instance_id": "synthetic-instance", "protocol_version": 1}
    (tmp_path / "runtime.json").write_text(json.dumps(info))
    raw = {"ok": True, "status": "paused", "status_label": "已暂停", "status_reason": "paused",
           "auth_state": "logged_in", "logged_in": True, "monitoring": False, "needs_login": False,
           "courses": [{"id": "a", "name": "测试一", "class_id": "private-class"},
                       {"id": "b", "name": "测试二", "class_id": "private-class"}],
           "selected_courses": ["a"], "course_statuses": {}, "duration_minutes": 90,
           "auth_url": "sensitive-url", "cookie": "synthetic-sensitive-cookie",
           "events": [{"text": "synthetic-sensitive-event"}]}
    calls = []

    def handle(request):
        calls.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json=info | {"ok": True})
        if path == "/":
            return httpx.Response(200, text="page", headers={"Set-Cookie": "local=synthetic-cookie; HttpOnly"})
        assert request.headers["X-STU-Client"] == "local-ui"
        assert request.headers["Origin"] == info["url"].rstrip("/")
        assert "local=synthetic-cookie" in request.headers["Cookie"]
        if path == "/api/state":
            return httpx.Response(200, json=raw)
        if path == "/api/results":
            return httpx.Response(200, json={"ok": True, "items": [
                {"course_id": "a", "activity_id": "one", "status": "already_signed", "code": "0123"},
                {"course_id": "b", "activity_id": "two", "status": "signed", "answer": "private-answer"},
            ]})
        body = json.loads(request.content)
        if path == "/api/select":
            raw["selected_courses"] = body["course_ids"]
        elif path == "/api/start":
            raw.update(status="monitoring", status_label="监听中", monitoring=True,
                       selected_courses=body["course_ids"], duration_minutes=body["minutes"])
        elif path == "/api/pause":
            raw.update(status="paused", status_label="已暂停", monitoring=False, resume_enabled=False)
        elif path == "/api/quit":
            (tmp_path / "runtime.json").unlink()
        else:
            raise AssertionError(path)
        return httpx.Response(200, json={"ok": True})

    opener = Mock(return_value=True)
    client = CheckinClient(tmp_path, transport=httpx.MockTransport(handle), opener=opener, startup_timeout=.4)
    client._launch = Mock(side_effect=AssertionError("must reuse running worker"))
    return client, raw, calls, info


def test_status_is_passive_and_missing_service_does_not_mean_not_logged_in(tmp_path):
    client = CheckinClient(tmp_path / "absent", opener=Mock())
    client._launch = Mock()
    view = client.status()
    assert view["status"] == "service_not_started" and view["service_running"] is False
    assert view["logged_in"] is None and view["monitoring"] is False
    assert not (tmp_path / "absent").exists()
    assert client.results()["results_available"] is False
    client.pause()
    client._launch.assert_not_called()
    client.opener.assert_not_called()


@pytest.mark.parametrize("status", ["not_logged_in", "paused", "monitoring", "query_error", "starting", "stopping"])
def test_status_preserves_backend_authority_and_strips_credentials(local, status):
    client, raw, _, _ = local
    raw["status"] = status
    result = client.status()
    assert result["status"] == status
    text = json.dumps(result)
    assert "sensitive" not in text and "auth_url" not in text and "private-class" not in text
    client.opener.assert_not_called()


def test_login_required_opens_page_once_without_queuing_start(local):
    client, raw, calls, info = local
    raw.update(status="not_logged_in", status_label="未登录", logged_in=False,
               auth_state="not_logged_in", needs_login=True, courses=[])
    result = client.start(all_courses=True)
    assert not result["ok"] and result["browser_opened"] and not result["monitoring"]
    client.opener.assert_called_once_with(info["url"] + "#login")
    assert client.courses()["login_page_already_requested"]
    assert not any(r.method == "POST" for r in calls)
    client.open_page()
    assert client.opener.call_count == 2


def test_open_failure_is_reported_truthfully(local):
    client, raw, _, _ = local
    raw.update(status="not_logged_in", needs_login=True, logged_in=False)
    client.opener.return_value = False
    result = client.start(["a"])
    assert not result["browser_opened"] and result["next_action"] == "open_local_browser"


def test_select_start_pause_and_stop_use_same_backend(local):
    client, raw, calls, _ = local
    assert client.select(all_courses=True)["selected_courses"] == ["a", "b"]
    result = client.start(minutes=0)
    assert result["status"] == "monitoring" and result["duration_minutes"] == 0
    assert client.select(["b"])["action_error"] == "pause_required"
    assert client.pause()["status"] == "paused"
    assert client.stop_service()["status"] == "service_not_started"
    assert [r.url.path for r in calls if r.method == "POST"] == [
        "/api/select", "/api/start", "/api/pause", "/api/pause", "/api/quit"]
    client._launch.assert_not_called()


@pytest.mark.parametrize("selection,all_courses", [([], False), (["a", "a"], False), (["other"], False),
                                                   (["a"], True), ("a", False)])
def test_invalid_course_selection_has_no_mutation(local, selection, all_courses):
    client, _, calls, _ = local
    assert client.start(selection, all_courses=all_courses)["action_error"] == "invalid_courses"
    assert not any(r.method == "POST" for r in calls)


def test_invalid_duration_has_no_side_effect(local):
    client, _, calls, _ = local
    assert client.start(["a"], minutes=True)["action_error"] == "invalid_duration"
    assert not any(r.method == "POST" for r in calls)


def test_results_keep_evidence_separate_and_paginate(local):
    client, _, _, _ = local
    result = client.results(limit=1)
    assert result["items"][0]["status"] == "already_signed" and result["next_offset"] == 1
    assert "0123" not in json.dumps(result)
    result = client.results(course_id="b")
    assert len(result["items"]) == 1 and result["items"][0]["status"] == "signed"
    assert "private-answer" not in json.dumps(result)


@pytest.mark.parametrize("url", ["https://evil.example/", "http://127.0.0.1:90/@bad?x=1",
                                 "http://user@127.0.0.1:90/", "http://localhost:90/"])
def test_untrusted_discovery_never_makes_request_or_launches(tmp_path, url):
    (tmp_path / "runtime.json").write_text(json.dumps({"url": url, "pid": 101, "service": "stu-checkin"}))
    transport = httpx.MockTransport(Mock(side_effect=AssertionError("no request allowed")))
    client = CheckinClient(tmp_path, transport=transport)
    client._launch = Mock()
    assert client.courses()["status"] == "query_error"
    client._launch.assert_not_called()


def test_pid_reuse_or_old_protocol_is_not_trusted(local):
    client, _, _, info = local
    info["instance_id"] = "reused-port-different-worker"
    assert client.status()["status_reason"] == "discovery_invalid"
    client._launch.assert_not_called()


@pytest.mark.parametrize("exception", [httpx.ConnectError, httpx.ConnectTimeout])
def test_dead_worker_with_stale_runtime_is_not_mistaken_for_running(local, exception):
    client, _, _, _ = local
    client.transport = httpx.MockTransport(Mock(side_effect=exception("private-details")))
    result = client.status()
    assert result["status"] == "service_not_started" and result["status_reason"] == "stale_runtime"
    assert "private-details" not in json.dumps(result)


def test_live_lock_and_timeout_never_start_second_worker(local):
    client, _, _, _ = local
    path = client.home / "worker.lock"
    path.write_bytes(b"0")
    with path.open("r+b") as handle:
        _lock(handle)
        try:
            assert worker_locked(client.home)
            client.transport = httpx.MockTransport(Mock(side_effect=httpx.ConnectError("hidden")))
            assert client.courses()["status_reason"] == "worker_unreachable"
            client.transport = httpx.MockTransport(Mock(side_effect=httpx.ReadTimeout("hidden")))
            assert client.courses()["status_reason"] == "worker_timeout"
        finally:
            _lock(handle, release=True)
    client._launch.assert_not_called()


def test_mutation_timeout_is_not_retried_or_reported_as_success(local):
    client, _, calls, _ = local
    original = client.transport.handler

    def handle(request):
        if request.method == "POST":
            calls.append(request)
            raise httpx.ReadTimeout("sensitive-token-in-error")
        return original(request)

    client.transport = httpx.MockTransport(handle)
    result = client.start(["a"])
    assert result["status_reason"] == "operation_uncertain" and result["monitoring"] is None
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert "sensitive-token" not in json.dumps(result)


def test_concurrent_clients_launch_once(local):
    first, _, _, info = local
    (first.home / "runtime.json").unlink()
    launched = Mock()

    def launch():
        launched()
        time.sleep(.05)
        (first.home / "runtime.json").write_text(json.dumps(info))

    clients = [CheckinClient(first.home, transport=first.transport, startup_timeout=2) for _ in range(4)]
    for client in clients:
        client._launch = launch
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda client: client.courses(), clients))
    assert all(r["status"] == "paused" for r in results)
    launched.assert_called_once()


def test_detached_launch_has_no_inherited_pipes(tmp_path, monkeypatch):
    fake_python = tmp_path / "python.exe"
    fake_python.touch()
    monkeypatch.setenv("STU_CHECKIN_PYTHON", str(fake_python))
    popen = Mock(return_value=Mock(wait=Mock(return_value=0)))
    monkeypatch.setattr(subprocess, "Popen", popen)
    windows_launch = Mock()
    monkeypatch.setattr("stu_mcp.checkin.launch_windows_worker", windows_launch)
    client = CheckinClient(tmp_path)
    client._launch()
    if os.name == "nt":
        args, _ = windows_launch.call_args
        assert args[0] == [str(fake_python), "-m", "stu_checkin.server", "--no-browser"]
        assert args[2] == tmp_path
        popen.assert_not_called()
        return
    args, kwargs = popen.call_args
    assert args[0] == [str(fake_python), "-m", "stu_checkin.server", "--no-browser"]
    assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL and kwargs["close_fds"]
    assert kwargs.get("creationflags") or kwargs.get("start_new_session")


def test_worker_environment_excludes_unrelated_client_secrets():
    env = {"LOCALAPPDATA": "local-data", "STU_CHECKIN_HOME": "worker-data", "PYTHONPATH": "worker-source",
           "OPENAI_API_KEY": "synthetic-secret", "OTHER_TOKEN": "private-token"}
    result = worker_environment(env)
    assert len(result) == 3 and not any("secret" in value or "token" in value for value in result)


def test_default_home_is_shared_outside_packaged_appdata(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.delenv("STU_CHECKIN_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "synthetic-packaged-redirect"))
    assert default_home() == tmp_path / ".local" / "share" / "stu-checkin"


def test_partial_failures_remain_query_error_with_monitoring_true(local):
    client, raw, _, _ = local
    raw.update(status="query_error", status_label="查询异常", monitoring=True, failed_courses=["b"],
               course_statuses={"b": {"error": "查询失败，正在重试", "last_read_at": 123, "stale": True}})
    result = client.status()
    assert result["status"] == "query_error" and result["monitoring"]
    assert result["course_statuses"]["b"]["last_read_at"] == 123


def test_discovery_waits_for_publishing_and_has_bounded_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("stu_mcp.checkin.worker_locked", lambda _: True)
    client = CheckinClient(tmp_path, startup_timeout=.1)
    client._launch = Mock()
    assert client.status()["status"] == "starting"
    assert client.courses()["status_reason"] == "startup_timeout"
    client._launch.assert_not_called()
