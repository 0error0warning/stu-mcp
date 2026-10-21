"""Private, single-user Streamable HTTP using the official MCP SDK.

Preconfigured bearer authentication is intentionally not an OAuth authorization
server. Only clients supporting a private bearer credential can use this mode.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import Response

from ..credentials import read_private_file
from ..runtime import AppError


@dataclass(frozen=True)
class HTTPSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    public_url: str | None = None

    def security(self) -> TransportSecuritySettings:
        try:
            ipaddress.ip_address(self.host)
            if type(self.port) is not int or not 1 <= self.port <= 65535:
                raise ValueError
            hosts = [f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"[::1]:{self.port}"]
            origins = [f"http://{host}" for host in hosts]
            if self.public_url:
                parsed = urlsplit(self.public_url)
                if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                        or parsed.username or parsed.password or parsed.query or parsed.fragment
                        or parsed.path not in {"", "/mcp"} or not parsed.netloc.isascii()
                        or re.search(r"[\s\\*]", self.public_url)):
                    raise ValueError
                # Plain HTTP is limited to loopback. TLS terminates at the
                # operator's private reverse proxy for every other hostname.
                if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                    raise ValueError
                if parsed.port is not None and not 1 <= parsed.port <= 65535:
                    raise ValueError
                hostname = parsed.hostname.lower()
                hostname = f"[{hostname}]" if ":" in hostname else hostname
                default_port = 443 if parsed.scheme == "https" else 80
                authority = hostname if parsed.port in {None, default_port} else f"{hostname}:{parsed.port}"
                # Clients normalize case and often remove the default port.
                # Accept both canonical spellings without allowing wildcards.
                authorities = [authority]
                if parsed.port in {None, default_port}:
                    authorities.append(f"{hostname}:{default_port}")
                hosts.extend(authorities)
                origins.extend(f"{parsed.scheme}://{entry}" for entry in authorities)
            return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                             allowed_hosts=hosts, allowed_origins=origins)
        except (ValueError, TypeError):
            raise AppError("invalid_http_settings", "HTTP 绑定需使用 IP 和有效端口；public-url 需为无凭据的 "
                           "HTTPS /mcp 地址，回环地址可用 HTTP。") from None


def load_bearer(path: Path | None) -> bytes:
    if path is None:
        raise AppError("http_auth_required", "HTTP 服务必须通过 --auth-token-file 指定独立私密令牌文件。")
    raw = read_private_file(path, limit=4096).strip()
    if not re.fullmatch(rb"[A-Za-z0-9_~+./=-]{32,512}", raw):
        raise AppError("invalid_http_token", "令牌文件需包含 32–512 位随机 Bearer 令牌；请用 server-init 生成。")
    # A Fernet key is not an HTTP credential, even if copied to another path.
    # Prevent handing the session master key to every connected MCP client.
    if re.fullmatch(rb"[A-Za-z0-9_-]{43}=", raw):
        raise AppError("invalid_http_token", "HTTP 令牌不能使用 Fernet 会话主密钥；请使用独立随机令牌。")
    if master_file := os.environ.get("STU_MCP_KEY_FILE"):
        master = Path(master_file).expanduser()
        if path.resolve() == master.resolve() or hmac.compare_digest(
                raw, read_private_file(master, limit=4096).strip()):
            raise AppError("invalid_http_token", "HTTP 令牌必须独立于会话主密钥。")
    return raw


class PrivateHTTP:
    def __init__(self, app, token: bytes, security: TransportSecuritySettings):
        self.app = app
        self._authorization = b"Bearer " + token
        self.security = security

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)
        authorization = headers.get(b"authorization", [])
        valid = len(authorization) == 1 and hmac.compare_digest(authorization[0], self._authorization)
        if not valid:
            response = Response("Authentication required", 401,
                                headers={"WWW-Authenticate": 'Bearer realm="stu-mcp-private"',
                                         "Cache-Control": "no-store"})
        elif scope.get("path") != "/mcp":
            response = Response("Not found", 404)
        elif scope.get("query_string"):
            response = Response("Query parameters are not supported", 400)
        elif len(headers.get(b"host", [])) != 1 or len(headers.get(b"origin", [])) > 1:
            response = Response("Invalid transport headers", 400)
        elif headers[b"host"][0].decode("latin-1") not in self.security.allowed_hosts:
            response = Response("Invalid Host header", 421)
        elif headers.get(b"origin") and headers[b"origin"][0].decode("latin-1") not in self.security.allowed_origins:
            response = Response("Invalid Origin header", 403)
        else:
            # Keep the SDK's own Host/Origin checks enabled too. It owns MCP
            # sessions, JSON/SSE, size limits and the instance-wide lifespan.
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


def build_http_app(server, settings: HTTPSettings, token_file: Path):
    security = settings.security()
    token = load_bearer(token_file)
    app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=False,
        max_request_body_size=1024 * 1024, session_idle_timeout=900, max_sessions=32,
        transport_security=security, host=settings.host)
    return PrivateHTTP(app, token, security)


def run_http(server, settings: HTTPSettings, token_file: Path) -> None:
    import uvicorn
    app = build_http_app(server, settings, token_file)
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1,
                log_level="error", access_log=False, proxy_headers=False,
                timeout_keep_alive=5, limit_concurrency=64)
