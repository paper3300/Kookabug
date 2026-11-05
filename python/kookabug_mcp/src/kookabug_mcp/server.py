"""MCP 서버 (M5 계획 D1·3.2): stdio 줄 단위 JSON-RPC 2.0, 필요한 메서드만.

- `initialize`(판 협상) · `notifications/initialized` · `ping` · `tools/list` · `tools/call`
- 서버 알림: `notifications/tools/list_changed` (툴셋을 켜서 도구 목록이 바뀌었을 때)
- `tools/call`은 작업 스레드에서 돈다(daemon 대기 중에도 `ping`에 답한다). 응답 순서는 id로 짝짓는다
- 알 수 없는 도구·입력 형식 틀림만 JSON-RPC 오류(-32602). 권한·충돌 같은 daemon 오류는
  `isError` 결과(`results`)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from kookabug_mcp import __version__
from kookabug_mcp.daemon_link import DaemonLink
from kookabug_mcp.results import ToolError, error_result
from kookabug_mcp.stdio import StdioChannel
from kookabug_mcp.tools import ToolDef, by_name, call_tool, listed

__all__ = ["PROTOCOL_VERSIONS", "McpServer", "negotiate"]

log = logging.getLogger(__name__)

PROTOCOL_VERSIONS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
"""받는 판 (앞이 최신). 클라이언트가 이 중 하나를 보내면 그대로, 아니면 맨 앞."""

PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603
WORKERS: Final = 4

INSTRUCTIONS: Final = (
    "Kookabug 워크스페이스 도구. kb_project_info로 시작하고, 필요한 툴셋은 kb_toolset_enable로 "
    "켠다. 그래프는 kb_graph_get → kb_graph_patch(base_revision)로 고치고 노드 ID를 바꾸지 않는다. "
    "권한 거부는 isError 결과로 온다 — 정책을 바꾸려 하지 말고 사람에게 알린다."
)


def negotiate(asked: Any) -> str:
    return asked if isinstance(asked, str) and asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


class McpServer:
    def __init__(self, channel: StdioChannel, link: DaemonLink) -> None:
        self.channel = channel
        self.link = link
        self.protocol: str | None = None
        self._pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="mcp-tool")
        self._validators: dict[str, Draft202012Validator] = {}

    # ---------------------------------------------------------------- 주 루프

    def serve(self) -> int:
        """stdin이 끝날 때까지 받는다. 진행 중인 도구 호출을 마친 뒤 0."""
        try:
            for line in self.channel.lines():
                if line is None:
                    self._error(None, INVALID_REQUEST, "메시지가 너무 크다")
                    continue
                self._dispatch_line(line)
        finally:
            self._pool.shutdown(wait=True)
            self.link.close()
        return 0

    def _dispatch_line(self, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._error(None, PARSE_ERROR, f"JSON으로 읽을 수 없다: {exc}")
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self._error(None, INVALID_REQUEST, "JSON-RPC 2.0 객체 하나여야 한다 (배치 없음)")
            return
        msg: dict[str, Any] = message
        method = msg.get("method")
        if not isinstance(method, str):
            return  # 응답(클라이언트 → 서버 요청에 대한)은 보내지 않으므로 받을 일이 없다
        if "id" not in msg:
            return  # 알림: initialized·cancelled 등. 따로 할 일이 없다
        request_id = msg["id"]
        params = msg.get("params", {})
        if not isinstance(params, dict):
            self._error(request_id, INVALID_PARAMS, "params는 객체여야 한다")
            return
        if method == "tools/call":
            self._pool.submit(self._tool_call, request_id, params)
            return
        try:
            result = self._handle(method, params)
        except _RpcError as exc:
            self._error(request_id, exc.code, exc.message)
            return
        self._result(request_id, result)

    def _handle(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        match method:
            case "initialize":
                self.protocol = negotiate(params.get("protocolVersion"))
                return {
                    "protocolVersion": self.protocol,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "kookabug", "title": "Kookabug", "version": __version__},
                    "instructions": INSTRUCTIONS,
                }
            case "ping":
                return {}
            case "tools/list":
                return {"tools": listed(self.link.toolsets)}
            case _:
                raise _RpcError(METHOD_NOT_FOUND, f"모르는 메서드 {method!r}")

    # ---------------------------------------------------------------- 도구

    def _validator(self, tool: ToolDef) -> Draft202012Validator:
        found = self._validators.get(tool.name)
        if found is None:
            found = Draft202012Validator(tool.input_schema)
            self._validators[tool.name] = found
        return found

    def _tool_call(self, request_id: Any, params: Mapping[str, Any]) -> None:
        try:
            name = params.get("name")
            tool = by_name().get(name) if isinstance(name, str) else None
            if tool is None:
                self._error(request_id, INVALID_PARAMS, f"모르는 도구 {name!r}")
                return
            args = params.get("arguments", {})
            if args is None:
                args = {}
            if not isinstance(args, dict):
                self._error(request_id, INVALID_PARAMS, "arguments는 객체여야 한다")
                return
            problem = best_match(self._validator(tool).iter_errors(args))
            if problem is not None:
                where = "/".join(str(p) for p in problem.absolute_path) or "(arguments)"
                self._error(
                    request_id,
                    INVALID_PARAMS,
                    f"{tool.name} 입력 형식이 틀렸다: {where}: {problem.message}",
                )
                return
            before = self.link.toolsets
            try:
                result = call_tool(self.link, tool, args)
            except ToolError as exc:
                result = error_result(exc.code, exc.message, **exc.data)
            self._result(request_id, result)
            if self.link.toolsets != before:
                self.channel.send({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        except Exception:
            log.exception("도구 호출 처리 중 오류")
            self._error(request_id, INTERNAL_ERROR, "도구 호출 처리 중 shim 내부 오류")

    # ---------------------------------------------------------------- 보내기

    def _result(self, request_id: Any, result: Mapping[str, Any]) -> None:
        self.channel.send({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def _error(self, request_id: Any, code: int, message: str) -> None:
        self.channel.send(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
        )


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
