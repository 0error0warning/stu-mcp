"""Real HTTP adapter + service/CLI, with an entirely synthetic transport."""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from test_http_repair import School, session

from stu_mcp.features.repair import RepairDrafts, cli
from stu_mcp.runtime import AppError


def manager(school):
    @contextmanager
    def factory(stop, update):
        current = session(school)
        current.stop = stop
        current.gate.cancelled = stop.is_set
        current.update = update
        try:
            yield current
        finally:
            current.closed = True
            current.flow.client.close()
    return RepairDrafts(factory)


def test_cli_http_drill_displays_complete_actual_preview_and_never_submits(monkeypatch):
    school = School()
    drafts = manager(school)
    monkeypatch.setattr(cli, "RepairDrafts", lambda **_: drafts)
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("drill cannot ask to submit"))
    displayed = []
    result = cli.run_cli(None, fields=school.fields, output=displayed.append)
    assert result["status"] == "awaiting_confirmation" and displayed == [result]
    assert "13800000000" in result["preview_markdown"]
    assert "synthetic@stu.edu.cn" in result["preview_markdown"]
    assert "__VIEWSTATE" not in result["preview_markdown"]
    assert not any(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts)


@pytest.mark.parametrize("answer,submitted", [("确认提交", True), ("yes", False), ("取消", False)])
def test_cli_submit_requires_tty_and_confirmation_after_actual_preview(monkeypatch, answer, submitted):
    school = School()
    drafts = manager(school)
    monkeypatch.setattr(cli, "RepairDrafts", lambda **_: drafts)
    checks, displayed = [], []
    monkeypatch.setattr(cli, "require_terminal", lambda: checks.append("tty"))
    def confirm(_prompt):
        assert displayed[-1]["requires_user_confirmation"] is True
        assert displayed[-1]["form_fields"]
        assert "13800000000" in displayed[-1]["preview_markdown"]
        assert not any(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts)
        return answer
    monkeypatch.setattr("builtins.input", confirm)
    if submitted:
        result = cli.run_cli(None, fields=school.fields, submit=True, output=displayed.append)
        assert result["status"] == "submitted" and result["receipt"]["order_id"] == school.order
    else:
        with pytest.raises(AppError) as error:
            cli.run_cli(None, fields=school.fields, submit=True, output=displayed.append)
        assert error.value.code == "operation_cancelled"
    assert checks == ["tty", "tty"]
    assert sum(post["__EVENTTARGET"] == ["btn_OK"] for post in school.posts) == int(submitted)


def test_cli_no_tty_stops_before_opening_or_any_post(monkeypatch):
    school = School()
    monkeypatch.setattr(cli, "RepairDrafts", lambda **_: pytest.fail("must reject before opening"))
    def unavailable():
        raise AppError("terminal_required", "synthetic missing terminal")
    monkeypatch.setattr(cli, "require_terminal", unavailable)
    with pytest.raises(AppError) as error:
        cli.run_cli(None, fields=school.fields, submit=True)
    assert error.value.code == "terminal_required" and not school.posts
