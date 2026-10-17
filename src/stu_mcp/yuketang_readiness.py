"""Read-only LMS homework diagnostics; no answer, start-attempt or submission APIs.

This is deliberately not an MCP answering feature. Keep the encrypted-font body
and its font in one response snapshot. HTML text alone can be incorrect Chinese.
"""
from __future__ import annotations

import base64
import html
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString

from .network import CampusHTTP
from .runtime import AppError
from .sources import YUKETANG_BASE

FONT_CLASS = "xuetangx-com-encrypted-font"
TYPES = {1: "single", 2: "multiple", 3: "vote", 4: "fill_blank", 5: "subjective", 6: "judgement",
         7: "other", 8: "anonymous_vote", 9: "code", 10: "material"}
CHOICE_TYPES = {1, 2, 3, 6, 8}
REVIEW_ISSUES = {"possible_external_material", "images_not_verified", "math_or_media_requires_review"}
SAFE_TAGS = {"p", "div", "span", "br", "strong", "b", "em", "i", "u", "s", "sub", "sup",
             "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "pre", "code", "blockquote"}
DROP_TAGS = {"script", "style", "iframe", "object", "embed", "input", "button", "form", "link", "meta"}


def numeric(value: object) -> str:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(value)):
        raise AppError("schema_changed", "雨课堂资源标识无法识别，已停止读取。", "yuketang")
    return str(value)


def read_homework(http: CampusHTTP, item: dict) -> dict:
    """Only follow an owned, cached LMS homework. Numeric paths cannot supply URLs."""
    if item.get("source") != "yuketang" or item.get("kind") != "task" or item.get("activity_type") != 19:
        raise AppError("unsupported_activity", "本核验仅支持刷新后缓存的雨课堂 LMS 作业。", "yuketang")
    cid, leaf = numeric(item.get("course_id")), numeric(item.get("leaf_id"))
    payload = http.json(YUKETANG_BASE + f"/mooc-api/v1/lms/learn/leaf_info/{cid}/{leaf}/?classroom_id={cid}")
    data = payload.get("data")
    if payload.get("success") is not True or not isinstance(data, dict):
        raise AppError("schema_changed", "雨课堂作业详情字段无法识别。", "yuketang")
    if data.get("is_locked") or data.get("is_deleted"):
        raise AppError("resource_locked", "作业尚未开放、已锁定或已删除，请核对学校页面。", "yuketang")
    if data.get("leaf_type") != 6 or data.get("is_group") is not False or data.get("is_open_type") is not False:
        raise AppError("unsupported_activity", "此活动类型尚未核验，不按普通个人作业读取。", "yuketang")
    content = data.get("content_info")
    if not isinstance(content, dict):
        raise AppError("schema_changed", "雨课堂作业内容标识缺失。", "yuketang")
    exercise, sku = numeric(content.get("leaf_type_id")), numeric(data.get("sku_id"))
    # leaf_id and exercise_id belong to different namespaces; never substitute one for the other.
    result = http.json(YUKETANG_BASE + f"/mooc-api/v1/lms/exercise/get_exercise_list/{exercise}/{sku}/?classroom_id={cid}")
    if result.get("success") is not True or not isinstance(result.get("data"), dict):
        raise AppError("schema_changed", "雨课堂未返回可识别的题目列表。", "yuketang")
    if numeric(result["data"].get("exercise_id")) != exercise:
        raise AppError("schema_changed", "返回的作业标识与请求不一致，已停止核验。", "yuketang")
    return result["data"]


