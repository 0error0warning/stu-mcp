"""Local read-only verification, deliberately separate from the stable MCP tools.

uv run python scripts/inspect_yuketang.py <cached-task-item-id> [--render output/playwright/homework.png]
Only synthetic samples belong in tests. Never log the raw response or session.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stu_mcp.app import App
from stu_mcp.network import CampusHTTP
from stu_mcp.runtime import AppError, key_lock, private_write
from stu_mcp.yuketang_readiness import inspect_exercise, read_homework, render_inspection


def main():
    parser = argparse.ArgumentParser(description="只读核验雨课堂 LMS 作业；不作答、不启动测验、不提交")
    parser.add_argument("item_id", help="先刷新雨课堂，从 task 缓存取得的记录 ID")
    parser.add_argument("--render", type=Path, help="可选的本地 PNG 核验图，可能含个人课程内容，请勿提交到 Git")
    args = parser.parse_args()
    try:
        app = App()
        version = app.vault.fingerprint("yuketang")
        item = app.store.get(args.item_id)
        with CampusHTTP("yuketang", app.vault.load("yuketang")) as http:
            inspection = inspect_exercise(read_homework(http, item))
        # A font URL must remain coupled to this exact response; don't refetch the questions for rendering.
        png = render_inspection(inspection) if args.render else None
        with key_lock(app.runtime.home, "yuketang"):
            if app.vault.fingerprint("yuketang") != version:
                raise AppError("session_changed", "读取期间登录态已变化，请刷新后重试。", "yuketang")
            if png is not None:
                private_write(args.render.absolute(), png)
        result = {**inspection.report, "rendered": png is not None,
                  "render_warning": "渲染成功不等于内容完整；图片、公式及外部教材仍须核对。"}
    except AppError as exc:
        result = exc.result()
    except Exception:
        result = AppError("operation_failed", "核验未完成；未输出原始响应或认证信息。", "yuketang").result()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
