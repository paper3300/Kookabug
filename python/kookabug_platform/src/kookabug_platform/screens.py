"""화면 판정 (구현 계획 M1 2.10): `*.screen.json`의 `detect` 조건을 프레임 하나에서 본다.

`all`의 target이 전부 보이고 `none`의 target이 하나도 안 보이면 그 화면이다. 파일 찾기·형식은
`kookabug_core.screens`, 매칭은 `vision`. `kookabug screen test`가 쓴다(실행 중 화면 판정으로
실행을 바꾸지 않는다).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from kookabug_core.screens import ScreenDef
    from kookabug_platform.vision import FindResult, FrameMeta, Pixels, Vision
    from kookabug_sdk.types import Target

__all__ = ["ConditionResult", "ScreenResult", "evaluate_screen"]


@dataclass(frozen=True, slots=True)
class ConditionResult:
    """조건 하나: `found`는 target이 보였는지, `ok`는 조건이 맞는지(`none`이면 안 보여야 맞음)."""

    kind: Literal["all", "none"]
    target: str
    found: bool
    ok: bool
    result: FindResult


@dataclass(frozen=True, slots=True)
class ScreenResult:
    screen: ScreenDef
    conditions: tuple[ConditionResult, ...]

    @property
    def matched(self) -> bool:
        return all(c.ok for c in self.conditions)


def evaluate_screen(
    screen: ScreenDef,
    load: Callable[[str], Target],
    pixels: Pixels,
    meta: FrameMeta,
    vision: Vision,
) -> ScreenResult:
    """모든 조건을 본다 (맞지 않는 조건이 있어도 끝까지 — 어느 조건이 틀렸는지 보이게).

    `load`는 target 경로(워크스페이스 기준)를 `Target`으로 읽는다.
    """
    results: list[ConditionResult] = []
    groups: tuple[tuple[Literal["all", "none"], tuple[str, ...]], ...] = (
        ("all", screen.all),
        ("none", screen.none),
    )
    for kind, targets in groups:
        for rel in targets:
            found = vision.find(pixels, meta, load(rel))
            visible = found.found
            ok = visible if kind == "all" else not visible
            results.append(ConditionResult(kind, rel, visible, ok, found))
    return ScreenResult(screen, tuple(results))
