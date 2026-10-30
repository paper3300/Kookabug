"""OCR 추론과 관측 기한 (구현 계획 M1 2.6, 계획 검수 11, T7).

추론 한 번은 끊을 수 없다: 시작 전·추론 직전·끝난 뒤에 취소·기한을 보고, 기한이 지났으면 결과를
버린다. 모델 대신 지연을 넣은 가짜 세션으로 본다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from kookabug_core.engine.cancel import Cancelled, CancelToken, DeadlineExceeded
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import CAPTURE_TIMEOUT, ObservationTimeout, PlatformError
from kookabug_platform.ocr import det as det_mod
from kookabug_platform.ocr import engine as engine_mod
from kookabug_platform.ocr.engine import Ocr, RapidOcrEngine

INFER_S = 0.5
SLACK_S = 0.15
CHARS = ["가", "나", "A"]


class FakeDet:
    """글자 상자 하나가 있는 확률 지도를 준다. `delay`초 걸리고, 불릴 때 `on_run`을 부른다."""

    def __init__(self, delay: float = 0.0, on_run: Callable[[], None] | None = None) -> None:
        self.delay = delay
        self.on_run = on_run
        self.calls = 0

    def run(self, x: np.ndarray) -> np.ndarray:
        self.calls += 1
        if self.on_run is not None:
            self.on_run()
        time.sleep(self.delay)
        _n, _c, h, w = x.shape
        prob = np.zeros((1, 1, h, w), dtype=np.float32)
        prob[0, 0, h // 3 : 2 * h // 3, w // 4 : 3 * w // 4] = 0.95
        return prob


class FakeRec:
    """줄마다 "가A"를 준다 (CTC: blank 0, 가 1, A 3)."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    def run(self, x: np.ndarray) -> np.ndarray:
        self.calls += 1
        time.sleep(self.delay)
        n = x.shape[0]
        out = np.zeros((n, 4, len(CHARS) + 2), dtype=np.float32)
        for t, token in enumerate([1, 0, 3, 0]):
            out[:, t, token] = 0.9
        return out


def engine(det: FakeDet, rec: FakeRec) -> RapidOcrEngine:
    return RapidOcrEngine(det=det, rec=rec, characters=CHARS)


IMAGE = np.full((120, 400, 3), 40, dtype=np.uint8)


def test_fake_pipeline_reads() -> None:
    det, rec = FakeDet(), FakeRec()
    result = Ocr(engine(det, rec)).read(IMAGE, deadline=ObservationDeadline(2000))
    assert result.text == "가A"
    assert (det.calls, rec.calls) == (1, 1)


def test_slow_inference_with_short_node_deadline_is_observation_timeout() -> None:
    det, rec = FakeDet(delay=INFER_S), FakeRec()
    eng = engine(det, rec)
    start = time.monotonic()
    with pytest.raises(ObservationTimeout):
        eng.read(IMAGE, deadline=ObservationDeadline(2000, node_ms=100, run_ms=60_000))
    elapsed = time.monotonic() - start
    # 결과를 버렸고(인식은 시작하지 않음), 늦어도 노드 기한 + 추론 한 번
    assert det.calls == 1 and rec.calls == 0
    assert elapsed <= 0.1 + INFER_S + SLACK_S
    assert eng.max_run_ms >= INFER_S * 1000 * 0.9


def test_slow_last_inference_result_discarded() -> None:
    # 마지막 추론(인식) 도중 기한이 지나면 다 읽었어도 버린다
    det, rec = FakeDet(), FakeRec(delay=0.3)
    start = time.monotonic()
    with pytest.raises(ObservationTimeout):
        engine(det, rec).read(IMAGE, deadline=ObservationDeadline(2000, node_ms=100))
    assert rec.calls == 1
    assert time.monotonic() - start <= 0.1 + 0.3 + SLACK_S


def test_config_and_run_deadline_kinds() -> None:
    with pytest.raises(PlatformError) as info:
        engine(FakeDet(delay=0.2), FakeRec()).read(
            IMAGE, deadline=ObservationDeadline(100, node_ms=5000)
        )
    assert info.value.code == CAPTURE_TIMEOUT
    with pytest.raises(DeadlineExceeded):
        engine(FakeDet(delay=0.2), FakeRec()).read(
            IMAGE, deadline=ObservationDeadline(2000, node_ms=5000, run_ms=100)
        )


