"""훅 메시지 계약의 수치와 관측 짝짓기 규칙 (M4 계획 2.1, `recorder-hook.schema.json`)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

__all__ = [
    "BATCH_MAX_EVENTS",
    "CRITICAL_KINDS",
    "CRIT_QUEUE_SIZE",
    "HEALTH_INTERVAL_NS",
    "HEALTH_SILENCE_NS",
    "HOOK_PROTOCOL",
    "IME_KEY_SAMPLE_GAP_NS",
    "IME_PERIODIC_NS",
    "IME_QUERY_TIMEOUT_MS",
    "IME_SAMPLE_VALID_NS",
    "IME_SWITCH_VKS",
    "INPUT_STALL_NS",
    "MOVE_COALESCE_NS",
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

# 훅 프로세스·받는 쪽이 같이 쓰는 수치 (M4 계획 2.1, Q17)
CRIT_QUEUE_SIZE: Final = 4096
"""중요 큐 고정 칸 수. 차면 그 이벤트를 버리고 `overflow`를 올린다."""
MOVE_COALESCE_NS: Final = 8_000_000
"""이동은 8 ms마다 마지막 위치 하나만 보낸다."""
HEALTH_INTERVAL_NS: Final = 500_000_000
HEALTH_SILENCE_NS: Final = 2_000_000_000
"""`hook.health`가 이만큼 오지 않으면 `hook_lost`."""
INPUT_STALL_NS: Final = 1_000_000_000
"""세션 마지막 입력 시각이 앞섰는데 이만큼 훅 이벤트가 없으면 `hook_lost` (OS가 훅을 뗌)."""
IME_QUERY_TIMEOUT_MS: Final = 50
IME_KEY_SAMPLE_GAP_NS: Final = 100_000_000
"""키 뒤 IME 표본은 직전 표본이 이보다 오래됐을 때만 (빠른 타이핑은 한 표본이 덮는다)."""
IME_PERIODIC_NS: Final = 250_000_000
IME_SWITCH_VKS: Final = frozenset({0x15, 0x17, 0x18, 0x19, 0x1C, 0x1D})
"""IME 전환 키: VK_HANGUL(=KANA)·VK_JUNJA·VK_FINAL·VK_HANJA(=KANJI)·VK_CONVERT·VK_NONCONVERT
(한국어 자판의 오른쪽 Alt·Ctrl도 이 VK로 온다)."""


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
