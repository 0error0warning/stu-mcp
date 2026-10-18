"""One cancellable worker rotates through all selected courses."""
from __future__ import annotations

import random
import threading
import time

from .vendor.duifene.models import Course


class MonitorStopped(RuntimeError):
    pass


class CourseMonitor:
    def __init__(self, settings, api, processor, push, log, *, auth_lock):
        self._settings = settings
        self._api = api
        self._processor = processor
        self._push = push
        self._log = log
        self._auth_lock = auth_lock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._stop.set()
        self._thread = None
        self._courses: list[Course] = []
        self._health: dict[str, dict] = {}
        self._last_tick_ts = 0.0
        self.deadline = 0.0

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    @property
    def is_stopping(self):
        return bool(self._thread and self._thread.is_alive() and self._stop.is_set())

    @property
    def last_tick_ts(self):
        return self._last_tick_ts

    @property
    def course_statuses(self):
        with self._lock:
            values = {key: dict(value) for key, value in self._health.items()}
        # A live thread alone does not prove that requests are succeeding.
        allowance = max(60, len(values) * (self._settings.poll_max_s + 3 * self._settings.request_timeout_s))
        for value in values.values():
            value["stale"] = bool(self.is_running and time.time() -
                                  (value["last_read_at"] or value["started_at"]) > allowance)
            if value["stale"] and not value["error"]:
                value["error"] = "课程查询长时间未完成"
        return values

    def set_course(self, course: Course | None):
        if course is None:
            self._stop.set()
        self.set_courses([course] if course else [])

    def set_courses(self, courses: list[Course]):
        with self._lock:
            self._courses = list(courses)

    def clear_status(self):
        with self._lock:
            self._health.clear()

    def ensure_submission_allowed(self):
        if self._stop.is_set() or (self.deadline and time.time() >= self.deadline):
            raise MonitorStopped

    def start(self):
        if self.is_running or self.is_stopping:
            raise RuntimeError("上一轮监听尚未结束，请稍候。")
        with self._lock:
            if not self._courses:
                raise RuntimeError("请至少选择一门课程。")
            self._health = {course.course_id: {"last_read_at": 0, "error": "", "activity_count": 0,
                                               "started_at": time.time(), "last_attempt_at": 0, "retry_at": 0}
                            for course in self._courses}
            count = len(self._courses)
        self._processor.reset()
        self._stop.clear()
        self._log(f"开始监听 {count} 门课程。")
        self._thread = threading.Thread(target=self._run, name="stu-checkin-monitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._push.stop()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        # Retain a still-alive thread: start() must never revive an old request loop.

    def _poll(self, course):
        with self._auth_lock:
            self.ensure_submission_allowed()
            user_id = self._api.fetch_user_id()
            if not user_id:
                raise RuntimeError("获取学生ID失败，请重新登录")
            self.ensure_submission_allowed()
            activities = self._api.fetch_activities(course.class_id, user_id)
            if activities is None:
                raise RuntimeError("获取签到列表失败")
            with self._lock:
                self._health[course.course_id].update(
                    last_read_at=time.time(), error="", activity_count=len(activities), retry_at=0,
                )
            for activity in activities:
                self.ensure_submission_allowed()
                try:
                    self._processor.process(activity, course)
                except MonitorStopped:
                    raise
                except Exception as exc:
                    self._log(f"课程: {course.name} 活动处理异常：{exc!s}")

    def _run(self):
        retries: dict[str, float] = {}
        failures: dict[str, int] = {}
        cursor = 0
        try:
            while not self._stop.is_set():
                self.ensure_submission_allowed()
                with self._lock:
                    courses = list(self._courses)
                if not courses:
                    break
                course = None
                for _ in courses:
                    candidate = courses[cursor % len(courses)]
                    cursor += 1
                    if retries.get(candidate.course_id, 0) <= time.monotonic():
                        course = candidate
                        break
                if course is None:
                    delay = max(0.05, min(retries.get(c.course_id, 0) for c in courses) - time.monotonic())
                    self._stop.wait(min(delay, self._settings.poll_max_s))
                    continue
                self._last_tick_ts = time.time()
                with self._lock:
                    self._health[course.course_id]["last_attempt_at"] = self._last_tick_ts
                try:
                    self._poll(course)
                    failures.pop(course.course_id, None)
                    retries.pop(course.course_id, None)
                except MonitorStopped:
                    break
                except Exception as exc:
                    failures[course.course_id] = failures.get(course.course_id, 0) + 1
                    backoff = min(self._settings.poll_min_s * 2 ** min(failures[course.course_id], 8),
                                  self._settings.error_backoff_max_s)
                    retries[course.course_id] = time.monotonic() + backoff
                    with self._lock:
                        self._health[course.course_id]["error"] = "查询失败，正在重试"
                        self._health[course.course_id]["retry_at"] = time.time() + backoff
                    self._log(f"课程: {course.name} 监控异常：{exc!s}（{int(backoff)} 秒后重试）")
                self._stop.wait(random.uniform(self._settings.poll_min_s, self._settings.poll_max_s))
        except MonitorStopped:
            pass
        finally:
            self._stop.set()
            self._log("监听已暂停。")
