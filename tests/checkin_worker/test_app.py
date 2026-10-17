import http.client
import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
from requests.cookies import RequestsCookieJar

from stu_checkin.controller import Controller, OperationError, clean_message
from stu_checkin.server import InstanceLock, LocalServer
from stu_checkin.storage import SecureStore, StorageError, default_home


class MemoryKeys:
    def __init__(self):
        self.values = {}

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self.values[service, name] = value


def wait_for(condition, seconds=3):
    until = time.monotonic() + seconds
    while not condition():
        if time.monotonic() >= until:
            raise AssertionError("Condition was not reached")
        time.sleep(0.02)


@pytest.fixture
def store(tmp_path):
    return SecureStore(tmp_path, key_store=MemoryKeys())


def test_persistent_state_is_encrypted_and_requires_key(tmp_path):
    keys = MemoryKeys()
    store = SecureStore(tmp_path, key_store=keys)
    store.save_cookie("session=synthetic-cookie-secret")
    assert b"synthetic-cookie-secret" not in store.path.read_bytes()
    assert SecureStore(tmp_path, key_store=keys).load_cookie() == "session=synthetic-cookie-secret"
    keys.values.clear()
    with pytest.raises(StorageError):
        SecureStore(tmp_path, key_store=keys).load_cookie()


def test_keyring_failure_has_no_plaintext_fallback(tmp_path):
    keys = Mock()
    keys.get_password.side_effect = RuntimeError("synthetic-sensitive-error")
    store = SecureStore(tmp_path, key_store=keys)
    with pytest.raises(StorageError, match="系统密钥库") as error:
        store.save_cookie("session=private")
    assert "sensitive" not in str(error.value)
    assert not store.path.exists()


def test_clear_removes_saved_connection(store):
    store.save_cookie("session=test")
    store.clear()
    assert not store.path.exists()
    assert store.load_cookie() is None


class Response:
    status_code = 200

    def __init__(self, value=None, text=None):
        self.value = value
        self.text = text if text is not None else json.dumps(value or {})

    def json(self):
        return self.value


@pytest.fixture
def controller(store, monkeypatch):
    class Session:
        instances = []
        kind = "1"
        attended = False
        fail_reads = False
        fail_classes = set()
        user_id = "synthetic-student"
        courses = [{"CourseID": "course-a", "TClassID": "class-a", "CourseName": "测试课程"}]

        def __init__(self):
            self.headers = {}
            self.cookies = RequestsCookieJar()
            self.proxies = {}
            self.calls = []
            self.verify = True
            self.instances.append(self)

        def get(self, url, **kwargs):
            self.calls.append(("GET", urlparse(url).path, kwargs.get("data")))
            if "/P.aspx" in url:
                self.cookies.set("DFSession", "synthetic-secret-session")
                return Response({})
            if "LoginInfo.ashx" in url:
                return Response({"msg": "1" if self.cookies else "0"})
            if "/MB/index.aspx" in url:
                return Response(text=f'<input id="hidUID" value="{self.user_id}">')
            raise AssertionError("Unexpected GET")

        def post(self, url, data=None, **kwargs):
            self.calls.append(("POST", urlparse(url).path, data))
            if "CourseInfo.ashx" in url:
                return Response(self.courses)
            if "MBCount.ashx" in url:
                if data.get("action") == "getcheckintotalbyciid":
                    return Response({"TotalNumber": 1, "AbsenceNumber": 0})
                if self.fail_reads or data.get("classid") in self.fail_classes:
                    raise __import__("requests").Timeout("synthetic outage")
                now = datetime.now()
                return Response({"msg": "1", "rows": [{
                    "ID": "activity-" + data["classid"], "CheckInType": self.kind, "CheckInCode": "0123",
                    "StatusID": "1" if self.attended else "0", "CanApply": "1",
                    "CheckInStatus": "1" if self.attended else "0",
                    "CreaterDate": (now - timedelta(seconds=15)).strftime("%Y/%m/%d %H:%M:%S"),
                    "ApplyLimitDate": (now + timedelta(hours=24, minutes=5)).strftime("%Y/%m/%d %H:%M:%S"),
                }]})
            if urlparse(url).path == "/_CheckIn/CheckIn.ashx":
                return Response({"msgbox": "签到成功"})
            raise AssertionError("Unexpected POST")

        def close(self):
            pass

    monkeypatch.setattr("requests.Session", Session)
    app = Controller(store.home, store=store)
    wait_for(lambda: not app.snapshot()["busy"])
    app._bridge._settings.poll_min_s = 0.03
    app._bridge._settings.poll_max_s = 0.03
    app.fake_session = Session
    yield app
    app.close()


