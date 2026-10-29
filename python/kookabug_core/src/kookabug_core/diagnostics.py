"""검사 결과(진단) 한 건을 나타내는 값."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """진단 한 건.

    `code`는 영문 snake_case(도구·테스트가 구분용으로 쓴다), `message`는 사람이 읽는 한국어.
    `pointer`는 파일 안 위치(JSON pointer), `node`는 그래프 노드 ID(있으면).
    """

    severity: Severity
    code: str
    message: str
    file: str | None = None
    node: str | None = None
    pointer: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def has_errors(diagnostics: Iterable[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in diagnostics)


def json_pointer(*parts: str | int) -> str:
    """경로 조각 → JSON pointer (`~`·`/` 이스케이프)."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)
