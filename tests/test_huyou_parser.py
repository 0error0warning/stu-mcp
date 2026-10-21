"""Synthetic provider drift; no real Huyou traffic or account data."""
from copy import deepcopy

import pytest

from stu_mcp.features.huyou import parser
from stu_mcp.runtime import AppError


def post(**fields):
    return {"feedId": "101", "content": "合成公开帖子", "status": 1, **fields}


def comment(**fields):
    return {"commentId": "501", "content": "合成评论", "status": 1, "replyCount": 0, **fields}


@pytest.mark.parametrize("field,value", [
    ("feedId", True), ("feedId", {}), ("feedId", []), ("feedId", "0"),
    ("feedId", ""), ("feedId", 101.0), ("content", {}), ("content", []),
    ("content", None), ("content", True), ("title", {}), ("userName", []),
    ("circle", []), ("circle", "renamed"), ("circleId", True),
    ("circle", {"circleId": {}}), ("circle", {"circleName": []}),
    ("anonymous", "false"), ("anonymous", {}), ("contentIsSub", []),
    ("status", False), ("ownerHidden", {}), ("feedAttr", True),
    ("commentCount", False), ("commentCount", -1), ("commentCount", "1.2"),
    ("commentCount", {}), ("score", []), ("score", 1791158400000.5),
    ("picFeed", []), ("picFeed", {"pics": {}}), ("picFeed", {"pics": [True]}),
])
def test_post_field_drift_is_schema_error_without_payload(field, value):
    row = post(**{field: value}, private="SYNTHETIC_PROVIDER_SECRET")
    with pytest.raises(AppError) as error:
        parser.post_record(row, detail=True)
    assert error.value.code == "schema_changed"
    assert "SYNTHETIC_PROVIDER_SECRET" not in str(error.value)


@pytest.mark.parametrize("field,value", [
    ("commentId", True), ("commentId", 0), ("commentId", []),
    ("content", {}), ("content", None), ("replyCount", False),
    ("replyCount", []), ("replyCount", -1), ("replyCommentId", {}),
    ("replyCommentId", 1.5), ("isAuthor", "true"), ("likeCount", {}),
])
def test_comment_field_drift_is_schema_error(field, value):
    with pytest.raises(AppError) as error:
        parser.comment_record(comment(**{field: value}))
    assert error.value.code == "schema_changed"


def test_explicit_cards_hidden_and_deleted_differ_from_missing_post_identity():
    assert parser.post_record({"feedAttr": 8, "userId": "private"}) is None
    assert parser.post_record({"feedId": "101", "status": 0}) is None
    assert parser.post_record({"feedId": "101", "ownerHidden": True}) is None
    assert parser.comment_record({"status": 0}) is None
    with pytest.raises(AppError, match="身份"):
        parser.post_record({"userId": "private"})


@pytest.mark.parametrize("decoder,rows", [
    (lambda rows: parser.search_records(rows, "", "合成"), [post(), post(content="冲突")]),
    (parser.comment_records, [comment(), comment(content="冲突")]),
    (lambda rows: parser.circle_records({"circleList": rows, "hasMore": False}),
     [{"circleId": "101"}, {"circleId": "101"}]),
])
def test_duplicate_identity_is_not_silently_merged(decoder, rows):
    with pytest.raises(AppError, match="重复"):
        decoder(rows)


@pytest.mark.parametrize("info", [
    {}, {"hasMore": "false"}, {"hasMore": []}, {"hasMore": 2},
    {"hasMore": True}, {"hasMore": True, "pageIndex": True},
    {"hasMore": True, "pageIndex": 1.5}, {"hasMore": True, "pageIndex": -1},
])
def test_numbered_pagination_drift(info):
    with pytest.raises(AppError) as error:
        parser.page_rows({"feedList": [], "pageInfo": info}, "feedList", numbered=True)
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("info", [
    {"hasMore": True}, {"hasMore": True, "score": []},
    {"hasMore": True, "score": float("inf")}, {"hasMore": False, "totalCount": False},
    {"hasMore": False, "totalCount": -1}, {"hasMore": False, "totalCount": {}},
])
def test_cursor_pagination_drift(info):
    with pytest.raises(AppError) as error:
        parser.page_rows({"list": [], "pageInfo": info}, "list")
    assert error.value.code == "schema_changed"


@pytest.mark.parametrize("value", [None, {}, {"renamed": []}, [], True, "changed", {"list": None},
                                    {"hasMore": "false"}, {"list": [comment(), comment()]}])
def test_embedded_reply_drift_cannot_prove_complete(value):
    with pytest.raises(AppError) as error:
        parser.reply_preview(comment(replies=value), "501", 0)
    assert error.value.code == "schema_changed"


def test_missing_reply_count_only_blocks_root_completeness():
    row = {"commentId": "502", "content": "合成子回复"}
    assert parser.comment_record(row, "501")["reply_count"] == 0
    with pytest.raises(AppError, match="回复数量"):
        parser.reply_preview(row, "502", 0)


@pytest.mark.parametrize("status", [None, True, False, {}, [], 100000.9, "100000.9", "1" * 5000])
def test_envelope_status_never_truncates_or_stringifies_invalid_type(status):
    with pytest.raises(AppError) as error:
        parser.response_data({"status": status, "data": {}, "message": "SYNTHETIC_PROVIDER_SECRET"})
    assert error.value.code == "schema_changed"
    assert "SYNTHETIC_PROVIDER_SECRET" not in str(error.value)


def test_optional_extra_fields_and_normal_empty_content_remain_compatible():
    row = post(content="", future={"anything": []}, picFeed={"pics": ["https://[", "https://example.org/a"]})
    before = deepcopy(row)
    record = parser.post_record(row)
    assert record["body"] == "" and record["title"] == "狐友帖子 101"
    assert record["images"] == ["https://example.org/a"]
    assert row == before and "future" not in record
    assert parser.page_rows({"list": [], "pageInfo": {"hasMore": False}}, "list")[0] == []
