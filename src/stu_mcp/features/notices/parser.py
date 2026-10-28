"""Pure page parsing. Unrecognized pages never become successful empty reads."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ...parsing import clean, is_login, item_id, published, text_body
from ...runtime import AppError
from .schema import (
    AUTH_QUERY_KEYS,
    BODY_SELECTORS,
    OA_ARTICLE_PATHS,
    OA_ATTACHMENT_FIELD_PATTERN,
    OA_BODY_SELECTORS,
    OA_COLUMNS,
    OA_EMPTY_TEXT,
    OA_HOSTS,
    PUBLIC_HOSTS,
)


def _changed(source: str, message: str) -> AppError:
    return AppError("schema_changed", message, source)


def _url(base: str, value: object, *, hosts: frozenset[str] | None = None) -> str | None:
    if not str(value or "").strip() or str(value).lstrip().startswith("#"):
        return None
    candidate = urljoin(base, str(value or ""))
    try:
        parsed = urlparse(candidate)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in {None, 80, 443} or hosts is not None and parsed.hostname not in hosts
                or any(key.casefold() in AUTH_QUERY_KEYS for key, _ in parse_qsl(parsed.query, keep_blank_values=True))):
            return None
    except ValueError:
        return None
    return candidate


def parse_public(html: str, base: str, category: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records, seen = [], set()
    for link in soup.select("a[href]"):
        url = _url(base, link["href"], hosts=PUBLIC_HOSTS)
        if url is None:
            continue
        path = urlparse(url).path.lower()
        if not ("/info/" in path or re.search(r"/(?:news|activity|notice)(?:detail|view)?\.aspx$", path, re.I)):
            continue
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if len(title) < 3 or title.lower() in {"more", "更多", "查看详情", "了解更多"} or url in seen:
            continue
        parent = link.find_parent("li") or link.parent
        records.append({"id": item_id("public", "notice", url), "kind": "notice", "title": title,
                        "url": url, "category": category,
                        "published_at": published(clean(parent.get_text(" ", strip=True)))})
        seen.add(url)
        if len(records) >= limit:
            break
    if not records:
        raise _changed("public", "此公开栏目未找到预期文章链接。")
    return records


def parse_links(html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    # The class contract survives changing section to div and extra wrappers.
    roots = soup.select(".n_kuaisu .box")
    if not roots:
        raise _changed("public", "未识别官网校园服务目录，未把页面变化当作空目录。")
    records, seen = [], set()
    for root in roots:
        for link in root.select("a[href]"):
            url, title = _url(base, link["href"]), clean(link.get_text(" ", strip=True))
            if not url or not title or url in seen:
                continue
            records.append({"id": item_id("public", "service", url), "kind": "service",
                            "title": title, "url": url})
            seen.add(url)
            if len(records) == 80:
                return records
    if not records:
        raise _changed("public", "官网校园服务目录未返回可识别入口。")
    return records


def _oa_identity(link: Tag, base: str) -> tuple[str, str] | None:
    url = _url(base, link.get("href"), hosts=OA_HOSTS)
    if url is None or urlparse(url).path not in OA_ARTICLE_PATHS:
        return None
    values = parse_qs(urlparse(url).query, keep_blank_values=True).get("docid", [])
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", values[0]):
        raise _changed("oa", "OA 通知标识缺失或有歧义。")
    return url, values[0]


def _column_map(table: Tag) -> tuple[dict[str, int], int] | None:
    candidates = []
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        names = [re.sub(r"\s+", "", cell.get_text(" ", strip=True)).rstrip(":：") for cell in cells]
        if len(cells) == 1 and cells[0].has_attr("colspan"):
            # A table title spanning all columns is decoration, not a header.
            continue
        mapped = {}
        for field, aliases in OA_COLUMNS.items():
            positions = [index for index, name in enumerate(names) if name in aliases]
            if len(positions) > 1:
                raise _changed("oa", "OA 列表存在重复列名，无法确认字段。")
            if positions:
                mapped[field] = positions[0]
        if (row.find("th", recursive=False) is not None or len(mapped) >= 2
                or mapped and row.find("a", href=True) is None):
            if set(mapped) != set(OA_COLUMNS):
                raise _changed("oa", "OA 列表缺少可识别的标题、部门或日期列。")
            candidates.append((mapped, len(cells)))
    if len(candidates) > 1 and any(candidate != candidates[0] for candidate in candidates[1:]):
        raise _changed("oa", "OA 列表存在不一致的表头。")
    return candidates[0] if candidates else None


def _oa_metadata(link: Tag, base: str) -> tuple[str, str | None]:
    row, table = link.find_parent("tr"), link.find_parent("table")
    if row is None or table is None:
        raise _changed("oa", "OA 通知链接缺少可识别的列表行。")
    cells = row.find_all("td", recursive=False)
    columns = _column_map(table)
    if columns:
        mapping, count = columns
        if len(cells) != count or any(cell.has_attr("colspan") or cell.has_attr("rowspan") for cell in cells):
            raise _changed("oa", "OA 通知列数与表头不一致。")
        if link not in cells[mapping["title"]].descendants:
            raise _changed("oa", "OA 通知链接不在标题列。")
        return clean(cells[mapping["department"]].get_text(" ", strip=True)), published(
            clean(cells[mapping["published_at"]].get_text(" ", strip=True)))
    # The repository's observed legacy fixtures prove only these two layouts.
    if len(cells) == 1 and link in cells[0].descendants:
        return "", None
    if len(cells) == 3 and link in cells[0].descendants:
        date = published(clean(cells[2].get_text(" ", strip=True)))
        identities = [candidate for candidate in row.select("a[href]") if _oa_identity(candidate, base)]
        if date and len(identities) == 1:
            return clean(cells[1].get_text(" ", strip=True)), date
    raise _changed("oa", "OA 列表旧格式发生变化，未按固定列号猜测字段。")


def parse_oa(html: str, base: str, limit: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records, seen = [], {}
    # A public OA board can legitimately share its page with a login form.
    for link in soup.select("a[href]"):
        identity = _oa_identity(link, base)
        if identity is None:
            continue
        url, docid = identity
        title = clean(link.get("title") or link.get_text(" ", strip=True))
        if not title:
            raise _changed("oa", "OA 通知标题为空。")
        department, date = _oa_metadata(link, base)
        record = {"id": item_id("oa", "notice", docid), "kind": "notice", "docid": docid,
                  "title": title, "url": url, "department": department, "published_at": date}
        if docid in seen:
            if any(record[key] != seen[docid][key] for key in ("title", "department", "published_at")):
                raise _changed("oa", "同一 OA 通知出现冲突内容。")
            continue
        records.append(record)
        seen[docid] = record
        if len(records) >= limit:
            break
    if records:
        return records
    search = soup.select("#searchForm")
    empty = any(clean(node.get_text(" ", strip=True)).rstrip("!！。") in OA_EMPTY_TEXT
                for node in soup.select("td, p, div, span") if node.find(["td", "p", "div", "span"]) is None)
    if len(search) == 1 and empty:
        return []
    raise AppError("oa_unavailable", "此网络无法读取 OA 列表；请查看本地设置中的 OA 状态。", "oa")


def _download_url(base: str, link: Tag, source: str) -> str | None:
    url = _url(base, link.get("href"), hosts=OA_HOSTS if source == "oa" else PUBLIC_HOSTS)
    if url and (urlparse(url).path.lower().endswith((".pdf", ".docx")) or "download" in url.lower()):
        return url
    return None


def _body_root(soup: BeautifulSoup, source: str, base: str, *, has_attachments: bool = False) -> Tag:
    # Unlike the anonymous listing board, the existing article read contract
    # rejects authentication documents even when they reuse a content wrapper.
    if is_login(str(soup)):
        raise AppError("needs_login", "正文需要在学校页面登录。", source)
    for node in soup.select("title, h1, h2"):
        if re.fullmatch(r"(?:\d{3}\s*[-:：]?\s*)?(?:服务器内部错误|系统错误|网络错误|服务不可用|"
                        r"系统维护(?:中)?|服务维护(?:中)?|服务升级(?:中)?|访问被拒绝|页面不存在|"
                        r"Internal Server Error|Service Unavailable|Access Denied|Not Found)",
                        clean(node.get_text(" ", strip=True)), re.I):
            raise AppError("source_unavailable", "学校返回错误或维护页面，未保存为通知正文。", source)
    selectors = OA_BODY_SELECTORS if source == "oa" else BODY_SELECTORS
    parsed = urlparse(base)
    if (source == "public" and parsed.hostname == "xsc.stu.edu.cn"
            and parsed.path.lower() == "/news.aspx" and soup.select("#cont")):
        # Student Affairs' observed article template (2026-10-28): title/date
        # are siblings of the body. Never accept the surrounding page/sidebar.
        titles = soup.select("#cont > h2")
        dates = soup.select("#cont > div.tc.p10")
        if (len(soup.select("#cont")) != 1 or len(titles) != 1
                or not clean(titles[0].get_text(" ", strip=True)) or len(dates) != 1
                or not re.fullmatch(r"发布时间[：:]\s*20\d{2}-\d{2}-\d{2}",
                                    clean(dates[0].get_text(" ", strip=True)))):
            raise _changed(source, "学生处通知缺少唯一标题或发布日期。")
        selectors = ("#cont > div.lh200.pl10.pr10",)
    for selector in selectors:
        candidates = soup.select(selector)
        if candidates:
            if len(candidates) != 1:
                raise _changed(source, "通知正文容器不唯一。")
            root = candidates[0]
            # A generic content wrapper containing only navigation is not an article.
            copy = BeautifulSoup(str(root), "html.parser")
            for node in copy.select("script, style, noscript, nav, header, footer, form"):
                node.decompose()
            for link in copy.select("a"):
                if not _download_url(base, link, source):
                    link.decompose()
            if not clean(copy.get_text(" ", strip=True)) and not has_attachments:
                raise _changed(source, "通知正文容器没有可识别的正文。")
            return root
    raise _changed(source, "未识别学校通知正文，未把整页模板当作全文。")


def parse_oa_article(html: str, base: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    attachments, seen = [], set()
    for row in soup.select('[id^="accessory_dsp_tr"]'):
        fields = [field for field in row.select("input[name]")
                  if re.fullmatch(OA_ATTACHMENT_FIELD_PATTERN, str(field.get("name", "")))]
        if len(fields) != 1 or not re.fullmatch(r"[0-9]+", str(fields[0].get("value", ""))):
            raise _changed("oa", "OA 附件标识缺失或有歧义。")
        file_id = str(fields[0]["value"])
        if file_id in seen:
            continue
        label = re.sub(r"附件\d+|下载", "", clean(row.get_text(" ", strip=True))).strip(" :：")
        attachments.append({"name": label or f"附件 {file_id}", "url": base +
                            f"/weaver/weaver.file.FileDownload?fileid={file_id}&download=1&requestid=0"})
        seen.add(file_id)
        if len(attachments) == 30:
            break
    root = _body_root(soup, "oa", base, has_attachments=bool(attachments))
    return {"body": text_body(str(root)), "attachments": attachments}


def parse_public_article(html: str, base: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = _body_root(soup, "public", base)
    attachments = []
    excluded = {id(link) for container in root.select("nav, header, footer, form")
                for link in container.select("a")}
    for link in root.select("a[href]"):
        if id(link) not in excluded and _download_url(base, link, "public"):
            attachments.append({"name": clean(link.get_text(" ", strip=True)) or "附件", "url": str(link["href"])})
        if len(attachments) == 30:
            break
    return {"body": text_body(str(root)), "attachments": attachments}
