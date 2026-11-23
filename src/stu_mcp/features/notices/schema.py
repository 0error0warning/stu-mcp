"""Observed page contracts; URLs retain their original source boundaries."""
from urllib.parse import parse_qsl, urlsplit

from ...sources import OA_DIRECT, OA_SECURE_PROXY, PUBLIC_LISTINGS, SOURCES

QUICK_LINKS = "https://www.stu.edu.cn/kstd.htm"
OA_LIST_PATH = "/login/Login.jsp?logintype=1"
OA_ARTICLE_PATH = "/newstemplateprotal.jsp"
OA_ARTICLE_PATHS = frozenset({OA_ARTICLE_PATH, "/page/maint/template/news/newstemplateprotal.jsp"})
PUBLIC_HOSTS = frozenset(SOURCES["public"].hosts)
OA_HOSTS = frozenset({"oa.stu.edu.cn", "oa-stu-edu-cn.webvpn.stu.edu.cn"})
XTW_HOST = "xtw.stu.edu.cn"
XTW_MAX_PAGES = 3
XTW_ARTICLE_FORM = ".art-main > form[name='_newscontent_fromname']"
XTW_BODY_SELECTOR = ", ".join(XTW_ARTICLE_FORM + " > #" + identity
                              for identity in ("vsb_content", "vsb_content_2"))
XTW_ATTACHMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                           ".txt", ".csv", ".zip", ".rar")

# These identify business fields, independently of column order and wrappers.
OA_COLUMNS = {
    "title": ("标题", "通知标题", "主题"),
    "department": ("部门", "发布部门", "发布单位", "发文单位"),
    "published_at": ("日期", "发布日期", "发布时间"),
}
BODY_SELECTORS = ("#docContent", "#vsb_content", ".v_news_content", "article", "#content", "main")
# The current OA template has a specific article field, not a whole-page wrapper.
OA_BODY_SELECTORS = ("#spanContent", *BODY_SELECTORS)
OA_ATTACHMENT_FIELD_PATTERN = r"accessory[0-9]*"
OA_EMPTY_TEXT = frozenset({"暂无通知", "暂无数据", "没有相关通知", "没有任何数据", "无相关记录"})
AUTH_QUERY_KEYS = frozenset({"token", "access_token", "refresh_token", "ticket", "sessionid",
                            "authorization", "password", "passwd", "pwd", "userpassword", "j_password"})


def is_oa_webvpn_url(url: str) -> bool:
    return urlsplit(url).hostname == urlsplit(OA_SECURE_PROXY).hostname


def oa_content_url(url: str, *, via_webvpn: bool = False) -> str:
    """Canonicalize the OA origin while keeping the page's access path."""
    try:
        parsed = urlsplit(url)
        port = {"http": 80, "https": 443}.get(parsed.scheme)
        if (parsed.hostname != urlsplit(OA_DIRECT).hostname or port is None or parsed.port not in {None, port}
                or parsed.username is not None or parsed.password is not None or parsed.fragment
                or any(key.casefold() in AUTH_QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True))):
            return url
    except ValueError:
        return url
    origin = OA_SECURE_PROXY if via_webvpn else OA_DIRECT
    return origin + parsed.path + ("?" + parsed.query if parsed.query else "")


__all__ = ["OA_DIRECT", "OA_SECURE_PROXY", "PUBLIC_LISTINGS"]
