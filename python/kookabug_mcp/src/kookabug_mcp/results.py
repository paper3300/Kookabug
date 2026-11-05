"""MCP 도구 결과 모양 (M5 계획 3.2).

- 성공: `content = [{type: text, text: <요약 한 줄 + JSON>}]` + `structuredContent`(같은 JSON)
- daemon 오류(권한·충돌·툴셋 등): JSON-RPC 오류가 아니라 `isError: true` + `"<code>: <메시지>"` +
  `structuredContent.error = {code, message, ...}` — 에이전트가 읽고 다시 할 수 있게
- 글자 결과 상한 256 KiB (넘으면 자르고 `truncated: true`)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.client import DaemonError

__all__ = ["MAX_TEXT", "ToolError", "error_result", "from_daemon_error", "ok_result"]

MAX_TEXT: Final = 256 * 1024


class ToolError(Exception):
    """도구가 `isError`로 답할 오류. `data`는 `structuredContent.error`에 더할 필드."""

    def __init__(self, code: str, message: str, **data: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _cut(text: str) -> tuple[str, bool]:
    data = text.encode("utf-8")
    if len(data) <= MAX_TEXT:
        return text, False
    return data[: MAX_TEXT - 64].decode("utf-8", errors="ignore") + "\n…(잘림)", True


def ok_result(summary: str, data: Mapping[str, Any]) -> dict[str, Any]:
    body = _dumps(data)
    text, truncated = _cut(f"{summary}\n{body}")
    structured: dict[str, Any] = dict(data)
    if truncated:
        # 같은 JSON을 다 실을 수 없다: 요약과 표시만 남긴다
        structured = {"truncated": True, "summary": summary}
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": structured,
        "isError": False,
    }


def error_result(code: str, message: str, **data: Any) -> dict[str, Any]:
    error = {"code": code, "message": message, **data}
    text, _ = _cut(f"{code}: {message}")
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"error": error},
        "isError": True,
    }


def from_daemon_error(exc: DaemonError) -> dict[str, Any]:
    """daemon 오류 응답 → `isError` 결과. -32100이면 `data.code`, 아니면 JSON-RPC 코드 이름."""
    data: dict[str, Any] = dict(exc.data) if isinstance(exc.data, dict) else {}
    code = exc.kind or {
        -32602: "invalid_params",
        -32601: "method_not_found",
        -32603: "internal_error",
    }.get(exc.code, f"daemon_error_{exc.code}")
    data.pop("code", None)
    extra = {k: data[k] for k in ("decision", "revision", "toolset", "index", "path") if k in data}
    if "diagnostics" in data:
        extra["diagnostics"] = data["diagnostics"]
    return error_result(code, exc.message, **extra)
