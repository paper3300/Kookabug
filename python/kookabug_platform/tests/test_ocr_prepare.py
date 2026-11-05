"""OCR 엔진 준비와 관측 기한 (M2 사람 확인 S 결함 ②).

설치본 앱에서 첫 OCR 스텝이 모델 불러오기(모듈 import·해시 확인·세션 만들기)를 설정 기한(2초)
안에 하다가 `capture_timeout`으로 끝났다. 이제 준비는 관측 기한 밖이다: runner가 실행 시작 때
백그라운드로 띄우고(`prepare_ocr`), 읽기는 준비가 끝나기를 취소·전체 기한만 보며 기다린 뒤 관측
기한을 잰다. 실행기는 코어 OCR 노드 함수를 부르기 전에 준비를 기다려, 대기 노드의 기한도 준비
뒤부터 잰다(`before_node`). 모델 대신 준비에 지연을 넣은 가짜 엔진으로 본다 (실제 runner 경로는
`test_runner_ocr_prepare.py`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
import pytest
from helpers.graphs import make_workspace
from helpers.m1 import SCENARIO
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import ExecOptions, Executor, MemoryArtifacts
from kookabug_core.engine.cancel import Cancelled, DeadlineExceeded
from kookabug_core.engine.clock import SystemClock
from kookabug_core.engine.context import ObservationLimits, PreparingPlatform
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.loader import load_program
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.engines import RunEngines
from kookabug_platform.errors import CAPTURE_TIMEOUT, OCR_MODEL_MISSING, PlatformError
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_platform.ocr.engine import Ocr, OcrLine, RapidOcrEngine
from kookabug_platform.ocr.rec import CtcDecoder
from kookabug_sdk.types import Image

CHARS = ["가", "나", "A"]
LOAD_S = 0.6
CONFIG_MS = 200
PIXELS = np.full((120, 400, 3), 40, dtype=np.uint8)
ok, png = cv2.imencode(".png", PIXELS)
assert ok
IMAGE = Image(data=png.tobytes())


class FakeDet:
    """글자 상자 하나가 있는 확률 지도 (`delay`초 걸린다)."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def run(self, x: np.ndarray) -> np.ndarray:
        time.sleep(self.delay)
        _n, _c, h, w = x.shape
        prob = np.zeros((1, 1, h, w), dtype=np.float32)
        prob[0, 0, h // 3 : 2 * h // 3, w // 4 : 3 * w // 4] = 0.95
        return prob


class FakeRec:
    """줄마다 "가A" (CTC: blank 0, 가 1, A 3)."""

    def run(self, x: np.ndarray) -> np.ndarray:
        out = np.zeros((x.shape[0], 4, len(CHARS) + 2), dtype=np.float32)
        for t, token in enumerate([1, 0, 3, 0]):
            out[:, t, token] = 0.9
        return out


class SlowLoadEngine(RapidOcrEngine):
    """모델 준비(`load`)가 `delay`초 걸리는 엔진. `fail_first`면 첫 준비는 모델 없음."""

    def __init__(self, delay: float = LOAD_S, *, fail_first: bool = False, det_s: float = 0.0):
        super().__init__()
        self.delay = delay
        self.fail_first = fail_first
        self.det_s = det_s
        self.loads = 0
        self.load_threads: list[str] = []

    def load(self) -> None:
        self.loads += 1
        self.load_threads.append(threading.current_thread().name)
        time.sleep(self.delay)
        if self.fail_first and self.loads == 1:
            raise PlatformError(OCR_MODEL_MISSING, "모델 없음 (주입)")
        self._det, self._rec = FakeDet(self.det_s), FakeRec()
        self._decoder = CtcDecoder(CHARS)


def limits(
    check: Callable[[], None] | None = None, *, run_ms: int | None = 60_000
) -> ObservationLimits:
    return ObservationLimits(CONFIG_MS, node_ms=5_000, run_ms=run_ms, check=check)


def test_lazy_load_inside_observation_was_capture_timeout() -> None:
    """대조: 준비를 관측 안에서 하면(엔진을 바로 읽는 경로 — 바꾸기 전 `read_text`) 설정 기한을
    먹는다."""
    with pytest.raises(PlatformError) as caught:
        Ocr(SlowLoadEngine()).read(PIXELS, deadline=ObservationDeadline(CONFIG_MS))
    assert caught.value.code == CAPTURE_TIMEOUT


def test_slow_first_preparation_is_outside_capture_timeout() -> None:
    engine = SlowLoadEngine()
    start = time.monotonic()
    result = RunEngines(ocr=engine).read_text(IMAGE, limits=limits())
    assert result.text == "가A"
    assert time.monotonic() - start >= LOAD_S  # 준비를 기다렸다 (설정 기한 0.2초보다 길게)
    assert engine.load_threads == ["ocr-prepare"]


def test_prepare_ocr_runs_in_background_before_first_read() -> None:
    engine = SlowLoadEngine()
    engines = RunEngines(ocr=engine)
    reported: list[tuple[float, BaseException | None]] = []
    done = threading.Event()

    def report(elapsed_ms: float, error: BaseException | None) -> None:
        reported.append((elapsed_ms, error))
        done.set()

    engines.prepare_ocr(report)
    assert done.wait(5)
    ((elapsed_ms, error),) = reported
    assert error is None and elapsed_ms >= LOAD_S * 1000 * 0.9
    start = time.monotonic()
    assert engines.read_text(IMAGE, limits=limits()).text == "가A"
    assert time.monotonic() - start < LOAD_S / 2  # 이미 준비됐다
    engines.prepare_ocr()  # 다시 불러도 한 번만
    assert engine.loads == 1


@pytest.mark.parametrize("error", [Cancelled, DeadlineExceeded])
def test_cancel_and_run_deadline_while_waiting(error: type[Cancelled]) -> None:
    """준비를 기다리는 동안에도 취소·전체 기한(`limits.check`)은 바로 끝낸다."""
    engine = SlowLoadEngine(delay=2.0)
    start = time.monotonic()
    stop_at = start + 0.2

    def check() -> None:
        if time.monotonic() >= stop_at:
            raise error("주입")

    with pytest.raises(error):
        RunEngines(ocr=engine).read_text(IMAGE, limits=limits(check))
    assert time.monotonic() - start < 1.0


def test_wait_counts_against_run_deadline() -> None:
    """기다린 만큼 전체 기한의 남은 시간이 준다: 준비 0.6초 + 추론 0.3초 > 전체 남은 0.7초."""
    engine = SlowLoadEngine(det_s=0.3)
    with pytest.raises(DeadlineExceeded):
        RunEngines(ocr=engine).read_text(IMAGE, limits=limits(run_ms=700))


class ChangingScreenEngine:
    """준비(`load`)가 `delay`초 걸리고, 첫 읽기는 글자 없음(로딩 화면), 그 뒤는 "ready"."""

    name = "changing"

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.reads = 0

    def load(self) -> None:
        time.sleep(self.delay)

    def read(
        self, image: object, *, region: object = None, deadline: object = None
    ) -> list[OcrLine]:
        self.reads += 1
        return [] if self.reads == 1 else [OcrLine("ready", (10, 10, 50, 20), 1.0)]


@pytest.mark.parametrize("delay", [0.0, 1.0])
def test_wait_node_keeps_its_timeout_after_slow_preparation(tmp_path: Path, delay: float) -> None:
    """준비(1초)가 대기 노드 기한(0.5초)보다 길고 첫 관측이 다르면, 실행기가 노드 함수를 부르기
    전에 준비를 기다리므로(`PreparingPlatform.before_node`) 노드 기한이 그대로 남아 다음 관측에서
    찾는다 (sfix 2 검수 Mid). 준비를 첫 읽기 안에서만 기다리면 한 번 읽고 `timeout`이었다."""
    ws = make_workspace(tmp_path / "ws")
    graph = (
        tk()
        .entry("launch")
        .node("launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "wait"})
        .node(
            "wait",
            "core.ocr.wait_text",
            inputs={"contains": "ready", "timeout_ms": 500},
            next={"found": "pass"},
        )
        .node("pass", "core.test.pass")
    )
    graph.write(ws, "tests/t.graph.json")
    program = load_program(ws, "tests/t.graph.json")
    store = FrameStore()
    engine = ChangingScreenEngine(delay)
    engines = RunEngines(store, ocr=engine)
    platform = ScenarioPlatform(FakeScenario.load(SCENARIO), decode=decode_image, engines=engines)
    assert isinstance(platform, PreparingPlatform)
    executor = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=SystemClock(),
        artifacts=MemoryArtifacts(),
        frames=store,
    )
    engines.prepare_ocr()
    result = executor.run(program, ExecOptions(run_id="r1", capture_timeout_ms=2000))
    (step,) = [
        e["step"] for e in result.events if e["event"] == "step.start" and e["node"] == "wait"
    ]
    (end,) = [e for e in result.events if e["event"] == "step.end" and e["step"] == step]
    assert end["exit"] == "found", end
    assert result.verdict == "pass"
    assert engine.reads == 2


def test_before_node_waits_only_for_ocr_nodes() -> None:
    engine = SlowLoadEngine()
    engines = RunEngines(ocr=engine)
    start = time.monotonic()
    engines.before_node("core.image.wait", lambda: None)
    assert time.monotonic() - start < LOAD_S / 2 and engine.loads == 0
    engines.before_node("core.ocr.wait_text", lambda: None)
    assert engine.loads == 1 and time.monotonic() - start >= LOAD_S * 0.9


def test_before_node_wait_still_sees_cancel() -> None:
    engine = SlowLoadEngine(delay=2.0)
    stop_at = time.monotonic() + 0.2

    def check() -> None:
        if time.monotonic() >= stop_at:
            raise Cancelled("주입")

    with pytest.raises(Cancelled):
        RunEngines(ocr=engine).before_node("core.assert.text", check)
    assert time.monotonic() < stop_at + 0.8


def test_failed_preparation_is_reported_then_retried() -> None:
    engine = SlowLoadEngine(delay=0.05, fail_first=True)
    engines = RunEngines(ocr=engine)
    with pytest.raises(PlatformError) as caught:
        engines.read_text(IMAGE, limits=limits())
    assert caught.value.code == OCR_MODEL_MISSING
    assert engines.read_text(IMAGE, limits=limits()).text == "가A"
    assert engine.loads == 2
