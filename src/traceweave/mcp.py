from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PROTOCOL_VERSION = "2025-11-25"


class MCPError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MCPServer:
    name: str
    url: str
    enabled: bool = True
    token_env: str = ""
    read_only: bool = True
    allowed_tools: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)

    def request_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.token_env:
            token = os.getenv(self.token_env, "").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers


def load_mcp_servers(path: Path = Path(".traceweave/mcp.toml")) -> list[MCPServer]:
    if not path.is_file():
        return []
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    servers: list[MCPServer] = []
    for item in payload.get("servers", []):
        server = MCPServer(
            name=str(item.get("name") or "").strip(),
            url=str(item.get("url") or "").strip(),
            enabled=bool(item.get("enabled", True)),
            token_env=str(item.get("token_env") or "").strip(),
            read_only=bool(item.get("read_only", True)),
            allowed_tools=tuple(str(value) for value in item.get("allowed_tools", [])),
            headers={str(key): str(value) for key, value in (item.get("headers") or {}).items()},
        )
        if not server.name or not server.url:
            continue
        parts = urlsplit(server.url)
        local = (parts.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise MCPError(f"MCP server {server.name!r} must use HTTPS or loopback HTTP")
        servers.append(server)
    return servers


class StreamableHTTPMCPClient:
    """Small MCP discovery client for configured Streamable HTTP servers.

    Stdio process launch is intentionally not implicit: an operator may expose a local stdio
    server through a loopback Streamable HTTP bridge, keeping subprocess authority out of the agent.
    """

    def __init__(
        self,
        server: MCPServer,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.server = server
        self.timeout = timeout
        self._session_id = ""
        self._protocol_version = PROTOCOL_VERSION
        self._next_id = 1
        self._transport = transport

    @staticmethod
    def _decode(response: httpx.Response) -> dict:
        content_type = response.headers.get("content-type", "").casefold()
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    try:
                        value = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(value, dict) and ("result" in value or "error" in value):
                        return value
            raise MCPError("MCP server returned no JSON-RPC result event")
        try:
            value = response.json()
        except ValueError as exc:
            raise MCPError("MCP server returned a non-JSON response") from exc
        if not isinstance(value, dict):
            raise MCPError("MCP response is not a JSON object")
        return value

    def _headers(self, method: str, name: str = "") -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._protocol_version,
            "Mcp-Method": method,
            **self.server.request_headers(),
        }
        if name:
            headers["Mcp-Name"] = name
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, method: str, params: dict | None = None, *, notification: bool = False) -> dict:
        request_id = self._next_id
        self._next_id += 1
        body: dict = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = request_id
        if params is not None:
            body["params"] = params
        name = str((params or {}).get("name") or (params or {}).get("uri") or "")
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            response = await client.post(
                self.server.url,
                headers=self._headers(method, name),
                json=body,
            )
            response.raise_for_status()
            session_id = response.headers.get("mcp-session-id", "").strip()
            if session_id:
                self._session_id = session_id
        if notification or response.status_code == 202 or not response.content:
            return {}
        value = self._decode(response)
        if value.get("error"):
            raise MCPError(str(value["error"]))
        return value

    async def initialize(self) -> dict:
        value = await self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "TraceWeave", "version": "1.0.2"},
            },
        )
        result = value.get("result") or {}
        negotiated = str(result.get("protocolVersion") or PROTOCOL_VERSION)
        if negotiated not in {"2025-11-25", "2025-06-18", "2025-03-26"}:
            raise MCPError(f"unsupported MCP protocol version: {negotiated}")
        self._protocol_version = negotiated
        await self._post("notifications/initialized", notification=True)
        return result

    async def list_tools(self) -> list[dict]:
        await self.initialize()
        cursor = ""
        tools: list[dict] = []
        while True:
            params = {"cursor": cursor} if cursor else {}
            value = await self._post("tools/list", params)
            result = value.get("result") or {}
            tools.extend(item for item in result.get("tools", []) if isinstance(item, dict))
            cursor = str(result.get("nextCursor") or "")
            if not cursor or len(tools) >= 1000:
                break
        return sorted(tools[:1000], key=lambda item: str(item.get("name") or ""))

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if name not in self.server.allowed_tools:
            raise MCPError(f"tool {name!r} is not in allowed_tools for {self.server.name!r}")
        await self.initialize()
        value = await self._post("tools/call", {"name": name, "arguments": arguments})
        result = value.get("result") or {}
        return result if isinstance(result, dict) else {"content": result}
