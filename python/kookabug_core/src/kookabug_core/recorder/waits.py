"""대기 추론의 판단 규칙 (M4 계획 2.7 "대기 추론", 검수 M2, Q8). 순수 — 픽셀 계산은 플랫폼.

대기는 "사람이 기다린 시간"이 아니라 **다음 동작이 필요로 하는 화면 상태**로 만든다. 비교는
`A` = 앞 동작 입력 직전 프레임, `B` = 이 동작 입력 직전 프레임, 그 사이 전이 기록.

1. A와 B가 같으면(바뀐 픽셀 ≤ 0.5%, 잠깐 바뀌었다 돌아온 것 포함) 대기 없음
2. 바뀐 영역 R이 칸 상자 안이면(칸 클릭 → 입력: 포커스 그림만 바뀜) 대기 없음
3. 다음 동작이 클릭이고 그 target이 A에서 안 보이면 `image.click`이 스스로 기다리므로 대기 없음
4. 그 밖(키·글자·끌기·휠 앞, A에서도 보이던 단추 클릭 앞): 옵션 켬이면 R에서 자른, A에는 없는
   조각으로 `image.wait`. 못 만들면 보수적 지연 + `wait_target_unknown`. 옵션 끔이면 지연(gap)
5. `timeout_ms = clamp(ceil(마지막 전이 - 앞 동작) x 3, 10 s, 120 s)` (전이 기록이 없으면 gap)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "CHANGE_RATIO",
    "DELAY_MIN_MS",
    "TIMEOUT_MAX_MS",
    "TIMEOUT_MIN_MS",
    "NextKind",
    "WaitDecision",
    "WaitFacts",
    "decide_wait",
    "delay_ms",
    "wait_timeout_ms",
]

CHANGE_RATIO: Final = 0.005
"""A와 B의 바뀐 픽셀 비율이 이 이하면 같은 화면."""
TIMEOUT_MIN_MS: Final = 10_000
TIMEOUT_MAX_MS: Final = 120_000
DELAY_MIN_MS: Final = 500
MS: Final = 1_000_000

type NextKind = Literal["click", "key", "text", "drag", "scroll", "check"]


@dataclass(frozen=True, slots=True)
class WaitFacts:
    """판단 재료. 시각은 단조 ns."""

    prev_t_ns: int
    """앞 동작 입력 시각."""
    t_ns: int
    """이 동작 입력 시각."""
    changed_ratio: float
    """A ↔ B 바뀐 픽셀 비율 (0~1)."""
    last_change_ns: int | None
    """전이 기록의 마지막 변화 도착 시각 (없으면 None)."""
    next_kind: NextKind
    r_in_field: bool = False
    """바뀐 영역이 칸 상자 안 (칸 클릭 → 입력)."""
    click_target_in_a: bool | None = None
    """다음이 클릭이면: 그 target이 A에서 찾아지는가 (None = 클릭 아님·target 없음)."""
    wait_target: bool = False
    """R에서 A에 없는 유일한 조각을 만들었다."""
    option_on: bool = True
    """시안 옵션 "기다린 시간을 '나타날 때까지 대기'로 바꾸기"."""


@dataclass(frozen=True, slots=True)
class WaitDecision:
    kind: Literal["none", "image_wait", "delay"]
    timeout_ms: int | None = None
    """`image.wait`·`image.click`의 timeout (none이어도 클릭이면 늘린 값을 쓴다)."""
    ms: int | None = None
    """`flow.delay`."""
    needs_review: tuple[str, ...] = ()


def wait_timeout_ms(prev_t_ns: int, t_ns: int, last_change_ns: int | None) -> int:
    """`clamp(ceil(마지막 전이 - 앞 동작) x 3, 10 s, 120 s)`. 전이 기록이 없으면 gap 기준."""
    end = last_change_ns if last_change_ns is not None else t_ns
    span_ms = max(0, math.ceil((end - prev_t_ns) / MS))
    return min(max(span_ms * 3, TIMEOUT_MIN_MS), TIMEOUT_MAX_MS)


def delay_ms(prev_t_ns: int, t_ns: int, last_change_ns: int | None) -> int:
    """보수적 지연: `max(500, ceil(마지막 전이 - 앞 동작) x 1.5)` (전이가 없으면 gap)."""
    end = last_change_ns if last_change_ns is not None else t_ns
    span_ms = max(0, math.ceil((end - prev_t_ns) / MS))
    return max(DELAY_MIN_MS, math.ceil(span_ms * 1.5))


def decide_wait(f: WaitFacts) -> WaitDecision:
    timeout = wait_timeout_ms(f.prev_t_ns, f.t_ns, f.last_change_ns)
    if f.changed_ratio <= CHANGE_RATIO or f.r_in_field:
        return WaitDecision("none")
    if not f.option_on:
        return WaitDecision("delay", ms=max(0, (f.t_ns - f.prev_t_ns) // MS))
    if f.next_kind == "click" and f.click_target_in_a is False:
        return WaitDecision("none", timeout_ms=timeout)  # image.click이 기다린다
    if f.wait_target:
        return WaitDecision("image_wait", timeout_ms=timeout)
    return WaitDecision(
        "delay",
        ms=delay_ms(f.prev_t_ns, f.t_ns, f.last_change_ns),
        needs_review=("wait_target_unknown",),
    )
