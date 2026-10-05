from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from . import __version__
from .app import App
from .auth import interactive_login
from .clients import connect, server_config
from .runtime import AppError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stu-mcp", description="汕头大学校园工具 · 本地 MCP 和按需查询")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("serve", help="启动 stdio MCP 服务")
    sub.add_parser("status", help="输出功能/登录/缓存状态")
    setup = sub.add_parser("setup", help="打开本机设置页")
    setup.add_argument("--no-browser", action="store_true", help="仅在终端输出本机设置地址")
    login = sub.add_parser("login", help="在独立浏览器中手动登录学校")
    login.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn"))
    logout = sub.add_parser("logout", help="移除指定来源的会话和缓存")
    logout.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn"))
    client = sub.add_parser("connect", help="预览或保存客户端接入，保留其他配置")
    client.add_argument("client", choices=("codex", "claude-code", "cursor", "generic"))
    client.add_argument("--apply", action="store_true", help="实际写入；默认只预览")
    client.add_argument("--replace", action="store_true", help="明确替换其他同名配置")
    refresh = sub.add_parser("refresh", help="按需更新一个来源")
    refresh.add_argument("source", choices=("public", "oa", "jw", "mystu", "yuketang"))
    refresh.add_argument("--limit", type=int, default=20)
    refresh.add_argument("--semester", default="")
    query = sub.add_parser("query", help="查询本地缓存，JSON 输出")
    query.add_argument("kind", choices=("notice", "grade", "exam", "course", "task", "resource", "event", "service"))
    query.add_argument("--source", default="all")
    query.add_argument("--search", default="")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--offset", type=int, default=0)
    browser = sub.add_parser("browser", help="安装手动登录所需浏览器")
    browser.add_argument("action", choices=("install",))
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
        app = App()
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
            return emit({"ok": True, "mcpServers": {"stu-mcp": server_config()}} if args.client == "generic"
                        else connect(args.client, app.runtime, apply=args.apply, replace=args.replace))
        if args.command == "refresh":
            return emit(app.refresh(args.source, args.limit, args.semester))
        if args.command == "query":
            return emit(app.query(args.kind, args.search, args.limit, args.offset, args.source))
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
