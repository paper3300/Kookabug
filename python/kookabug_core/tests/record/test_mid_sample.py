"""실패 스텝의 근사 중간 캡처 (구현 계획 M3 2.6, 검수 M5·2차 N3, 조율자 결정 Q13).

프레임 저장소는 열린 캡처 스텝마다 첫 캡처와 시간 간격이 고른 표본 최대 8장을 붙잡는다(넘치면
첫 표본을 뺀 나머지를 하나 걸러 버리고 간격을 두 배로). 스텝이 끝나면 표본 중 (시작 + 끝)/2에 가장
가까운 장을 `_mid`로 쓰고 실제 캡처 시각·편차를 남긴다. 최선 노력이고 오차 상한을 약속하지 않는다:
편차가 경과의 1/4을 넘거나 첫·마지막 말고 표본이 없으면 `mid: null`·`no_sample_near_mid`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pytest

from kookabug_core.engine import MemoryArtifacts
from kookabug_core.record.artifacts import (
    MID_MISSING,
    Recorder,
    StagedFrame,
    TimedCapture,
    choose_mid,
)
from kookabug_core.record.policy import RecordPolicy
from kookabug_platform.frames import SAMPLES, STEP_RECENT, FrameStore
from kookabug_sdk.types import Image

SHAPE = (8, 8, 3)


class Clock:
    def __init__(self) -> None:
        self.ms = 0

    def __call__(self) -> int:
        return self.ms


def frame(n: int) -> np.ndarray:
    pixels = np.zeros(SHAPE, np.uint8)
    pixels[0, 0] = (n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF)
    return pixels


def run_step(
    times: Iterable[int], end: int, *, budget_bytes: int | None = None
) -> tuple[dict[str, Any], FrameStore, Recorder]:
    """`times`(ms)마다 캡처하고 `end`에 fail로 끝난 스텝의 `evidence`."""
    store = FrameStore() if budget_bytes is None else FrameStore(budget_bytes=budget_bytes)
    clock = Clock()
    recorder = Recorder(MemoryArtifacts(), store, clock=clock)
    recorder.open_step("s1", RecordPolicy())
    for n, at in enumerate(times):
        clock.ms = at
        recorder.captured("s1", Image(8, 8, frame=n), StagedFrame(("f", n), frame(n)))
    clock.ms = end
    recorder.fail_screenshot("s1")
    evidence = recorder.evidence("s1")
    assert evidence is not None
    return evidence, store, recorder


def closest(samples: Sequence[TimedCapture], exclude: set[int], center: float) -> TimedCapture:
    return min(
        (s for s in samples if s.capture_id not in exclude), key=lambda s: abs(s.at_ms - center)
    )


@pytest.mark.parametrize("end_s", [1, 7, 60, 600])
def test_mid_is_closest_sample_and_reports_actual_time_and_offset(end_s: int) -> None:
    end = end_s * 1000
    times = list(range(0, end, 100))  # 고른 폴링 (100 ms)
    store = FrameStore()
    clock = Clock()
    recorder = Recorder(MemoryArtifacts(), store, clock=clock)
    recorder.open_step("s1", RecordPolicy())
    for n, at in enumerate(times):
        clock.ms = at
        recorder.captured("s1", Image(8, 8, frame=n), StagedFrame(("f", n), frame(n)))
    held = store.step_frames("s1")
    assert held is not None and len(held.samples) <= SAMPLES
    clock.ms = end
    recorder.fail_screenshot("s1")
    evidence = recorder.evidence("s1")
    assert evidence is not None
    # 고른 장 = 표본(첫·마지막 제외) 중 중간에 가장 가까운 것, 시각·편차는 그 장의 실제 값
    last_id = len(times)  # 캡처 번호는 1부터
    best = closest(held.samples, {held.first.capture_id, last_id}, end / 2)
    assert evidence["mid"] == "steps/s1_mid.png"
    assert evidence["mid_at_ms"] == best.at_ms
    assert evidence["mid_offset_ms"] == round(abs(best.at_ms - end / 2))
    assert evidence["mid_offset_ms"] <= end / 4
    assert (evidence["first_at_ms"], evidence["last_at_ms"]) == (0, times[-1])
    # 표본이 고르게 퍼져 있어 근사가 경과의 1/8 안이다 (약속은 아니고 이 폴링에서의 결과)
    assert evidence["mid_offset_ms"] <= end / 8


def test_long_poll_pause_gap_no_mid_when_far() -> None:
    # 1~99초를 디버거로 멈춰 캡처가 없다: 중간 50초에 가장 가까운 99초도 49초 차이 > 100/4초
    evidence, _, _ = run_step([0, 1000, 99000, 100000], 100000)
    assert (evidence["mid"], evidence["mid_missing"]) == (None, MID_MISSING)
    assert "mid_at_ms" not in evidence and "mid_offset_ms" not in evidence
    assert (evidence["first_at_ms"], evidence["last_at_ms"]) == (0, 100000)


def test_sparse_captures_no_mid() -> None:
    # 첫 장과 마지막 장 말고 표본이 없다
    evidence, _, _ = run_step([0, 60000], 60000)
    assert (evidence["mid"], evidence["mid_missing"]) == (None, MID_MISSING)
    assert evidence["first"] == "steps/s1_first.png"
    assert choose_mid(0, 60000, [TimedCapture(2, 60000)], {1, 2}) is None


def test_all_samples_evicted_by_budget_no_mid() -> None:
    one = frame(0).nbytes
    # 예산이 첫 장 + 최근 두 장만큼: 표본은 들어오는 대로 버려진다 (최근 두 장과 같은 캡처인
    # 표본은 바이트가 들지 않아 남지만 중간에서 멀다)
    evidence, store, _ = run_step(range(0, 2000, 100), 2000, budget_bytes=one * 3)
    held = store.step_frames("s1")
    assert held is not None and {s.capture_id for s in held.samples} <= {19, 20}
    assert store.held() == {1, 19, 20}
    assert (evidence["mid"], evidence["mid_missing"]) == (None, MID_MISSING)
    assert evidence["first"] == "steps/s1_first.png" and evidence["last"] == "steps/s1_fail.png"


def test_sample_never_exceeds_8_plus_first_and_last_two() -> None:
    store = FrameStore()
    rng = np.random.default_rng(3)
    at = 0
    for n in range(1, 3001):
        at += int(rng.integers(1, 400))  # 불규칙한 폴링
        store.register(n, StagedFrame(("f", n), frame(n)), "s1", at_ms=at)
        held = store.step_frames("s1")
        assert held is not None and held.first.capture_id == 1
        assert len(held.samples) <= SAMPLES
        assert [s.at_ms for s in held.samples] == sorted(s.at_ms for s in held.samples)
        assert len(store.held()) <= 1 + SAMPLES + STEP_RECENT
    # 표본은 실행 전체에 퍼져 있다 (첫 표본은 앞쪽, 마지막 표본은 뒤쪽)
    held = store.step_frames("s1")
    assert held is not None
    assert held.samples[0].at_ms < at / 4 and held.samples[-1].at_ms > at * 3 / 4
    store.close_step("s1")
    assert store.held() == set() and store.step_frames("s1") is None


def test_budget_pressure_drops_samples_first() -> None:
    one = frame(0).nbytes
    store = FrameStore(budget_bytes=one * 8, output_refs=32)
    # 앞 스텝의 출력 참조 둘 (뒤 스텝이 쓸 수 있다)
    for n in (1, 2):
        store.register(n, StagedFrame(("o", n), frame(1000 + n)), "s0", at_ms=n)
        store.mark_output(n)
    store.close_step("s0")
    assert store.held() == {1, 2}
    for n in range(3, 40):
        store.register(n, StagedFrame(("f", n), frame(n)), "s1", at_ms=n * 100)
        assert store.bytes_held <= store.budget_bytes
    held = store.step_frames("s1")
    assert held is not None
    # 출력 참조·첫 장·최근 두 장은 남고, 예산을 넘는 만큼 표본이 먼저 빠졌다
    assert {1, 2, 3, 38, 39} <= store.held()
    assert held.first.capture_id == 3
    extra = {s.capture_id for s in held.samples} - {38, 39}
    assert len(extra) <= 8 - 5  # 예산 8장 - (출력 둘 + 첫 장 + 최근 둘)
    assert store.held() == {1, 2, 3, 38, 39} | extra
    # 표본까지 다 빠져도 넘으면 그다음에 출력 참조를 버린다
    tight = FrameStore(budget_bytes=one * 3)
    tight.register(1, StagedFrame("o", frame(1)), "s0", at_ms=0)
    tight.mark_output(1)
    tight.close_step("s0")
    for n in range(2, 10):
        tight.register(n, StagedFrame(("f", n), frame(n)), "s1", at_ms=n * 100)
    assert tight.is_expired(1)
    assert tight.held() == {2, 8, 9}
