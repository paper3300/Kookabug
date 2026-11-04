"""키 이벤트의 IME 모드 정하기 (순수, M4 계획 2.1 "IME 모드 표본", 3차 검수 N6).

`recorder-hook.schema.json` `ImeSample` 설명의 규칙을 그대로 옮긴다. "사이 변화"는 IME 전환 키를
뗀 때, 포그라운드·자판(`hkl`)이 바뀐 때다. 변화 시각을 정확히 모르면 구간으로 둔다(이웃 관측이
다르면 앞 관측 ~ 뒤 관측, 앞뒤 표본이 다르면 앞 표본 뒤 ~ 뒤 표본 조회 시작). 키의 즉시 관측을
주면 그 창·자판과 같은 표본만 쓴다.

1. 앞 표본 S⁻ = 키 시각 t 앞 300 ms 안 마지막 정상 표본 중 S⁻~t 사이 변화 없음, 뒤 표본 S⁺ = t 뒤
   300 ms 안 첫 정상 표본 중 t~S⁺ 사이 변화 없음
2. 실패 표본의 조회 구간 [query_started_ns, sampled_at_ns]이 (S⁻ 시각, 없으면 t-300 ms) ~ (S⁺ 시각,
   없으면 t+300 ms)와 겹치면 판정 불가 — 조회 실패를 건너뛰고 한쪽 정상 표본으로 확정하지 않는다
3. 실패 없이 한쪽만 있으면 그 모드, 둘 다 있고 같으면 그 모드, 다르거나 둘 다 없으면 판정 불가
4. 정상 표본이라도 자기 조회 구간 안에 사이 변화가 있으면 쓰지 않는다
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from kookabug_core.recorder.contract import IME_SAMPLE_VALID_NS, IME_SWITCH_VKS

__all__ = ["ImeMode", "Interval", "ime_changes", "ime_mode_at"]

type ImeMode = Literal["alphanumeric", "native"]
type Interval = tuple[int, int]
"""변화가 일어났을 수 있는 시각 구간 `[lo, hi]` (점이면 lo == hi)."""


def ime_changes(
    events: Iterable[Mapping[str, Any]],
    obs: Iterable[Mapping[str, Any]] = (),
    samples: Iterable[Mapping[str, Any]] = (),
) -> list[Interval]:
    """사이 변화 구간: IME 전환 키를 뗀 시각, 이웃한 즉시 관측의 포그라운드·`hkl`이 다르면 앞 관측
    시각 ~ 뒤 관측 시각(관측은 바뀐 뒤 늦게 볼 수 있다 — 바뀐 때는 그 사이 어딘가다), 이웃한 IME
    표본의 `fg`·`hkl`이 다르면 앞 표본 끝 ~ 뒤 표본 조회 시작."""
    out: list[Interval] = []
    for event in events:
        if event.get("kind") == "key_up" and event.get("vk") in IME_SWITCH_VKS:
            t = int(event["t_ns"])
            out.append((t, t))
    previous: Mapping[str, Any] | None = None
    for item in sorted(obs, key=lambda o: int(o["obs_at_ns"])):
        if previous is not None and (item["fg"], item["hkl"]) != (previous["fg"], previous["hkl"]):
            out.append((int(previous["obs_at_ns"]), int(item["obs_at_ns"])))
        previous = item
    previous = None
    for sample in sorted(samples, key=lambda s: int(s["sampled_at_ns"])):
        if previous is not None and (sample["fg"], sample["hkl"]) != (
            previous["fg"],
            previous["hkl"],
        ):
            # 뒤 표본은 바뀐 뒤 상태를 물었다: 바뀐 때는 그 조회 시작 **전**이다
            # (뒤 표본 자신은 쓴다)
            lo = int(previous["sampled_at_ns"])
            out.append((lo, max(lo, int(sample["query_started_ns"]) - 1)))
        previous = sample
    return out


def _crosses(lo: int, hi: int, changes: Sequence[Interval]) -> bool:
    """닫힌 구간 [lo, hi]가 변화 구간과 겹치는가."""
    return any(c_lo <= hi and c_hi >= lo for c_lo, c_hi in changes)


def ime_mode_at(
    t_ns: int,
    samples: Iterable[Mapping[str, Any]],
    changes: Sequence[Interval] = (),
    *,
    valid_ns: int = IME_SAMPLE_VALID_NS,
    key_obs: Mapping[str, Any] | None = None,
) -> ImeMode | None:
    """키 시각 `t_ns`의 IME 모드. 판정 불가면 None (그 키가 든 입력 칸은 `ime_unknown`).

    `key_obs`는 그 키의 쓸 수 있는 즉시 관측(`obs_usable`)이다. 주면 그 관측과 `fg`·`hkl`이 같은
    표본만 쓴다 — 다른 창·자판의 모드를 가져오지 않는다.
    """
    every = list(samples)
    context = None if key_obs is None else (key_obs.get("fg"), key_obs.get("hkl"))
    ok = [
        s
        for s in every
        if s.get("status") == "ok"
        and not _crosses(int(s["query_started_ns"]), int(s["sampled_at_ns"]), changes)
        and (context is None or (s.get("fg"), s.get("hkl")) == context)
    ]
    before = [
        s
        for s in ok
        if t_ns - valid_ns <= int(s["sampled_at_ns"]) <= t_ns
        and not _crosses(int(s["sampled_at_ns"]), t_ns, changes)
    ]
    after = [
        s
        for s in ok
        if t_ns <= int(s["sampled_at_ns"]) <= t_ns + valid_ns
        and not _crosses(t_ns, int(s["sampled_at_ns"]), changes)
    ]
    s_before = max(before, key=lambda s: int(s["sampled_at_ns"])) if before else None
    s_after = min(after, key=lambda s: int(s["sampled_at_ns"])) if after else None
    lo = int(s_before["sampled_at_ns"]) if s_before is not None else t_ns - valid_ns
    hi = int(s_after["sampled_at_ns"]) if s_after is not None else t_ns + valid_ns
    for s in every:
        if s.get("status") == "ok":
            continue
        # 열린 구간 (lo, hi)와 조회 구간이 겹치면 그 키는 판정 불가
        if int(s["query_started_ns"]) < hi and int(s["sampled_at_ns"]) > lo:
            return None
    modes = {s["mode"] for s in (s_before, s_after) if s is not None}
    if len(modes) != 1:
        return None
    mode = modes.pop()
    return mode if mode in ("alphanumeric", "native") else None