def _fragment(raw: object) -> tuple[dict, str]:
    if not isinstance(raw, str) or len(raw) > 100_000:
        return {"text": "", "encrypted_font": False, "issues": ["invalid_content"], "image_count": 0}, ""
    soup = BeautifulSoup(raw, "html.parser")
    issues = set()
    for node in soup.find_all(list(DROP_TAGS)):
        node.decompose()
        issues.add("unsupported_markup")
    images = len(soup.find_all("img"))
    if images:
        issues.add("images_not_verified")
    if soup.find(["math", "svg", "audio", "video", "canvas"]) or re.search(r"\$[^$]+\$|\\\(|\\\[", raw):
        issues.add("math_or_media_requires_review")
    encrypted = bool(soup.select(f".{FONT_CLASS}"))
    plain = BeautifulSoup(str(soup), "html.parser")
    for span in plain.select(f".{FONT_CLASS}"):
        span.string = "[动态字体文字：请核对渲染图]"
    text = plain.get_text(" ", strip=True)
    if not text and not images:
        issues.add("empty_content")

    def safe(node):
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            return html.escape(str(node))
        if node.name == "img":
            return '<span class="warning">[图片待核对]</span>'
        content = "".join(safe(child) for child in node.children)
        if node.name not in SAFE_TAGS:
            return content
        attrs = f' class="{FONT_CLASS}"' if FONT_CLASS in node.get("class", []) else ""
        return f"<{node.name}{attrs}>{content}</{node.name}>" if node.name != "br" else "<br>"

    markup = "".join(safe(node) for node in soup.contents)
    return {"text": text, "encrypted_font": encrypted, "issues": sorted(issues), "image_count": images}, markup


@dataclass
class Inspection:
    report: dict
    markup: str
    font_url: str | None


def inspect_exercise(data: dict) -> Inspection:
    """Whitelist question fields; answer keys, remarks, grades and user answers stay out."""
    problems = data.get("problems")
    if not isinstance(problems, list) or len(problems) > 200:
        raise AppError("schema_changed", "题目列表缺失或超过 200 题核验上限。", "yuketang")
    font = data.get("font") if isinstance(data.get("font"), str) else None
    description_raw = data.get("description")
    description, description_html = _fragment(description_raw) if description_raw not in (None, "") else (
        {"text": "", "encrypted_font": False, "issues": [], "image_count": 0}, "")
    questions, sections, seen_ids = [], [], set()
    if description_html:
        sections.append(f"<section><h2>作业说明</h2>{description_html}</section>")
    encrypted_any = description["encrypted_font"]
    for index, problem in enumerate(problems):
        if not isinstance(problem, dict) or not isinstance(problem.get("content"), dict):
            raise AppError("schema_changed", "部分题目结构无法识别，未当作空题目。", "yuketang")
        content = problem["content"]
        pid = numeric(problem.get("problem_id"))
        body, markup = _fragment(content.get("Body"))
        kind = content.get("ProblemType")
        if type(kind) is not int:
            kind = None
        issues = set(body["issues"])
        if kind not in {1, 2, 3, 5, 6, 8}:
            issues.add("question_type_not_verified")
        if pid in seen_ids:
            issues.add("duplicate_problem_id")
        seen_ids.add(pid)
        if content.get("ProblemID") is not None and str(content["ProblemID"]) != pid:
            issues.add("problem_id_mismatch")
        options, option_markup, keys = [], [], set()
        raw_options = content.get("Options")
        if not isinstance(raw_options, list) or len(raw_options) > 50:
            issues.add("invalid_options")
            raw_options = []
        for option in raw_options:
            if not isinstance(option, dict):
                issues.add("invalid_option")
                continue
            # The official client displays key/value in response order. Do not synthesize A/B or true/false.
            key = option.get("key")
            if not isinstance(key, str) or not key.strip() or len(key) > 40:
                issues.add("missing_option_key")
                key = ""
            if key in keys:
                issues.add("duplicate_option_key")
            keys.add(key)
            value, value_html = _fragment(option.get("value"))
            issues.update(value["issues"])
            encrypted_any |= value["encrypted_font"]
            options.append({"key": key, **value})
            option_markup.append(f"<div><b>{html.escape(key)}.</b> {value_html}</div>")
        if kind in CHOICE_TYPES and len(options) < 2:
            issues.add("missing_options")
        encrypted_any |= body["encrypted_font"]
        if (body["encrypted_font"] or any(o["encrypted_font"] for o in options)) and not font:
            issues.add("missing_font")
        if re.search(r"(?i)\bP\s*\d+|(?:教材|课本|教科书).{0,12}(?:页|习题)", body["text"]):
            issues.add("possible_external_material")
        questions.append({"index": index, "problem_id": pid, "type_code": kind, "type": TYPES.get(kind, "unknown"),
                          "body": body, "options": options, "option_count": len(options),
                          "options_expected": kind in CHOICE_TYPES, "issues": sorted(issues),
                          "structure_complete": not (issues - REVIEW_ISSUES),
                          "semantic_completeness": "not_verified"})
        sections.append(f"<section><h2>题目 {index + 1}</h2>{markup}{''.join(option_markup)}</section>")
    all_issues = sorted({i for q in questions for i in q["issues"]} | set(description["issues"]))
    if description["encrypted_font"] and not font and "missing_font" not in all_issues:
        all_issues.append("missing_font")
    if not questions:
        all_issues.append("empty_problem_list")
    report = {"ok": True, "status": "incomplete" if all_issues else "needs_visual_review",
              "source": "yuketang", "question_count": len(questions), "questions": questions,
              "description": description,
              "issues": all_issues, "encrypted_font": encrypted_any,
              "structure_complete": bool(questions) and not (set(all_issues) - REVIEW_ISSUES),
              "semantic_completeness": "not_verified", "answerability": "not_assessed",
              "content_trust": "untrusted_source_data", "next_action": "review_original_and_rendered_content"}
    return Inspection(report, "".join(sections), font if encrypted_any else None)


