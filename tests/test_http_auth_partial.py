"""Partial Moodle initialization never discards a proven MySTU API session."""
import pytest

from stu_mcp.auth_http import Candidate, Credentials, _next_step, login_http


@pytest.mark.parametrize("bootstrap,labels", [
    ({"elc": {"bootstrapped": False, "status": "moodle_session_unconfirmed"}}, ("ELC",)),
    ({"campus": {"bootstrapped": False, "status": "authentication_network_error"}}, ("Campus",)),
    ({"elc": {"bootstrapped": False, "status": "authentication_budget"},
      "campus": {"bootstrapped": False, "status": "moodle_verification_unavailable"}}, ("ELC", "Campus")),
])
def test_next_step_reports_only_failed_known_moodle_instances(bootstrap, labels):
    step = _next_step("mystu", {"moodle_bootstrap": bootstrap})
    assert "MySTU 身份及课程会话已加密保存" in step
    assert "课程查询可用" in step
    assert "Moodle 业务仍需单独验证" in step
    for label in labels:
        assert label in step


def test_next_step_cannot_echo_unknown_instance_or_status_text():
    step = _next_step("mystu", {"moodle_bootstrap": {
        "elc": {"bootstrapped": False, "status": "SYNTHETIC_PRIVATE_ERROR"},
        "SYNTHETIC_PRIVATE_INSTANCE": {"bootstrapped": False, "status": "SYNTHETIC_PRIVATE_ERROR"},
    }})
    assert "ELC（moodle_verification_unavailable）" in step
    assert "SYNTHETIC_PRIVATE" not in step


@pytest.mark.parametrize("source,proof", [
    ("mystu", {}),
    ("mystu", {"moodle_bootstrap": {"elc": {"bootstrapped": True, "status": "verified"}}}),
    ("yuketang", {"moodle_bootstrap": {"elc": {"bootstrapped": False, "status": "authentication_budget"}}}),
])
def test_complete_or_other_source_keeps_existing_next_step(source, proof):
    assert _next_step(source, proof) == "登录会话已加密保存，现在可读取此来源。"


def test_partial_bootstrap_keeps_guarded_encrypted_api_session(app, session, monkeypatch):
    from stu_mcp.auth_http import cas

    proof = {"authenticated": True, "identity_verified": True, "courses_verified": True,
             "course_count": 1, "course_inventory_complete": True,
             "moodle_bootstrap": {"elc": {"bootstrapped": False, "status": "authentication_network_error"}}}
    monkeypatch.setattr(cas, "acquire_state", lambda *_args, **_kwargs: Candidate(session, proof))
    result = login_http(app.vault, "mystu", credentials=Credentials("synthetic-user", "synthetic-password"))
    assert result["ok"] is True
    assert result["status"] == "session_saved"
    assert result["proof"] == proof
    assert app.vault.load("mystu") == session
    assert "ELC（authentication_network_error）" in result["next_step"]
    assert b"SYNTHETIC_SESSION_NEVER_REAL" not in app.runtime.session_file("mystu").read_bytes()
