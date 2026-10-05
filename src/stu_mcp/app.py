from __future__ import annotations

import hashlib
import io
import math
import re
import threading
from contextlib import nullcontext
from urllib.parse import urljoin

from pypdf import PdfReader

from . import __version__, collectors
from .clients import detected_clients
from .network import CampusHTTP
from .parsers import text_body
from .runtime import AppError, Runtime, key_lock
from .sources import SOURCES
from .store import Store
from .vault import Vault


class App:
    def __init__(self, runtime: Runtime | None = None, vault: Vault | None = None):
        self.runtime = runtime or Runtime.default()
        self.vault = vault or Vault(self.runtime)
        self.store = Store(self.runtime, self.vault)
        self._refresh_lock = threading.Lock()

    def status(self) -> dict:
        features = []
        for name, source in SOURCES.items():
            auth = self.vault.status(source.session) if source.session else {"status": "not_required"}
            features.append({"source": name, "label": source.label, "features": list(source.features),
                             "auth": auth, "login_required": name in {"jw", "mystu", "yuketang"},
                             "access": "anonymous_first" if name == "oa" else "public" if name == "public" else "personal"})
        return {"ok": True, "version": __version__, "sources": features, "freshness": self.store.freshness(),
                "clients": detected_clients(), "profile": self.runtime.profile(), "transport": self.runtime.preferences(),
                "privacy": {"model_api_key_required": False, "background_ai": False,
                            "private_wechat": False, "storage": "os_keyring_and_encrypted_sessions"}}

    def refresh(self, source: str, limit: int = 20, semester: str = "") -> dict:
        if source not in SOURCES or not 1 <= limit <= 50:
            raise AppError("invalid_source", "请选择 public、oa、jw、mystu 或 yuketang；数量为 1–50。")
        if semester and not re.fullmatch(r"20\d{2}-20\d{2}-[12]", semester):
            raise AppError("invalid_semester", "学期格式为 2026-2027-1；留空时成绩查全部、考试使用推定学期。")
        if not self._refresh_lock.acquire(blocking=False):
            raise AppError("refresh_running", "已有刷新正在进行，请稍后重试。", source)
        try:
            service = SOURCES[source].session
            def session_version():
                path = self.runtime.session_file(service) if service else None
                return hashlib.sha256(path.read_bytes()).digest() if path and path.is_file() else None
            initial_session = session_version()
            if source in {"jw", "mystu", "yuketang"}:
                auth = self.vault.status(SOURCES[source].session)
                if auth["status"] != "session_saved":
                    raise AppError(auth["status"], "此来源需要在本地设置页登录；公开功能可直接使用。", source)
            if source == "public":
                result = collectors.public(limit)
            elif source == "oa":
                result = collectors.oa(self.vault, limit)
            elif source == "jw":
                result = collectors.jw(self.vault, limit, semester)
            elif source == "mystu":
                result = collectors.mystu(self.vault, limit)
            else:
                result = collectors.yuketang(self.vault, limit)
            unique = {item["id"]: item for item in result.items}
            with key_lock(self.runtime.home, service) if service else nullcontext():
                if result.private and initial_session != session_version():
                    raise AppError("session_changed", "登录状态在刷新期间改变；已丢弃此次个人结果，请重新刷新。", source)
                saved = self.store.save_batch(source, list(unique.values()), private=result.private)
            self.store.record_status(source, result.status, saved)
            return {"ok": True, "status": result.status, "source": source, "saved": saved,
                    "limited": result.limited, "coverage": result.coverage, "errors": result.errors,
                    "freshness": self.store.freshness()}
        except AppError as exc:
            self.store.record_status(source, exc.code)
            raise
        except Exception:
            self.store.record_status(source, "source_error")
            raise AppError("source_error", "来源数据未能处理；未把解析失败当作空结果，也未输出认证信息。", source) from None
        finally:
            self._refresh_lock.release()

    def query(self, kind: str, query: str = "", limit: int = 20, offset: int = 0,
              source: str = "all") -> dict:
        if kind not in {"notice", "grade", "exam", "course", "task", "resource", "event", "service"}:
            raise AppError("invalid_kind", "不支持此记录类型。")
        if len(query) > 200:
            raise AppError("invalid_query", "查询文字最长 200 字。")
        sources = tuple(SOURCES) if source == "all" else (source,)
        if not set(sources).issubset(SOURCES):
            raise AppError("invalid_source", "数据来源不受支持。")
        result = self.store.list(sources=sources, kind=kind, limit=limit, query=query, offset=offset)
        dependencies = {"grade": {"jw"}, "exam": {"jw"}, "course": {"mystu", "yuketang"},
                        "task": {"mystu", "yuketang"}, "resource": {"mystu", "yuketang"}, "event": {"mystu"}}
        needed = dependencies.get(kind, set()).intersection(sources)
        result["auth"] = [{"source": name, **self.vault.status(SOURCES[name].session)} for name in sorted(needed)]
        if not result["total_count"] and len(needed) == 1:
            auth = result["auth"][0]
            if auth["status"] != "session_saved":
                raise AppError(auth["status"], "此来源还需要本地登录和刷新；其他功能可独立使用。", auth["source"])
        if not result["total_count"]:
            result["message"] = "缓存中没有匹配记录；请按需刷新对应来源，不能据此判断学校没有该事项。"
        result["content_trust"] = "untrusted_source_data"
        return result

    def notice(self, item_id: str, refresh: bool = False) -> dict:
        record = self.store.get(item_id)
        if record["kind"] != "notice":
            raise AppError("invalid_notice", "请选择通知记录。")
        if refresh:
            record.update(collectors.article(record, self.vault))
            private = record["source"] == "oa" and str(record.get("url", "")).startswith("https:")
            self.store.save_batch(record["source"], [record], private=private)
        return {"ok": True, "item": record, "cached": not refresh, "content_trust": "untrusted_source_data"}

    def attachment(self, item_id: str, index: int = 0) -> dict:
        record = self.store.get(item_id)
        attachments = record.get("attachments", [])
        if not 0 <= index < len(attachments):
            raise AppError("attachment_not_cached", "请先读取并刷新通知正文，再选择附件序号。")
        source = record["source"]
        if source not in {"public", "oa"}:
            raise AppError("unsupported_source", "此来源暂不支持附件文字提取。")
        url = urljoin(record["url"], attachments[index]["url"])
        state = self.vault.load("webvpn") if source == "oa" and url.startswith("https:") else None
        with CampusHTTP(source, state) as http:
            response = http.request(url)
        content_type = response.headers.get("content-type", "").lower()
        data = response.content
        if data.startswith(b"%PDF"):
            try:
                reader = PdfReader(io.BytesIO(data))
                if len(reader.pages) > 100:
                    raise AppError("attachment_too_long", "此 PDF 超过 100 页，请在学校页面查看。")
                text = "\n".join((p.extract_text() or "") for p in reader.pages)[:60000]
            except AppError:
                raise
            except Exception:
                raise AppError("attachment_unreadable", "PDF 无法提取文字；扫描件需另行 OCR。") from None
        elif "html" in content_type:
            text = text_body(response.text)
        elif content_type.startswith("text/"):
            text = response.text[:60000]
        else:
            raise AppError("unsupported_attachment", "首版支持 PDF 和文本附件；其他格式请通过学校原链接查看。")
        return {"ok": True, "name": attachments[index]["name"], "text": text,
                "url": url, "content_trust": "untrusted_source_data", "truncated": len(text) >= 60000}

    def academic_summary(self, semester: str = "") -> dict:
        # One internal scan; the MCP response contains aggregates, not an unbounded grade list.
        page = self.store.list(sources=("jw",), kind="grade", _all_items=True)
        items = page["items"]
        if not items:
            self.query("grade", source="jw")  # Report missing login / inaccessible encryption honestly.
        if semester:
            items = [i for i in items if i.get("semester") == semester]
        def weighted(field: str):
            eligible = []
            for item in items:
                try:
                    score, credit = float(item[field]), float(item["credits"])
                    if credit > 0 and math.isfinite(score) and math.isfinite(credit):
                        eligible.append((score, credit))
                except (ValueError, TypeError, KeyError):
                    pass
            credits = sum(c for _, c in eligible)
            return {"value": round(sum(s * c for s, c in eligible) / credits, 4) if credits else None,
                    "included_count": len(eligible), "included_credits": credits}
        return {"ok": True, "cached": True, "semester": semester or "all", "course_count": len(items),
                "weighted_score": weighted("score"), "weighted_gpa": weighted("gpa"),
                "method": "按缓存中每条成绩的学分加权；非数值成绩排除，重修/补考逐条计入。不是学校官方绩点认定。",
                "freshness": self.store.freshness(), "scan_capped": page["scan_capped"]}

    def logout(self, service: str) -> dict:
        source = "oa" if service == "webvpn" else service
        if source not in SOURCES or not SOURCES[source].session:
            raise AppError("unknown_service", "此来源没有需要移除的登录态。")
        with key_lock(self.runtime.home, SOURCES[source].session):
            result = self.vault.logout(SOURCES[source].session)
            self.store.forget(source)
        return result
