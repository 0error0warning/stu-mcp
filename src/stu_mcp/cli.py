from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from . import __version__
from .app import App
from .auth import interactive_login
from .clients import CLIENTS, catalog, connect
from .huyou import DEFAULT_CIRCLE
from .runtime import AppError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stu-mcp", description="汕头大学校园工具 · 本地 MCP 和按需查询")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("serve", help="启动 stdio MCP 服务")
    sub.add_parser("status", help="输出功能/登录/缓存状态")
    sub.add_parser("clients", help="查看客户端接入方式与官方说明")
    setup = sub.add_parser("setup", help="打开本机设置页")
    setup.add_argument("--no-browser", action="store_true", help="仅在终端输出本机设置地址")
    login = sub.add_parser("login", help="在独立浏览器中手动登录学校")
    login.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn"))
    logout = sub.add_parser("logout", help="移除指定来源的会话和缓存")
    logout.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn"))
    client = sub.add_parser("connect", help="预览或保存客户端接入，保留其他配置")
    client.add_argument("client", choices=tuple(CLIENTS))
    client.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    client.add_argument("--replace", action="store_true", help="明确替换其他同名配置")
    refresh = sub.add_parser("refresh", help="按需更新一个来源")
    refresh.add_argument("source", choices=("public", "oa", "jw", "mystu", "yuketang"))
    refresh.add_argument("--limit", type=int, default=20)
    refresh.add_argument("--semester", default="")
    query = sub.add_parser("query", help="查询本地缓存，JSON 输出")
    query.add_argument("kind", choices=("notice", "grade", "exam", "course", "task", "resource", "event", "service", "post"))
    query.add_argument("--source", default="all")
    query.add_argument("--search", default="")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    notice = sub.add_parser("notice", help="读取已缓存通知的正文和附件列表")
    notice.add_argument("item_id")
    notice.add_argument("--refresh", action="store_true")
    attachment = sub.add_parser("attachment", help="读取已缓存通知的 PDF / 文本附件")
    attachment.add_argument("item_id")
    attachment.add_argument("--index", type=int, default=0)
    summary = sub.add_parser("academic-summary", help="计算已缓存成绩的学分加权统计")
    summary.add_argument("--semester", default="")
    task = sub.add_parser("task-status", help="更新本机待办状态，不提交学校作业")
    task.add_argument("item_id")
    task.add_argument("status", choices=("todo", "done", "ignored"))
    profile = sub.add_parser("profile", help="读取或更新可选学生资料")
    for field in ("college", "major", "entry-year", "interests"):
        profile.add_argument("--" + field)
    browser = sub.add_parser("browser", help="安装手动登录所需浏览器")
    browser.add_argument("action", choices=("install",))
    huyou = sub.add_parser("huyou", help="按需搜索狐友公开圈子和讨论，无需登录")
    community = huyou.add_subparsers(dest="huyou_action", required=True)
    search = community.add_parser("search", help="圈内字面词搜索；当前 agent 规划关键词")
    search.add_argument("query")
    search.add_argument("--keyword", action="append", dest="keywords")
    search.add_argument("--circle-id", default=DEFAULT_CIRCLE)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--pages", type=int, default=2)
    search.add_argument("--with-discussion", action="store_true")
    search.add_argument("--local", action="store_true")
    search.add_argument("--offset", type=int, default=0)
    detail = community.add_parser("detail", help="公开帖子正文、评论和回复")
    detail.add_argument("target")
    detail.add_argument("--local", action="store_true")
    detail.add_argument("--no-comments", action="store_true")
    detail.add_argument("--comment-limit", type=int, default=20)
    detail.add_argument("--reply-limit", type=int, default=10)
    circles = community.add_parser("circles", help="发现公开圈子及 ID")
    circles.add_argument("query", nargs="?", default="汕大")
    circles.add_argument("--page", type=int, default=1)
    return p


def emit(result: dict) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command == "browser":
            return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if args.command in (None, "serve"):
            from .server import build_server
            build_server().run(transport="stdio")
            return 0
        if args.command == "clients":
            return emit({"ok": True, "clients": catalog()})
        app = App()
        if args.command == "huyou":
            if args.huyou_action == "search":
                return emit(app.huyou_search(args.query, args.keywords, args.circle_id, args.limit, args.pages,
                                            args.with_discussion, args.local, args.offset))
            if args.huyou_action == "detail":
                return emit(app.huyou_post(args.target, not args.local, not args.no_comments,
                                          args.comment_limit, args.reply_limit))
            return emit(app.huyou_circles(args.query, args.page))
        if args.command == "status":
            return emit(app.status())
        if args.command == "setup":
            from .setup_web import SetupServer
            ui = SetupServer(app)
            opened = ui.start(open_browser=not args.no_browser)
            # This URL is printed only by an explicit local terminal command, never an MCP tool.
            print("设置页已在本机浏览器打开。按 Ctrl+C 结束。" if opened else "本机设置地址：" + ui.url, flush=True)
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                ui.close()
            return 0
        if args.command == "login":
            return emit(interactive_login(app.vault, args.service))
        if args.command == "logout":
            return emit(app.logout(args.service))
        if args.command == "connect":
            return emit(connect(args.client, app.runtime, apply=args.apply, replace=args.replace))
        if args.command == "refresh":
            return emit(app.refresh(args.source, args.limit, args.semester))
        if args.command == "query":
            return emit(app.query(args.kind, args.search, args.limit, args.offset, args.source))
        if args.command == "notice":
            return emit(app.notice(args.item_id, args.refresh))
        if args.command == "attachment":
            return emit(app.attachment(args.item_id, args.index))
        if args.command == "academic-summary":
            return emit(app.academic_summary(args.semester))
        if args.command == "task-status":
            return emit(app.store.set_task_status(args.item_id, args.status))
        if args.command == "profile":
            fields = {field: getattr(args, field) for field in ("college", "major", "entry_year", "interests")
                      if getattr(args, field) is not None}
            if fields:
                app.runtime.save_profile(fields)
            return emit({"ok": True, "profile": app.runtime.profile()})
    except AppError as exc:
        return emit(exc.result())
    except KeyboardInterrupt:
        return 130
    except Exception:
        if args.command in (None, "serve"):
            print("STU MCP 启动失败，请运行 stu-mcp status 检查本地状态。", file=sys.stderr)
            return 1
        return emit({"ok": False, "status": "operation_failed", "message": "操作未完成；未输出认证信息。请检查本地状态或重试。"})
    return 0
