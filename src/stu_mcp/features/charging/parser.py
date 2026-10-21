"""Pure, bounded charging-client discovery and API decoding; no provider requests."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ...runtime import AppError
from .models import PublicConfig
from .schema import AFTER_TYPES, BASE, BEFORE_TYPES, SCRIPT_PATH_PATTERN, STATE_LABELS


def _changed(message: str) -> AppError:
    return AppError("schema_changed", message, "charging")


class ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources: list[str] = []
        self.ambiguous = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            sources = [value for name, value in attrs if name == "src"]
            if len(set(sources)) > 1:
                self.ambiguous = True
            self.sources.extend(value for value in sources if isinstance(value, str))


def discover_script(html: str) -> str:
    if not isinstance(html, str):
        raise _changed("充电平台公开客户端入口变化。")
    parser = ScriptSources()
    parser.feed(html)
    candidates = set()
    for value in parser.sources:
        try:
            url = urlsplit(urljoin(BASE + "/", value))
        except ValueError:
            continue
        if (url.scheme == "https" and url.netloc == "wx.isfdz.com" and not url.query and not url.fragment
                and re.fullmatch(SCRIPT_PATH_PATTERN, url.path)):
            candidates.add(url.path)
    if parser.ambiguous or len(candidates) != 1:
        raise _changed("充电平台公开客户端入口变化或存在多个候选。")
    return candidates.pop()


_JS_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_REGEX_PREFIXES = frozenset({"=", "(", "[", "{", ":", ",", ";", "!", "?", "&", "|", "+", "-",
                              "*", "%", "^", "~", "<", ">", "return", "throw", "case", "yield",
                              "else", "do", "void", "delete", "typeof", "await"})
_CONTROL_PARENTHESES = frozenset({"if", "while", "for", "with", "switch", "catch"})


def _configuration_changed() -> AppError:
    return _changed("充电平台公开请求配置字段变化或存在歧义。")


def _regex_end(source: str, start: int) -> int | None:
    """Skip a regex literal only in expression-prefix positions; never interpret it."""
    position, character_class = start + 1, False
    while position < len(source):
        char = source[position]
        if char in "\r\n":
            return None
        if char == "\\":
            position += 2
            continue
        if char == "[":
            character_class = True
        elif char == "]":
            character_class = False
        elif char == "/" and not character_class:
            position += 1
            while position < len(source) and source[position].isalpha():
                position += 1
            return position
        position += 1
    return None


def _template_end(source: str, start: int, depth: int) -> int:
    if depth > 64:
        raise _configuration_changed()
    position = start + 1
    while position < len(source):
        if source[position] == "\\":
            position += 2
        elif source[position] == "`":
            return position + 1
        elif source.startswith("${", position):
            position, braces, previous = position + 2, 1, None
            while braces:
                token = _configuration_token(source, position, previous, depth + 1)
                if token is None:
                    raise _configuration_changed()
                kind, value, position = token
                if kind == "punct" and value in {"{", "}"}:
                    braces += 1 if value == "{" else -1
                previous = value if kind in {"identifier", "punct"} else "literal"
        else:
            position += 1
    raise _configuration_changed()


def _configuration_token(source: str, position: int, previous: str | None, depth: int = 0):
    """A small lexical boundary reader, not a JS evaluator or general JS parser."""
    while position < len(source):
        if source[position].isspace():
            position += 1
        elif source.startswith("//", position):
            ending = source.find("\n", position + 2)
            position = len(source) if ending < 0 else ending + 1
        elif source.startswith("/*", position):
            ending = source.find("*/", position + 2)
            if ending < 0:
                raise _configuration_changed()
            position = ending + 2
        else:
            break
    if position >= len(source):
        return None
    char = source[position]
    if char in {"'", '"'}:
        start, position, literal = position + 1, position + 1, True
        while position < len(source):
            if source[position] == char:
                return "string", source[start:position] if literal else None, position + 1
            if source[position] == "\\":
                literal = False  # Known fields permit plain literals only; no escape decoding.
                position += 2
            elif source[position] in "\r\n":
                raise _configuration_changed()
            else:
                position += 1
        raise _configuration_changed()
    if char == "`":
        return "opaque", "template", _template_end(source, position, depth)
    if char == "/" and (previous is None or previous in _REGEX_PREFIXES):
        ending = _regex_end(source, position)
        if ending is not None:
            return "opaque", "regex", ending
    identifier = _JS_IDENTIFIER.match(source, position)
    if identifier:
        return "identifier", identifier[0], identifier.end()
    return "punct", char, position + 1


def _object_configuration(tokens: list[tuple[str, str | None]]) -> tuple[str, str] | None:
    members: list[list[tuple[str, str | None]]] = [[]]
    for token in tokens:
        if token == ("punct", ","):
            members.append([])
        else:
            members[-1].append(token)
    fields: dict[str, set[str]] = {}
    invalid = False
    for index, member in enumerate(members):
        if not member:
            invalid |= index != len(members) - 1
            continue
        kind, name = member[0]
        static = kind in {"identifier", "string"} and name is not None
        property_value = static and len(member) >= 3 and member[1] == ("punct", ":")
        invalid |= not property_value  # Spread, computed keys, getters and shorthand cannot override identities.
        if not static or name not in {"app_id", "app_secret"}:
            continue
        if (not property_value or len(member) != 3 or member[2][0] != "string"
                or member[2][1] is None or not 1 <= len(member[2][1]) <= (128 if name == "app_id" else 256)):
            raise _configuration_changed()
        fields.setdefault(name, set()).add(member[2][1])
    if not fields:
        return None
    if invalid or set(fields) != {"app_id", "app_secret"} or any(len(values) != 1 for values in fields.values()):
        raise _configuration_changed()
    return next(iter(fields["app_id"])), next(iter(fields["app_secret"]))


def parse_configuration(source: str, loaded_at: float) -> PublicConfig:
    """Recognize one direct literal pair; ignore strings, comments and unrelated nesting."""
    if not isinstance(source, str):
        raise _changed("充电平台公开请求配置变化。")
    configurations: set[tuple[str, str]] = set()
    frames: list[tuple[str, list, bool]] = [("root", [], False)]
    position, previous = 0, None
    while (token := _configuration_token(source, position, previous)) is not None:
        kind, value, position = token
        before = previous
        previous = value if kind in {"identifier", "punct"} else "literal"
        if kind == "punct" and value in {"{", "[", "("}:
            if len(frames) >= 256:
                raise _configuration_changed()
            frames.append((value, [], value == "(" and before in _CONTROL_PARENTHESES))
        elif kind == "punct" and value in {"}", "]", ")"}:
            if len(frames) == 1 or frames[-1][0] != {"}": "{", "]": "[", ")": "("}[value]:
                raise _configuration_changed()
            opening, members, control = frames.pop()
            if opening == "{" and (configuration := _object_configuration(members)) is not None:
                configurations.add(configuration)
            frames[-1][1].append(("group", opening))
            if control:
                previous = ";"  # A control condition may be followed by a regex expression statement.
        else:
            frames[-1][1].append((kind, value))
    if len(frames) != 1:
        raise _configuration_changed()
    if len(configurations) != 1:
        raise _changed("充电平台公开请求配置变化或存在多个候选。")
    app_id, secret = configurations.pop()
    return PublicConfig(app_id, secret, loaded_at)


@dataclass(frozen=True)
class ApiResult:
    data: object = None
    renew_config: bool = False


def parse_envelope(payload: object) -> ApiResult:
    if not isinstance(payload, dict) or type(payload.get("code")) is not int:
        raise _changed("充电平台响应结构变化。")
    code = payload["code"]
    if code == 200:
        if "data" not in payload:
            raise _changed("充电平台成功响应缺少数据字段。")
        return ApiResult(data=payload["data"])
    # Provider-wide access failures cannot be downgraded by conflicting free text.
    if code in (401, 403, 429):
        status = "rate_limited" if code == 429 else "access_denied"
        raise AppError(status, "充电平台限制或拒绝此次公开读取。", "charging", http_status=200)
    message = payload.get("msg")
    if message is not None and not isinstance(message, str):
        raise _changed("充电平台业务状态字段变化。")
    if isinstance(message, str) and "设备不在线" in message:
        raise AppError("device_offline", "充电平台报告设备不在线，当前插座状态未知。", "charging", http_status=200)
    if message in ("签名错误", "时间戳已过期"):
        return ApiResult(renew_config=True)
    raise AppError("source_error", "充电平台返回业务失败，未将其当作零空闲。", "charging", http_status=200)


def device_protocol(kind: object) -> str:
    if type(kind) is not int or kind not in AFTER_TYPES | BEFORE_TYPES:
        raise AppError("unsupported_device", "充电平台返回了未支持的设备类型。", "charging")
    return "afterProtocol" if kind in AFTER_TYPES else "beforeProtocol"


def timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


def sign_params(params: dict, config: PublicConfig, unix_seconds: int) -> dict:
    values = {**params, "timestamp": unix_seconds, "app_id": config.app_id}
    basis = "".join(f"{key}={values[key]}" for key in sorted(values)) + config.secret
    return {**values, "sign": hashlib.md5(basis.encode("utf-8")).hexdigest()}


def parse_ports(data, capacity: int) -> dict:
    if not isinstance(data, list) or not data or len(data) > capacity:
        raise _changed("充电平台未返回有效的插座列表，未将其当作零空闲。")
    seen, ports = set(), []
    for port in data:
        if (not isinstance(port, dict) or type(port.get("num")) is not int
                or not 1 <= port["num"] <= capacity or port["num"] in seen
                or type(port.get("state")) is not int or port["state"] < 0):
            raise _changed("插座编号或状态结构变化，未覆盖上次成功数据。")
        seen.add(port["num"])
        ports.append({"num": port["num"], "state": port["state"],
                      "label": STATE_LABELS.get(port["state"], "未知状态")})
    free = sum(p["state"] == 1 for p in ports)
    occupied = sum(p["state"] == 2 for p in ports)
    fault = sum(p["state"] in STATE_LABELS and p["state"] not in (1, 2) for p in ports)
    return {"ports": sorted(ports, key=lambda p: p["num"]), "ports_complete": len(seen) == capacity,
            "counts": {"total": capacity, "observed": len(ports), "free": free, "occupied": occupied,
                       "fault": fault, "unknown": capacity - free - occupied - fault}}
