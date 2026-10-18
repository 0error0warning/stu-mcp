import copy
import json
from pathlib import Path

import httpx
import pytest

from stu_mcp.network import CampusHTTP
from stu_mcp.runtime import AppError
from stu_mcp.yuketang_readiness import font_bytes, inspect_exercise, read_homework, render_inspection


def exercise():
    return {"exercise_id": 30, "font": None, "problems": [
        {"problem_id": 40, "content": {"ProblemID": 40, "ProblemType": 1, "Body": "合成问题：一加一等于几？",
         "Options": [{"key": "B", "value": "二"}, {"key": "A", "value": "三"}],
         "Answer": "SYNTHETIC_HIDDEN_ANSWER", "Remark": "SYNTHETIC_HIDDEN_EXPLANATION"},
         "user": {"answer": "SYNTHETIC_USER_ANSWER"}}]}


def item():
    return {"source": "yuketang", "kind": "task", "activity_type": 19, "course_id": "10", "leaf_id": "20"}


def leaf():
    return {"success": True, "data": {"leaf_type": 6, "is_group": False, "is_open_type": False,
            "is_locked": False, "is_deleted": False, "sku_id": 50, "content_info": {"leaf_type_id": 30}}}


def test_response_order_and_keys_preserved_no_answers_or_fake_readiness():
    inspected = inspect_exercise(exercise())
    q = inspected.report["questions"][0]
    assert [o["key"] for o in q["options"]] == ["B", "A"]
    assert [o["text"] for o in q["options"]] == ["二", "三"]
    assert q["body"]["text"].endswith("等于几？") and q["structure_complete"]
    assert q["semantic_completeness"] == "not_verified"
    assert inspected.report["answerability"] == "not_assessed"
    assert "SYNTHETIC_" not in json.dumps(inspected.report) + inspected.markup


@pytest.mark.parametrize("options,issue", [([], "missing_options"), (None, "invalid_options"),
    ([{"value": "一"}, {"key": "B", "value": "二"}], "missing_option_key"),
    ([{"key": "A", "value": "一"}, {"key": "A", "value": "二"}], "duplicate_option_key"),
    ([{"key": "A", "value": ""}, {"key": "B", "value": "二"}], "empty_content")])
def test_incomplete_options_never_fabricated(options, issue):
    data = exercise()
    data["problems"][0]["content"]["Options"] = options
    report = inspect_exercise(data).report
    assert issue in report["issues"] and not report["structure_complete"]


def test_subjective_empty_options_are_valid_but_textbook_reference_needs_context():
    data = exercise()
    data["problems"][0]["content"].update(ProblemType=5, Options=[], Body="教材 P27, 1、2 题")
    report = inspect_exercise(data).report
    assert report["questions"][0]["options_expected"] is False
    assert "missing_options" not in report["issues"]
    assert report["structure_complete"] and report["status"] == "incomplete"
    assert "possible_external_material" in report["issues"]


def test_obfuscated_font_never_exposed_as_readable_chinese_and_stays_with_snapshot():
    data = exercise()
    data["font"] = "https://fe-static-yuketang.yuketang.cn/fe_font/product/exam_font_first.ttf"
    data["problems"][0]["content"]["Body"] = '<span class="xuetangx-com-encrypted-font">假汉字</span>P28'
    first = inspect_exercise(data)
    data["font"] = data["font"].replace("first", "second")
    second = inspect_exercise(data)
    assert first.font_url != second.font_url
    assert first.report["encrypted_font"] and "假汉字" not in json.dumps(first.report, ensure_ascii=False)
    assert "假汉字" in first.markup  # Retained only for the paired-font renderer, never reported as decoded text.
    data["font"] = None
    assert "missing_font" in inspect_exercise(data).report["issues"]


def test_question_images_math_and_scripts_require_review_and_cannot_execute():
    data = exercise()
    data["problems"][0]["content"]["Body"] = ('<p onclick="bad()">$x^2$</p><script>steal()</script>'
        '<img src="https://evil.example/track" onerror="bad()"><iframe src="file:///secret"></iframe>')
    inspected = inspect_exercise(data)
    assert {"images_not_verified", "math_or_media_requires_review", "unsupported_markup"} <= set(inspected.report["issues"])
    assert not any(t in inspected.markup for t in ["onclick", "onerror", "evil.example", "file:", "steal", "<script"])
    assert inspected.report["questions"][0]["body"]["image_count"] == 1


def test_unknown_type_duplicate_id_and_unparseable_list_do_not_look_empty():
    data = exercise()
    data["problems"].append(copy.deepcopy(data["problems"][0]))
    data["problems"][1]["content"]["ProblemType"] = 99
    issues = inspect_exercise(data).report["issues"]
    assert {"duplicate_problem_id", "question_type_not_verified"} <= set(issues)
    for bad in ({}, {"problems": None}, {"problems": [{}]}):
        with pytest.raises(AppError):
            inspect_exercise(bad)
    assert inspect_exercise({"problems": []}).report["status"] == "incomplete"


