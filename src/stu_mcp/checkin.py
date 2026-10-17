"""Local control client for the independent stu-checkin worker (never owns its lifetime)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .checkin_process import launch_windows_worker

LABELS = {"service_not_started": "服务未启动", "not_logged_in": "未登录", "paused": "已暂停",
          "monitoring": "监听中", "query_error": "查询异常", "starting": "正在启动", "stopping": "正在暂停"}
STATE_KEYS = {"status", "status_label", "status_reason", "observed_at", "logged_in", "auth_state",
              "monitoring", "busy", "stopping", "needs_login", "selected_courses", "selection_revision",
              "duration_minutes", "continuous", "resume_enabled", "until", "last_read_at",
              "last_activity_count", "last_confirmed_at", "cooldown_seconds", "failed_courses", "verification"}
RESULT_KEYS = {"course_id", "course_name", "activity_id", "type", "status", "message", "created_at",
               "check_in_date", "updated_at", "first_observed_at", "evidence"}


def default_home():
    if raw := os.environ.get("STU_CHECKIN_HOME"):
        return Path(raw).expanduser().resolve()
    # LocalAppData is redirected inside packaged Windows clients; a user-profile
    # location is shared with independently launched processes and desktop shortcuts.
    return Path.home() / ".local" / "share" / "stu-checkin"


def _lock(stream, *, release=False):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN if release else fcntl.LOCK_EX | fcntl.LOCK_NB)


def worker_locked(home):
    """Read-only discovery: do not create files or signal a PID from stale metadata."""
    try:
        stream = (home / "worker.lock").open("r+b")
    except FileNotFoundError:
        return False
    with stream:
        try:
            _lock(stream)
        except OSError:
            return True
        _lock(stream, release=True)
    return False


class CheckinClient:
    def __init__(self, home: Path | None = None, *, opener=webbrowser.open, transport=None,
                 startup_timeout=15):
        self.home = home if home is not None else default_home()
        self.opener = opener
        self.transport = transport
        self.startup_timeout = startup_timeout
        self._mutex = threading.Lock()
        self._last_login_open = 0.0

    @staticmethod
    def _state(status, reason, message="", *, running=None):
        return {"ok": status != "query_error", "source": "duifene", "status": status,
                "status_label": LABELS[status], "status_reason": reason, "message": message or LABELS[status],
                "service_running": running, "monitoring": False if running is False else None,
                "logged_in": None, "needs_login": False, "observed_at": time.time()}

    def _client(self):
        return httpx.Client(trust_env=False, follow_redirects=False, timeout=2, transport=self.transport)

    def _discover(self):
        try:
            info = json.loads((self.home / "runtime.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(info, dict):
            raise ValueError
        parsed = urlparse(info.get("url", ""))
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/"
                or info.get("service") != "stu-checkin" or type(info.get("pid")) is not int or info["pid"] <= 0):
            raise ValueError
        return info

    @staticmethod
    def _verify(client, info):
        response = client.get(info["url"] + "health")
        response.raise_for_status()
        health = response.json()
        if (health.get("service") != "stu-checkin" or health.get("pid") != info["pid"]
                or not info.get("instance_id") or health.get("instance_id") != info["instance_id"]
                or health.get("protocol_version") != 1 or info.get("protocol_version") != 1):
            raise ValueError
        return health

    @staticmethod
    def _authorize(client, info):
        # Browser-session cookies stay in this short-lived client, never in MCP arguments/results/config.
        client.get(info["url"]).raise_for_status()
        client.headers.update({"Origin": info["url"].rstrip("/"), "X-STU-Client": "local-ui"})

    def _snapshot(self):
        info = None
        try:
            info = self._discover()
            if info is None:
                if worker_locked(self.home):
                    return self._state("starting", "discovery_pending", running=True), None
                return self._state("service_not_started", "no_worker", running=False), None
            with self._client() as client:
                health = self._verify(client, info)
                if health.get("shutting_down"):
                    return self._state("stopping", "service_exiting", running=True), info
                self._authorize(client, info)
                response = client.get(info["url"] + "api/state")
                response.raise_for_status()
                raw = response.json()
                if raw.get("ok") is not True or raw.get("status") not in LABELS:
                    raise ValueError
            view = {k: v for k, v in raw.items() if k in STATE_KEYS}
            view.update(ok=True, source="duifene", service_running=True, process_id=info["pid"],
                        service_instance=info["instance_id"], message=raw["status_label"])
            view["courses"] = [{k: c[k] for k in ("id", "name")} for c in raw.get("courses", [])]
            view["course_statuses"] = {key: {k: value[k] for k in
                ("last_read_at", "last_attempt_at", "activity_count", "retry_at", "error", "stale") if k in value}
                for key, value in raw.get("course_statuses", {}).items()}
            view["next_action"] = "open_checkin_page" if view.get("needs_login") else (
                "check_course_statuses" if view["status"] == "query_error" else "none")
            return view, info
        except (httpx.ConnectError, httpx.ConnectTimeout):
            try:
                if not worker_locked(self.home):
                    return self._state("service_not_started", "stale_runtime", running=False), None
            except OSError:
                pass
            return self._state("query_error", "worker_unreachable", "后台无响应；未启动额外进程。"), None
        except httpx.TimeoutException:
            return self._state("query_error", "worker_timeout", "读取后台状态超时；监听状态未知。"), None
        except (OSError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError):
            return self._state("query_error", "discovery_invalid",
                               "无法验证本地后台，请重新打开本地页面或更新 stu-checkin。"), None

    def status(self):
        """Passive: no process, browser or platform request is started."""
        return self._snapshot()[0]

    @contextmanager
    def _launch_lock(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.home / "launch.lock").open("a+b") as stream:
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + self.startup_timeout
            while True:
                try:
                    _lock(stream)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                _lock(stream, release=True)

    def _launch(self):
        """Resolve executable locally, never from runtime.json or a model-supplied path."""
        launch_home = self.home.resolve()
        env = dict(os.environ, STU_CHECKIN_HOME=str(launch_home))
        configured = os.environ.get("STU_CHECKIN_PYTHON")
        if configured:
            executable = Path(configured).expanduser()
            if not executable.is_absolute() or not executable.is_file():
                raise FileNotFoundError
        else:
            # The wheel contains the worker and web assets. Never prefer a stale
            # sibling checkout, nor resolve a uv symlink out of its environment.
            import importlib.util
            if importlib.util.find_spec("stu_checkin") is None:
                raise FileNotFoundError
            executable = Path(sys.executable)
        if not executable.is_file():
            raise FileNotFoundError
        args = [str(executable), "-m", "stu_checkin.server", "--no-browser"]
        if os.name == "nt":
            # DETACHED_PROCESS alone still inherits the MCP client's kill-on-close Job Object.
            launch_windows_worker(args, env, launch_home)
            return
        # POSIX workers get an independent session and no inherited stdio pipes.
        process = subprocess.Popen(args,
                                   cwd=launch_home, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        threading.Thread(target=process.wait, name="checkin-launch-reaper", daemon=True).start()

    def _ensure(self):
        view, info = self._snapshot()
        if view["status"] not in {"service_not_started", "starting"}:
            return view, info
        try:
            with self._launch_lock():
                view, info = self._snapshot()
                if view["status"] == "service_not_started":
                    self._launch()
                elif view["status"] != "starting":
                    return view, info
                deadline = time.monotonic() + self.startup_timeout
                while time.monotonic() < deadline:
                    view, info = self._snapshot()
                    transient = view.get("status_reason") in {"worker_unreachable", "worker_timeout", "discovery_invalid"}
                    if view["status"] not in {"service_not_started", "starting"} and not transient:
                        return view, info
                    time.sleep(0.1)
            return self._state("query_error", "startup_timeout", "后台启动尚未完成，请稍后查询状态。"), None
        except FileNotFoundError:
            return self._state("service_not_started", "worker_not_installed",
                               "请先安装 stu-checkin，或配置本机 STU_CHECKIN_PYTHON。", running=False), None
        except (OSError, TimeoutError):
            return self._state("query_error", "startup_failed", "本地后台未能启动，请检查安装与本机权限。"), None

    def _open(self, info, *, login=False, force=False):
        if not info:
            return {"browser_opened": False}
        if login and not force and time.monotonic() - self._last_login_open < 30:
            return {"browser_opened": False, "login_page_already_requested": True}
        try:
            opened = bool(self.opener(info["url"] + ("#login" if login else "")))
        except Exception:
            opened = False
        if login and opened:
            self._last_login_open = time.monotonic()
        return {"browser_opened": opened, "next_action": "complete_login_in_local_page" if login and opened
                else "open_local_browser" if not opened else "use_local_page"}

    def _ready(self):
        view, info = self._ensure()
        if view.get("needs_login"):
            opened = self._open(info, login=True)
            view.update(opened, ok=False, message="请在本地网页完成微信登录，再重新发起本次操作。")
        elif not info or not view.get("logged_in") or view.get("stopping"):
            view["ok"] = False
        return view, info

    def open_page(self):
        with self._mutex:
            view, info = self._ensure()
            opened = self._open(info, login=view.get("needs_login", False), force=True)
            return view | opened | {"ok": bool(opened["browser_opened"])}

    def courses(self):
        with self._mutex:
            return self._ready()[0]

    @staticmethod
    def _selection(view, course_ids, all_courses):
        if type(all_courses) is not bool or (all_courses and course_ids is not None):
            raise ValueError
        if all_courses:
            course_ids = [c["id"] for c in view.get("courses", [])]
        elif course_ids is None:
            course_ids = view.get("selected_courses", [])
        if (not isinstance(course_ids, list) or not 1 <= len(course_ids) <= 100
                or any(not isinstance(key, str) for key in course_ids) or len(set(course_ids)) != len(course_ids)
                or not set(course_ids) <= {c["id"] for c in view.get("courses", [])}):
            raise ValueError
        return course_ids

    def _post(self, info, path, data):
        try:
            with self._client() as client:
                if self._verify(client, info).get("shutting_down"):
                    return self._state("stopping", "service_exiting", running=True) | {"ok": False}
                self._authorize(client, info)
                response = client.post(info["url"] + path, json=data, timeout=20)
                result = response.json()
                if response.status_code != 200 or result.get("ok") is not True:
                    view = self.status()
                    if view.get("needs_login"):
                        view.update(self._open(info, login=True))
                    return view | {"ok": False, "action_error": "operation_rejected",
                                   "message": "操作未完成，请检查当前状态和课程选择后重试。"}
            return None
        except (OSError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError):
            # Never retry a mutation after a timeout: it may already have taken effect.
            return self._state("query_error", "operation_uncertain",
                               "未能确认操作结果，请先查询状态；没有自动重复发送。")

    def select(self, course_ids=None, *, all_courses=False):
        with self._mutex:
            view, info = self._ready()
            if not view["ok"]:
                return view
            try:
                selected = self._selection(view, course_ids, all_courses)
            except ValueError:
                return view | {"ok": False, "action_error": "invalid_courses", "message": "请从课程列表选择 ID，或仅指定 all_courses。"}
            if view.get("monitoring"):
                return view | {"ok": False, "action_error": "pause_required", "message": "请先暂停监听，再选择课程。"}
            error = self._post(info, "api/select", {"course_ids": selected})
            return error if error is not None else self.status()

    def start(self, course_ids=None, *, minutes=90, all_courses=False):
        with self._mutex:
            if type(minutes) is not int or minutes not in {0, 30, 60, 90, 120, 180}:
                return self.status() | {"ok": False, "action_error": "invalid_duration",
                                        "message": "时长支持 30/60/90/120/180 分钟，0 表示持续监听。"}
            view, info = self._ready()
            if not view["ok"]:
                return view
            try:
                selected = self._selection(view, course_ids, all_courses)
            except ValueError:
                return view | {"ok": False, "action_error": "invalid_courses", "message": "请从课程列表选择 ID，或仅指定 all_courses。"}
            error = self._post(info, "api/start", {"course_ids": selected, "minutes": minutes})
            return error if error is not None else self.status()

    def pause(self):
        with self._mutex:
            view, info = self._snapshot()
            if not info or view["status"] in {"starting", "stopping"}:
                return view
            # Pausing must also cancel a saved continuous plan while the login has expired.
            error = self._post(info, "api/pause", {})
            return error if error is not None else self.status()

    def results(self, *, course_id="", limit=20, offset=0):
        if (type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0
                or not isinstance(course_id, str)):
            return {"ok": False, "source": "duifene", "action_error": "invalid_pagination"}
        view, info = self._snapshot()
        if not info or view["status"] in {"starting", "stopping"}:
            return view | {"results_available": False}
        try:
            with self._client() as client:
                self._verify(client, info)
                self._authorize(client, info)
                response = client.get(info["url"] + "api/results")
                response.raise_for_status()
                raw = response.json()
            items = [{k: v for k, v in row.items() if k in RESULT_KEYS}
                     for row in raw["items"] if not course_id or row["course_id"] == course_id]
            end = offset + limit
            return view | {"items": items[offset:end], "total": len(items), "has_more": end < len(items),
                           "next_offset": end if end < len(items) else None, "results_available": True,
                           "scope": "本机最近 200 条已观察活动；不是平台完整签到历史"}
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            return self._state("query_error", "results_unavailable", "签到结果暂时无法读取。") | {"results_available": False}

    def stop_service(self):
        with self._mutex:
            view, info = self._snapshot()
            if not info or view["status"] in {"starting", "stopping"}:
                return view
            # Explicit stop disables auto-resume; a normal MCP exit never calls this method.
            error = self._post(info, "api/pause", {})
            if error is not None:
                return error
            error = self._post(info, "api/quit", {})
            if error is not None:
                return error
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                view, current = self._snapshot()
                if view["status"] == "service_not_started":
                    return view
                if current and current.get("instance_id") != info["instance_id"]:
                    return view | {"ok": False, "action_error": "service_replaced"}
                time.sleep(0.1)
            return self._state("query_error", "shutdown_timeout", "后台尚未确认退出；未强制结束任何进程。")
