"""실행 중 고장(`error`)의 코드.

노드 함수가 던진 예외와 실행기가 찾은 문제는 모두 `error`다 (출구로 나가지 않고 위로 전파한다).
코드는 영문 snake_case. 실행 전 검증과 같은 문제면 같은 코드를 쓴다.

| 코드 | 뜻 |
|---|---|
| `node_error` | 노드 함수가 예외를 던졌다 |
| `node_contract` | 노드가 선언과 다르게 동작했다 (선언 안 한 출구·출력) |
| `context_violation` | 쓸 수 없는 ctx 기능을 불렀다 (순수 노드의 캡처·기록, 선언 안 한 효과) |
| `link_missing` | `$link`가 이번 경로에서 만들어지지 않은 출력을 읽는다 (건너뛴 분기 등) |
| `pure_reentry` | 순수 노드 계산 중에 같은 순수 노드로 다시 들어왔다 (data 순환) |
| `deadline_exceeded` | 테스트 전체 기한을 넘었다 (G11) |
| `cancelled` | 실행이 취소됐다 (판정은 `error`) |
| `type_mismatch`·`input_invalid` | 실행 때 계산한 입력 값이 핀 타입·제약에 맞지 않는다 |
| 그 밖 | 검증을 건너뛴(`validate=False`) 그래프에서 실행 전 검증 코드와 같은 문제 |
"""

from __future__ import annotations

from kookabug_sdk import NodeContractError
from kookabug_sdk.context import ContextViolation

__all__ = ["EngineError", "error_code"]


class EngineError(Exception):
    """실행기가 찾은 고장. 그 스텝의 `error`가 된다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def error_code(exc: Exception) -> str:
    if isinstance(exc, EngineError):
        return exc.code
    if isinstance(exc, ContextViolation):
        return "context_violation"
    if isinstance(exc, NodeContractError):
        return "node_contract"
    return "node_error"