def test_only_two_gets_with_verified_leaf_to_exercise_mapping():
    sent = []
    def handler(request):
        sent.append(request)
        if "/leaf_info/" in request.url.path:
            return httpx.Response(200, json=leaf())
        return httpx.Response(200, json={"success": True, "data": exercise()})
    with CampusHTTP("yuketang", transport=httpx.MockTransport(handler)) as http:
        data = read_homework(http, item())
    assert data["exercise_id"] == 30
    assert [r.method for r in sent] == ["GET", "GET"]
    assert sent[0].url.path.endswith("/10/20/") and sent[1].url.path.endswith("/30/50/")
    assert all(r.url.params["classroom_id"] == "10" for r in sent)


@pytest.mark.parametrize("change", [{"activity_type": 3}, {"kind": "resource"}, {"source": "mystu"},
                                   {"course_id": "1/../../secret"}, {"leaf_id": None}])
def test_invalid_or_exam_targets_never_issue_requests(change):
    with (CampusHTTP("yuketang", transport=httpx.MockTransport(lambda _: pytest.fail("unexpected request"))) as http,
          pytest.raises(AppError)):
        read_homework(http, item() | change)


@pytest.mark.parametrize("change,code", [({"is_locked": True}, "resource_locked"),
    ({"is_deleted": True}, "resource_locked"), ({"leaf_type": 5}, "unsupported_activity"),
    ({"is_group": True}, "unsupported_activity"), ({"is_open_type": True}, "unsupported_activity"),
    ({"content_info": {}}, "schema_changed")])
def test_locked_or_unsupported_leaf_does_not_fetch_questions(change, code):
    response = leaf()
    response["data"].update(change)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=response)
    with CampusHTTP("yuketang", transport=httpx.MockTransport(handler)) as http, pytest.raises(AppError) as error:
        read_homework(http, item())
    assert error.value.code == code and len(sent) == 1


@pytest.mark.parametrize("url", ["https://evil.example/a.ttf", "http://fe-static-yuketang.yuketang.cn/a.ttf",
                               "https://fe-static-yuketang.yuketang.cn/fe_font/product/exam_font_x.ttf?token=secret"])
def test_font_fetch_is_allowlisted_and_never_contains_account_session(monkeypatch, url):
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("must reject before network"))
    with pytest.raises(AppError) as error:
        font_bytes(url)
    assert error.value.code == "media_unavailable" and "secret" not in str(error.value)


def test_renderer_refuses_missing_font_before_browser():
    data = exercise()
    data["problems"][0]["content"]["Body"] = '<span class="xuetangx-com-encrypted-font">测试</span>'
    with pytest.raises(AppError) as error:
        render_inspection(inspect_exercise(data))
    assert error.value.code == "media_unavailable"


def test_shared_instructions_preserved_with_same_font_and_no_extra_fields():
    data = exercise()
    data["description"] = '<span class="xuetangx-com-encrypted-font">合成文字</span>'
    inspected = inspect_exercise(data)
    assert "作业说明" in inspected.markup
    assert inspected.report["description"]["encrypted_font"]
    assert "missing_font" in inspected.report["issues"] and not inspected.report["structure_complete"]


@pytest.mark.parametrize("status,content", [(302, b""), (200, b"<html>login</html>"),
                                          (200, b"\0\1\0\0" + b"0" * (4 * 1024 * 1024))],
                         ids=["redirect", "not-a-font", "oversize"])
def test_font_loading_rejects_redirect_non_font_and_oversize(monkeypatch, status, content):
    original = httpx.Client
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(status, content=content, headers={"Location": "https://evil.example/"})
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "Client", client)
    with pytest.raises(AppError) as error:
        font_bytes("https://fe-static-yuketang.yuketang.cn/fe_font/product/exam_font_synthetic.ttf")
    assert error.value.code == "media_unavailable" and len(seen) == 1
    assert "cookie" not in seen[0].headers and "authorization" not in seen[0].headers


def test_real_offline_renderer_uses_sanitized_question_only(monkeypatch):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip("Chromium not installed; browser CI exercises the renderer")
    monkeypatch.setattr(httpx, "Client", lambda **_: pytest.fail("synthetic renderer must not fetch media"))
    data = exercise()
    data["problems"][0]["content"]["Body"] += '<img src="https://evil.example/track"><script>fetch("https://evil.example")</script>'
    inspected = inspect_exercise(data)
    before = copy.deepcopy(inspected.report)
    png = render_inspection(inspected)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert inspected.report == before and inspected.report["status"] == "incomplete"
