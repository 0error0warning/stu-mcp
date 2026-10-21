"""Business workflow through an injected session, without Playwright or network."""
import copy
import threading
from contextlib import contextmanager
from datetime import timedelta

import pytest

from stu_mcp.features.repair.models import campus_today
from stu_mcp.features.repair.service import RepairService
from stu_mcp.runtime import AppError


class MemorySession:
    def __init__(self, stop):
        self.stop = stop
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.request_sent = False
        self.submits = 0
        self.checks = 0
        self.prepared = False
        self.error = None
        self.current = {
            "fields": [{"key": "Detail", "label": "详细描述", "value": "合成故障"}],
            "body": {"Detail": ["合成故障"]}, "fingerprint": "synthetic",
            "submission_fingerprint": "synthetic-payload", "problems": [],
        }

    def open(self, fields):
        return {"matches": dict.fromkeys(fields, True), "missing_page_fields": []}

    def capture(self):
        return copy.deepcopy(self.current)

    def prepare_receipt(self):
        self.prepared = True

    def submit(self, capture):
        assert self.prepared and capture == self.current
        self.submits += 1
        self.request_sent = True
        if self.error:
            raise self.error
        return {"status": "submission_unknown", "request_sent": True, "submitted_by_mcp": False}

    def check(self):
        self.checks += 1
        return {"status": "submitted", "request_sent": True, "submitted_by_mcp": True,
                "receipt_fresh": True,
                "receipt": {"order_id": "20260102900001", "processing_status": "等待处理"}}

    def is_closed(self):
        return self.closed.is_set()

    def on_form(self):
        return True

    def wait(self, milliseconds):
        self.ready.set()  # Service has recorded its initial readback.
        self.stop.wait(min(milliseconds / 1000, .01))


@pytest.fixture
def workflow(monkeypatch):
    monkeypatch.setattr("stu_mcp.features.repair.adapter.direct_preflight",
                        lambda: pytest.fail("injected workflow must not touch the school"))
    sessions = []
    created = threading.Event()

    @contextmanager
    def factory(stop, update):
        session = MemorySession(stop)
        sessions.append(session)
        created.set()
        try:
            yield session
        finally:
            session.closed.set()

    service = RepairService(factory)
    draft = service.prepare(
        name="合成同学", college="工学院", building="桑浦山校区学生宿舍C栋",
        location="合成房间", phone="13800000000", title="合成故障", description="合成故障",
        visit_date=(campus_today() + timedelta(days=1)).isoformat(),
        visit_start="14:00", visit_end="17:00",
    )
    draft_id = draft["draft_id"]
    try:
        service.open(draft_id)
        assert created.wait(timeout=2) and sessions[0].ready.wait(timeout=2)
        yield service, draft_id, sessions[0]
    finally:
        service.shutdown()
        assert sessions[0].closed.wait(timeout=2)
        assert not service.threads[draft_id].is_alive()


def test_workflow_previews_confirms_once_and_recovers_read_only(workflow):
    service, draft_id, session = workflow
    review = service.review(draft_id)
    assert review["form_fields"] == session.current["fields"]
    assert session.submits == 0
    with pytest.raises(AppError) as error:
        service.submit(draft_id, review["review_id"])
    assert error.value.code == "repair_confirmation_required"
    result = service.submit(draft_id, review["review_id"], confirmed=True)
    assert result["status"] == "submission_unknown"
    assert service.submit(draft_id, review["review_id"], confirmed=True)["request_sent"]
    assert session.submits == 1
    assert service.check_submission(draft_id)["receipt_fresh"]
    assert session.checks == 1 and session.submits == 1
    service.close(draft_id)
    assert service.snapshot(draft_id)["receipt"]["processing_status"] == "等待处理"


@pytest.mark.parametrize("error", [
    RuntimeError("SYNTHETIC_PRIVATE_RESPONSE"),
    AppError("adapter_failure", "SYNTHETIC_PRIVATE_RESPONSE", "repair"),
])
def test_exception_after_sending_cannot_rearm_submission(workflow, error):
    service, draft_id, session = workflow
    review = service.review(draft_id)
    session.error = error
    result = service.submit(draft_id, review["review_id"], confirmed=True)
    assert result["status"] == "submission_unknown" and result["request_sent"]
    assert "SYNTHETIC_PRIVATE_RESPONSE" not in str(result)
    assert service.submit(draft_id, review["review_id"], confirmed=True)["request_sent"]
    assert session.submits == 1


def test_form_edit_or_close_requires_a_new_review(workflow):
    service, draft_id, session = workflow
    review = service.review(draft_id)
    session.current["fingerprint"] = "edited-after-review"
    with pytest.raises(AppError):
        service.submit(draft_id, review["review_id"], confirmed=True)
    assert session.submits == 0
    service.close(draft_id)
    with pytest.raises(AppError):
        service.submit(draft_id, review["review_id"], confirmed=True)
    assert session.submits == 0
