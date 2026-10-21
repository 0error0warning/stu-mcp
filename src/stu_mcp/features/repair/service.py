"""In-memory repair workflow; depends on a session port, not Playwright or DOM."""
from __future__ import annotations

import copy
import html
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError
from queue import Empty, Queue

from ...runtime import AppError
from .models import ACTIVE, RepairSession, Review, SessionFactory, validate_fields
from .schema import BUILDINGS, FIELDS, OPTIONAL, REPAIR_FORM, REPAIR_HOME, VERIFIED_ON

REVIEW_SECONDS = 300

def review_result(review: dict) -> dict:
    def escaped(value):
        return html.escape(value or "（未填写）").replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
    lines = ["请核对以下报修单，确认后才会向学校提交。", "", "接收方：汕头大学学生社区网上报修系统（repair.stu.edu.cn）。",
             "", "| 项目 | 实际填写内容 |", "| --- | --- |"]
    lines += [f'| {escaped(f["label"])} | {escaped(f["value"])} |' for f in review["capture"]["fields"]]
    lines += ["", "提交将发送上述姓名、电话、宿舍地址及故障信息，用于联系和安排维修。",
              "请明确回复是否确认提交；未确认或要求修改时不提交。"]
    return {"ok": True, "status": "awaiting_confirmation", "review_id": review["review_id"],
            "expires_at": review["expires_at"], "form_fields": copy.deepcopy(review["capture"]["fields"]),
            "preview_markdown": "\n".join(lines), "requires_user_confirmation": True,
            "destination": "https://repair.stu.edu.cn/", "submitted_by_mcp": False}

def check_review(review: dict | None, review_id: str, capture: dict) -> None:
    if not review or review["review_id"] != review_id or time.time() >= review["expires_at"]:
        raise AppError("repair_confirmation_expired", "本次表单确认已失效，请重新展示预览并等待用户确认。", "repair")
    if capture["problems"] or capture["fingerprint"] != review["capture"]["fingerprint"]:
        raise AppError("repair_form_changed", "表单内容已改变，原确认不可使用；请重新展示并确认。", "repair")

