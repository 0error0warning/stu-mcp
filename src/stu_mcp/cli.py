from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .app import App
from .auth import interactive_login
from .clients import CLIENTS, catalog, connect
from .huyou import DEFAULT_CIRCLE
from .runtime import AppError, Runtime
from .skill_export import SKILL_NAMES, export_skill


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stu-mcp", description="汕头大学校园工具 · 本地 MCP 和按需查询")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="启动 stdio 或个人实例 Streamable HTTP MCP")
    serve.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    serve.add_argument("--host", default="127.0.0.1", help="HTTP 监听 IP；默认只监听回环")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--auth-token-file", type=Path, help="私密随机 Bearer 令牌文件路径，不传令牌内容")
    serve.add_argument("--public-url", help="私有 HTTPS 反向代理的完整 /mcp 地址，用于 Host/Origin 白名单")
    serve.add_argument("--name", help="非敏感实例标签；字母数字、下划线、短横线，最多64字符")
    init = sub.add_parser("server-init", help="在新目录生成服务器主密钥和 HTTP 令牌，仅输出路径")
    init.add_argument("directory", type=Path)
    sub.add_parser("status", help="输出功能/登录/缓存状态")
    sub.add_parser("clients", help="查看客户端接入方式与官方说明")
    skill = sub.add_parser("skill-export", help="预览或导出随包技能，不修改 agent 配置")
    skill.add_argument("--skill", choices=SKILL_NAMES, default="stu-campus")
    skill.add_argument("--apply", action="store_true", help="生成 ZIP；默认只预览")
    network = sub.add_parser("network", help="匿名诊断指定校园服务的直连、DNS及本机代理，不改设置")
    network.add_argument("--service-id", default="sangpushan_repair")
    network.add_argument("--location-hint", choices=("unknown", "campus", "off_campus"), default="unknown")
    network.add_argument("--refresh", action="store_true")
    login_check = network.add_mutually_exclusive_group()
    login_check.add_argument("--check-login", action="store_true", default=None,
                             help="对已知依赖SSO的业务额外检查统一认证")
    login_check.add_argument("--anonymous-only", dest="check_login", action="store_false",
                             help="仅检查该匿名入口，不额外检查SSO")
    network.add_argument("--compare-proxy", action="store_true", help="额外比较无凭据本机代理；不自动切换")
    audit = sub.add_parser("network-audit", help="批量检查已登记学校域名的DNS与匿名直连，不改设置")
    audit.add_argument("--location-hint", choices=("unknown", "campus", "off_campus"), default="unknown")
    audit.add_argument("--compare-public-dns", action="store_true", help="额外对比阿里与腾讯公共DNS的A/AAAA")
    audit.add_argument("--refresh", action="store_true", help="切网后重新检测，跳过进程内缓存")
    repair = sub.add_parser("repair", help="从业务JSON准备宿舍报修草稿，默认HTTP填写并展示实际表单")
    repair.add_argument("repair_action", choices=("plan", "preview", "drill"))
    repair.add_argument("--submit", action="store_true", help="CLI演练后展示实际表单并等待本人明确确认，才提交")
    repair.add_argument("--fields-file", type=Path, help="业务字段JSON文件路径；认证输入仍只从本人终端隐藏读取")
    repair.add_argument("--browser", action="store_true", help="仅preview显式使用原浏览器兼容演练")
    setup = sub.add_parser("setup", help="打开本机设置页")
    setup.add_argument("--no-browser", action="store_true", help="仅在终端输出本机设置地址")
    setup.add_argument("--port", type=int, default=0, help="本机设置端口，默认随机；远程转发可指定8766")
    login = sub.add_parser("login", help="默认纯HTTP登录；认证输入只在本人终端输入")
    login.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn", "duifene", "repair"))
    login.add_argument("--browser", action="store_true", help="显式使用原浏览器兼容登录，不自动回退")
    login.add_argument("--allow-http-callback", action="store_true", help="仅本次教务登录允许官方HTTP票据回调；密码仍HTTPS")
    transport = sub.add_parser("transport", help="查看或明确设置本地HTTP兼容选项")
    transport.add_argument("--jw-http", choices=("on", "off"))
    transport.add_argument("--oa-http", choices=("on", "off"))
    auto = sub.add_parser("webvpn-auto", help="在本人终端配置原有 WebVPN 按需自动重登")
    auto_actions = auto.add_subparsers(dest="auto_action", required=True)
    configure = auto_actions.add_parser("configure", help="启用自动重登；凭据只在终端隐藏输入")
    configure.add_argument("--encoding", choices=("auto", "base32", "base64", "hex"), default="auto")
    auto_actions.add_parser("status", help="仅查看开关和失败状态，不读取或输出凭据")
    auto_actions.add_parser("remove", help="关闭自动重登并移除所存凭据")
    logout = sub.add_parser("logout", help="移除指定来源的会话和缓存")
    logout.add_argument("service", choices=("jw", "mystu", "yuketang", "webvpn", "repair"))
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
    charging = sub.add_parser("charging", help="独立读取充电设备状态，无需账号或网站服务")
    charge = charging.add_subparsers(dest="charging_action", required=True)
    overview = charge.add_parser("overview", help="按位置查询已核验设备，每页最多4台")
    overview.add_argument("location", nargs="?", default="")
    overview.add_argument("--limit", type=int, default=4)
    overview.add_argument("--offset", type=int, default=0)
    overview.add_argument("--local", action="store_true", help="仅读取本机缓存")
    device = charge.add_parser("device", help="读取一台设备的插座状态")
    device.add_argument("device_code")
    device.add_argument("--local", action="store_true", help="仅读取本机缓存")
    return p


