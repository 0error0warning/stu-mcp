"""User-facing configuration families and exact business scopes, not access policy.

This metadata never grants a source, URL, login or network probe permission. Build
the view from already-read local status only; saved sessions do not prove that a
school endpoint or its business data can currently be read.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

CATALOG_VERIFIED_ON = "2026-10-22"
_INVENTORY = "docs/verification/2026-10-22-campus-entries.md"
_HTTP_VERIFICATION = "docs/verification/2026-10-21-http-default.md"
_AUTH_STATUSES = frozenset({"session_saved", "needs_login", "login_expired", "session_invalid",
                            "secure_storage_unavailable", "not_required", "unknown"})
_WORKER_STATUSES = frozenset({"service_not_started", "not_logged_in", "paused", "monitoring", "query_error",
                              "starting", "stopping"})
_READ_STATUSES = frozenset({"ok", "partial", "needs_login", "login_expired", "session_invalid", "source_error",
                            "network_error", "schema_changed", "secure_storage_unavailable"})


def _known_status(value: Any, known: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in known else "unknown"


def _feature(feature_id: str, label: str, *tools: str) -> dict:
    return {"id": feature_id, "label": label, "tools": list(tools)}


def _service(service_id: str, label: str, configuration_id: str, auth_family: str, *,
             scope: str, entries: tuple[str, ...] = (), source_id: str | None = None,
             login_id: str | None = None, features: tuple[dict, ...] = (),
             integration: str = "implemented", limits: tuple[str, ...] = (),
             evidence_level: str = "implementation", evidence_on: str = CATALOG_VERIFIED_ON,
             evidence_document: str = _INVENTORY, configuration_ids: tuple[str, ...] = ()) -> dict:
    return {"service_id": service_id, "label": label, "configuration_id": configuration_id,
            "configuration_ids": list(configuration_ids or (configuration_id,)), "auth_family": auth_family,
            "integration": integration, "scope": scope, "entry_urls": list(entries), "source_id": source_id,
            "login_id": login_id, "setup_command": f"stu-mcp login {login_id}" if login_id else None,
            "features": list(features), "limits": list(limits),
            "evidence": {"level": evidence_level, "verified_on": evidence_on, "document": evidence_document}}


_SERVICES = (
    _service("public_notices", "官网与学生处通知", "anonymous", "anonymous", source_id="public",
             scope="学校官网、学生处已适配栏目及本地通知缓存",
             entries=("https://www.stu.edu.cn/", "https://xsc.stu.edu.cn/"),
             features=(_feature("public_notices", "通知、活动、正文与附件文字", "refresh_source",
                                "search_notices", "get_notice", "read_attachment"),),
             limits=("缓存搜索不是全校或全部历史通知搜索；附件支持 PDF/文本，扫描件不做 OCR。",)),
    _service("oa_notices", "OA 通知读取", "anonymous", "anonymous_or_webvpn", source_id="oa",
             login_id="webvpn", configuration_ids=("anonymous", "webvpn"),
             scope="允许匿名直读的公告，或已配置 WebVPN 路由可读的通知与附件",
             entries=("http://oa.stu.edu.cn/login/Login.jsp?logintype=1",),
             features=(_feature("oa_notices", "通知列表、正文、附件列表及 PDF/文本附件", "refresh_source",
                                "search_notices", "get_notice", "read_attachment"),),
             limits=("优先匿名直读；网络、内容权限与附件格式分别决定可读范围。",
                     "WebVPN 登录只提供另一条访问通道，不保证所有正文和附件可读。"),
             evidence_level="anonymous_content_sample", evidence_document=
             "docs/verification/2026-10-22-oa-entry-boundaries.md"),
    _service("jw_academics", "教务成绩、考试与课表", "school", "school_cas", source_id="jw", login_id="jw",
             scope="本人教务成绩、学分加权统计、考试安排与按学期读取的理论课表",
             entries=("https://jw.stu.edu.cn/jwglxt/xtgl/login_slogin.html",),
             features=(_feature("grades", "成绩与加权统计", "refresh_source", "get_grades", "academic_summary"),
                       _feature("exams", "考试安排", "refresh_source", "get_exams"),
                       _feature("academic_timetable", "本人理论课表（按需读取）", "get_academic_timetable")),
             limits=("课表会列出读取范围和待核对项；实验课表、选课和评教尚未接入。",
                     "周次和节次不等于日期；导出仍需核对最新校历、作息与调课安排。",
                     "设置页使用已验证的学校官方登录路线；CLI 可用 --allow-http-callback 兼容旧入口。"),
             evidence_level="authenticated_http_read", evidence_on="2026-10-21",
             evidence_document=_HTTP_VERIFICATION),
    _service("mystu_learning", "MySTU 课程与待办", "school", "school_cas", source_id="mystu", login_id="mystu",
             scope="MySTU 本人课程、课程所属 Moodle/ELC/Campus 活动与有限时间窗个人日程",
             entries=("https://my.stu.edu.cn/discussion/my-courses", "https://my.stu.edu.cn/courses/elc/"),
             features=(_feature("mystu_courses", "课程、作业/测验及课程资料", "refresh_source", "get_courses",
                                "get_tasks", "get_course_resources"),
                       _feature("personal_calendar", "个人日程（过去 7 天至未来 31 天）", "refresh_source",
                                "get_schedule")),
             limits=("课程读取不包含同域 ELC/CILL 预约；个人日程不是完整学期课表。",
                     "课程关联的 Moodle/ELC 页面仍按各自实际会话和读取结果核实。"),
             evidence_level="authenticated_http_read", evidence_on="2026-10-21",
             evidence_document=_HTTP_VERIFICATION),
    _service("sangpushan_repair", "桑浦山宿舍设施报修", "school", "school_cas", login_id="repair",
             scope="repair.stu.edu.cn 桑浦山学生社区表单与本进程草稿的提交回执",
             entries=("https://repair.stu.edu.cn/",),
             features=(_feature("dorm_repair", "报修草稿、完整预览、确认后单次提交及回执核查",
                                "prepare_repair_draft", "open_repair_form", "get_repair_draft",
                                "review_repair_draft", "submit_repair_draft", "check_repair_submission",
                                "close_repair_form"),),
             limits=("不覆盖 r 综合报修、校园网报修或任意历史工单管理。",
                     "提交必须先完整展示实际表单并等待本人确认；HTTP 最终写入尚无新增真实工单验收。"),
             evidence_level="http_login_and_form_review", evidence_on="2026-10-21",
             evidence_document=_HTTP_VERIFICATION),
    _service("yuketang_learning", "雨课堂课程与待办", "yuketang", "official_phone_qr", source_id="yuketang",
             login_id="yuketang", scope="本人雨课堂课程、作业/测验、活动/资源与课程公告",
             entries=("https://changjiang.yuketang.cn/",),
             features=(_feature("yuketang_courses", "课程、作业/测验及活动/资源", "refresh_source", "get_courses",
                                "get_tasks", "get_course_resources"),
                       _feature("course_notices", "课程公告", "refresh_source", "search_notices", "get_notice")),
             limits=("官方二维码需本人手机授权；MCP 宿主无需启动浏览器。",
                     "公告正文随来源刷新进入缓存；get_notice 不支持对雨课堂单篇联网刷新，也不支持附件文字提取。"),
             evidence_level="authenticated_http_read", evidence_on="2026-10-21",
             evidence_document=_HTTP_VERIFICATION),
    _service("duifene_checkin", "对分易", "duifene", "wechat_callback", login_id="duifene",
             scope="本人课程选择、明确启动的独立监听与结果查询", entries=("https://www.duifene.com/",),
             features=(_feature("checkin", "课程、监听控制与结果", "get_checkin_status", "open_checkin_page",
                                "list_checkin_courses", "select_checkin_courses", "start_checkin_monitor",
                                "pause_checkin_monitor", "get_checkin_results", "stop_checkin_service"),),
             limits=("沿用原微信回调；登录不会新建监听计划。",
                     "状态读取不会启动 worker；自动化测试不是真实课堂提交验收。"),
             evidence_level="implemented_callback_flow", evidence_document="docs/checkin.md"),
    _service("campus_navigation", "学校服务入口导航", "anonymous", "anonymous",
             scope="官网缓存与维护目录中的入口、用途和核验范围",
             features=(_feature("service_navigation", "查找学校服务入口", "get_service_links"),),
             limits=("入口导航不办理对应业务，不代表已登录或站点当前可达。",)),
    _service("campus_network_diagnostics", "校园连接与入口检测", "anonymous", "anonymous",
             scope="固定服务的单站点诊断，以及固定学校入口目录的批量匿名检测",
             features=(_feature("network_diagnostics", "单站点诊断与学校入口批量检测", "diagnose_campus_network",
                                "audit_campus_network"),),
             limits=("不是全校域名扫描；匿名端点可达不证明认证或业务成功，不改变代理、DNS 或路由。",)),
    _service("public_charging", "充电设备状态（第三方）", "anonymous", "anonymous", source_id="charging",
             scope="已核验的第三方充电设备清单和插座状态",
             features=(_feature("charging", "按位置查设备和逐口状态", "get_charging_overview",
                                "get_charging_device"),),
             limits=("不是全校完整清单；只读状态，不启动充电或支付。",)),
    _service("huyou_public", "狐友公开讨论（第三方）", "anonymous", "anonymous", source_id="huyou",
             scope="选定公开圈子的字面词搜索、帖子与讨论",
             features=(_feature("huyou", "公开圈子、帖子、评论与回复", "search_huyou_posts", "get_huyou_post",
                                "search_huyou_circles"),),
             limits=("不是学校官方通知；不读取账号私密内容。",)),
    _service("takeout_catalog", "外卖目录与选餐（实验）", "takeout", "third_party_configuration",
             scope="第三方平台商家、菜单、配送批次、规格和非交易选餐",
             features=(_feature("takeout", "商家、菜单、配送批次与选餐", "search_takeout_shops",
                                "find_takeout_meal_shops", "get_takeout_delivery_slots", "get_takeout_shop",
                                "get_takeout_menu", "get_takeout_product", "prepare_takeout_selection"),),
             limits=("不使用学校登录；不提交订单、支付或修改地址。",)),
    _service("local_maintenance", "工具维护与反馈", "local", "none",
             scope="MCP 宿主上的安装、配置、更新、本地待办、资料偏好、课表文件转换与向维护者反馈",
             features=(_feature("maintenance", "能力与配置引导、更新、本地待办和个人偏好", "get_capabilities",
                                "open_setup", "check_updates", "update_self", "set_task_status",
                                "set_student_profile"),
                       _feature("timetable_conversion", "已有课表文件转换（CLI/技能）"),
                       _feature("agent_feedback", "向维护者提交脱敏反馈", "report_feedback")),
             limits=("文件转换不代表已自动获取学期课表；课表与校历核对仍有独立步骤。",
                     "反馈先本地预览，完整展示接收方与准确内容，须等待本轮用户明确同意后外发。",
                     "优先脱敏示例；个人业务信息须确实必要且逐项同意，凭据始终禁止外发。")),
    _service("campus_card", "一卡通本人查询", "smartcard", "independent_query_password_captcha",
             source_id="smartcard", login_id="smartcard",
             scope="本人卡概况、余额、状态及按日期和类型读取的历史流水",
             entries=("http://smartcard.stu.edu.cn/homeLogin.action",),
             features=(_feature("campus_card", "卡概况与余额", "get_campus_card"),
                       _feature("campus_card_transactions", "本人历史流水", "get_campus_card_transactions")),
             limits=("独立一卡通查询密码和本人填写的图片验证码，不属于学校统一账号配置。",
                     "学校官方入口为明文 HTTP；只向固定一卡通入口提交其独立查询密码。",
                     "不接入挂失、充值、改密、完整个人资料或统计图；分页未核实范围明确报告。"),
             evidence_level="implementation", evidence_on="2026-10-24", evidence_document="docs/smartcard.md"),
)


def _gap(service_id: str, label: str, entry: str, scope: str, *, configuration_id: str = "unverified",
         auth_family: str = "not_verified", integration: str = "not_integrated",
         evidence_level: str = "published_entry", evidence_on: str = CATALOG_VERIFIED_ON) -> dict:
    return _service(service_id, label, configuration_id, auth_family, scope=scope, entries=(entry,),
                    integration=integration, evidence_level=evidence_level, evidence_on=evidence_on,
                    limits=("没有该业务适配器；配置同类账号或其他同域功能不会自动接入本业务。",))


_GAPS = (
    _gap("school_service_portal", "一网通办事项目录与申请", "https://service.stu.edu.cn/fe/",
         "已维护入口；未读取全部事项、办理目标或提交申请", configuration_id="school", auth_family="school_cas",
         integration="navigation_only", evidence_level="authenticated_directory_sample", evidence_on="2026-10-18"),
    _gap("campus_repair", "校园综合报修（含网络故障）", "https://r.stu.edu.cn/",
         "两校区综合故障表单；本人请求、状态和提交均未接入", configuration_id="school", auth_family="school_cas",
         integration="navigation_only", evidence_level="authenticated_form", evidence_on="2026-10-18"),
    _gap("network_account", "上网账号与套餐", "https://netms.stu.edu.cn/",
         "套餐、余额、到期与账号业务待核实", configuration_id="school", auth_family="school_cas",
         integration="navigation_only", evidence_level="anonymous_sso_redirect"),
    _gap("network_repair", "ITS 校园网报修原有引用", "http://its.stu.edu.cn/",
         "原有网络报修引用，停用或迁移未证实", integration="navigation_only",
         evidence_level="published_reference_not_workflow", evidence_on="2026-10-18"),
    _gap("student_affairs", "学生事务", "https://xg.stu.edu.cn/",
         "本人可访问菜单及当期事项待核实", configuration_id="school", auth_family="school_cas",
         evidence_level="anonymous_sso_redirect"),
    _gap("dorm_management", "宿舍管理与查询", "http://dorm.stu.edu.cn/",
         "与学工的现行分工待核实；不是设施报修", configuration_id="school", auth_family="school_cas",
         evidence_level="anonymous_sso_redirect"),
    _gap("dorm_utilities", "宿舍水电", "http://power.stu.edu.cn/",
         "现行安全入口、本人房间关联、余额及用量待核实", configuration_id="school", auth_family="school_cas",
         evidence_level="anonymous_sso_redirect"),
    _gap("library_catalog", "公开馆藏检索", "https://opac.lib.stu.edu.cn/opac.php",
         "书目、分馆及馆藏查询", configuration_id="anonymous", auth_family="anonymous",
         evidence_level="official_access_description"),
    _gap("library_resources", "图书馆数据库目录", "https://www.lib.stu.edu.cn/zy/database",
         "公开资源导航及访问说明；订购全文权限另核实", configuration_id="anonymous", auth_family="anonymous",
         evidence_level="official_access_description"),
    _gap("library_reader", "本人借阅与到期", "https://opac.lib.stu.edu.cn/web/index.html?type=reader",
         "馆内账号/一卡通及 MySTU 入口有官方说明，实际认证和本人借阅未验证",
         auth_family="library_account_or_mystu_unverified", evidence_level="official_access_description"),
    _gap("library_space", "图书馆空间预约", "https://app.lib.stu.edu.cn/newic/",
         "校区、空间、时段与认证待核实", evidence_level="official_entry"),
    _gap("campus_booking", "校园预约平台", "https://ehall.stu.edu.cn/yy-sys/pc/home",
         "具体预约对象与认证未核实", evidence_level="official_entry"),
    _gap("slc_booking", "SLC/活动预约中心", "https://booking.stu.edu.cn/",
         "预约对象和现行认证未核实"),
    _gap("classroom_booking", "教室预约", "https://classroom.stu.edu.cn/",
         "现行预约对象和权限未核实", configuration_id="school", auth_family="school_cas",
         evidence_level="anonymous_sso_redirect"),
    _gap("elc_cill_booking", "ELC/CILL 预约", "http://my.stu.edu.cn/courses/elc/blocks/mrbs/web/index.php",
         "具体预约路径未验证；同域课程活动适配不覆盖预约", auth_family="not_verified_for_business_path"),
)

_PROFILES = (
    ("anonymous", "无需学校登录", "anonymous", None,
     "公开查询仍取决于宿主网络、目标内容权限和实际读取结果。"),
    ("school", "学校统一账号", "school_cas", "stu-mcp login school",
     "一次输入学校账号，为已接入业务分别认证并保存独立会话，不保存密码。"
     "设置页自动连接已接入业务；CLI 保留业务筛选及官方旧入口的兼容参数。"),
    ("webvpn", "WebVPN 登录", "webvpn", "stu-mcp login webvpn",
     "只为已适配的 OA 读取提供另一条访问通道；不是新增学校业务授权。"),
    ("yuketang", "雨课堂授权", "official_phone_qr", "stu-mcp login yuketang",
     "本人手机确认官方二维码，宿主通过 HTTP 建立独立会话。"),
    ("duifene", "对分易授权", "wechat_callback", "stu-mcp login duifene",
     "沿用原微信回调和独立后台；登录不新建监听计划。"),
    ("smartcard", "一卡通查询", "independent_query_password_captcha", "stu-mcp login smartcard",
     "本人使用独立查询密码并填写正常图片验证码；官方入口为明文 HTTP，不保存查询密码。"),
    ("takeout", "外卖平台配置（实验）", "third_party_configuration", "stu-mcp takeout configure --file <文件>",
     "仅在宿主导入第三方配置，不使用学校账号。"),
    ("local", "本地工具维护", "none", None,
     "不需要学校登录；操作范围是 MCP 宿主，本地文件转换不是学校业务接入。"),
)


def _indexed_statuses(statuses: Iterable[Mapping] | Mapping) -> dict[str, Mapping]:
    if isinstance(statuses, Mapping):
        return {key: value for key, value in statuses.items() if isinstance(value, Mapping)}
    return {row["source"]: row for row in statuses if isinstance(row, Mapping) and isinstance(row.get("source"), str)}


def _auth_state(raw: Mapping | None, *, required: bool) -> dict:
    raw = raw if isinstance(raw, Mapping) else {}
    status = raw.get("status", "unknown") if required else "not_required"
    status = _known_status(status, _AUTH_STATUSES)
    messages = {"session_saved": "已保存此业务会话，尚未检查当前读取。", "needs_login": "尚未登录此业务。",
                "login_expired": "此业务会话已过期。", "session_invalid": "此业务保存的会话无效。",
                "secure_storage_unavailable": "无法访问安全存储。", "not_required": "无需学校登录。",
                "unknown": "尚未读取此业务的本地认证状态。"}
    return {"status": status, "message": messages[status], "authentication": status,
            "session_saved": None if status == "unknown" else status == "session_saved",
            "current_access": "not_checked", "business_read": "not_checked"}


def _timestamp(value: Any) -> str | int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\d[T ][\d:.+Z-]+", value):
        return value
    return None


def build_capability_catalog(source_statuses: Iterable[Mapping] | Mapping = (), *,
                             repair_status: Mapping | None = None, checkin_status: Mapping | None = None,
                             takeout_status: Mapping | None = None,
                             freshness: Iterable[Mapping] | Mapping = ()) -> dict:
    """Describe configuration outcomes without I/O or copying private status data.

    ``source_statuses`` accepts App.status()['sources'] or a source-keyed mapping;
    repair_status is the already-read Vault.status('repair'), not its capability
    metadata. All authentication/network freshness remains explicitly unverified.
    """
    sources, refreshes = _indexed_statuses(source_statuses), _indexed_statuses(freshness)
    sessions = {source: row.get("auth", row) for source, row in sources.items()}
    sessions["webvpn"] = sessions.get("webvpn", sessions.get("oa", {}))
    sessions["repair"] = repair_status or {}
    services = deepcopy(_SERVICES + _GAPS)
    for service in services:
        login_id = service["login_id"]
        if service["integration"] != "implemented":
            service["state"] = {"status": "not_integrated", "message": "尚无此业务适配器。",
                                "authentication": "not_integrated", "current_access": "not_checked",
                                "business_read": "not_checked"}
            continue
        service["state"] = _auth_state(sessions.get(login_id), required=login_id is not None)
        if service["service_id"] == "oa_notices":
            service["state"] = _auth_state(None, required=False)
            service["state"]["alternate_access"] = {"webvpn": _auth_state(sessions["webvpn"], required=True)}
        fresh = refreshes.get(service["source_id"], {})
        if fresh:
            service["state"]["last_refresh"] = {
                "status": _known_status(fresh.get("status"), _READ_STATUSES),
                "attempted_at": _timestamp(fresh.get("attempted_at")),
                "success_at": _timestamp(fresh.get("success_at")),
                "historical": True}
        if service["configuration_id"] == "duifene":
            worker = checkin_status or {}
            service["state"] = {"worker_status": _known_status(worker.get("status"), _WORKER_STATUSES),
                                "service_running": worker.get("service_running")
                                if type(worker.get("service_running")) is bool else None,
                                "logged_in": worker.get("logged_in") if type(worker.get("logged_in")) is bool else None,
                                "monitoring": worker.get("monitoring") if type(worker.get("monitoring")) is bool else None,
                                "current_access": "not_checked", "business_read": "not_checked"}
            service["state"]["status"] = service["state"]["worker_status"]
            service["state"]["message"] = {
                "unknown": "尚未读取对分易后台状态，可通过状态工具或对分易页面检查。",
                "service_not_started": "对分易服务尚未启动。",
                "not_logged_in": "对分易尚未登录。", "paused": "对分易监听已暂停。",
                "monitoring": "对分易正按已授权计划监听；尚未核验当前课堂业务。",
                "query_error": "对分易最近一次查询失败，请查看状态详情。",
                "starting": "对分易服务正在启动。", "stopping": "对分易服务正在停止。",
            }[service["state"]["status"]]
        elif service["configuration_id"] == "takeout":
            configured = (takeout_status or {}).get("configured")
            service["state"] = {"configuration_saved": configured if type(configured) is bool else None,
                                "current_access": "not_checked", "business_read": "not_checked"}
            service["state"]["status"] = ("configuration_saved" if configured is True else "not_configured"
                                           if configured is False else "unknown")
            service["state"]["message"] = "配置保存状态不证明平台当前可读。"
    profiles = []
    for profile_id, label, auth_family, command, note in _PROFILES:
        supported = [item for item in services if profile_id in item["configuration_ids"]
                     and item["integration"] == "implemented"]
        gaps = [item for item in services if profile_id in item["configuration_ids"]
                and item["integration"] != "implemented"]
        features = [dict(feature, service_id=item["service_id"]) for item in supported for feature in item["features"]]
        if profile_id == "webvpn":
            features = [_feature("oa_access_channel", "为 OA 通知读取提供另一条访问通道", "refresh_source",
                                 "get_notice", "read_attachment")]
        states = {item["service_id"]: deepcopy(item["state"]) for item in supported}
        if profile_id == "webvpn":
            states = {"oa_notices": deepcopy(states["oa_notices"]["alternate_access"]["webvpn"])}
        state = {"current_access": "not_checked", "business_read": "not_checked", "services": states}
        if profile_id == "school":
            saved = sum(item.get("session_saved") is True for item in states.values())
            state.update(status="sessions_saved" if saved == len(states) else "partially_configured" if saved
                         else "needs_login" if all(item["status"] != "unknown" for item in states.values())
                         else "unknown", saved_session_count=saved, session_count=len(states),
                         message="各业务会话独立；已保存会话仍需实际读取核实。")
        elif len(states) == 1:
            state.update(status=next(iter(states.values()))["status"],
                         message=next(iter(states.values()))["message"])
        else:
            state.update(status="not_required", message="无需学校登录，实际可读范围须分别核实。")
        profiles.append({"configuration_id": profile_id, "label": label, "auth_family": auth_family,
                         "setup_command": command, "setup_on": "mcp_host", "note": note,
                         "setup_ui": {"available": profile_id in {"school", "webvpn", "yuketang", "duifene", "smartcard"},
                                      "tool": "open_setup", "backend": "http"},
                         "service_ids": [item["service_id"] for item in supported],
                         "not_integrated_service_ids": [item["service_id"] for item in gaps],
                         "features": features, "state": state,
                         "sessions_shared": False})
    return {"catalog_version": 1, "schema_implemented_on": "2026-10-23", "verified_on": CATALOG_VERIFIED_ON,
            "profiles": profiles, "services": services,
            "state_scope": "already_read_local_status_not_live_business_verification"}