class RepairService:
    """One owned form session at a time; bounded in-memory drafts, no hidden daemon."""
    def __init__(self, adapter_factory: SessionFactory):
        self.adapter_factory = adapter_factory
        self.lock = threading.RLock()
        self.drafts: dict[str, dict] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.stops: dict[str, threading.Event] = {}
        self.commands: dict[str, Queue] = {}
        self.reviews: dict[str, Review] = {}
        self.sent_fingerprints: set[str] = set()

    def prepare(self, draft_id: str = "", **updates) -> dict:
        with self.lock:
            if set(updates) - (set(FIELDS) | OPTIONAL | {"campus"}):
                raise AppError("invalid_repair_fields", "报修只接受声明的业务字段，不接收凭据或任意网址。", "repair")
            if any(not isinstance(v, str) or len(v) > (800 if k == "description" else 200)
                   for k, v in updates.items()):
                raise AppError("invalid_repair_fields", "报修字段必须为有界文字，详细描述最多800字。", "repair")
            if draft_id:
                draft = self._get(draft_id)
                if draft.get("request_sent"):
                    raise AppError("repair_already_sent", "此草稿已发出提交请求，请先核对学校单据，不能重复发送。", "repair")
                if draft["status"] in ACTIVE or (draft_id in self.threads and self.threads[draft_id].is_alive()):
                    raise AppError("repair_window_open", "请先关闭此草稿的演练窗口，再更新并重新打开。", "repair")
            else:
                if len(self.drafts) >= 20:
                    removable = next((k for k, v in self.drafts.items() if v["status"] == "closed"
                                      and not (k in self.threads and self.threads[k].is_alive())), None)
                    if not removable:
                        raise AppError("repair_draft_limit", "本进程最多保留20份草稿；请关闭不再需要的草稿。", "repair")
                    self.drafts.pop(removable)
                    self.threads.pop(removable, None)
                    self.stops.pop(removable, None)
                    self.commands.pop(removable, None)
                    self.reviews.pop(removable, None)
                draft_id = uuid.uuid4().hex
                draft = {"draft_id": draft_id, "fields": {"campus": "桑浦山"}}
            fields = draft["fields"] | {k: v.strip() for k, v in updates.items()}
            problems = validate_fields(fields)
            draft.update(fields=fields, status="needs_information" if problems else "draft_ready",
                         problems=problems, checked_at=None, field_matches={}, missing_page_fields=[], error=None,
                         submitted_by_mcp=False, request_sent=False, review_id=None, review_expires_at=None,
                         message="先填写、展示实际表单并等待用户明确确认；未确认不提交。")
            self.reviews.pop(draft_id, None)
            self.drafts[draft_id] = draft
            return self.snapshot(draft_id)

    def _get(self, draft_id: str) -> dict:
        if draft_id not in self.drafts:
            raise AppError("repair_draft_not_found", "草稿不存在或所属 MCP 进程已退出；请重新准备。", "repair")
        return self.drafts[draft_id]

    def _update(self, draft_id: str, **values) -> None:
        with self.lock:
            self._get(draft_id).update(values)

    def snapshot(self, draft_id: str) -> dict:
        with self.lock:
            draft = copy.deepcopy(self._get(draft_id))
        fields = draft.pop("fields")
        phone = fields.get("phone", "")
        preview = fields | {"phone": phone[:3] + "****" + phone[-4:] if len(phone) >= 8 else "已提供" if phone else ""}
        return {"ok": True, **draft, "preview": preview, "system": "sangpushan_dorm",
                "entry_url": REPAIR_HOME, "form_url": REPAIR_FORM, "form_verified_on": VERIFIED_ON,
                "building_options": list(BUILDINGS), "submission_supported": True, "confirmation_required": True,
                "storage": "process_memory_only", "login_session_saved": draft.get("login_session_saved", False),
                "message": draft.get("message", "先填写、展示实际表单并等待用户明确确认；未确认不提交。")}

    def open(self, draft_id: str) -> dict:
        with self.lock:
            draft = self._get(draft_id)
            if draft.get("request_sent"):
                return self.snapshot(draft_id)
            if draft_id in self.threads and self.threads[draft_id].is_alive():
                return self.snapshot(draft_id)
            if any(t.is_alive() for t in self.threads.values()):
                raise AppError("repair_window_open", "已有报修演练窗口，请先关闭它。", "repair")
            problems = validate_fields(draft["fields"])
            if problems:
                draft.update(status="needs_information", problems=problems)
                return self.snapshot(draft_id)
            draft.update(status="starting", checked_at=None, error=None, field_matches={}, missing_page_fields=[],
                         message="正在打开并填写学校表单；正式提交须另行展示预览和确认。")
            stop = self.stops[draft_id] = threading.Event()
            self.commands[draft_id] = Queue()
            self.reviews.pop(draft_id, None)
            draft.update(review_id=None, review_expires_at=None, window_status="open")
            fields = copy.deepcopy(draft["fields"])
            worker = threading.Thread(target=self._run, args=(draft_id, fields, stop), daemon=True,
                                      name="stu-repair-preview")
            self.threads[draft_id] = worker
            worker.start()
            return self.snapshot(draft_id)

    def review(self, draft_id: str) -> dict:
        return self._command(draft_id, "review", {})

    def submit(self, draft_id: str, review_id: str, *, confirmed: bool = False) -> dict:
        if confirmed is not True:
            raise AppError("repair_confirmation_required", "请先展示完整预览，等待用户明确确认提交；当前未提交。", "repair")
        return self._command(draft_id, "submit", {"review_id": review_id})

    def check_submission(self, draft_id: str) -> dict:
        return self._command(draft_id, "check", {})

    def _command(self, draft_id: str, operation: str, values: dict) -> dict:
        with self.lock:
            draft = self._get(draft_id)
            if draft["status"] == "submitting" or (draft.get("request_sent") and operation != "check"):
                return self.snapshot(draft_id)
            if operation == "check" and not draft.get("request_sent"):
                raise AppError("repair_not_submitted", "此草稿尚未发出提交请求，无需查询提交结果。", "repair")
            if (draft_id not in self.threads or not self.threads[draft_id].is_alive() or
                    draft_id not in self.commands or self.stops[draft_id].is_set()):
                raise AppError("repair_window_required", "请先打开并填写学校表单，再生成提交预览。", "repair")
            if draft["status"] in {"starting", "preparing_browser", "waiting_for_login", "opening_form", "filling"}:
                raise AppError("repair_not_ready", "学校表单还未填写完成，请稍后读取状态。", "repair")
            future = Future()
            self.commands[draft_id].put((operation, values, future))
        try:
            return future.result(timeout=25)
        except TimeoutError:
            if future.cancel():
                raise AppError("repair_command_timeout", "本次操作尚未执行，已取消；请检查学校窗口后重试。", "repair") from None
            # A running confirmed request may already have reached school; never retry it here.
            return self.snapshot(draft_id)

    def _process_command(self, draft_id: str, session: RepairSession) -> None:
        try:
            operation, values, future = self.commands[draft_id].get_nowait()
        except Empty:
            return
        if not future.set_running_or_notify_cancel():
            return
        capture = None
        try:
            if self.stops[draft_id].is_set():
                raise AppError("repair_window_required", "报修窗口正在关闭，本次未执行。", "repair")
            if operation == "check":
                if not self.drafts[draft_id].get("request_sent"):
                    raise AppError("repair_not_submitted", "此草稿尚未提交。", "repair")
                result = session.check()
                self._update(draft_id, **result)
                future.set_result(self.snapshot(draft_id))
                return
            if self.drafts[draft_id].get("request_sent"):
                future.set_result(self.snapshot(draft_id))
                return
            capture = session.capture()
            if operation == "review":
                if capture["problems"]:
                    future.set_result({"ok": False, "status": "repair_incomplete_form",
                                       "problems": capture["problems"], "submitted_by_mcp": False,
                                       "message": "学校表单仍有缺失或无效必填项，请先在窗口补齐。"})
                    return
                self.reviews.pop(draft_id, None)
                self._update(draft_id, status="filled_unsubmitted", review_id=None, review_expires_at=None)
                session.prepare_receipt()
                review = {"review_id": uuid.uuid4().hex, "expires_at": time.time() + REVIEW_SECONDS,
                          "capture": capture}
                with self.lock:
                    self.reviews[draft_id] = review
                    self._update(draft_id, status="awaiting_confirmation", review_id=review["review_id"],
                                 review_expires_at=review["expires_at"], message="请展示完整预览，等待用户明确确认后提交。")
                future.set_result(review_result(review) | {"draft_id": draft_id})
            else:
                review = self.reviews.get(draft_id)
                check_review(review, values["review_id"], capture)
                if self.stops[draft_id].is_set():
                    raise AppError("repair_window_required", "窗口已关闭，未执行提交。", "repair")
                fingerprint = capture.get("submission_fingerprint", capture["fingerprint"])
                if fingerprint in self.sent_fingerprints:
                    raise AppError("repair_already_sent", "相同表单已发出过请求，请先核对学校单据，不能重复发送。", "repair")
                self.reviews.pop(draft_id, None)
                self._update(draft_id, status="submitting", review_id=None, review_expires_at=None,
                             message="用户已确认，正在尝试发送一次报修请求。")
                result = session.submit(capture)
                if result["request_sent"]:
                    self.sent_fingerprints.add(fingerprint)
                self._update(draft_id, **result)
                future.set_result(self.snapshot(draft_id))
        except Exception as exc:
            if operation == "submit" and session.request_sent:
                if capture:
                    self.sent_fingerprints.add(capture.get("submission_fingerprint", capture["fingerprint"]))
                self._update(draft_id, status="submission_unknown", request_sent=True, submitted_by_mcp=False,
                             message="已发送一次请求但未确认回执；请先检查学校单据，不能重复提交。")
                future.set_result(self.snapshot(draft_id))
            elif isinstance(exc, AppError):
                future.set_exception(exc)
            else:
                future.set_exception(AppError("repair_review_failed", "学校表单未能核对，请检查窗口；未输出个人页面或认证信息。", "repair"))

    def _run(self, draft_id: str, fields: dict, stop: threading.Event) -> None:
        try:
            with self.adapter_factory(stop, lambda **values: self._update(draft_id, **values)) as session:
                if stop.is_set():
                    return
                readback = session.open(fields)
                if readback is None:
                    return
                self._record_readback(draft_id, readback)
                # Submission is reachable only through a reviewed, confirmed worker command.
                deadline = time.monotonic() + 1800
                next_review_check = 0.0
                while not stop.is_set() and not session.is_closed() and time.monotonic() < deadline:
                    session.wait(100)
                    self._process_command(draft_id, session)
                    if self.drafts[draft_id].get("request_sent"):
                        continue
                    if self.drafts[draft_id]["status"] == "submission_not_sent":
                        continue
                    if not session.on_form():
                        self.reviews.pop(draft_id, None)
                        self._update(draft_id, status="form_changed", checked_at=time.time(), field_matches={},
                                     review_id=None, review_expires_at=None)
                        continue
                    review = self.reviews.get(draft_id)
                    if review:
                        if time.monotonic() < next_review_check:
                            continue
                        next_review_check = time.monotonic() + 1
                        current = session.capture()
                        if time.time() >= review["expires_at"] or current["fingerprint"] != review["capture"]["fingerprint"]:
                            expired = time.time() >= review["expires_at"]
                            self.reviews.pop(draft_id, None)
                            self._update(draft_id, status="confirmation_expired" if expired else "confirmation_invalidated",
                                         review_id=None, review_expires_at=None)
                        continue
                    if self.drafts[draft_id]["status"] in {"confirmation_invalidated", "confirmation_expired"}:
                        continue
                    # No repeated multi-field polling while idle. Review/submit always
                    # read the actual form again; cached readback is explicitly timestamped.
                if not self.drafts[draft_id].get("request_sent"):
                    self._update(draft_id, status="closed" if stop.is_set() or session.is_closed() else "preview_expired",
                                 field_matches={})
                self._update(draft_id, window_status="closed")
        except AppError as exc:
            if self.drafts[draft_id].get("request_sent"):
                self._update(draft_id, window_status="closed", error=exc.result())
            else:
                self._update(draft_id, status=exc.code, error=exc.result(), field_matches={})
        except Exception:
            # Transport exceptions can contain URLs or entered values.
            error = {"status": "repair_session_error", "message": "报修会话已关闭、页面无法访问或字段变化；"
                     "未输出个人页面和认证信息。"}
            if self.drafts[draft_id].get("request_sent"):
                self._update(draft_id, window_status="closed", error=error)
            else:
                self._update(draft_id, status="repair_session_error", field_matches={}, error=error)
        finally:
            self.reviews.pop(draft_id, None)
            if stop.is_set():
                self._update(draft_id, window_status="closed", review_id=None, review_expires_at=None)
                if not self.drafts[draft_id].get("request_sent"):
                    self._update(draft_id, status="closed", field_matches={})

    def _record_readback(self, draft_id: str, result: dict) -> None:
        matched = result["matches"]
        with self.lock:
            if draft_id in self.stops and self.stops[draft_id].is_set():
                return
            self._update(draft_id, status="needs_manual_fields" if result["missing_page_fields"] else
                         "form_changed" if not all(matched.values()) else "filled_unsubmitted",
                         checked_at=time.time(), field_matches=matched, missing_page_fields=result["missing_page_fields"])

    def close(self, draft_id: str) -> dict:
        with self.lock:
            draft = self._get(draft_id)
            stop = self.stops.get(draft_id)
            self.reviews.pop(draft_id, None)
            draft.update(review_id=None, review_expires_at=None)
            if stop:
                stop.set()
            worker = self.threads.get(draft_id)
            if worker and worker.is_alive():
                draft.update(window_status="closing", field_matches={})
                if not draft.get("request_sent"):
                    draft["status"] = "closing"
            else:
                draft.update(window_status="closed", field_matches={})
                if not draft.get("request_sent"):
                    draft["status"] = "closed"
            return self.snapshot(draft_id)

    def shutdown(self) -> None:
        with self.lock:
            for stop in self.stops.values():
                stop.set()
        # Workers own Playwright on their own thread and observe cancellation.
        for worker in list(self.threads.values()):
            worker.join(timeout=2)