def test_cancel_checked_before_and_after_inference() -> None:
    # 시작 전에 취소됐으면 추론하지 않는다
    token = CancelToken()
    token.cancel()
    det, rec = FakeDet(), FakeRec()
    with pytest.raises(Cancelled):
        engine(det, rec).read(IMAGE, deadline=ObservationDeadline(2000, check=token.check))
    assert det.calls == 0

    # 추론 중에 취소되면 끝난 뒤 확인해서 결과를 버리고 다음 추론을 하지 않는다
    token = CancelToken()
    checks: list[int] = []

    def check() -> None:
        checks.append(det.calls)
        token.check()

    det, rec = FakeDet(on_run=token.cancel), FakeRec()
    with pytest.raises(Cancelled):
        engine(det, rec).read(IMAGE, deadline=ObservationDeadline(2000, check=check))
    assert det.calls == 1 and rec.calls == 0
    assert checks[0] == 0 and checks[-1] == 1  # 추론 전에도, 뒤에도 확인했다


def test_cancel_during_inference_skips_postprocess() -> None:
    # 추론 안에서 취소되면 그 결과를 후처리에 넘기지 않는다 (검수 T7_1 1번 반례)
    token = CancelToken()
    det, rec = FakeDet(on_run=token.cancel), FakeRec()
    eng = engine(det, rec)
    posts: list[object] = []
    real_post = eng._post

    def spy(*args: object, **kwargs: object) -> object:
        posts.append(args)
        return real_post(*args, **kwargs)  # type: ignore[arg-type]

    eng._post = spy  # type: ignore[assignment]
    start = time.monotonic()
    with pytest.raises(Cancelled):
        eng.read(IMAGE, deadline=ObservationDeadline(2000, check=token.check))
    assert posts == [] and rec.calls == 0
    assert time.monotonic() - start < SLACK_S


class DenseDet:
    """작은 글자 덩어리가 촘촘한 확률 지도 (윤곽 수백 개)."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, x: np.ndarray) -> np.ndarray:
        self.calls += 1
        _n, _c, h, w = x.shape
        prob = np.zeros((1, 1, h, w), dtype=np.float32)
        for y in range(10, h - 20, 28):
            for x0 in range(10, w - 30, 48):
                prob[0, 0, y : y + 12, x0 : x0 + 25] = 0.95
        return prob


def test_deadline_checked_inside_postprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    # 후처리(윤곽마다 상자 만들기)가 길어도 도중에 취소를 본다 (검수 T7_1 1번 촘촘한 반례)
    boxes_made: list[int] = []
    real_mini_box = det_mod._mini_box

    def counting(contour: object) -> object:
        boxes_made.append(1)
        return real_mini_box(contour)

    monkeypatch.setattr(det_mod, "_mini_box", counting)
    token = CancelToken()
    checks = 0

    def check() -> None:
        nonlocal checks
        checks += 1
        if boxes_made:  # 후처리가 시작된 뒤 첫 확인에서 취소
            token.cancel()
        token.check()

    rec = FakeRec()
    eng = RapidOcrEngine(det=DenseDet(), rec=rec, characters=CHARS)
    image = np.zeros((540, 960, 3), dtype=np.uint8)  # 한 번에 검출하는 크기
    with pytest.raises(Cancelled):
        eng.read(image, deadline=ObservationDeadline(2000, check=check))
    total = (540 - 30) // 28 * ((960 - 40) // 48)  # 대략의 윤곽 수 (수백 개)
    # 윤곽 하나에 상자 계산 두 번(확장 전·후). 확인 한 번 사이의 윤곽만 처리하고 멈춘다
    assert 0 < len(boxes_made) <= 2 * det_mod.CHECK_EVERY < total
    assert rec.calls == 0


def test_deadline_checked_between_tiles() -> None:
    # 타일로 나눠 검출할 때 타일마다 기한을 본다: 늦어도 추론 한 번
    det, rec = FakeDet(delay=0.2), FakeRec()
    eng = engine(det, rec)
    image = np.full((1400, 1400, 3), 40, dtype=np.uint8)
    assert len(det_mod.tiles(1400, 1400)) > 1
    start = time.monotonic()
    with pytest.raises(ObservationTimeout):
        eng.read(image, deadline=ObservationDeadline(2000, node_ms=100))
    assert det.calls == 1 and rec.calls == 0
    assert time.monotonic() - start <= 0.1 + 0.2 + SLACK_S


class MergeSpy:
    """엔진이 부르는 타일 합치기를 감싸, 합치기 안에서 예외가 났는지 본다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.active = False
        self.raised: BaseException | None = None
        self.boxes = 0
        real = engine_mod.merge_tile_boxes

        def merge(found: Any, check: Any = None) -> Any:
            self.active, self.boxes = True, len(found)
            try:
                return real(found, check)
            except BaseException as exc:
                self.raised = exc
                raise
            finally:
                self.active = False

        monkeypatch.setattr(engine_mod, "merge_tile_boxes", merge)


