"""Extract article text, never execute scripts or mistake an interstitial for it."""
from __future__ import annotations

import re
from html import unescape

from bs4 import BeautifulSoup

from ...parsing import clean, stamp
from ...runtime import AppError


def _literal(scripts: str, key: str) -> str:
    # Only a quoted string RHS, optionally inside the known HTML decoder. No eval.
    pattern = (r"(?<![\w$])" + re.escape(key) + r"\s*=\s*(?:htmlDecode\(\s*)?"
               r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')(?=\s*\)?\s*;)''')
    match = re.search(pattern, scripts, re.S)
    if not match:
        return ""

    def escape(m):
        value = m[0][1:]
        if value.startswith(("u", "x")):
            return chr(int(value[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
                "v": "\v", "0": "\0", "\n": "", "\r\n": ""}.get(value, value)

    value = re.sub(r"\\(?:u[\da-fA-F]{4}|x[\da-fA-F]{2}|\r\n|.)", escape,
                   match[1][1:-1], flags=re.S)
    # Combine valid JS UTF-16 surrogate pairs and replace malformed lone surrogates.
    return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def _text(node) -> str:
    for child in node.select("script, style, noscript, iframe, svg, form"):
        child.decompose()
    for br in node.select("br"):
        br.replace_with("\n")
    for block in node.select("p, section, div, li, h1, h2, h3, h4, blockquote, tr"):
        block.append("\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in node.get_text().splitlines()]
    return "\n".join(line for line in lines if line)


def parse_article(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    scripts = "\n".join(script.get_text() for script in soup.select("script:not([src])"))

    def text(selector):
        node = soup.select_one(selector)
        return clean(node.get_text()) if node else ""

    def meta(name):
        node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        return clean(node.get("content")) if node else ""

    title = text("#activity-name") or meta("og:title") or clean(unescape(_literal(scripts, "msg_title")))
    account = text("#js_name") or clean(unescape(_literal(scripts, "nickname")))
    author = meta("author") or text("#js_author_name, #meta_content > .rich_media_meta_text:not(#publish_time)")
    ct = re.search(r'''\b(?:var\s+)?ct\s*=\s*["']?(\d{10})\b''', scripts)
    # Prefer the source epoch over browser-localized display dates.
    published = (stamp(ct[1]) if ct else None) or meta("article:published_time") or text("#publish_time")

    node = soup.select_one("#js_content")
    method, body, image_count = "dom", "", 0
    if node is not None:
        image_count = len(node.select("img"))
        body = _text(node)
    if len(re.sub(r"\s", "", body)) < 20:
        literal = _literal(scripts, "content_noencode")
        if literal:
            method = "content_noencode"
            fragment = BeautifulSoup(unescape(literal), "html.parser")
            image_count = len(fragment.select("img"))
            body = _text(fragment)

    # A valid article may itself discuss CAPTCHA or deletion. Only classify a
    # dedicated interstitial, or the page without usable article identity/body.
    gate = soup.select_one(".weui-msg__text-area, #js_verify, .weui_msg")
    hint = gate.get_text(" ", strip=True) if gate else ""
    if not hint and (not title or len(body.strip()) < 20):
        for script in soup.select("script, style, noscript"):
            script.decompose()
        hint = soup.get_text(" ", strip=True)
    states = (
        ("rate_limited", ("访问过于频繁", "操作过于频繁", "请稍后再试"), "来源限制访问频率，请稍后重试。"),
        ("captcha_required", ("环境异常", "完成验证后即可继续访问", "安全验证", "请输入验证码"),
         "来源要求人工验证；未读取到正文，请在原文页面检查。"),
        ("article_unavailable", ("参数错误", "该内容已被发布者删除", "此内容已被删除", "内容已被删除",
                                 "该内容无法查看", "此内容因违规无法查看", "链接已过期"),
         "文章链接无效、已删除或当前不可查看，请核对原文。"),
    )
    for code, markers, message in states:
        if any(marker in hint for marker in markers):
            raise AppError(code, message, "wechat")
    if not title or not (account or published):
        raise AppError("schema_changed", "未识别到完整文章元数据；未把页面当成正文。", "wechat")
    if len(re.sub(r"\s", "", body)) < 20:
        raise AppError("insufficient_content", "正文不足 20 个非空白字符，可能是纯图片、音视频或尚未加载；未做 OCR。", "wechat")
    return {"title": title, "account": account or None, "author": author or None,
            "published_at": published or None, "text": body, "extraction": method,
            "image_count": image_count, "identity_verified": False}
