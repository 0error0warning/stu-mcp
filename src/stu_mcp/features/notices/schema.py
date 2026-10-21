"""Observed page contracts; URLs retain their original source boundaries."""
from ...sources import OA_DIRECT, OA_SECURE_PROXY, PUBLIC_LISTINGS

QUICK_LINKS = "https://www.stu.edu.cn/kstd.htm"
OA_LIST_PATH = "/login/Login.jsp?logintype=1"
OA_ARTICLE_PATH = "/newstemplateprotal.jsp"
PUBLIC_HOSTS = frozenset({"www.stu.edu.cn", "xsc.stu.edu.cn"})
OA_HOSTS = frozenset({"oa.stu.edu.cn", "oa-stu-edu-cn.webvpn.stu.edu.cn"})

# These identify business fields, independently of column order and wrappers.
OA_COLUMNS = {
    "title": ("标题", "通知标题", "主题"),
    "department": ("部门", "发布部门", "发布单位", "发文单位"),
    "published_at": ("日期", "发布日期", "发布时间"),
}
BODY_SELECTORS = ("#docContent", "#vsb_content", ".v_news_content", "article", "#content", "main")
OA_EMPTY_TEXT = frozenset({"暂无通知", "暂无数据", "没有相关通知", "没有任何数据", "无相关记录"})
AUTH_QUERY_KEYS = frozenset({"token", "access_token", "refresh_token", "ticket", "sessionid",
                            "authorization", "password", "passwd", "pwd", "userpassword", "j_password"})

__all__ = ["OA_DIRECT", "OA_SECURE_PROXY", "PUBLIC_LISTINGS"]
