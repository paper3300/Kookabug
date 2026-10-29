"""테스트 판정 (스키마 v0 2장 판정 순서표).

| 순서 | 조건 | 판정 |
|---|---|---|
| 1 | `error`나 취소가 있었다 | `error` |
| 2 | 처리되지 않은 `fail`이 있었다 | `fail` |
| 3 | `core.test.fail` 종료 노드에 도달 | `fail` |
| 4 | `core.test.skip` 종료 노드에 도달 | `skipped` |
| 5 | 검증 노드 또는 `core.test.pass`가 하나 이상 성공 | `pass` |
| 6 | 그 외 | `fail` ("검증 없음") |

`judge()`는 실행이 모은 사실(`Facts`)만 보고 정하는 순수 함수다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Cause", "Facts", "Judgement", "Terminal", "Verdict", "judge"]

type Verdict = Literal["pass", "fail", "skipped", "error"]
type Terminal = Literal["pass", "fail", "skip"]


@dataclass(frozen=True, slots=True)
class Cause:
    """판정 원인. `step`은 스텝 ID, `path`는 테스트부터의 호출 경로(호출 노드들 + 노드).

    `code`: error면 고장 코드(`cancelled` = 취소), fail이면 `fail`, 종료 노드면 노드 종류.
    """

    step: str | None
    path: tuple[str, ...]
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Facts:
    error: Cause | None = None
    """`error`나 취소 (취소는 `code == "cancelled"`)."""
    unhandled_fail: Cause | None = None
    terminal: Terminal | None = None
    terminal_cause: Cause | None = None
    assertions_passed: int = 0


@dataclass(frozen=True, slots=True)
class Judgement:
    verdict: Verdict
    code: str
    reason: str
    cause: Cause | None = None


def judge(facts: Facts) -> Judgement:
    if facts.error is not None:
        return Judgement("error", facts.error.code, facts.error.message, facts.error)
    if facts.unhandled_fail is not None:
        cause = facts.unhandled_fail
        return Judgement("fail", "unhandled_fail", f"처리되지 않은 fail: {cause.message}", cause)
    if facts.terminal == "fail":
        cause = facts.terminal_cause
        reason = cause.message if cause is not None else "core.test.fail에 도달했다"
        return Judgement("fail", "test_fail", reason, cause)
    if facts.terminal == "skip":
        cause = facts.terminal_cause
        reason = cause.message if cause is not None else "core.test.skip에 도달했다"
        return Judgement("skipped", "test_skip", reason, cause)
    if facts.terminal == "pass":
        cause = facts.terminal_cause
        reason = cause.message if cause is not None else "core.test.pass에 도달했다"
        return Judgement("pass", "test_pass", reason)
    if facts.assertions_passed > 0:
        return Judgement("pass", "assertion_passed", f"검증 {facts.assertions_passed}개 성공")
    return Judgement(
        "fail", "no_assertion", "검증 없이 끝났다 (성공한 검증 노드도 core.test.pass도 없다)"
    )
