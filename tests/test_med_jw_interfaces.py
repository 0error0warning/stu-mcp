"""Medical entry points share one service and the existing authentication fences."""
import json
from types import SimpleNamespace

import pytest

from stu_mcp import cli
from stu_mcp.auth_http import Candidate, Credentials, login_http
from stu_mcp.auth_http.school import SCHOOL_SERVICES
from stu_mcp.capability_catalog import build_capability_catalog
from stu_mcp.features.jw.schema import JW_SCHEMA_VERSION
from stu_mcp.features.med_jw import service
from stu_mcp.hosting import HostRuntime
from stu_mcp.runtime import AppError
from stu_mcp.server import build_server
from stu_mcp.sources import SOURCES

TOKEN = "SYNTHETIC_PRIVATE_MED_TOKEN"
USERNAME = "SYNTHETIC_MED_ACCOUNT"
PASSWORD = "SYNTHETIC_MED_PASSWORD"


def candidate():
    return Candidate({"cookies": [], "origins": [], "med_jw_token": TOKEN},
                     {"authenticated": True, "identity_verified": True, "timetable_verified": True})


def interaction():
    return SimpleNamespace(credentials=lambda: Credentials(USERNAME, PASSWORD), captcha=lambda *_args, **_kw: "AB12")


@pytest.mark.asyncio
async def test_app_cli_and_mcp_share_on_demand_medical_service_without_cache(app, monkeypatch, capsys):
    calls = []
    expected = {"ok": True, "source": "med_jw", "semester": "native-medical-term", "courses": [],
                "coverage": {"kind": "medical_current_timetable", "complete": True}, "pending": []}

    def read(vault, semester):
        assert vault is app.vault
        calls.append(semester)
        return expected

    def forbidden(*_args, **_kwargs):
        pytest.fail("Medical timetable is an on-demand read, not a cache refresh")

    monkeypatch.setattr(service, "academic_timetable", read)
    monkeypatch.setattr(cli, "App", lambda: app)
    monkeypatch.setattr(app, "refresh", forbidden)
    monkeypatch.setattr(app.store, "list", forbidden)
    monkeypatch.setattr(app.store, "save_batch", forbidden)
    assert app.medical_timetable() == expected
    assert cli.main(["timetable", "--source", "med_jw"]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    host = HostRuntime(app)
    try:
        result = await build_server(host=host).call_tool("get_medical_timetable", {})
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
    finally:
        host.close()
    assert calls == ["", "", ""]


@pytest.mark.asyncio
async def test_medical_tool_is_read_only_and_never_accepts_session_material(app):
    host = HostRuntime(app)
    try:
        tools = {tool.name: tool for tool in await build_server(host=host).list_tools()}
        medical = tools["get_medical_timetable"]
        assert medical.annotations.read_only_hint is True
        assert medical.annotations.idempotent_hint is True
        assert medical.annotations.open_world_hint is True
        assert medical.input_schema.get("properties", {}) == {}
        assert tools["get_academic_timetable"].input_schema["properties"]["semester"]["default"] == ""
    finally:
        host.close()


@pytest.mark.asyncio
async def test_medical_login_failure_is_actionable_through_cli_and_mcp(app, monkeypatch, capsys):
    def missing(*_args, **_kwargs):
        raise AppError("needs_login", "请先登录医学院教务。", "med_jw")

    monkeypatch.setattr(service, "academic_timetable", missing)
    monkeypatch.setattr(cli, "App", lambda: app)
    assert cli.main(["timetable", "--source", "med_jw"]) == 1
    expected = json.loads(capsys.readouterr().out)
    assert expected["status"] == "needs_login" and expected["next_action"] == "open_setup"
    assert expected["source"] == "med_jw"
    host = HostRuntime(app)
    try:
        result = await build_server(host=host).call_tool("get_medical_timetable", {})
        assert result.model_dump(by_alias=True)["structuredContent"] == expected
    finally:
        host.close()


def test_medical_catalog_and_source_remain_separate_from_main_campus_school_group():
    catalog = build_capability_catalog()
    medical = next(row for row in catalog["services"] if row["service_id"] == "medical_timetable")
    assert medical["source_id"] == medical["login_id"] == medical["configuration_id"] == "med_jw"
    assert medical["features"][0]["tools"] == ["get_medical_timetable"]
    assert medical["evidence"]["level"] == "implementation"
    assert "真实账号验收" in " ".join(medical["limits"])
    assert SOURCES["med_jw"].session == "med_jw" and SOURCES["jw"].session == "jw"
    assert SOURCES["med_jw"].hosts == ("jwgl.med.stu.edu.cn",)
    assert "med_jw" not in SCHOOL_SERVICES
    school = next(row for row in catalog["profiles"] if row["configuration_id"] == "school")
    assert "medical_timetable" not in school["service_ids"]


def test_generic_refresh_cannot_silently_add_medical_background_collection(app):
    with pytest.raises(AppError) as error:
        app.refresh("med_jw")
    assert error.value.code == "query_required"


def test_login_dispatch_encrypts_only_medical_token_and_logout_preserves_main_campus(app, monkeypatch):
    from stu_mcp.auth_http import med_jw

    app.vault.save("jw", {"cookies": [], "origins": []})
    jw_fingerprint = app.vault.fingerprint("jw")
    app.store.save_batch("jw", [{"id": "synthetic-grade", "kind": "grade", "title": "合成课程",
                                  "jw_schema_version": JW_SCHEMA_VERSION}], private=True)
    calls = []

    def acquire(username, password, *, captcha, check, transport):
        assert username == USERNAME and password == PASSWORD
        assert captcha(b"synthetic image") == "AB12" and transport is None
        check()
        calls.append(True)
        value = candidate()
        value.state.update(password=PASSWORD, username=USERNAME, irrelevant_token="OTHER_SECRET",
                           cookies=[{"name": "cas", "value": "SYNTHETIC_COOKIE", "domain": ".stu.edu.cn"}],
                           origins=[{"origin": "https://jwgl.med.stu.edu.cn", "localStorage": []}])
        return value

    monkeypatch.setattr(med_jw, "acquire_state", acquire)
    result = login_http(app.vault, "med_jw", interaction=interaction())
    assert calls == [True] and result["service"] == "med_jw" and result["status"] == "session_saved"
    assert app.vault.load("med_jw") == {"cookies": [], "origins": [], "med_jw_token": TOKEN}
    encoded = app.runtime.session_file("med_jw").read_bytes()
    assert TOKEN.encode() not in encoded and PASSWORD.encode() not in encoded
    assert all(secret not in json.dumps(result) for secret in (TOKEN, USERNAME, PASSWORD, "SYNTHETIC_COOKIE"))
    assert app.logout("med_jw")["status"] == "logged_out"
    assert app.vault.status("med_jw")["status"] == "needs_login"
    assert app.vault.fingerprint("jw") == jw_fingerprint
    assert len(app.store.list(sources=("jw",))["items"]) == 1


@pytest.mark.parametrize("boundary", ["adapter", "save"])
@pytest.mark.parametrize("event", ["cancel", "logout", "replacement"])
def test_medical_login_uses_cancellation_and_final_save_generation_guard(app, monkeypatch, boundary, event):
    from stu_mcp.auth_http import med_jw

    cancelled = False
    original_save = app.vault.save
    replacement = {"cookies": [], "origins": [], "med_jw_token": "SYNTHETIC_REPLACEMENT"}

    def change():
        nonlocal cancelled
        if event == "cancel":
            cancelled = True
        elif event == "logout":
            app.logout("med_jw")
        else:
            original_save("med_jw", replacement)

    def acquire(*_args, **_kwargs):
        if boundary == "adapter":
            change()
        return candidate()

    def save(*args, **kwargs):
        if boundary == "save":
            change()
        return original_save(*args, **kwargs)

    def check_cancelled():
        if cancelled:
            raise AppError("login_cancelled", "登录已取消。", "med_jw")

    monkeypatch.setattr(med_jw, "acquire_state", acquire)
    monkeypatch.setattr(app.vault, "save", save)
    with pytest.raises(AppError) as error:
        login_http(app.vault, "med_jw", interaction=interaction(), check_cancelled=check_cancelled)
    assert error.value.code == ("login_cancelled" if event == "cancel" else "session_changed")
    if event == "replacement":
        assert app.vault.load("med_jw") == replacement
    else:
        assert not app.runtime.session_file("med_jw").exists()


def test_medical_login_without_positive_proof_preserves_saved_session(app, monkeypatch):
    from stu_mcp.auth_http import med_jw

    saved = {"cookies": [], "origins": [], "med_jw_token": "SYNTHETIC_OLD_TOKEN"}
    app.vault.save("med_jw", saved)
    fingerprint = app.vault.fingerprint("med_jw")
    monkeypatch.setattr(med_jw, "acquire_state", lambda *_args, **_kwargs: Candidate(
        candidate().state, {"authenticated": False}))
    with pytest.raises(AppError) as error:
        login_http(app.vault, "med_jw", interaction=interaction())
    assert error.value.code == "authentication_unconfirmed"
    assert app.vault.fingerprint("med_jw") == fingerprint
