"""Local business controller shared by the browser and MCP clients."""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from stu_mcp.http_privacy import private_http_logging

from . import __version__
from .auth import AUTH_URL, callback_code
from .auth import CALLBACK as CALLBACK
from .monitor import CourseMonitor, MonitorStopped
from .status import describe
from .storage import SecureStore, StorageError
from .vendor.duifene.bridge import Bridge
from .vendor.duifene.errors import AuthError
from .vendor.duifene.models import Course, Outcome
from .vendor.duifene.settings import Settings


class OperationError(RuntimeError):
    pass


def clean_message(text: str) -> str:
    text = re.sub(r"https?://[^\s<>]+", "对分易页面", str(text))
    text = re.sub(r"[A-Za-z0-9_-]{32,}", "[已隐藏]", text)
    text = re.sub(r"提交签到码\s+\S+", "提交签到码", text)
    return re.sub(r"提交汉字\s+\S+", "提交汉字签到", text)[:360]


class Controller:
    def __init__(self, home: Path, *, store=None, bridge_factory=Bridge):
        self.store = store if store is not None else SecureStore(home)
        self._operation = threading.Lock()
        self._events_lock = threading.Lock()
        self._results_lock = threading.Lock()
        self._stop = threading.Event()
        self._bridge = None
        self._bridge_factory = bridge_factory
        self._events: list[dict] = []
        self._results: list[dict] = []
        self._serial = 0
        self._until = 0.0
        self._selected_course_ids: list[str] = []
        self._minutes = 90
        self._resume_enabled = False
        self._requested = False
        self._auth_state = "unknown"
        self._revision = 0
        self._last_confirmed = 0.0
        self._busy = True
        self._error = ""
        self._auth_check_error = ""
        self._manual_notices: set[str] = set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="stu-checkin-lifecycle")
        self._thread.start()

    def _run(self):
        try:
            saved = self.store.get("events", [])
            if isinstance(saved, list):
                self._events = saved[-40:]
                self._serial = max((e.get("id", 0) for e in self._events), default=0)
            self._results = self.store.get("results", [])[-200:]
            self._last_confirmed = max((r["updated_at"] for r in self._results
                                        if r.get("status") == "signed"), default=0)
            settings = Settings()
            controller = self
            base = self._bridge_factory

            class BrowserBridge(base):
                def _log(self, text):
                    if str(text).startswith("监听其他用户签到"):
                        return
                    super()._log(text)
                    controller.event(text)

                def _on_login_invalid(self):
                    controller._auth_state = "not_logged_in"
                    controller._requested = False
                    controller._error = ""
                    super()._on_login_invalid()

                def bootstrap(self):
                    # Preserve the distinction between absent/expired credentials and an offline school.
                    cookie = self._store.load_cookie()
                    if not cookie:
                        controller._auth_state = "not_logged_in"
                    else:
                        self._session.cookies.update(self._parse_cookie(cookie))
                        try:
                            message = self._refresh_courses()
                            if message:
                                controller._error = "课程列表暂时无法读取，请检查网络后重试。"
                            else:
                                controller._auth_state = "logged_in"
                        except AuthError:
                            self._api.clear_session()
                            controller._auth_state = "not_logged_in"
                        except Exception:
                            controller._error = "登录状态暂时无法验证，请检查网络后重试。"
                    self._sentinel.start()
                    return {}

            self._bridge = BrowserBridge(settings, store=self.store)
            bridge = self._bridge
            bridge._watcher = CourseMonitor(
                settings, bridge._api, bridge._processor, bridge._push, bridge._log,
                auth_lock=bridge._auth_lock,
            )
            bridge._api.submission_guard = bridge._watcher.ensure_submission_allowed
            original_check_login = bridge._api.check_login

            def check_login():
                try:
                    result = original_check_login()
                except Exception:
                    self._auth_check_error = "登录状态查询失败，请检查网络。"
                    raise
                self._auth_check_error = "登录状态暂时无法验证，请稍后重试。" if result is None else ""
                return result

            bridge._api.check_login = check_login
            processor = self._bridge._processor
            original_process = processor.process
            original_report = processor._report

            def report(activity_id, message, course):
                outcome = original_report(activity_id, message, course)
                # Record structured evidence even when upstream suppresses a repeated log line.
                current = getattr(processor, "_current_activity", None)
                if current is not None:
                    self._record_result(current, course, "signed" if outcome is Outcome.SIGNED else "failed")
                return outcome

            processor._report = report

            def process(activity, course):
                attended = (activity.status_id == "1" or activity.check_in_status == "1"
                            or activity.status_name == "出勤")
                if activity.type == "3" and not attended:
                    if activity.id not in self._manual_notices:
                        self._manual_notices.add(activity.id)
                        self.event(f"课程: {course.name} 检测到定位签到，请在对分易完成。", "warning")
                    self._record_result(activity, course, "manual_required")
                    return Outcome.DEFERRED
                if attended:
                    self._record_result(activity, course, "already_signed")
                processor._current_activity = activity
                try:
                    outcome = original_process(activity, course)
                except MonitorStopped:
                    raise
                except Exception:
                    self._record_result(activity, course, "error")
                    raise
                finally:
                    processor._current_activity = None
                self._record_result(activity, course, {Outcome.SIGNED: "signed", Outcome.SKIPPED: "skipped",
                                                       Outcome.DEFERRED: "waiting"}[outcome])
                return outcome

            processor.process = process
            boot = self._bridge.bootstrap()
            if boot.get("message"):
                self._error = clean_message(boot["message"])
            if not self._stop.is_set():
                self._restore_plan()
        except StorageError as exc:
            self._error = str(exc)
        except Exception:
            self._error = "连接状态暂时无法恢复，请重新连接微信。"
        finally:
            self._busy = False
        while not self._stop.wait(0.8):
            if self._until and time.time() >= self._until:
                with self._operation:
                    if self._until and time.time() >= self._until:
                        self._until = 0
                        self._requested = False
                        if self._bridge is not None:
                            self._bridge.stop_watching()
                        self.event("本次监听已到时，已自动暂停。")

    def _restore_plan(self):
        bridge = self._bridge
        plan = self.store.get("monitor_plan", {})
        if not isinstance(plan, dict):
            plan = {}
        saved_ids = plan.get("course_ids", [])
        if not isinstance(saved_ids, list):
            saved_ids = []
        available = [c["id"] for c in bridge._courses_payload()] if bridge._logged_in else []
        matches = [key for key in available if key in saved_ids]
        self._selected_course_ids = matches or available
        minutes = plan.get("minutes", 90)
        self._minutes = minutes if type(minutes) is int and minutes in {0, 30, 60, 90, 120, 180} else 90
        self._resume_enabled = bool(plan.get("enabled") and self._minutes == 0)
        if not self._resume_enabled or not bridge._logged_in:
            return
        try:
            owner = bridge._api.fetch_user_id()
            if not owner:
                raise OperationError("无法确认账号")
            if owner != plan.get("owner") or not matches:
                self._resume_enabled = False
                self.store.update(monitor_plan={**plan, "enabled": False})
                self.event("账号或课程已变化，请重新选择课程并开始监听。", "warning")
                return
            self._activate(matches, 0)
            self.event(f"已恢复持续监听，共 {len(matches)} 门课程。")
        except Exception:
            self._error = "持续监听暂未恢复，请检查网络后手动开始。"

    def _activate(self, course_ids, minutes):
        if self._stop.is_set():
            raise OperationError("服务正在退出。")
        bridge = self._bridge
        payload = {c["id"]: c for c in bridge._courses_payload()}
        courses = [Course(course_id=key, class_id=payload[key]["class_id"], name=payload[key]["name"])
                   for key in course_ids]
        bridge.select_course(course_ids[0])
        bridge._watcher.set_courses(courses)
        self._selected_course_ids = list(course_ids)
        self._minutes = minutes
        self._until = time.time() + minutes * 60 if minutes else 0
        bridge._watcher.deadline = self._until
        bridge._api.last_activity_fetch_success = 0
        bridge._api.last_activity_count = 0
        result = bridge.start_watching()
        if not result.get("ok"):
            self._until = 0
            raise OperationError(clean_message(result.get("message", "监听未启动。")))
        self._requested = True
        self._revision += 1

    def _record_result(self, activity, course, status):
        messages = {"signed": "平台返回签到成功", "already_signed": "平台已记录出勤",
                    "failed": "本次提交未获成功确认", "manual_required": "定位签到需在对分易完成",
                    "waiting": "等待签到条件满足", "skipped": "未提交，活动不满足当前签到条件",
                    "error": "活动处理异常，未取得签到结果"}
        with self._results_lock:
            previous = next((r for r in self._results if r["course_id"] == course.course_id
                             and r["activity_id"] == activity.id), None)
            if previous and (previous["status"] == status or previous["status"] == "signed"
                             or previous["status"] == "already_signed" and status != "signed"
                             or previous["status"] in {"failed", "error"} and status in {"waiting", "skipped"}):
                return
            now = time.time()
            result = {"course_id": course.course_id, "course_name": clean_message(course.name),
                      "activity_id": activity.id, "type": activity.type, "status": status,
                      "message": messages[status], "created_at": activity.create_date,
                      "check_in_date": activity.check_in_date, "updated_at": now,
                      "first_observed_at": previous["first_observed_at"] if previous else now,
                      "evidence": "submission_response" if status in {"signed", "failed"} else
                                  "platform_attendance" if status == "already_signed" else
                                  "local_error" if status == "error" else "local_decision"}
            self._results = [r for r in self._results if r is not previous] + [result]
            self._results = self._results[-200:]
            if status == "signed":
                self._last_confirmed = now
            try:
                self.store.update(results=self._results)
            except StorageError:
                self._error = "签到结果未能安全保存，请检查系统密钥库。"

    def results(self):
        with self._results_lock:
            return {"ok": True, "items": [dict(r) for r in reversed(self._results)],
                    "scope": "本机最近 200 条已观察活动；不是平台完整签到历史"}

    def event(self, text, level=None):
        text = clean_message(text)
        if not text:
            return
        if level is None:
            level = "error" if any(s in text for s in ("失败", "错误", "异常", "失效")) else (
                "success" if "签到成功" in text else "info")
        with self._events_lock:
            self._serial += 1
            self._events.append({"id": self._serial, "at": time.time(), "level": level, "text": text})
            self._events = self._events[-40:]
            events = list(self._events)
        try:
            if self.store.load_cookie():
                self.store.update(events=events)
        except StorageError:
            self._error = "运行记录未能安全保存，请检查系统密钥库。"

    def _ready(self):
        if self._stop.is_set():
            raise OperationError("服务正在退出。")
        if self._busy:
            raise OperationError("正在恢复连接，请稍候。")
        if self._bridge is None:
            raise OperationError(self._error or "连接暂时不可用，请重新打开本地服务。")
        if self._bridge._watcher.is_stopping:
            raise OperationError("正在结束上一轮请求，请稍候。")
        return self._bridge

    def snapshot(self) -> dict:
        bridge = self._bridge
        with self._events_lock:
            events = list(self._events)
        logged_in = bool(bridge and bridge._logged_in)
        monitoring = bool(bridge and bridge._watcher.is_running)
        courses = bridge._courses_payload() if bridge else []
        api = bridge._api if bridge else None
        health = getattr(bridge._watcher, "course_statuses", {}) if bridge else {}
        stopping = bool(bridge and getattr(bridge._watcher, "is_stopping", False))
        auth_state = "logged_in" if logged_in else self._auth_state
        status = describe(busy=self._busy, auth_state=auth_state, monitoring=monitoring, stopping=stopping,
                          requested=self._requested, error=self._error or self._auth_check_error, course_statuses=health)
        return {
            **status, "observed_at": time.time(), "selection_revision": self._revision,
            "ok": True, "version": __version__, "busy": self._busy,
            "logged_in": logged_in, "monitoring": monitoring,
            "courses": courses if logged_in else [],
            "selected_courses": self._selected_course_ids if logged_in else [],
            "duration_minutes": self._minutes,
            "continuous": self._minutes == 0,
            "resume_enabled": self._resume_enabled,
            "stopping": stopping,
            "course_statuses": health,
            "until": self._until if monitoring else 0,
            "last_read_at": getattr(api, "last_activity_fetch_success", 0),
            "last_activity_count": getattr(api, "last_activity_count", 0),
            "last_confirmed_at": self._last_confirmed,
            "cooldown_seconds": round(bridge._limiter.remaining()) if bridge else 0,
            "error": self._error or self._auth_check_error, "events": events,
            "auth_url": AUTH_URL,
            "verification": {"live_auto_submission": False, "location_enabled": False},
        }

    def connect(self, link: str):
        try:
            code = callback_code(link)
        except ValueError:
            raise OperationError("请粘贴微信打开后、包含 code 的对分易完整链接。") from None
        with self._operation:
            bridge = self._ready()
            if bridge._watcher.is_running:
                raise OperationError("请先暂停监听，再切换微信连接。")
            self._busy = True
            try:
                # LocalServer calls connect synchronously on its handler thread.
                # Keep the upstream one-time callback and session traces private
                # on that same thread; do not rely on executor propagation.
                with private_http_logging():
                    result = bridge.login_by_link("https://www.duifene.com/?code=" + code)
                if not result.get("ok"):
                    raise OperationError(clean_message(result.get("message", "连接未完成，请重新获取微信链接。")))
                bridge._sentinel.start()
                self._last_confirmed = 0
                bridge._api.last_activity_fetch_success = 0
                bridge._api.last_activity_count = 0
                bridge._watcher.clear_status()
                with self._events_lock:
                    self._events.clear()
                with self._results_lock:
                    self._results.clear()
                self._auth_state = "logged_in"
                self._auth_check_error = ""
                self._revision += 1
                self._error = ""
                self.event("微信已连接，课程列表已更新。")
                self._restore_plan()
            finally:
                self._busy = False
        return {"ok": True}

    def start(self, course_ids: list[str], minutes: int):
        if type(minutes) is not int or minutes not in {0, 30, 60, 90, 120, 180}:
            raise OperationError("请选择监听时长，或选择持续监听。")
        if (not isinstance(course_ids, list) or not 1 <= len(course_ids) <= 100
                or any(not isinstance(key, str) for key in course_ids)
                or len(set(course_ids)) != len(course_ids)):
            raise OperationError("请至少选择一门课程。")
        with self._operation:
            bridge = self._ready()
            if not bridge._logged_in:
                raise OperationError("请先连接微信。")
            available = {c["id"] for c in bridge._courses_payload()}
            if not set(course_ids) <= available:
                raise OperationError("请选择当前账号中的课程。")
            if bridge._watcher.is_running:
                if set(course_ids) == set(self._selected_course_ids) and minutes == self._minutes:
                    return {"ok": True, "already_running": True}
                raise OperationError("当前正在监听，请先暂停。")
            self._manual_notices.clear()
            try:
                owner = bridge._api.fetch_user_id() if minutes == 0 else ""
            except Exception:
                raise OperationError("读取账号信息失败，请检查网络后重试。") from None
            if minutes == 0 and not owner:
                raise OperationError("无法确认账号，请重新登录。")
            plan = {"course_ids": course_ids, "minutes": minutes, "owner": owner, "enabled": minutes == 0}
            self.store.update(monitor_plan=plan)
            try:
                self._activate(course_ids, minutes)
            except Exception:
                self.store.update(monitor_plan={**plan, "enabled": False})
                raise
            self._resume_enabled = minutes == 0
            self._error = ""
        return {"ok": True}

    def pause(self):
        with self._operation:
            bridge = self._ready()
            plan = self.store.get("monitor_plan", {})
            self._resume_enabled = False
            self._requested = False
            self._until = 0
            try:
                if plan:
                    self.store.update(monitor_plan={**plan, "enabled": False})
            finally:
                bridge.stop_watching()
        return {"ok": True}

    def select(self, course_ids: list[str]):
        if (not isinstance(course_ids, list) or not 1 <= len(course_ids) <= 100
                or any(not isinstance(key, str) for key in course_ids)
                or len(set(course_ids)) != len(course_ids)):
            raise OperationError("请至少选择一门课程。")
        with self._operation:
            bridge = self._ready()
            if not bridge._logged_in:
                raise OperationError("请先连接微信。")
            if not set(course_ids) <= {c["id"] for c in bridge._courses_payload()}:
                raise OperationError("请选择当前账号中的课程。")
            if bridge._watcher.is_running:
                raise OperationError("请先暂停监听，再选择课程。")
            self.store.update(monitor_plan={"course_ids": course_ids, "minutes": self._minutes,
                                            "owner": "", "enabled": False})
            self._selected_course_ids = list(course_ids)
            self._resume_enabled = False
            self._revision += 1
        return {"ok": True}

    def disconnect(self):
        with self._operation:
            if self._busy:
                raise OperationError("连接正在处理中，请稍候。")
            bridge = self._bridge
            if bridge:
                bridge.stop_watching()
                bridge._sentinel.stop()
                with bridge._auth_lock:
                    bridge._api.clear_session()
                    bridge._courses = []
                    bridge._course = None
                    bridge._logged_in = False
                    bridge._watcher.set_course(None)
                    bridge._api.last_activity_fetch_success = 0
                    bridge._api.last_activity_count = 0
                    bridge._watcher.clear_status()
            self._until = 0
            self._last_confirmed = 0
            self._selected_course_ids = []
            self._minutes = 90
            self._resume_enabled = False
            self._requested = False
            self._auth_state = "not_logged_in"
            self._auth_check_error = ""
            self._revision += 1
            self.store.clear()
            with self._events_lock:
                self._events.clear()
            with self._results_lock:
                self._results.clear()
            self._error = ""
        return {"ok": True}

    def close(self):
        self._stop.set()
        self._thread.join(timeout=12)
        if self._bridge is not None:
            self._bridge.stop_watching()
            self._bridge._sentinel.stop()
            self._bridge._session.close()
