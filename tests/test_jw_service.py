"""Academic query and cache boundaries, using synthetic pages and an injected HTTP client."""
from copy import deepcopy
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from stu_mcp import collectors
from stu_mcp.features.jw.schema import JW_EXAM_LIST_URL, JW_EXAM_QUERY_URL, JW_GRADE_URL
from stu_mcp.features.jw.service import jw
from stu_mcp.runtime import AppError

FIXTURES = Path(__file__).parent / "fixtures"
TERMS = ('<select name="xnxqid"><option value="2026-2027-1">合成学期一</option>'
         '<option value="2025-2026-3" selected>合成学期二</option></select>')


@pytest.fixture
def school(app, session, monkeypatch):
    state = {
        "grades": (FIXTURES / "grades-current.html").read_text(encoding="utf-8"),
        "exams": (FIXTURES / "exams-current.html").read_text(encoding="utf-8"),
        "terms": TERMS, "requests": [], "contexts": [], "http_form": False,
    }
    saved = deepcopy(session)
    saved["cookies"][0]["domain"] = "jw.stu.edu.cn"
    app.vault.save("jw", saved)

    class SyntheticHTTP:
        def __init__(self, source, _saved, **kwargs):
            assert source == "jw"
            self.used_legacy_http = False
            state["contexts"].append(("open", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            state["contexts"].append(("close", {}))

        def request(self, url, *, data):
            state["requests"].append(("POST", url, data.copy()))
            assert url in {JW_GRADE_URL, JW_EXAM_LIST_URL}
            value = state["grades" if url == JW_GRADE_URL else "exams"]
            if isinstance(value, Exception):
                raise value
            from types import SimpleNamespace
            return SimpleNamespace(text=value)

        def text(self, url):
            state["requests"].append(("GET", url, None))
            assert url == JW_EXAM_QUERY_URL
            self.used_legacy_http |= state["http_form"]
            if isinstance(state["terms"], Exception):
                raise state["terms"]
            return state["terms"]

    monkeypatch.setattr(collectors, "CampusHTTP", SyntheticHTTP)
    return state, SyntheticHTTP


def duplicated_column(html, label):
    soup = BeautifulSoup(html, "html.parser")
    header = soup.table.find("tr")
    labels = header.find_all(["th", "td"], recursive=False)
    index = next(i for i, cell in enumerate(labels) if cell.get_text(strip=True) == label)
    for row in soup.table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        row.append(deepcopy(cells[index]))
    return str(soup)


def header_only(html):
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.table.find_all("tr")[1:]:
        row.decompose()
    return str(soup)


@pytest.mark.parametrize("changed", ["duplicate_column", "multiple_tables", "unknown_page"])
def test_ambiguous_grade_refresh_is_atomic_and_keeps_existing_records(app, school, changed):
    state, _ = school
    app.refresh("jw")
    before = {item["id"]: item for item in app.query("grade", source="jw")["items"]}
    state["requests"].clear()
    state["grades"] = (duplicated_column(state["grades"], "成绩") if changed == "duplicate_column" else
                       state["grades"] * 2 if changed == "multiple_tables" else "<h1>合成未知页面</h1>")
    with pytest.raises(AppError) as error:
        app.refresh("jw")
    assert error.value.code == "schema_changed"
    assert {item["id"]: item for item in app.query("grade", source="jw")["items"]} == before
    assert len(state["requests"]) == 1 and state["requests"][0][1] == JW_GRADE_URL
    assert state["contexts"][-1] == ("close", {})


@pytest.mark.parametrize("changed", ["duplicate_column", "multiple_tables", "duplicate_terms", "login"])
def test_exam_ambiguity_is_partial_and_keeps_prior_exam_details(app, school, changed):
    state, _ = school
    app.refresh("jw")
    previous = {item["id"]: item for item in app.query("exam", source="jw")["items"]}
    state["requests"].clear()
    if changed == "duplicate_column":
        state["exams"] = duplicated_column(state["exams"], "考试时间")
    elif changed == "multiple_tables":
        state["exams"] *= 2
    elif changed == "duplicate_terms":
        state["terms"] *= 2
    else:
        state["terms"] = '<title>统一身份认证</title><input type="password">'
    result = app.refresh("jw")
    assert result["status"] == "partial" and result["saved"] == 3
    assert result["errors"][0]["part"] == "考试安排"
    assert result["errors"][0]["status"] == ("login_expired" if changed == "login" else "schema_changed")
    assert app.query("grade", source="jw")["total_count"] == 3
    assert {item["id"]: item for item in app.query("exam", source="jw")["items"]} == previous
    if changed in {"duplicate_terms", "login"}:
        assert not any(url == JW_EXAM_LIST_URL for _, url, _ in state["requests"])
    assert state["contexts"][-1] == ("close", {})


def test_verified_empty_tables_do_not_delete_jw_history(app, school):
    state, _ = school
    app.refresh("jw")
    before = {kind: app.query(kind, source="jw")["total_count"] for kind in ("grade", "exam")}
    state["grades"], state["exams"] = header_only(state["grades"]), header_only(state["exams"])
    result = app.refresh("jw")
    assert result["saved"] == 0 and result["status"] == "partial"  # Existing bounded-source semantics.
    assert result["errors"] == []
    assert result["coverage"]["grade_rows_read"] == result["coverage"]["exam_rows_read"] == 0
    assert {kind: app.query(kind, source="jw")["total_count"] for kind in before} == before


@pytest.mark.parametrize("compat", [False, True])
def test_adapter_keeps_https_query_shapes_and_one_context(app, school, compat):
    state, factory = school
    app.runtime.save_preferences({"jw_http_compat": compat})
    result = jw(app.vault, 1, "2026-2027-1", http_factory=factory)
    assert state["contexts"] == [("open", {"allow_legacy_http": compat}), ("close", {})]
    assert state["requests"] == [
        ("POST", JW_GRADE_URL, {"kksj": "2026-2027-1", "kcmc": "", "kcxz": "", "kspage": "1", "jspage": "200"}),
        ("POST", JW_EXAM_LIST_URL, {"xnxqid": "2026-2027-1", "xqlb": "", "xqlbmc": ""}),
    ]
    assert all(url.startswith("https://jw.stu.edu.cn/") for _, url, _ in state["requests"])
    assert len([item for item in result.items if item["kind"] == "grade"]) == 2
    assert len([item for item in result.items if item["kind"] == "exam"]) == 1
    assert result.coverage == {"grade_scope": "2026-2027-1", "max_grade_rows": 200,
                               "exam_semester": "2026-2027-1", "transport": "https", "login_entry": "jwglxt",
                               "grade_rows_read": 3, "exam_rows_read": 2}
    assert result.private is True and result.sync is None


def test_school_term_is_used_without_guessing_and_reports_form_transport(app, school):
    state, factory = school
    app.runtime.save_preferences({"jw_http_compat": True})
    state["http_form"] = True
    result = jw(app.vault, 20, "", http_factory=factory)
    assert [method for method, _, _ in state["requests"]] == ["POST", "GET", "POST"]
    assert state["requests"][-1][2]["xnxqid"] == "2025-2026-3"
    assert result.coverage["exam_semester"] == "2025-2026-3"
    assert result.coverage["transport"] == "school_legacy_http"


def test_unrelated_preference_and_other_sources_are_untouched(app, school):
    state, _ = school
    before = app.runtime.preferences()
    app.refresh("jw", semester="2026-2027-1")
    assert app.runtime.preferences() == before
    assert {source["source"] for source in app.store.freshness()} == {"jw"}
    assert state["contexts"] == [("open", {"allow_legacy_http": False}), ("close", {})]
