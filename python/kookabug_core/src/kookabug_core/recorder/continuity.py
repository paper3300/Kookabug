"""훅 스트림 연속성 검사 (M4 계획 2.1 "번호 셋", 2.9 상태별 마무리).

받는 쪽(daemon 녹화 세션, 훅 프로세스 검사)이 `hook.events`·`hook.health`를 받은 차례대로 넣는다.

- `batch_no`는 1부터 빈틈 없이 이어진다 (전송 연속성). `hook.health`의 `batch_no`가 받은 마지막
  묶음보다 크면 묶음을 잃은 것이다
- `crit_seq`는 묶음 안·사이에서 빈틈 없이 이어진다. 빈 번호 = 중요 이벤트 유실
- `overflow` 누적은 0이어야 한다
- `event_id`는 커지기만 하고(빈 번호는 정상 — 이동 합치기·우리 표식 제외), 시각은 줄지 않는다
- 누적 개수(`dropped_marker`·`coalesced_moves`·`overflow`)는 줄지 않는다

위반은 처음 하나만 남는다(끈적함). 녹화는 그때 `input_overflow`로 멈추고, `cut_crit_seq` **앞**의
중요 이벤트까지만 동작으로 쓴다(그 뒤 이벤트는 "없었던 것"으로 이어 붙이지 않는다). 위반을 본
묶음 안에서도 그 앞 이벤트(`valid_prefix`개)는 유실 앞 동작이라 버리지 않는다 — 훅은 넘침을 첫
유실 앞 큐를 다 보낸 묶음에 싣기 때문에, 그 묶음의 앞부분이 유실 직전 동작이다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = ["STOP_REASON", "ContinuityChecker", "ContinuityViolation", "ViolationReason"]

STOP_REASON: Final = "input_overflow"
"""위반이면 녹화를 멈추는 이유 (모든 위반 공통)."""

type ViolationReason = Literal[
    "batch_gap", "counter_regressed", "crit_gap", "crit_range", "event_order", "overflow"
]

_COUNTERS: Final = ("dropped_marker", "coalesced_moves", "overflow")


def _earliest(*seqs: int | None) -> int:
    """자를 번호: 주어진 것(첫 빈 번호·다음 기대 번호·어긋난 이벤트 번호) 중 가장 이른 것."""
    return min(s for s in seqs if s is not None)


@dataclass(frozen=True, slots=True)
class ContinuityViolation:
    reason: ViolationReason
    batch_no: int
    """위반을 본 묶음 번호 (health면 그 보고의 batch_no)."""
    cut_crit_seq: int
    """이 번호와 그 뒤의 중요 이벤트는 쓰지 않는다 (첫 빈 번호, 모르면 받은 마지막 다음)."""
    message: str
    valid_prefix: int = 0
    """위반을 본 `hook.events` 묶음의 앞에서부터 이만큼은 유실 앞 동작으로 쓴다 — `cut_crit_seq`
    앞 마지막 중요 이벤트까지(그 뒤 이동은 유실된 이벤트보다 뒤일 수 있어 뺀다). health면 0."""


def _prefix(events: Sequence[Mapping[str, Any]], upto: int, cut: int) -> int:
    """`events[:upto]` 중 `cut` 앞 마지막 중요 이벤트까지의 길이 (없으면 0)."""
    last = 0
    for index, event in enumerate(events[:upto]):
        seq = event.get("crit_seq")
        if seq is None:
            continue
        if int(seq) >= cut:
            break
        last = index + 1
    return last


class ContinuityChecker:
    def __init__(self) -> None:
        self.last_batch = 0
        self.last_crit = 0
        self.last_event_id = 0
        self.last_t_ns = -1
        self.counters: dict[str, int] = dict.fromkeys(_COUNTERS, 0)
        self.violation: ContinuityViolation | None = None

    def _fail(
        self,
        reason: ViolationReason,
        batch_no: int,
        cut: int,
        message: str,
        events: Sequence[Mapping[str, Any]] = (),
        upto: int = 0,
    ) -> ContinuityViolation:
        prefix = _prefix(events, upto, cut)
        self.violation = ContinuityViolation(reason, batch_no, cut, message, prefix)
        return self.violation

    def feed_events(self, params: Mapping[str, Any]) -> ContinuityViolation | None:
        """`hook.events` params 하나. 위반이면 (처음) 위반, 아니면 None."""
        if self.violation is not None:
            return self.violation
        batch_no = int(params["batch_no"])
        if batch_no != self.last_batch + 1:
            return self._fail(
                "batch_gap",
                batch_no,
                self.last_crit + 1,
                f"묶음 번호가 {self.last_batch + 1}이 아니라 {batch_no}",
            )
        for name in _COUNTERS:
            if int(params[name]) < self.counters[name]:
                return self._fail(
                    "counter_regressed", batch_no, self.last_crit + 1, f"누적 {name}가 줄었다"
                )
        events: Sequence[Mapping[str, Any]] = params["events"]
        crit_seen: list[int] = []
        gap: int | None = None
        expected = self.last_crit + 1
        for index, event in enumerate(events):
            event_id, t_ns = int(event["event_id"]), int(event["t_ns"])
            seq = event.get("crit_seq")
            if event_id <= self.last_event_id or t_ns < self.last_t_ns:
                # 이미 본 첫 빈 번호·차례가 어긋난 이벤트의 번호 중 가장 이른 곳에서 자른다
                return self._fail(
                    "event_order",
                    batch_no,
                    _earliest(gap, expected, seq),
                    f"이벤트 {event_id}의 차례·시각이 거꾸로다",
                    events,
                    index,
                )
            self.last_event_id, self.last_t_ns = event_id, t_ns
            if seq is None:
                continue
            if seq < expected:
                return self._fail(
                    "event_order",
                    batch_no,
                    _earliest(gap, expected, seq),
                    f"crit_seq {seq}가 거꾸로·다시 나왔다",
                    events,
                    index,
                )
            if seq > expected and gap is None:
                gap = expected
            crit_seen.append(seq)
            expected = seq + 1
        first = crit_seen[0] if crit_seen else None
        last = crit_seen[-1] if crit_seen else None
        if (params["crit_first"], params["crit_last"]) != (first, last):
            return self._fail(
                "crit_range",
                batch_no,
                gap if gap is not None else self.last_crit + 1,
                "crit_first·crit_last가 묶음의 중요 이벤트와 다르다",
            )
        if int(params["overflow"]) > 0:
            # 버린 이벤트의 번호는 이 묶음 안 빈틈이거나, 이 묶음 뒤(아직 보내지 않은 번호)다
            cut = gap if gap is not None else expected
            return self._fail(
                "overflow",
                batch_no,
                cut,
                f"중요 큐가 차서 {params['overflow']}개를 버렸다",
                events,
                len(events),
            )
        if gap is not None:
            message = f"crit_seq {gap}가 빠졌다"
            return self._fail("crit_gap", batch_no, gap, message, events, len(events))
        self.last_batch = batch_no
        self.last_crit = expected - 1
        self.counters = {name: int(params[name]) for name in _COUNTERS}
        return None

    def feed_health(self, params: Mapping[str, Any]) -> ContinuityViolation | None:
        """`hook.health` params 하나. 받은 마지막 묶음보다 뒤 번호를 말하면 묶음을 잃은 것."""
        if self.violation is not None:
            return self.violation
        batch_no = int(params["batch_no"])
        if batch_no > self.last_batch:
            return self._fail(
                "batch_gap",
                batch_no,
                self.last_crit + 1,
                f"생존 보고는 묶음 {batch_no}까지 보냈다는데 {self.last_batch}까지만 받았다",
            )
        return None
