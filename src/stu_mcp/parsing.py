"""Shared pure text, identity and page helpers; no source orchestration or I/O."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup

CST = timezone(timedelta(hours=8))


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def item_id(source: str, kind: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:24]
    return f"{source}:{kind}:{digest}"


def stamp(value: object) -> str | None:
    try:
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        return datetime.fromtimestamp(seconds, CST).isoformat() if seconds > 0 else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})日?.*?(\d{1,2}):(\d{2})", value)
    if match:
        try:
            return datetime(*map(int, match.groups()), tzinfo=CST).isoformat()
        except ValueError:
            return None
    for fmt in ("%A, %d %B %Y, %I:%M %p", "%A, %d %B %Y, %H:%M",
                "%d %B %Y, %I:%M %p", "%d %B %Y, %H:%M"):
        try:
            return datetime.strptime(clean(value), fmt).replace(tzinfo=CST).isoformat()
        except ValueError:
            pass
    return clean(value)


def is_login(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("input[type=password]") or re.search(
            r"<title[^>]*>[^<]*(?:统一身份认证|用户登录|SSO Login)", html, re.I):
        return True
    # The school gateway returns HTTP 200 plus a small immediate SSO redirect.
    for script in soup.select("script:not([src])"):
        match = re.fullmatch(r"\s*(?:(?:window|top|self)\.)?location(?:\.href)?\s*=\s*"
                             r"['\"]([^'\"]+)['\"]\s*;?\s*", script.get_text())
        if match and urlparse(match[1]).hostname == "sso.stu.edu.cn":
            return True
    return False


def text_body(html: str, limit: int = 60000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, nav, header, footer, form"):
        node.decompose()
    node = soup.select_one("#docContent, #content, #vsb_content, .v_news_content, article, main")
    return clean((node or soup).get_text(" ", strip=True))[:limit]


def published(text: str) -> str | None:
    m = re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?", text)
    return m.group(0) if m else None
