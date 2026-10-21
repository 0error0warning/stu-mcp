"""Small, local service policies. A research window is not live availability.

The product runs on the user's machine: campus access means that machine's
existing campus/VPN route, never a hidden Hermes/SSH/proxy dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ServiceAccess:
    endpoint_id: str
    service_id: str
    url: str
    preferred_access: str
    hint: str
    sso_dependency: bool = False
    check_login_default: bool = False

    def public(self) -> dict:
        return {"endpoint_id": self.endpoint_id, "transport": "direct",
                "preferred_access": self.preferred_access, "hint": self.hint,
                "sso_dependency": self.sso_dependency,
                "automatic_proxy_fallback": False, "availability": "not_checked"}


POLICIES = {
    "sangpushan_repair": ServiceAccess(
        "sangpushan_repair", "sangpushan_repair", "https://repair.stu.edu.cn/", "campus_access_if_needed",
        "先用本机现有网络直连；若无法解析或连接，核实校园网或获准的校园 VPN 接入，普通代理不能替代。",
        sso_dependency=True, check_login_default=True),
    "campus_repair": ServiceAccess(
        "campus_repair", "campus_repair", "https://r.stu.edu.cn/", "direct_first",
        "入口优先直连，不预设必须在校园；需要登录时单独核对统一认证。", sso_dependency=True),
    "school_service_portal": ServiceAccess(
        "school_service_portal", "school_service_portal", "https://service.stu.edu.cn/fe/", "direct_first",
        "公开入口优先直连；具体业务与统一认证分别判断，不因其他校内站点失败而切换代理。",
        sso_dependency=True),
    "school_sso": ServiceAccess(
        "school_sso", "school_sso", "https://sso.stu.edu.cn/login", "direct_first",
        "统一认证单独直连检查；失败只影响需要该认证的操作，不自动改走普通代理。"),
    "school_homepage": ServiceAccess(
        "school_homepage", "school_homepage", "https://www.stu.edu.cn/", "direct_first",
        "官网按当前网络直连；单机路径失败不推广为学校停服，其他服务继续独立读取。"),
    "network_repair": ServiceAccess(
        "network_repair", "network_repair", "https://its.stu.edu.cn/", "diagnostic_only",
        "ITS HTTPS 单独诊断；本次不可达不证明停用，网络故障优先查看 r 的已核验表单。"),
    "network_repair_http": ServiceAccess(
        "network_repair_http", "network_repair", "http://its.stu.edu.cn/", "diagnostic_only",
        "ITS 旧 HTTP 入口仅匿名诊断，与 HTTPS 分开；不能发送登录态或因 HTTPS 失败自动降级。"),
}


def policy_for_url(url: str) -> ServiceAccess | None:
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password or parsed.scheme not in {"http", "https"}:
            return None
        _port = parsed.port  # Validate before comparing against fixed policy origins.
    except ValueError:
        return None
    def origin(value):
        return (value.scheme, value.hostname,
                value.port if value.port is not None else 443 if value.scheme == "https" else 80)
    for policy in POLICIES.values():
        endpoint = urlparse(policy.url)
        if origin(parsed) == origin(endpoint):
            return policy
    return None