def connect(app):
    app.connect("https://www.duifene.com/_FileManage/PdfView.aspx?code=" + "A" * 32)


def test_login_course_list_and_snapshot_never_expose_session(controller):
    connect(controller)
    view = controller.snapshot()
    assert view["logged_in"]
    assert view["courses"] == [{"id": "course-a", "class_id": "class-a", "name": "测试课程"}]
    assert "synthetic-secret-session" not in json.dumps(view)
    assert "A" * 32 not in json.dumps(view)


@pytest.mark.parametrize("link", [
    "https://evil.example/?code=" + "A" * 32,
    "http://www.duifene.com/?code=" + "A" * 32,
    "https://www.duifene.com/?code=short",
    "https://www.duifene.com/?code=" + "A" * 32 + "&code=" + "B" * 32,
])
def test_invalid_authorization_never_makes_requests(controller, link):
    before = len(controller._bridge._session.calls)
    with pytest.raises(OperationError):
        controller.connect(link)
    assert len(controller._bridge._session.calls) == before


def test_monitor_submits_once_and_records_successful_queries(controller):
    connect(controller)
    controller.start(["course-a"], 30)
    wait_for(lambda: controller.snapshot()["last_confirmed_at"] > 0)
    time.sleep(0.13)
    controller.pause()
    view = controller.snapshot()
    assert view["last_read_at"] > 0
    assert not view["monitoring"]
    submissions = [c for c in controller._bridge._session.calls if c[1] == "/_CheckIn/CheckIn.ashx"]
    assert len(submissions) == 1
    assert submissions[0][2]["checkincode"] == "0123"


def test_attended_activity_is_not_resubmitted(controller):
    controller.fake_session.attended = True
    connect(controller)
    controller.start(["course-a"], 30)
    wait_for(lambda: controller.snapshot()["last_read_at"] > 0)
    controller.pause()
    assert not any(c[1] == "/_CheckIn/CheckIn.ashx" for c in controller._bridge._session.calls)
    assert controller.snapshot()["last_confirmed_at"] == 0


def test_location_activity_does_not_probe_or_subscribe(controller):
    controller.fake_session.kind = "3"
    connect(controller)
    controller._bridge._push.subscribe = Mock(side_effect=AssertionError("should not subscribe"))
    controller._bridge._api.probe_distance = Mock(side_effect=AssertionError("should not probe"))
    controller.start(["course-a"], 30)
    wait_for(lambda: any("定位签到" in e["text"] for e in controller.snapshot()["events"]))
    controller.pause()
    controller._bridge._push.subscribe.assert_not_called()
    controller._bridge._api.probe_distance.assert_not_called()


def test_poll_failure_does_not_look_like_success(controller):
    controller.fake_session.fail_reads = True
    connect(controller)
    controller.start(["course-a"], 30)
    wait_for(lambda: any("监控异常" in e["text"] for e in controller.snapshot()["events"]))
    controller.pause()
    assert controller.snapshot()["last_read_at"] == 0


def test_automatic_deadline_and_logout_stop_monitor(controller):
    connect(controller)
    controller.start(["course-a"], 30)
    controller._until = time.time() - 1
    wait_for(lambda: not controller.snapshot()["monitoring"])
    controller.disconnect()
    assert not controller.snapshot()["logged_in"]
    assert not controller.snapshot()["course_statuses"]
    assert not controller.store.path.exists()
    connect(controller)
    assert controller._bridge._sentinel.is_running


def test_unknown_course_cannot_start_monitoring(controller):
    connect(controller)
    with pytest.raises(OperationError):
        controller.start(["another-account-course"], 30)
    assert not controller.snapshot()["monitoring"]


