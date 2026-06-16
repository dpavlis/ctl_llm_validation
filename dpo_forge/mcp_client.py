"""MCP client over the Streamable HTTP transport.

Implements the minimal JSON-RPC 2.0 handshake + tool dispatch needed
to drive a clover-server MCP endpoint from Python.

The Streamable HTTP transport:
  - All requests are HTTP POST to a single endpoint URL
  - Body: JSON-RPC 2.0 object
  - Response: either application/json (direct) or text/event-stream (SSE)
  - Notifications (fire-and-forget) are POST with no id field

Requires: httpx  (pip install httpx)
"""

from __future__ import annotations

import json
import threading
from typing import Any, Optional


class MCPError(Exception):
    pass


class MCPClient:

    def __init__(
        self,
        endpoint: str,
        headers: Optional[dict] = None,
        timeout: int = 120,
    ):
        try:
            import httpx
            self._httpx = httpx
        except ImportError:
            raise ImportError("httpx is required for MCPClient: pip install httpx")

        self._endpoint = endpoint.rstrip("/")
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if headers:
            self._headers.update(headers)
        self._timeout = timeout
        self._id_lock = threading.Lock()
        self._id_counter = 0
        self._initialized = False
        self._tools: list[dict] = []

    # ------------------------------------------------------------------
    # JSON-RPC transport
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        with self._id_lock:
            self._id_counter += 1
            return self._id_counter

    def _post(self, payload: dict) -> Optional[Any]:
        resp = self._httpx.post(
            self._endpoint,
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()

        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            return self._parse_sse(resp.text)
        else:
            data = resp.json()
            if "error" in data:
                raise MCPError(f"JSON-RPC error {data['error'].get('code')}: {data['error'].get('message')}")
            return data.get("result")

    def _rpc(self, method: str, params: Optional[dict] = None) -> Any:
        payload: dict = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            payload["params"] = params
        return self._post(payload)

    def _notify(self, method: str, params: Optional[dict] = None):
        """Fire-and-forget notification (no id, no response expected)."""
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        try:
            self._httpx.post(
                self._endpoint,
                json=payload,
                headers=self._headers,
                timeout=10,
            )
        except Exception:
            pass  # notifications are best-effort

    @staticmethod
    def _parse_sse(text: str) -> Any:
        """Extract the last result from an SSE response body."""
        last_result = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "error" in msg:
                raise MCPError(f"SSE error: {msg['error']}")
            if "result" in msg:
                last_result = msg["result"]
        return last_result

    # ------------------------------------------------------------------
    # MCP protocol
    # ------------------------------------------------------------------

    def initialize(self):
        """Perform the MCP initialize handshake (idempotent)."""
        if self._initialized:
            return
        # Do the POST directly so we can capture Mcp-Session-Id from response headers
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "dpo-forge", "version": "0.1"},
            },
        }
        resp = self._httpx.post(
            self._endpoint,
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        session_id = (
            resp.headers.get("Mcp-Session-Id")
            or resp.headers.get("mcp-session-id")
        )
        if session_id:
            self._headers["Mcp-Session-Id"] = session_id
        self._initialized = True
        # Notify the server we're ready (session ID now included in headers)
        self._notify("notifications/initialized")

    def list_tools(self, force_refresh: bool = False) -> list[dict]:
        """Return available MCP tool definitions, caching after first call."""
        if not self._initialized:
            self.initialize()
        if self._tools and not force_refresh:
            return self._tools
        result = self._rpc("tools/list") or {}
        self._tools = result.get("tools", [])
        return self._tools

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Call an MCP tool and return its result content.

        If the response content is a single text item, returns the text string.
        Otherwise returns the full content array.
        """
        if not self._initialized:
            self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}
        content = result.get("content", [])
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
            return content[0]["text"]
        return content

    # ------------------------------------------------------------------
    # Tool format converters (for LLM binding)
    # ------------------------------------------------------------------

    def to_anthropic_tools(self, tools: Optional[list[dict]] = None) -> list[dict]:
        """Convert MCP tool list to Anthropic tool_use format."""
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
            }
            for t in (tools if tools is not None else self._tools)
        ]

    def to_openai_tools(self, tools: Optional[list[dict]] = None) -> list[dict]:
        """Convert MCP tool list to OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
                },
            }
            for t in (tools if tools is not None else self._tools)
        ]
