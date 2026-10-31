"""UI·에이전트 ↔ daemon 계약 (M2 계획 2.4). 단일 출처는 `daemon-rpc.schema.json`이다.

- 값 규칙은 M0b와 같다 (`kookabug_sdk.rpc`의 `decode_text`·`check_value`): 표준 JSON 숫자,
  NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단
- 받은 요청은 `Request` 봉투와 그 메서드의 params 스키마로, 보내는 응답은 그 메서드의 result
  스키마로, 보내는 알림은 `Notifications` 표의 params 스키마로 검사한다. `run.event`의 본문은 이
  params 검사가 events 스키마로 본다 (봉투 검사 `check_shape(msg, "daemon-rpc")`만으로는 보지 않음)
- 앱 오류는 -32100 `request_failed` 하나이고 종류는 `error.data.code`다
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import check_shape, metaschema
from kookabug_daemon import __version__
from kookabug_sdk.rpc import check_value, decode_text

__all__ = [
    "DAEMON_VERSION",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "MAX_FRAME",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "PROTOCOL",
    "REQUEST_FAILED",
    "UI_ONLY",
    "InvalidParams",
    "MethodInfo",
    "RequestFailed",
    "decode",
    "diagnostics_data",
    "encode",
    "error_message",
    "json_text",
    "methods",
    "notification_names",
    "notification_problems",
    "params_problems",
    "request_failed_codes",
    "request_id",
    "request_problems",
    "response_problems",
    "result_problems",
    "success_message",
    "utf8_size",
]

PROTOCOL: Final = 1
DAEMON_VERSION: Final = __version__
MAX_FRAME: Final = 16 * 1024 * 1024

PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603
REQUEST_FAILED: Final = -32100

UI_ONLY: Final = "ui_only"
_KIND: Final = "daemon-rpc"


@dataclass(frozen=True, slots=True)
class MethodInfo:
    """메서드 표(`$defs/Methods`) 한 줄."""

    name: str
    tool: str
    renderer: bool


def _defs() -> dict[str, Any]:
    return metaschema(_KIND)["$defs"]


@cache
def methods() -> dict[str, MethodInfo]:
    """계약의 메서드 표: 이름 → 권한 도구·렌더러 표면 여부."""
    table: dict[str, Any] = _defs()["Methods"]["properties"]
    return {
        name: MethodInfo(
            name, row["properties"]["tool"]["const"], row["properties"]["renderer"]["const"]
        )
        for name, row in table.items()
    }


@cache
def notification_names() -> frozenset[str]:
    return frozenset(_defs()["Notifications"]["properties"])


@cache
def request_failed_codes() -> frozenset[str]:
    return frozenset(_defs()["RequestFailedCode"]["enum"])


def request_id(message: Any) -> int | None:
    """메시지의 요청 ID (1 ~ 2^53-1). 읽을 수 없으면 None.

    JSON Schema의 `integer`는 `2.0` 같은 정수값 실수도 받는다. JS `JSON.parse("2.0")`도 2라서
    구별할 수 없으므로 정수로 바꿔 쓰고, 응답도 그 정수로 보낸다."""
    if not isinstance(message, dict):
        return None
    value: Any = message.get("id")  # pyright: ignore[reportUnknownMemberType]
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and 1 <= value <= 2**53 - 1:
        return value
    return None


def request_problems(message: Any) -> list[Diagnostic]:
    """받은 메시지가 `Request` 봉투가 아니면 그 이유."""
    return check_shape(message, _KIND, ref="#/$defs/Request")


def params_problems(method: str, params: Any) -> list[Diagnostic]:
    return check_shape(params, _KIND, ref=f"#/$defs/Methods/properties/{method}/properties/params")


def result_problems(method: str, result: Any) -> list[Diagnostic]:
    return check_shape(result, _KIND, ref=f"#/$defs/Methods/properties/{method}/properties/result")


def notification_problems(name: str, params: Any) -> list[Diagnostic]:
    """알림 이름과 params 모양. `run.event`면 이벤트 본문까지 events 스키마로 본다."""
    if name not in notification_names():
        return [Diagnostic("error", "unknown_notification", f"계약에 없는 알림 {name!r}")]
    message = {"jsonrpc": "2.0", "method": name, "params": params}
    return [
        *check_shape(message, _KIND, ref="#/$defs/Notification"),
        *check_shape(
            params, _KIND, ref=f"#/$defs/Notifications/properties/{name}/properties/params"
        ),
    ]


def response_problems(message: Any) -> list[Diagnostic]:
    """응답 봉투(성공·오류). 결과 모양은 `result_problems`가 메서드별로 본다."""
    if isinstance(message, dict) and "error" in message:
        return check_shape(message, _KIND, ref="#/$defs/DaemonErrorResponse")
    return check_shape(message, _KIND, ref="#/$defs/SuccessResponse")


class RequestFailed(Exception):
    """-32100 request_failed. `code`는 `RequestFailedCode`, `fields`는 종류별 추가 필드."""

    def __init__(self, code: str, text: str, /, **fields: Any) -> None:
        if code not in request_failed_codes():
            raise ValueError(f"계약에 없는 오류 종류 {code!r}")
        super().__init__(text)
        self.code = code
        self.message = text
        self.fields = fields

    def error(self) -> dict[str, Any]:
        return {
            "code": REQUEST_FAILED,
            "message": self.message,
            "data": {"code": self.code, **self.fields},
        }


class InvalidParams(Exception):
    """-32602 invalid_params: 형식 검사는 지났지만 그 메서드가 받을 수 없는 인자 (예: 그래프
    메서드에 `*.graph.json`이 아닌 경로). `data`는 사람이 읽는 정보다."""

    def __init__(self, text: str, /, **data: Any) -> None:
        super().__init__(text)
        self.message = text
        self.data = data


def success_message(request_id: int, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_message(
    request_id: int | None,
    code: int,
    message: str,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = dict(data)
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


_SURROGATE: Final = re.compile("[\ud800-\udfff]")


def json_text(value: Any) -> str:
    """UTF-8로 바꿀 수 있는 JSON 텍스트. 한글 등은 그대로 두고, 짝 없는 대리 문자(`"\\ud800"`)만
    `\\udXXX` 이스케이프로 쓴다 — `ensure_ascii=False`는 이를 날것으로 남겨 UTF-8 인코딩·전송이
    실패한다. 대리 문자는 JSON 문자열 안에만 나올 수 있으므로 이스케이프해도 값이 같다."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if text.isascii():
        return text
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", text)


def utf8_size(text: str) -> int:
    """프레임·큐 크기 = 실제 UTF-8 바이트 수."""
    return len(text) if text.isascii() else len(text.encode("utf-8"))


def encode(message: Mapping[str, Any]) -> str:
    """JSON 텍스트 한 프레임. 값 규칙을 어기면 `ValueError`/`TypeError`, 상한을 넘으면 `ValueError`.

    Python float는 `repr` 표기라 `1e+20`·`9007199254740992.0`처럼 float로 남는다 (M2 계획 2.4)."""
    check_value(message)
    text = json_text(message)
    if utf8_size(text) > MAX_FRAME:
        raise ValueError(f"메시지가 프레임 상한({MAX_FRAME}바이트)보다 크다")
    return text


def decode(text: str) -> Any:
    """받은 텍스트 프레임 → 값. 값 규칙 위반·JSON 아님은 `ValueError` (→ parse_error)."""
    return decode_text(text)


def diagnostics_data(problems: list[Diagnostic]) -> dict[str, Any]:
    return {"diagnostics": [d.to_dict() for d in problems]}