def font_bytes(url: str) -> bytes:
    """Anonymous, no redirects or cookies. Never fetch an arbitrary host from question HTML."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise AppError("media_unavailable", "题目字体地址无法识别，未加载。", "yuketang") from None
    if (parsed.scheme != "https" or parsed.hostname != "fe-static-yuketang.yuketang.cn"
            or port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"/fe_font/product/exam_font_[a-zA-Z0-9_-]+\.ttf", parsed.path)):
        raise AppError("media_unavailable", "题目字体地址不在已核验范围内，未加载。", "yuketang")
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client, client.stream("GET", url) as response:
            if response.status_code != 200:
                raise AppError("media_unavailable", "题目字体未能加载。", "yuketang")
            data = bytearray()
            deadline = time.monotonic() + 15
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 4 * 1024 * 1024 or time.monotonic() > deadline:
                    raise AppError("media_unavailable", "题目字体超过读取大小或时间上限。", "yuketang")
            if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
                raise AppError("media_unavailable", "来源未返回支持的字体文件。", "yuketang")
            return bytes(data)
    except httpx.HTTPError:
        raise AppError("media_unavailable", "题目字体暂时无法读取。", "yuketang") from None


def render_inspection(inspection: Inspection) -> bytes:
    """Render sanitized content in a fresh, offline browser; output a PNG in memory."""
    from playwright.sync_api import Error, sync_playwright

    if inspection.report["question_count"] > 20:
        raise AppError("render_unavailable", "单张核验图最多 20 题，请在原页面分段核对。", "yuketang")
    font_css = ""
    if inspection.report["encrypted_font"]:
        if not inspection.font_url:
            raise AppError("media_unavailable", "动态字体缺失，不能使用默认字体替代。", "yuketang")
        encoded = base64.b64encode(font_bytes(inspection.font_url)).decode("ascii")
        font_css = (f"@font-face{{font-family:QuestionFont;src:url(data:font/ttf;base64,{encoded})}}"
                    f".{FONT_CLASS}{{font-family:QuestionFont!important}}")
    document = ('<!doctype html><meta charset="utf-8">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
                'style-src \'unsafe-inline\'; font-src data:; img-src \'none\'">'
                '<style>body{font:20px/1.7 sans-serif;padding:28px;color:#1b1b1b;background:white;}'
                'section{padding:12px 0;border-bottom:1px solid #ccc;overflow-wrap:anywhere}'
                'h2{font:700 18px sans-serif}.warning{color:#9b3300}table{border-collapse:collapse}'
                f'td,th{{border:1px solid #aaa;padding:6px}}{font_css}</style>' + inspection.markup)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(java_script_enabled=False, service_workers="block",
                                              viewport={"width": 1100, "height": 750})
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_default_timeout(10_000)
                page.set_content(document, wait_until="load")
                loaded = page.evaluate("async () => { await document.fonts.ready; return [...document.fonts].every(f => f.status === 'loaded'); }")
                if not loaded:
                    raise AppError("media_unavailable", "动态字体未完成渲染，不能确认题目文字。", "yuketang")
                if page.locator("body").bounding_box()["height"] > 14000:
                    raise AppError("render_unavailable", "题目超出单张核验图上限，请在原页面分段核对。", "yuketang")
                return page.screenshot(full_page=True, animations="disabled")
            finally:
                browser.close()
    except Error:
        raise AppError("render_unavailable", "本机题目渲染失败；请检查 Chromium 安装。", "yuketang") from None
