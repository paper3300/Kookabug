"""찾기 병렬 계산의 픽셀 수명 (T6 검수 2 — 구현 계획 M1 2.7 "지나간 프레임은 즉시 해제").

오래 걸리는 계산은 `Vision._try`에 장벽을 넣어 흉내 낸다(실제 저장소·기한·풀 경로는 그대로).
저장소 카운터만이 아니라 weakref로 실제 픽셀 배열이 풀렸는지 본다.
"""

from __future__ import annotations

import gc
import threading
import time
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from kookabug_core.record.artifacts import StagedFrame
from kookabug_platform import vision as vision_module
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import FRAME_EXPIRED, ObservationTimeout, PlatformError
from kookabug_platform.frames import FrameStore
from kookabug_platform.vision import WORKERS, FrameMeta, TargetSpec, Vision

SIDE = 256
FRAME_BYTES = SIDE * SIDE * 3


class Gate:
    """`Vision._try` 대신: 시작 수를 세고 장벽이 열릴 때까지 기다린다(최대 10초)."""

    def __init__(self) -> None:
        self.open = threading.Event()
        self.started = 0
        self.lock = threading.Lock()

    def __call__(self, *_args: Any) -> None:
        with self.lock:
            self.started += 1
        assert self.open.wait(10), "검사 장벽이 열리지 않았다"


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[Gate]:
    g = Gate()
    monkeypatch.setattr(Vision, "_try", staticmethod(g))
    try:
        yield g
    finally:
        g.open.set()


@pytest.fixture
def target(tmp_path: Path) -> TargetSpec:
    path = tmp_path / "t.png"
    path.write_bytes(cv2.imencode(".png", np.zeros((8, 8, 3), np.uint8))[1].tobytes())
    return TargetSpec("t", path)


def wait_until(condition: Any, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "조건이 기한 안에 맞지 않았다"
        time.sleep(0.01)


def live(refs: list[weakref.ref[np.ndarray]]) -> list[int]:
    gc.collect()
    return [i for i, ref in enumerate(refs, start=1) if ref() is not None]


def test_timed_out_requests_do_not_keep_unstarted_frames(gate: Gate, target: TargetSpec) -> None:
    # 첫 요청이 일꾼 WORKERS개를 붙잡은 동안, 다른 프레임으로 짧은 기한 요청 40개가 연달아 끝난다
    store = FrameStore(budget_bytes=1 << 20)
    vision = Vision(store)
    refs: list[weakref.ref[np.ndarray]] = []
    timeouts = 0

    def call(index: int, node_ms: int) -> None:
        nonlocal timeouts
        pixels = np.full((SIDE, SIDE, 3), index % 256, dtype=np.uint8)
        pixels.setflags(write=False)
        refs.append(weakref.ref(pixels))
        store.register(index, StagedFrame(("lifetime", index), pixels), f"s{index}")
        del pixels
        deadline = ObservationDeadline(5000, node_ms=node_ms)
        try:
            vision.find_capture(index, FrameMeta((SIDE, SIDE)), target, deadline=deadline)
        except ObservationTimeout:
            timeouts += 1
        finally:
            store.close_step(f"s{index}")

    call(1, 100)
    wait_until(lambda: gate.started == WORKERS)
    for index in range(2, 42):
        call(index, 2)
    assert timeouts == 41
    # 계산 중인 첫 프레임만 남는다. 시작하지 않은 시도의 프레임 40개는 이미 풀렸다
    assert live(refs) == [1]
    assert gate.started == WORKERS
    # 저장소도 계산 중인 프레임을 작업 중 고정으로 센다 (카운터 = 실제로 붙잡은 픽셀)
    assert store.held() == {1}
    assert store.bytes_held == FRAME_BYTES
    # 대기열의 일꾼은 상한까지만 늘었다 (요청마다 시도 수만큼 쌓이지 않음)
    assert vision_module._pending_lanes <= vision_module.MAX_PENDING_LANES + 40

    gate.open.set()
    wait_until(lambda: not store.held())
    wait_until(lambda: vision_module._pending_lanes == 0)
    assert live(refs) == []
    assert store.bytes_held == 0
    # 첫 요청의 시도 10개 중 장벽에 걸린 것만 시작됐고, 놓인 뒤 나머지는 시작되지 않았다
    assert gate.started == WORKERS


def test_pin_held_until_running_attempts_finish(
    gate: Gate, target: TargetSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 버린 캡처는 고정하지 못한다 (계산을 시작하지 않는다)
    store = FrameStore()
    store.register(1, StagedFrame(("one", 1), np.zeros((SIDE, SIDE, 3), np.uint8)), "s1")
    store.close_step("s1")
    vision = Vision(store)
    with pytest.raises(PlatformError) as caught:
        vision.find_capture(1, FrameMeta((SIDE, SIDE)), target)
    assert caught.value.code == FRAME_EXPIRED and gate.started == 0

    def first_done(*_args: Any) -> None:
        # 첫 시도는 바로 끝내 결과(후보 없음)를 주고, 나머지는 장벽에 걸린다
        with gate.lock:
            gate.started += 1
            first = gate.started == 1
        if not first:
            assert gate.open.wait(10)

    monkeypatch.setattr(Vision, "_try", staticmethod(first_done))
    store.register(2, StagedFrame(("two", 2), np.ones((SIDE, SIDE, 3), np.uint8)), "s2")
    with pytest.raises(ObservationTimeout):
        deadline = ObservationDeadline(5000, node_ms=300)
        vision.find_capture(2, FrameMeta((SIDE, SIDE)), target, deadline=deadline)
    store.close_step("s2")
    # 호출은 기한에 돌아왔지만 계산 중인 시도가 있어 작업 중 고정이 남는다
    assert store.held() == {2}
    gate.open.set()
    wait_until(lambda: not store.held())
    assert store.bytes_held == 0
