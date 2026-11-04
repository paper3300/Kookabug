"""훅 메시지 계약의 수치와 관측 짝짓기 규칙 (M4 계획 2.1, `recorder-hook.schema.json`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

__all__ = [
    "BATCH_MAX_EVENTS",
    "CRITICAL_KINDS",
    "HOOK_PROTOCOL",
    "IME_SAMPLE_VALID_NS",
    "OBS_MAX_SKEW_NS",
    "is_critical",
    "obs_usable",
]

HOOK_PROTOCOL: Final = 1
BATCH_MAX_EVENTS: Final = 256
"""hook.events 묶음 하나의 최대 이벤트 수 (스키마 maxItems와 같다)."""

OBS_MAX_SKEW_NS: Final = 50_000_000
"""즉시 관측을 이벤트에 쓸 수 있는 시각 차 (50 ms)."""

IME_SAMPLE_VALID_NS: Final = 300_000_000
"""IME 표본이 키 앞뒤로 유효한 범위 (300 ms)."""

CRITICAL_KINDS: Final = frozenset({"mouse_down", "mouse_up", "wheel", "key_down", "key_up"})
"""crit_seq를 받는 중요 이벤트 (이동만 아니다)."""


def is_critical(event: Mapping[str, Any]) -> bool:
    return event.get("kind") in CRITICAL_KINDS


def obs_usable(event: Mapping[str, Any], obs: Mapping[str, Any] | None) -> bool:
    """즉시 관측을 그 이벤트의 창 판정에 써도 되는가.

    그 이벤트가 원인이고(`cause_event_id`), 시각 차가 50 ms 이하이고, 이벤트 뒤에 Z 순서·포그라운드
    표가 바뀌지 않았을 때만(`table_changed_ns ≤ t_ns`). 아니면 판정 불가 — 지금 상태로 채우지
    않는다.
    """
    if obs is None or obs.get("cause_event_id") != event.get("event_id"):
        return False
    t_ns, obs_at, changed = event.get("t_ns"), obs.get("obs_at_ns"), obs.get("table_changed_ns")
    if not (isinstance(t_ns, int) and isinstance(obs_at, int) and isinstance(changed, int)):
        return False
    return abs(obs_at - t_ns) <= OBS_MAX_SKEW_NS and changed <= t_ns
