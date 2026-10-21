"""Synthetic local converter checks, not real school or calendar-import acceptance."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import venv
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from stu_mcp.features.timetable import export as helper
from stu_mcp.runtime import Runtime
from stu_mcp.skill_export import export_skill

SCRIPT = (Path(__file__).parents[1] / "src/stu_mcp/skills/stu-timetable-export/scripts/build_timetable.py")


@pytest.fixture
def timetable():
    return {
        "schema_version": 1,
        "semester": "2026-autumn",
        "calendar": {"semester": "2026-autumn", "version": "synthetic-v1", "week1_monday": "2026-09-07",
                     "weeks": 20, "source_url": "https://jwc.stu.edu.cn/calendar.pdf",
                     "checked_at": "2026-10-20T09:00:00+08:00", "latest_verified": True},
        "timetable": {"source_url": "https://jw.stu.edu.cn/timetable", "complete": True,
                      "checked_at": "2026-10-20T09:00:00+08:00"},
        "periods": [{"number": 1, "start": "08:00", "end": "08:45"},
                    {"number": 2, "start": "08:55", "end": "09:40"},
                    {"number": 3, "start": "10:00", "end": "10:45"}],
        "courses": [{"id": "c1", "title": "合成课程", "teacher": "合成教师", "location": "合成教室",
                     "meetings": [{"id": "m1", "weekday": 1, "weeks": [1, 3, 5], "periods": [1, 2]}]}],
    }


def rule(kind, **kwargs):
    return {"id": "rule1", "kind": kind, "date": "2026-09-07",
            "source_url": "https://jwc.stu.edu.cn/holiday", "checked_at": "2026-10-21T08:00:00+08:00",
            **kwargs}


def rows(body):
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


def test_expands_exact_weeks_csv_and_utc_independent_of_host(timetable, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    manifest, files = helper.convert(timetable)
    assert manifest["status"] == "generated"
    assert [event["date"] for event in manifest["events"]] == ["2026-09-07", "2026-09-21", "2026-10-05"]
    assert manifest["events"][0]["start"] == "2026-09-07T08:00:00+08:00"
    assert manifest["events"][0]["end"] == "2026-09-07T09:40:00+08:00"
    assert b"DTSTART:20260907T000000Z\r\nDTEND:20260907T014000Z" in files["schedule.ics"]
    assert rows(files["wakeup.csv"])[1] == ["合成课程", "1", "1", "2", "合成教师", "合成教室", "1-1、3-3、5-5"]
    assert manifest["oa"] == {"enabled": False, "status": "not_checked"}
    assert manifest["calendar"]["verification_basis"] == "caller_assertion_from_reviewed_sources"
    assert "checked_at" in manifest["calendar"] and "generated_at" not in manifest
    settings = json.loads(files["wakeup-settings.json"])
    assert settings["week1_monday"] == "2026-09-07"
    assert settings["automatic_settings_import"] is False


def test_oa_default_performs_no_io(timetable, monkeypatch):
    monkeypatch.setattr(helper.Path, "open", lambda *_args, **_kwargs: pytest.fail("unexpected I/O"))
    manifest, _ = helper.convert(timetable)
    assert manifest["oa"] == {"enabled": False, "status": "not_checked"}


def test_periods_source_explicit_or_inherited(timetable):
    manifest, _ = helper.convert(timetable)
    assert manifest["periods_source"]["inherited_from_timetable"] is True
    assert manifest["periods_source"]["source_url"] == timetable["timetable"]["source_url"]
    timetable["periods_source"] = {"source_url": "https://jwc.stu.edu.cn/bell-times",
                                   "checked_at": "2026-10-21T09:00:00+08:00"}
    manifest, files = helper.convert(timetable)
    assert manifest["periods_source"] == {"source_url": "https://jwc.stu.edu.cn/bell-times",
                                          "checked_at": "2026-10-21T01:00:00Z"}
    assert b"DTSTAMP:20261021T010000Z" in files["schedule.ics"]


def test_meeting_teacher_location_override_course(timetable):
    timetable["courses"][0]["meetings"][0].update(teacher="", location="第二教室")
    manifest, files = helper.convert(timetable)
    assert all(event["teacher"] == "" and event["location"] == "第二教室" for event in manifest["events"])
    assert rows(files["wakeup.csv"])[1][4:6] == ["无", "第二教室"]


def test_oa_enabled_requires_evidenced_scope(timetable):
    timetable["oa"] = {"enabled": True, "status": "checked", "scope": "合成目标学期放假调课关键词",
                       "source_url": "http://oa.stu.edu.cn/search", "checked_at": "2026-10-21T01:00:00Z"}
    manifest, _ = helper.convert(timetable)
    assert manifest["oa"]["scope"] == "合成目标学期放假调课关键词"


@pytest.mark.parametrize("oa", [None, [], {"enabled": 1, "status": "checked"},
                                    {"enabled": False, "status": "checked"},
                                    {"enabled": True, "status": "not_checked"},
                                    {"enabled": True, "status": "checked"}])
def test_oa_misleading_states_rejected(timetable, oa):
    timetable["oa"] = oa
    with pytest.raises(helper.InputError):
        helper.convert(timetable)


@pytest.mark.parametrize("path,value", [("calendar.latest_verified", False), ("timetable.complete", False),
                                       ("pending", ["教学周基准尚有歧义"])])
def test_unverified_review_blocks_files(timetable, path, value):
    set_value(timetable, path, value)
    manifest, files = helper.convert(timetable)
    assert manifest["status"] == "blocked"
    assert manifest["pending"]
    assert set(files) == {"review.json"}


def test_cancel_retains_other_weeks_and_provenance(timetable):
    timetable["adjustments"] = [rule("cancel", course_id="c1", meeting_id="m1")]
    manifest, files = helper.convert(timetable)
    assert len(manifest["events"]) == 2
    assert manifest["adjustments"][0]["removed_occurrences"] == 1
    assert rows(files["wakeup.csv"])[1][-1] == "3-3、5-5"


def test_move_deletes_original_and_retains_uid(timetable):
    original, _ = helper.convert(timetable)
    timetable["adjustments"] = [rule("move", to_date="2026-09-12")]
    manifest, files = helper.convert(timetable)
    moved = manifest["events"][0]
    assert moved["date"] == "2026-09-12" and moved["original_date"] == "2026-09-07"
    assert moved["uid"] == original["events"][0]["uid"]
    assert "2026-09-07" not in [event["date"] for event in manifest["events"]]
    assert any(row[1] == "6" and row[-1] == "1-1" for row in rows(files["wakeup.csv"])[1:])
    assert b"DTSTART:20260912T000000Z" in files["schedule.ics"]


@pytest.mark.parametrize("action,expected", [("keep", 4), ("cancel", 3)])
def test_replace_day_explicit_source_behavior(timetable, action, expected):
    timetable["adjustments"] = [rule("replace_day", date="2026-09-12", teaching_date="2026-09-07",
                                     source_action=action)]
    manifest, _ = helper.convert(timetable)
    assert len(manifest["events"]) == expected
    assert ("2026-09-07" in [event["date"] for event in manifest["events"]]) == (action == "keep")
    assert len({event["uid"] for event in manifest["events"]}) == expected


def test_replace_day_replaces_target_timetable(timetable):
    timetable["courses"][0]["meetings"].append({"id": "m2", "weekday": 6, "weeks": [1], "periods": [3]})
    timetable["adjustments"] = [rule("replace_day", date="2026-09-12", teaching_date="2026-09-07",
                                     source_action="cancel")]
    manifest, _ = helper.convert(timetable)
    target = [event for event in manifest["events"] if event["date"] == "2026-09-12"]
    assert len(target) == 1 and target[0]["meeting_id"] == "m1"


@pytest.mark.parametrize("change", [
    rule("replace_day", date="2026-09-12", teaching_date="2026-09-07"),
    rule("replace_day", date="2026-09-12", teaching_date="2026-09-07", source_action="guess"),
    rule("replace_day", date="2026-09-12", teaching_date="2026-09-08", source_action="cancel"),
    rule("replace_day", date="2026-09-12", teaching_date="2026-09-07", source_action="keep", course_id="c1"),
    rule("cancel", course_id="missing"), rule("cancel", course_id="c1", meeting_id="missing"),
    rule("cancel", meeting_id="m1"), rule("cancel", date="2026-09-08"),
    rule("move", to_date="2026-09-07"), rule("move"), rule("unknown"),
    rule("cancel", to_date="2026-09-08"), rule("move", to_date="2026-09-08", source_action=[]),
])
def test_adjustment_ambiguity_is_rejected(timetable, change):
    timetable["adjustments"] = [change]
    with pytest.raises(helper.InputError):
        helper.convert(timetable)


def test_overlapping_adjustments_rejected_without_order_dependence(timetable):
    timetable["adjustments"] = [rule("cancel"), rule("move", id="r2", to_date="2026-09-12")]
    with pytest.raises(helper.InputError, match="overlapping"):
        helper.convert(timetable)


def test_conflicting_events_block_export(timetable):
    timetable["courses"].append({**deepcopy(timetable["courses"][0]), "id": "c2"})
    manifest, files = helper.convert(timetable)
    assert manifest["status"] == "blocked" and set(files) == {"review.json"}
    assert "冲突" in manifest["pending"][0]


def test_many_conflicts_bound_review_size(timetable):
    timetable["courses"] = [{**deepcopy(timetable["courses"][0]), "id": f"c{i}"} for i in range(200)]
    manifest, _ = helper.convert(timetable)
    assert len(manifest["pending"]) == 101


def test_expansion_limit_checked_before_excess_events_constructed(timetable, monkeypatch):
    timetable["calendar"]["weeks"] = 60
    meeting = timetable["courses"][0]["meetings"][0]
    meeting["weeks"] = list(range(1, 61))
    timetable["courses"] = [{**deepcopy(timetable["courses"][0]), "id": f"c{i}"} for i in range(500)]
    constructed = 0
    original = helper.occurrence

    def count(*args):
        nonlocal constructed
        constructed += 1
        return original(*args)

    monkeypatch.setattr(helper, "occurrence", count)
    with pytest.raises(helper.InputError, match="too many expanded"):
        helper.convert(timetable)
    assert constructed <= 20000


def test_all_keeps_ics_when_wakeup_outside_grid(timetable):
    timetable["adjustments"] = [rule("move", to_date="2026-09-05")]
    manifest, files = helper.convert(timetable)
    assert manifest["status"] == "partial"
    assert manifest["targets"]["ics"]["status"] == "generated"
    assert manifest["targets"]["wakeup"]["status"] == "unsupported"
    assert set(files) == {"schedule.ics", "review.json"}
    only, only_files = helper.convert(timetable, "ics")
    assert only["status"] == "generated" and "wakeup.csv" not in only_files


def test_repeat_export_stable_and_order_independent(timetable):
    manifest1, files1 = helper.convert(timetable)
    timetable["courses"][0]["meetings"][0]["weeks"].reverse()
    manifest2, files2 = helper.convert(timetable)
    assert manifest1 == manifest2 and files1 == files2
    timetable["courses"][0]["title"] = "改名后的课程"
    manifest3, _ = helper.convert(timetable)
    assert [item["uid"] for item in manifest1["events"]] == [item["uid"] for item in manifest3["events"]]


def test_same_name_distinct_identity_not_merged(timetable):
    other = deepcopy(timetable["courses"][0])
    other["id"] = "c2"
    other["meetings"][0]["weeks"] = [2, 4]
    timetable["courses"].append(other)
    manifest, files = helper.convert(timetable)
    assert len(manifest["events"]) == 5
    assert len(rows(files["wakeup.csv"])) == 3
    assert len({item["uid"] for item in manifest["events"]}) == 5


def test_csv_quoting_ics_escaping_and_utf8_folding(timetable):
    title = '中文,"课\\程;\n' + "长标题" * 40
    timetable["courses"][0].update(title=title, teacher="", location="")
    manifest, files = helper.convert(timetable)
    assert rows(files["wakeup.csv"])[1][0] == title
    assert rows(files["wakeup.csv"])[1][4:6] == ["无", "无"]
    raw = files["schedule.ics"]
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    unfolded = raw.decode().replace("\r\n ", "")
    assert "SUMMARY:" + helper.ics_text(title) in unfolded
    assert "\\n" in unfolded and "\\;" in unfolded and "\\," in unfolded and "\\\\" in unfolded
    assert all(item["import_verification"] == "not_performed" for item in manifest["targets"].values())


def test_cross_year_and_sunday_exact(timetable):
    timetable["calendar"]["week1_monday"] = "2026-12-28"
    timetable["courses"][0]["meetings"][0].update(weeks=[1, 2], weekday=7)
    manifest, _ = helper.convert(timetable)
    assert [event["date"] for event in manifest["events"]] == ["2027-01-03", "2027-01-10"]


def test_continuous_weeks_compress_without_reintroducing_cancelled_days(timetable):
    timetable["courses"][0]["meetings"][0]["weeks"] = [1, 2, 3, 4, 5]
    timetable["adjustments"] = [rule("cancel", date="2026-09-21")]
    _, files = helper.convert(timetable)
    assert rows(files["wakeup.csv"])[1][-1] == "1-2、4-5"


def test_empty_confirmed_timetable_is_distinct_from_failure(timetable):
    timetable["courses"] = []
    manifest, files = helper.convert(timetable)
    assert manifest["status"] == "generated"
    assert manifest["counts"]["actual_occurrences"] == 0
    assert rows(files["wakeup.csv"]) == [helper.WAKEUP_HEADER]
    assert b"BEGIN:VEVENT" not in files["schedule.ics"]


def set_value(data, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        data = data[int(part)] if isinstance(data, list) else data[part]
    if isinstance(data, list):
        data[int(parts[-1])] = value
    else:
        data[parts[-1]] = value


@pytest.mark.parametrize("path,value", [
    ("schema_version", True), ("schema_version", 2), ("semester", {}),
    ("calendar", []), ("calendar.semester", "different"), ("calendar.version", []),
    ("calendar.week1_monday", "2026-09-08"), ("calendar.week1_monday", "2026-02-30"),
    ("calendar.week1_monday", "1999-09-06"), ("calendar.week1_monday", "2026-9-7"),
    ("calendar.weeks", True), ("calendar.weeks", 0), ("calendar.weeks", 61),
    ("calendar.latest_verified", 1), ("calendar.checked_at", "2026-10-20T09:00:00"),
    ("calendar.checked_at", "bad"), ("calendar.checked_at", []),
    ("calendar.source_url", "https://example.org/calendar"),
    ("calendar.source_url", "https://stu.edu.cn.example.org/calendar"),
    ("calendar.source_url", "https://user:password@jwc.stu.edu.cn/calendar"),
    ("calendar.source_url", "https://jwc.stu.edu.cn/calendar?ticket=secret"),
    ("calendar.source_url", "https://jwc.stu.edu.cn/calendar?%74icket=secret"),
    ("calendar.source_url", "https://jwc.stu.edu.cn/calendar#token"),
    ("calendar.source_url", "file:///calendar"), ("timetable", None),
    ("timetable.complete", "true"), ("periods", None), ("periods", []),
    ("periods.0.number", True), ("periods.0.start", "8:00"), ("periods.0.end", "25:00"),
    ("periods.0.end", "07:00"), ("periods.1.start", "08:30"), ("courses", {}),
    ("courses.0.id", 12), ("courses.0.id", " "), ("courses.0.title", {"name": "bad"}),
    ("courses.0.title", "a\x00b"), ("courses.0.teacher", None), ("courses.0.location", []),
    ("courses.0.meetings", []), ("courses.0.meetings.0", "bad"),
    ("courses.0.meetings.0.id", True), ("courses.0.meetings.0.weekday", True),
    ("courses.0.meetings.0.teacher", {}), ("courses.0.meetings.0.location", None),
    ("courses.0.meetings.0.weekday", 0), ("courses.0.meetings.0.weekday", 8),
    ("courses.0.meetings.0.weeks", [1, True]), ("courses.0.meetings.0.weeks", [1, 1]),
    ("courses.0.meetings.0.weeks", [21]), ("courses.0.meetings.0.weeks", []),
    ("courses.0.meetings.0.weeks", "1-3"), ("courses.0.meetings.0.periods", [1, 3]),
    ("courses.0.meetings.0.periods", [4]), ("courses.0.meetings.0.periods", [1, 1]),
    ("pending", {}), ("pending", [None]), ("adjustments", {}),
])
def test_known_field_drift_rejected_without_echoing_values(timetable, path, value):
    set_value(timetable, path, value)
    with pytest.raises(helper.InputError) as error:
        helper.convert(timetable)
    assert "password@" not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.parametrize("field", ["courses", "meetings", "periods", "adjustments"])
def test_duplicate_identities_rejected(timetable, field):
    if field == "meetings":
        values = timetable["courses"][0]["meetings"]
    elif field == "adjustments":
        timetable["adjustments"] = [rule("cancel")]
        values = timetable["adjustments"]
    else:
        values = timetable[field]
    values.append(deepcopy(values[0]))
    with pytest.raises(helper.InputError, match="duplicate"):
        helper.convert(timetable)


def test_unknown_additive_fields_do_not_change_export(timetable):
    before = helper.convert(timetable)
    timetable["future"] = {"arbitrary": [True, "value"]}
    timetable["courses"][0]["future"] = []
    timetable["calendar"]["future"] = 1
    assert helper.convert(timetable) == before


def test_stdlib_only_cli_from_stdin_and_reject_stale_output(timetable, tmp_path):
    output = tmp_path / "export"
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--output-dir", str(output)],
                            input=json.dumps(timetable), capture_output=True, text=True,
                            cwd=tmp_path, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "generated"
    previous = {path.name: path.read_bytes() for path in output.iterdir()}
    repeat = subprocess.run([sys.executable, "-I", str(SCRIPT), "--output-dir", str(output)],
                            input="{}", capture_output=True, text=True, timeout=15)
    assert repeat.returncode == 2
    assert "must be new or empty" in repeat.stderr
    assert previous == {path.name: path.read_bytes() for path in output.iterdir()}


def test_cli_json_file_partial_and_invalid_input(timetable, tmp_path):
    timetable["adjustments"] = [rule("move", to_date="2026-09-05")]
    source = tmp_path / "input.json"
    source.write_text(json.dumps(timetable), encoding="utf-8-sig")
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--input", str(source),
                             "--output-dir", str(tmp_path / "partial")],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "partial"
    assert (tmp_path / "partial" / "schedule.ics").exists()
    invalid = subprocess.run([sys.executable, "-I", str(SCRIPT), "--output-dir", str(tmp_path / "invalid")],
                             input="not json containing private text", capture_output=True, text=True, timeout=15)
    assert invalid.returncode == 2 and "private text" not in invalid.stderr
    assert not (tmp_path / "invalid").exists()


def test_cli_utf8_stdin_and_duplicate_json_keys(timetable, tmp_path):
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--output-dir", str(tmp_path / "utf8")],
                            input=json.dumps(timetable, ensure_ascii=False).encode("utf-8"),
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    review = json.loads((tmp_path / "utf8" / "review.json").read_bytes())
    assert review["events"][0]["title"] == "合成课程"
    duplicate = json.dumps(timetable).replace('"latest_verified": true',
                                               '"latest_verified": false, "latest_verified": true')
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--output-dir", str(tmp_path / "duplicate")],
                            input=duplicate.encode(), capture_output=True, timeout=15)
    assert result.returncode == 2
    assert b"duplicate JSON key" in result.stderr
    assert not (tmp_path / "duplicate").exists()


def test_exported_skill_runs_without_package_and_matches_shared_converter(timetable, tmp_path):
    # A fresh stdlib-only interpreter ensures the ZIP is independent of the
    # editable checkout and installed application dependencies.
    environment = tmp_path / "isolated-python"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    work = tmp_path / "work"
    work.mkdir()
    probe = subprocess.run([str(python), "-I", "-c",
                            "import importlib.util; assert importlib.util.find_spec('stu_mcp') is None"],
                           cwd=work, capture_output=True, timeout=15)
    assert probe.returncode == 0, probe.stderr
    result = export_skill(Runtime(tmp_path / "runtime"), name="stu-timetable-export", apply=True)
    with zipfile.ZipFile(result["artifact"]) as archive:
        archive.extractall(work)
    script = work / "stu-timetable-export/scripts/build_timetable.py"
    # Include a normal export and one where WakeUp cannot represent a moved
    # occurrence but the ICS must still succeed.
    for index, changes in enumerate(([], [rule("move", to_date="2026-09-05")])):
        timetable["adjustments"] = changes
        manifest, expected = helper.convert(timetable)
        output = work / f"export-{index}"
        run = subprocess.run([str(python), "-I", str(script), "--output-dir", str(output)],
                             input=json.dumps(timetable, ensure_ascii=False).encode("utf-8"),
                             cwd=work, capture_output=True, timeout=15)
        assert run.returncode == (0 if manifest["status"] == "generated" else 2), run.stderr
        assert json.loads(run.stdout)["status"] == manifest["status"]
        assert {path.name: path.read_bytes() for path in output.iterdir()} == expected


@pytest.mark.parametrize("source", [SCRIPT, Path(helper.__file__)])
def test_module_has_no_third_party_or_network_imports(source):
    import ast

    imported = {node.names[0].name.split(".")[0] if isinstance(node, ast.Import) else node.module.split(".")[0]
                for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
                if isinstance(node, (ast.Import, ast.ImportFrom))}
    assert imported.issubset(sys.stdlib_module_names | {"__future__"})
    assert not imported.intersection({"socket", "http", "urllib.request", "stu_mcp", "requests", "httpx"})
