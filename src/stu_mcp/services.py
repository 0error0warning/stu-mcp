"""Verified service purposes, separate from cached labels and live availability."""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import parse_qsl, urlparse

from .access_policy import policy_for_url
from .network import AUTH_QUERY_KEYS
from .parsing import item_id

VERIFIED_ON = "2026-10-18"
QUICK_LINKS = "https://www.stu.edu.cn/kstd.htm"
NETWORK_REPAIR_REFERENCE = "https://info.stu.edu.cn/its/info/1184/4090.htm"

# Exact hosts identify different businesses. Sharing school SSO does not merge them.
SERVICE_DIRECTORY = {
    "www.stu.edu.cn": {
        "service_id": "school_homepage", "title": "汕头大学官网", "url": "https://www.stu.edu.cn/",
        "purpose": "学校公开新闻、通知与服务入口。", "keywords": ["官网", "学校", "通知"],
        "evidence_urls": [QUICK_LINKS],
    },
    "its.stu.edu.cn": {
        "service_id": "network_repair", "title": "校园网报修原有引用（待核实）", "url": "http://its.stu.edu.cn/",
        "purpose": "网络中心公开说明保留的校园网故障报修地址。", "campus": None,
        "keywords": ["校园网", "网络", "上网", "故障", "报修", "校园网报修", "网络报修", "网络故障", "上网故障", "断网"],
        "evidence_urls": [NETWORK_REPAIR_REFERENCE, "https://repair.stu.edu.cn/"],
        "recommended": False, "migration_confirmed": False, "alternative_service_ids": ["campus_repair"],
        "last_connection_check": {"checked_on": VERIFIED_ON, "access": "anonymous_campus_direct",
                                  "http": "connection_refused", "https": "connect_timeout"},
        "verification_note": "原有公开引用仍在；本次校园网直连失败，未找到停用或迁移公告，不能认定已正式废弃。优先查看已核验网络故障表单的 r.stu.edu.cn。",
    },
    "repair.stu.edu.cn": {
        "service_id": "sangpushan_repair", "title": "桑浦山宿舍网上报修",
        "url": "https://repair.stu.edu.cn/", "purpose": "桑浦山校区学生社区、宿舍设施报修。",
        "campus": "桑浦山", "keywords": ["桑浦山", "宿舍", "学生社区", "设施", "网上报修", "宿舍报修", "宿舍维修", "空调"],
        "evidence_urls": [QUICK_LINKS, "https://repair.stu.edu.cn/"],
        "form_verified": True, "form_verified_on": "2026-10-19", "draft_fill_verified": True,
        "native_browser_live_verified": True,
        "native_browser_verification_scope": "shared_adapter_cli_login_fill_readback",
        "last_live_verification": {"checked_on": "2026-10-19", "access": "user_browser_school_sso",
                                   "scope": "authenticated_dorm_air_conditioner_draft", "request_submitted": False},
        "mcp_draft_tool": "prepare_repair_draft", "mcp_preview_tool": "open_repair_form",
        "mcp_review_tool": "review_repair_draft", "mcp_submit_tool": "submit_repair_draft",
        "confirmation_required": True, "submission_supported": True,
        "verification_note": "已实际填写并回读空调故障草稿，未提交；无故障类别下拉框。姓名、学院、准确楼座、电话、邮箱、标题、发生地址、描述及预约日期/起止时间必填；楼座不能凭B栋简称推断。首页仍把网络方面报修指向 its。",
    },
    "r.stu.edu.cn": {
        "service_id": "campus_repair", "title": "校园综合报修（含网络故障）", "url": "https://r.stu.edu.cn/",
        "purpose": "综合故障报修；分类包含网络故障、应用系统故障、一卡通、电话、门禁、多媒体及设施故障。",
        "campus": "桑浦山、东海岸", "campuses": ["桑浦山", "东海岸"],
        "keywords": ["校园网", "网络报修", "校园网报修", "网络故障", "上网故障", "断网", "东海岸", "桑浦山",
                     "网上报修", "报修系统", "东海岸报修", "东海岸网上报修", "应用系统故障", "一卡通故障", "设施报修",
                     "空调", "空调故障"],
        "evidence_urls": ["https://r.stu.edu.cn/WorkOrder.do?woMode=newWO", QUICK_LINKS,
                          "https://stuecc.stu.edu.cn/info/1032/1139.htm"],
        "recommended": True, "form_verified": True, "form_verified_on": VERIFIED_ON,
        "last_live_verification": {"checked_on": VERIFIED_ON, "access": "user_browser_school_sso",
                                   "scope": "authenticated_request_form", "category": "网络故障",
                                   "campus_options": ["桑浦山校区", "东海岸校区"], "request_submitted": False},
        "workflow_steps": ["打开 https://r.stu.edu.cn/，选择 SSO单点登录并完成学校认证。",
                           "进入“请求”页，点击“新建”。",
                           "在“校区”选择实际校区，在“分类”选择“网络故障”。",
                           "填写详细故障地址、联系人电话、预约时间和主题，并在描述中说明故障现象。",
                           "核对后由用户点击“添加请求”；本项目未验证提交或实际受理。"],
        "alternate_channels": [{"type": "wechat_mini_program", "name": "汕大报修",
                                "evidence_url": "https://stuecc.stu.edu.cn/info/1032/1139.htm",
                                "verification_scope": "official_guide_only", "workflow_verified": False}],
        "support_contacts": [{"campus": "桑浦山", "phone": "0754-86503400-1"},
                             {"campus": "东海岸", "phone": "0754-86500115"}],
        "contact_evidence_url": "https://info.stu.edu.cn/its/info/1040/4020.htm",
        "contact_verification_scope": "official_listing_not_called",
        "verification_note": "2026-10-18 已实际登录并选择网络故障分类，展开校区确认两校区选项；官网快捷链接仍称东海岸网上报修，但表单范围更广。未提交工单。",
    },
    "a.stu.edu.cn": {
        "service_id": "network_access", "title": "校园网上网认证", "url": "https://a.stu.edu.cn/",
        "purpose": "校园网接入、上网认证。", "keywords": ["校园网", "上网", "认证", "直通车"],
        "evidence_urls": [QUICK_LINKS],
    },
    "netms.stu.edu.cn": {
        "service_id": "network_account", "title": "上网套餐与校内账号服务",
        "url": "https://netms.stu.edu.cn/", "purpose": "上网流量套餐预订、校内账号密码管理。",
        "keywords": ["上网", "流量", "套餐", "账号", "密码"], "evidence_urls": [QUICK_LINKS],
    },
    "sso.stu.edu.cn": {
        "service_id": "school_sso", "title": "学校统一认证", "url": "https://sso.stu.edu.cn/",
        "purpose": "学校统一登录与业务系统认证跳转。", "keywords": ["登录", "统一认证", "SSO"],
        "evidence_urls": ["https://repair.stu.edu.cn/"],
    },
    "uptime.stu.edu.cn": {
        "service_id": "network_information", "title": "网络与校园卡服务旧版网站",
        "url": "http://uptime.stu.edu.cn/", "purpose": "网络与校园卡服务信息、旧版网络中心网站。",
        "keywords": ["网络中心", "校园卡", "网络服务", "旧版"],
        "evidence_urls": ["https://info.stu.edu.cn/its/index.htm"],
    },
    "d.stulip.org": {
        "service_id": "community_navigation", "title": "郁金香校园导航", "url": "https://d.stulip.org/",
        "purpose": "郁金香 BBS 筹建的校园网址与电话导航。", "official": False,
        "keywords": ["郁金香", "导航", "百事通"], "evidence_urls": ["https://d.stulip.org/"],
    },
    "service.stu.edu.cn": {
        "service_id": "school_service_portal", "title": "一网通办服务大厅",
        "url": "https://service.stu.edu.cn/fe/", "purpose": "学校业务服务目录与申请入口，包含网络服务专题。",
        "keywords": ["一网通办", "服务大厅", "网络服务", "科研流量包", "防火墙网络", "WebVPN开通", "国际学术资源访问"],
        "evidence_urls": [QUICK_LINKS, "https://service.stu.edu.cn/fe/site/themeServiceDetails?topic_id=3"],
        "topic_services": ["科研流量包", "防火墙网络", "校外人员WebVPN开通", "国际学术资源访问申请"],
        "verification_note": "2026-10-18 已在浏览器查看登录后的网络服务专题；当时列出四类申请，未将其当作网络故障工单或与 r 合并。",
    },
}
MAINTAINED_HOSTS = ("r.stu.edu.cn", "repair.stu.edu.cn", "its.stu.edu.cn", "service.stu.edu.cn")