def test_auth_urls_and_tokens_are_redacted():
    result = clean_message("failed https://www.duifene.com/P.aspx?code=" + "A" * 32)
    assert "https" not in result and "A" * 32 not in result


@pytest.fixture
def http_server():
    controller = Mock()
    controller.snapshot.return_value = {"ok": True, "logged_in": False}
    controller.start.return_value = {"ok": True}
    server = LocalServer(controller)
    thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
    thread.start()
    yield server
    server.close()
    thread.join(timeout=2)


def request(server, path, *, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.httpd.server_port, timeout=2)
    connection.request("POST" if body is not None else "GET", path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = (response.status, response.read(), dict(response.getheaders()))
    connection.close()
    return result


def browser_headers(server):
    status, _, headers = request(server, "/")
    assert status == 200
    return {"Cookie": headers["Set-Cookie"].split(";", 1)[0], "X-STU-Client": "local-ui",
            "Origin": server.url.rstrip("/"), "Content-Type": "application/json"}


def test_browser_access_and_cross_origin_guard(http_server):
    headers = browser_headers(http_server)
    assert request(http_server, "/api/state", headers=headers)[0] == 200
    assert request(http_server, "/api/state")[0] == 403
    hostile = {**headers, "Origin": "https://evil.example"}
    assert request(http_server, "/api/start", body='{"course_ids":["x"],"minutes":30}', headers=hostile)[0] == 403
    http_server.controller.start.assert_not_called()


def test_rejected_post_with_delayed_body_keeps_error_readable(http_server):
    connection = http.client.HTTPConnection("127.0.0.1", http_server.httpd.server_port, timeout=3)
    try:
        body = b'{"course_ids":["x"],"minutes":30}'
        connection.putrequest("POST", "/api/start")
        connection.putheader("Content-Length", str(len(body)))
        connection.putheader("Content-Type", "application/json")
        connection.endheaders()
        time.sleep(.05)
        connection.send(body)
        response = connection.getresponse()
        assert response.status == 403 and json.loads(response.read())["ok"] is False
        http_server.controller.start.assert_not_called()
    finally:
        connection.close()


def test_extra_parameters_and_bad_host_cannot_call_backend(http_server):
    headers = browser_headers(http_server)
    assert request(http_server, "/api/start", body='{"course_ids":["x"],"minutes":30,"host":"evil"}', headers=headers)[0] == 400
    assert request(http_server, "/health", headers={"Host": "evil.example"})[0] == 403
    http_server.controller.start.assert_not_called()


def test_instance_lock_prevents_duplicate_workers(tmp_path):
    with InstanceLock(tmp_path), pytest.raises(OperationError), InstanceLock(tmp_path):
        pass


def add_second_course(controller):
    controller.fake_session.courses.append({"CourseID": "course-b", "TClassID": "class-b", "CourseName": "另一门课"})


def test_multiple_courses_rotate_and_do_not_resubmit(controller):
    add_second_course(controller)
    connect(controller)
    assert controller.snapshot()["selected_courses"] == ["course-a", "course-b"]
    controller.start(["course-a", "course-b"], 30)
    wait_for(lambda: all(s["last_read_at"] for s in controller.snapshot()["course_statuses"].values()))
    time.sleep(0.15)
    controller.pause()
    submissions = [call for call in controller._bridge._session.calls if call[1] == "/_CheckIn/CheckIn.ashx"]
    assert len(submissions) == 2
    assert set(controller.snapshot()["course_statuses"]) == {"course-a", "course-b"}


def test_one_course_failure_does_not_block_others(controller):
    add_second_course(controller)
    controller.fake_session.fail_classes = {"class-a"}
    connect(controller)
    controller.start(["course-a", "course-b"], 0)
    wait_for(lambda: controller.snapshot()["course_statuses"].get("course-b", {}).get("last_read_at", 0) > 0)
    assert controller.snapshot()["course_statuses"]["course-a"]["error"]
    assert controller.snapshot()["monitoring"]
    controller.pause()


def test_continuous_monitor_has_no_deadline_and_restores_after_restart(controller):
    add_second_course(controller)
    controller.fake_session.attended = True
    connect(controller)
    controller.start(["course-a", "course-b"], 0)
    assert controller.snapshot()["until"] == 0
    assert controller.snapshot()["continuous"] and controller.snapshot()["resume_enabled"]
    controller.close()
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        assert restored.snapshot()["monitoring"]
        assert restored.snapshot()["selected_courses"] == ["course-a", "course-b"]
        assert restored.snapshot()["duration_minutes"] == 0
    finally:
        restored.close()


def test_pause_disables_continuous_restart(controller):
    connect(controller)
    controller.start(["course-a"], 0)
    controller.pause()
    controller.close()
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        assert not restored.snapshot()["monitoring"]
        assert not restored.snapshot()["resume_enabled"]
    finally:
        restored.close()


def test_continuous_plan_cannot_resume_for_a_different_account(controller):
    connect(controller)
    controller.start(["course-a"], 0)
    controller.close()
    controller.fake_session.user_id = "different-synthetic-student"
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        assert not restored.snapshot()["monitoring"]
        assert not restored.store.get("monitor_plan")["enabled"]
    finally:
        restored.close()


def test_relogin_same_account_recovers_continuous_monitoring(controller):
    connect(controller)
    controller.start(["course-a"], 0)
    controller._bridge._on_login_invalid()
    assert not controller.snapshot()["logged_in"]
    connect(controller)
    assert controller.snapshot()["monitoring"]
    controller.pause()


def test_timed_monitor_is_not_restored_after_restart(controller):
    connect(controller)
    controller.start(["course-a"], 30)
    controller.close()
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        assert not restored.snapshot()["monitoring"]
        assert restored.snapshot()["selected_courses"] == ["course-a"]
    finally:
        restored.close()


@pytest.mark.parametrize("courses", [[], ["course-a", "course-a"], ["course-a", "foreign-course"],
                                      "course-a", ["course-a", 123]])
def test_invalid_multicourse_selection_is_rejected(controller, courses):
    connect(controller)
    with pytest.raises(OperationError):
        controller.start(courses, 0)
    assert not controller.snapshot()["monitoring"]


def test_pause_during_headcount_prevents_late_submission(controller):
    entered = threading.Event()
    release = threading.Event()
    original_post = controller._bridge._session.post

    def post(url, data=None, **kwargs):
        if isinstance(data, dict) and data.get("action") == "getcheckintotalbyciid":
            entered.set()
            assert release.wait(3)
        return original_post(url, data=data, **kwargs)

    controller._bridge._session.post = post
    connect(controller)
    controller.start(["course-a"], 30)
    assert entered.wait(2)
    pauser = threading.Thread(target=controller.pause)
    pauser.start()
    wait_for(controller._bridge._watcher._stop.is_set)
    release.set()
    pauser.join(timeout=3)
    assert not pauser.is_alive()
    assert not controller.snapshot()["monitoring"]
    assert not any(call[1] == "/_CheckIn/CheckIn.ashx" for call in controller._bridge._session.calls)


def test_api_accepts_multiple_courses_and_continuous_duration(http_server):
    headers = browser_headers(http_server)
    assert request(http_server, "/api/start", body='{"course_ids":["a","b"],"minutes":0}', headers=headers)[0] == 200
    http_server.controller.start.assert_called_once_with(["a", "b"], 0)


def test_pause_still_stops_worker_if_saving_preferences_fails(controller, monkeypatch):
    connect(controller)
    controller.start(["course-a"], 0)
    monkeypatch.setattr(controller.store, "update", Mock(side_effect=StorageError("系统密钥库不可用")))
    with pytest.raises(StorageError):
        controller.pause()
    assert not controller.snapshot()["monitoring"]


def test_local_workers_on_different_ports_do_not_replace_each_others_cookies(http_server):
    import requests
    other = LocalServer(http_server.controller)
    thread = threading.Thread(target=other.httpd.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    try:
        session.get(http_server.url, timeout=2).raise_for_status()
        session.get(other.url, timeout=2).raise_for_status()
        headers = {"X-STU-Client": "local-ui"}
        assert session.get(http_server.url + "api/state", headers=headers, timeout=2).status_code == 200
        assert session.get(other.url + "api/state", headers=headers, timeout=2).status_code == 200
    finally:
        session.close()
        other.close()
        thread.join(timeout=2)


def test_shared_status_transitions_and_partial_failure_recovery(controller):
    assert controller.snapshot()["status"] == "not_logged_in"
    add_second_course(controller)
    connect(controller)
    assert controller.snapshot()["status"] == "paused"
    controller.fake_session.attended = True
    controller.fake_session.fail_classes = {"class-b"}
    controller.start(["course-a", "course-b"], 30)
    wait_for(lambda: controller.snapshot()["status"] == "query_error")
    state = controller.snapshot()
    assert state["monitoring"] and state["failed_courses"] == ["course-b"]
    assert state["course_statuses"]["course-a"]["last_read_at"] > 0
    assert state["course_statuses"]["course-b"]["last_read_at"] == 0
    controller.fake_session.fail_classes = set()
    wait_for(lambda: controller.snapshot()["status"] == "monitoring")
    controller.pause()
    assert controller.snapshot()["status"] == "paused"


def test_expired_login_is_not_reported_as_paused(controller):
    connect(controller)
    controller.start(["course-a"], 30)
    controller._bridge._on_login_invalid()
    state = controller.snapshot()
    assert state["status"] == "not_logged_in" and state["needs_login"]
    assert not state["monitoring"] and state["auth_state"] == "not_logged_in"


def test_offline_boot_does_not_claim_missing_login(controller, monkeypatch):
    connect(controller)
    controller.close()
    monkeypatch.setattr(controller.fake_session, "post", Mock(side_effect=__import__("requests").Timeout()))
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        state = restored.snapshot()
        assert state["status"] == "query_error" and state["auth_state"] == "unknown"
        assert not state["needs_login"]
    finally:
        restored.close()


def test_stale_queries_and_unexpected_worker_exit_are_not_healthy(controller):
    connect(controller)
    controller.fake_session.attended = True
    controller.start(["course-a"], 30)
    wait_for(lambda: controller.snapshot()["last_read_at"] > 0)
    watcher = controller._bridge._watcher
    # Hold the shared request lock to simulate an outstanding/blocked request.
    with controller._bridge._auth_lock:
        with watcher._lock:
            watcher._health["course-a"]["last_read_at"] = time.time() - 999
        assert controller.snapshot()["status"] == "query_error"
    watcher.stop()  # A worker died without a controller pause/deadline.
    assert controller.snapshot()["status_reason"] == "worker_stopped_unexpectedly"
    controller.pause()
    assert controller.snapshot()["status"] == "paused"


def test_duplicate_start_reuses_worker_and_does_not_extend_deadline(controller):
    connect(controller)
    controller.start(["course-a"], 30)
    thread = controller._bridge._watcher._thread
    until = controller.snapshot()["until"]
    assert controller.start(["course-a"], 30)["already_running"]
    assert controller._bridge._watcher._thread is thread
    assert controller.snapshot()["until"] == until
    with pytest.raises(OperationError, match="先暂停"):
        controller.start(["course-a"], 0)


def test_selection_is_shared_persistent_and_does_not_start_monitoring(controller):
    add_second_course(controller)
    connect(controller)
    revision = controller.snapshot()["selection_revision"]
    controller.select(["course-b"])
    state = controller.snapshot()
    assert state["selected_courses"] == ["course-b"] and state["status"] == "paused"
    assert state["selection_revision"] > revision
    assert controller.store.get("monitor_plan")["course_ids"] == ["course-b"]
    controller.start(["course-b"], 30)
    with pytest.raises(OperationError, match="先暂停"):
        controller.select(["course-a"])


def test_pause_cancels_auto_resume_even_after_session_expired(controller):
    connect(controller)
    controller.start(["course-a"], 0)
    controller._bridge._on_login_invalid()
    controller.pause()
    assert not controller.store.get("monitor_plan")["enabled"]
    assert controller.snapshot()["status"] == "not_logged_in"


def test_result_evidence_distinguishes_attended_from_submitted_and_survives_restart(controller):
    add_second_course(controller)
    connect(controller)
    controller.fake_session.attended = True
    controller.start(["course-a"], 30)
    wait_for(lambda: len(controller.results()["items"]) == 1)
    controller.pause()
    controller.fake_session.attended = False
    controller.start(["course-b"], 30)
    wait_for(lambda: controller.snapshot()["last_confirmed_at"] > 0)
    controller.pause()
    results = {r["course_id"]: r for r in controller.results()["items"]}
    assert results["course-a"]["status"] == "already_signed"
    assert results["course-a"]["evidence"] == "platform_attendance"
    assert results["course-b"]["status"] == "signed"
    assert results["course-b"]["evidence"] == "submission_response"
    assert "0123" not in json.dumps(results)
    assert "synthetic-secret" not in json.dumps(results)
    assert b"course-a" not in controller.store.path.read_bytes()
    confirmed = controller.snapshot()["last_confirmed_at"]
    controller.close()
    restored = Controller(controller.store.home, store=controller.store)
    try:
        wait_for(lambda: not restored.snapshot()["busy"])
        assert len(restored.results()["items"]) == 2
        assert restored.snapshot()["last_confirmed_at"] == confirmed
    finally:
        restored.close()


def test_failed_submission_can_later_become_success_even_if_vendor_logs_are_silent(controller):
    connect(controller)
    answer = ["签到失败"]
    controller._bridge._api.sign_by_code = lambda _: answer[0]
    controller.start(["course-a"], 30)
    wait_for(lambda: any(r["status"] == "failed" for r in controller.results()["items"]))
    assert controller.snapshot()["last_confirmed_at"] == 0
    answer[0] = "签到成功"
    wait_for(lambda: controller.snapshot()["last_confirmed_at"] > 0)
    controller.pause()
    assert len(controller.results()["items"]) == 1
    assert controller.results()["items"][0]["status"] == "signed"


def test_location_result_requires_manual_action(controller):
    connect(controller)
    controller.fake_session.kind = "3"
    controller.start(["course-a"], 30)
    wait_for(lambda: controller.results()["items"])
    controller.pause()
    assert controller.results()["items"][0]["status"] == "manual_required"
    assert controller.snapshot()["last_confirmed_at"] == 0


def test_selection_and_result_http_routes_require_existing_session(http_server):
    http_server.controller.select.return_value = {"ok": True}
    http_server.controller.results.return_value = {"ok": True, "items": []}
    assert request(http_server, "/api/results")[0] == 403
    headers = browser_headers(http_server)
    assert request(http_server, "/api/results", headers=headers)[0] == 200
    assert request(http_server, "/api/select", body='{"course_ids":["a","b"]}', headers=headers)[0] == 200
    http_server.controller.select.assert_called_once_with(["a", "b"])
    health = json.loads(request(http_server, "/health")[1])
    assert health["protocol_version"] == 1 and health["instance_id"]
    assert "session" not in health


@pytest.mark.parametrize("response", [None, {"msg": "unexpected"}])
def test_login_probe_error_does_not_invent_expiration_and_can_recover(controller, monkeypatch, response):
    connect(controller)
    bridge = controller._bridge
    original = bridge._session.get

    def broken(url, **kwargs):
        if "LoginInfo.ashx" in url:
            if response is None:
                raise __import__("requests").Timeout("synthetic outage")
            return Response(response)
        return original(url, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(bridge._session, "get", broken)
        if response is None:
            with pytest.raises(__import__("requests").Timeout):
                bridge._sentinel._probe()
        else:
            bridge._sentinel._probe()
        state = controller.snapshot()
        assert state["status"] == "query_error" and state["logged_in"] and not state["needs_login"]
    bridge._sentinel._probe()
    assert controller.snapshot()["status"] == "paused"


def test_submission_timeout_is_unknown_result_not_false_success(controller):
    connect(controller)
    controller._bridge._api.sign_by_code = Mock(side_effect=__import__("requests").Timeout("private-error"))
    controller.start(["course-a"], 30)
    wait_for(lambda: controller.results()["items"])
    controller.pause()
    result = controller.results()["items"][0]
    assert result["status"] == "error" and result["evidence"] == "local_error"
    assert controller.snapshot()["last_confirmed_at"] == 0
    assert "private-error" not in json.dumps(result)


def test_default_home_is_shared_outside_packaged_appdata(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.delenv("STU_CHECKIN_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "synthetic-packaged-redirect"))
    assert default_home() == tmp_path / ".local" / "share" / "stu-checkin"