DENSE_SCREEN = np.zeros((1080, 1920, 3), dtype=np.uint8)  # 타일 8개, 상자 1200개쯤


def test_cancel_during_tile_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    # 타일 상자 합치기 도중의 취소 (검수 T7_2 1번: 상자 1200개 합치기가 취소 뒤 19초)
    spy = MergeSpy(monkeypatch)
    token = CancelToken()

    def check() -> None:
        if spy.active:
            token.cancel()  # 합치기가 시작된 뒤 첫 확인에서 취소
        token.check()

    rec = FakeRec()
    eng = RapidOcrEngine(det=DenseDet(), rec=rec, characters=CHARS)
    with pytest.raises(Cancelled):
        eng.read(DENSE_SCREEN, deadline=ObservationDeadline(60_000, check=check))
    assert spy.boxes > 1000 and isinstance(spy.raised, Cancelled)
    assert rec.calls == 0


def test_deadline_expires_during_tile_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    # 합치기 도중 노드 기한이 지나면 합치기 안에서 ObservationTimeout
    spy = MergeSpy(monkeypatch)
    real_clock = time.monotonic
    jump = 0.0

    def clock() -> float:
        nonlocal jump
        if spy.active:
            jump = 1000.0  # 합치기가 시작되면 시계를 기한 너머로
        return real_clock() + jump

    rec = FakeRec()
    eng = RapidOcrEngine(det=DenseDet(), rec=rec, characters=CHARS)
    deadline = ObservationDeadline(60_000, node_ms=30_000, run_ms=120_000, clock=clock)
    with pytest.raises(ObservationTimeout):
        eng.read(DENSE_SCREEN, deadline=deadline)
    assert isinstance(spy.raised, ObservationTimeout)
    assert rec.calls == 0


def test_tile_merge_is_fast_and_checks_periodically(monkeypatch: pytest.MonkeyPatch) -> None:
    # 합치기는 이웃만 비교한다 (2라운드 구현은 합칠 때마다 처음부터 다시 훑어 1200개에 19초)
    found: list[Any] = []
    real = engine_mod.merge_tile_boxes

    def capture(f: Any, check: Any = None) -> Any:
        found.extend(f)
        return real(f, check)

    monkeypatch.setattr(engine_mod, "merge_tile_boxes", capture)
    RapidOcrEngine(det=DenseDet(), rec=FakeRec(), characters=CHARS).read(DENSE_SCREEN)
    assert len(found) > 1000
    calls = 0

    def check() -> None:
        nonlocal calls
        calls += 1

    start = time.monotonic()
    boxes, _scores = det_mod.merge_tile_boxes(found, check)
    assert time.monotonic() - start < 2.0
    assert 0 < len(boxes) < len(found)
    assert calls >= 2  # 비교·든 상자 판정 도중에 불린다

    # 확인이 예외를 던지면 그 자리에서 멈춘다
    seen = 0

    def stop_third() -> None:
        nonlocal seen
        seen += 1
        if seen == 3:
            raise Cancelled("취소")

    with pytest.raises(Cancelled):
        det_mod.merge_tile_boxes(found, stop_third)
    assert seen == 3


def test_zero_remaining_does_not_infer() -> None:
    det, rec = FakeDet(), FakeRec()
    with pytest.raises(ObservationTimeout):
        engine(det, rec).read(IMAGE, deadline=ObservationDeadline(2000, node_ms=0))
    with pytest.raises(DeadlineExceeded):
        engine(det, rec).read(IMAGE, deadline=ObservationDeadline(2000, run_ms=0))
    assert (det.calls, rec.calls) == (0, 0)