def describe_service(record: dict) -> dict | None:
    """Classify exact hosts; never expose a login callback ticket as an entry."""
    try:
        parsed = urlparse(str(record.get("url", "")))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        port = parsed.port
    except ValueError:
        return None
    spec = SERVICE_DIRECTORY.get(parsed.hostname) if port in (None, 80, 443) else None
    if spec is None:
        if any(key.lower() in AUTH_QUERY_KEYS for key, _ in parse_qsl(parsed.query)):
            return None
        return {**record, "purpose_verified": False, "availability": "not_checked"}
    result = {**record, **deepcopy(spec), "purpose_verified": True,
              "purpose_verified_on": VERIFIED_ON, "verification_scope": "entry_purpose",
              "availability": "not_checked", "workflow_verified": False, "submission_verified": False,
              "access_hint": "按该服务页面说明直连，访问条件需分别核实。"}
    policy = policy_for_url(spec["url"])
    if policy:
        result["access_hint"] = policy.hint
        result["access_policy"] = policy.public()
    if spec.get("official") is False:
        result["access_hint"] = "第三方校园导航；业务要求与服务入口应结合校方原页面核对。"
    if record.get("title") and record["title"] != spec["title"]:
        result["original_title"] = record["title"]
    return result


def service_results(cached: list[dict], query: str, limit: int, offset: int) -> dict:
    """Merge maintained repair references with cache, then filter and paginate."""
    records = []
    for host in MAINTAINED_HOSTS:
        spec = SERVICE_DIRECTORY[host]
        records.append({"id": item_id("public", "service", spec["url"]), "kind": "service",
                        "source": "public", "title": spec["title"], "url": spec["url"],
                        "record_origin": "maintained_service_directory", "collected_at": None})
    # Prefer a discovered record's collection time, without treating it as endpoint health evidence.
    records.extend(reversed(cached))
    merged = {}
    for record in records:
        item = describe_service(record)
        if item is not None:
            merged[item.get("service_id", item["url"])] = item
    matches = []
    for item in merged.values():
        # A stale/misleading label or a negative routing note must not create a positive match.
        text = " ".join(str(item.get(key, "")) for key in ("title", "purpose", "campus", "keywords", "url"))
        if all(term.casefold() in text.casefold() for term in query.split()):
            matches.append(item)
    return {"items": matches[offset:offset + limit], "total_count": len(matches),
            "offset": offset, "has_more": len(matches) > offset + limit,
            "directory_verified_on": VERIFIED_ON, "availability_checked": False}
