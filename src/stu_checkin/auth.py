"""The existing WeChat authorization route and callback validation."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse

CALLBACK = (
    "https://www.duifene.com/_FileManage/PdfView.aspx?file="
    "https%3A%2F%2Ffs.duifene.com%2Fres%2Fr2%2Fu6106199%2F"
    "%E5%AF%B9%E5%88%86%E6%98%93%E7%99%BB%E5%BD%95_876c9d439ca68ead389c.pdf"
)
AUTH_URL = "https://open.weixin.qq.com/connect/oauth2/authorize?" + urlencode({
    "appid": "wx1b5650884f657981", "redirect_uri": CALLBACK, "response_type": "code",
    "scope": "snsapi_userinfo", "state": "1", "connect_redirect": "1",
}) + "#wechat_redirect"


def callback_code(link: str) -> str:
    """Extract only the existing route's code; never fetch the supplied URL."""
    try:
        parsed = urlparse(str(link).strip())
        values = parse_qs(parsed.query).get("code", [])
    except ValueError:
        raise ValueError("invalid callback") from None
    if (parsed.scheme != "https" or parsed.hostname not in {"www.duifene.com", "duifene.com"}
            or len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{32}", values[0])):
        raise ValueError("invalid callback")
    return values[0]