def emit(result: dict) -> int:
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.get("ok", True) else 1


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command == "browser":
            from importlib.util import find_spec
            if find_spec("playwright") is None:
                raise AppError("browser_unavailable", "请先安装可选的 browser 依赖，再安装 Chromium；默认 HTTP 登录无需浏览器。")
            return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if args.command in (None, "serve"):
            from .server import build_server
            transport = getattr(args, "transport", "stdio")
            if name := getattr(args, "name", None):
                import os
                import re
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name) is None:
                    raise AppError("invalid_instance_name", "实例名仅接受字母数字、下划线或短横线，最多64字符。")
                os.environ["STU_MCP_INSTANCE_NAME"] = name
            if transport == "stdio":
                if (getattr(args, "auth_token_file", None) or getattr(args, "public_url", None)
                        or getattr(args, "host", "127.0.0.1") != "127.0.0.1"
                        or getattr(args, "port", 8765) != 8765):
                    raise AppError("invalid_transport_options", "HTTP 选项需要 --transport streamable-http。")
                build_server().run(transport="stdio")
            else:
                from .hosting import HostRuntime
                from .transports.http import HTTPSettings, load_bearer, run_http
                settings = HTTPSettings(args.host, args.port, args.public_url)
                settings.security()
                load_bearer(args.auth_token_file)
                host = HostRuntime(transport=transport)
                try:
                    run_http(build_server(host=host), settings, args.auth_token_file)
                finally:
                    host.close()
            return 0
        if args.command == "server-init":
            from .server_init import initialize_secrets
            return emit(initialize_secrets(args.directory))
        if args.command == "clients":
            return emit({"ok": True, "clients": catalog()})
        if args.command == "skill-export":
            return emit(export_skill(Runtime.default(), apply=args.apply, name=args.skill))
        if args.command == "network":
            from .connectivity import NetworkDiagnostics
            return emit(NetworkDiagnostics().diagnose(args.service_id, args.location_hint, args.refresh,
                                                     check_login=args.check_login, compare_proxy=args.compare_proxy))
        if args.command == "network-audit":
            from .network_audit import NetworkAudit
            return emit(NetworkAudit().audit(args.location_hint, compare_public_dns=args.compare_public_dns,
                                              refresh=args.refresh))
        if args.command == "transport":
            runtime = Runtime.default()
            updates = {key: value == "on" for key, value in
                       (("jw_http_compat", args.jw_http), ("oa_http_compat", args.oa_http)) if value is not None}
            if updates:
                runtime.save_preferences(updates)
            return emit({"ok": True, "transport": runtime.preferences(),
                         "message": "HTTP兼容仅限已核验的学校官方路线；密码及动态码始终使用HTTPS。"})
        if args.command == "repair":
            from .features.repair import RepairDrafts
            from .features.repair.models import ACTIVE
            try:
                if hasattr(sys.stdin, "reconfigure"):
                    sys.stdin.reconfigure(encoding="utf-8")
                if args.fields_file:
                    with args.fields_file.open(encoding="utf-8") as fields_stream:
                        raw = fields_stream.read(8193)
                else:
                    raw = sys.stdin.read(8193)
                fields = json.loads(raw) if len(raw) <= 8192 else None
                if not isinstance(fields, dict) or "draft_id" in fields:
                    raise ValueError
            except (ValueError, TypeError):
                raise AppError("invalid_repair_fields", "请从标准输入提供不超过8192字的报修字段JSON对象。") from None
            if args.browser and (args.repair_action != "preview" or args.submit):
                raise AppError("invalid_repair_action", "浏览器兼容只用于不提交的 preview。", "repair")
            if args.repair_action in {"drill", "preview"} and not args.browser:
                from .features.repair.cli import run_cli
                from .vault import Vault
                result = run_cli(Vault(Runtime.default()), fields=fields, submit=args.submit, output=emit)
                return 0 if result.get("ok", True) else 1
            if args.submit:
                raise AppError("invalid_repair_action", "提交选项只用于本人终端中的报修演练。", "repair")
            if args.browser:
                from .features.repair.adapter import open_browser
                drafts = RepairDrafts(open_browser)
            else:
                drafts = RepairDrafts()
            result = drafts.prepare(**fields)
            if args.repair_action == "plan" or result["problems"]:
                return emit(result)
            try:
                result = drafts.open(result["draft_id"])
                previous = None
                while True:
                    if result["status"] != previous:
                        emit(result)
                        previous = result["status"]
                    if result["status"] not in ACTIVE:
                        return 0 if result["status"] in {"closed", "preview_expired"} else 1
                    time.sleep(.5)
                    result = drafts.snapshot(result["draft_id"])
            except KeyboardInterrupt:
                return 0
            finally:
                drafts.shutdown()
        if args.command == "login" and args.service == "duifene":
            if args.browser or args.allow_http_callback:
                raise AppError("invalid_login_options", "对分易沿用原微信回调登录，不使用这些选项。")
            from .checkin_login import login_via_callback
            return emit(login_via_callback())
        if args.command == "login":
            if args.allow_http_callback and args.service != "jw":
                raise AppError("invalid_login_options", "HTTP票据回调选项只适用于教务。")
            if args.browser and args.allow_http_callback:
                raise AppError("invalid_login_options", "本次回调选项用于HTTP登录；浏览器兼容请先明确设置教务传输兼容。")
            if args.browser and args.service == "repair":
                raise AppError("invalid_login_options", "报修CLI使用独立HTTP登录，请运行 login repair。")
            if not args.browser:
                from .terminal import require_terminal
                require_terminal()
        if args.command == "webvpn-auto" and args.auto_action == "configure":
            from .terminal import require_terminal
            require_terminal()
        app = App()
        if args.command == "webvpn-auto":
            from .webvpn import WebVPNConfig
            if args.auto_action == "configure":
                from .webvpn_cli import configure
                return emit(configure(app.vault, encoding=args.encoding))
            config = WebVPNConfig(app.vault)
            return emit({"ok": True, **config.status()} if args.auto_action == "status" else config.remove())
        if args.command == "charging":
            if args.charging_action == "overview":
                return emit(app.charging_overview(args.location, args.limit, args.offset, not args.local))
            return emit(app.charging_device(args.device_code, not args.local))
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
            ui = SetupServer(app, port=args.port)
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
            if args.browser:
                return emit(interactive_login(app.vault, args.service))
            from .auth_http import login_http
            return emit(login_http(app.vault, args.service, allow_http_callback=args.allow_http_callback))
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
        if args.command in (None, "serve"):
            print(exc.message, file=sys.stderr)
            return 1
        return emit(exc.result())
    except KeyboardInterrupt:
        return 130
    except Exception:
        if args.command in (None, "serve"):
            print("STU MCP 启动失败，请运行 stu-mcp status 检查本地状态。", file=sys.stderr)
            return 1
        return emit(AppError("operation_failed", "操作未完成；未输出认证信息。请检查本地状态或重试。").result())
    return 0
