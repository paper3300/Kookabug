"""OCR 엔진 인터페이스와 RapidOCR 파이프라인 (구현 계획 M1 2.6).

**파이프라인** (`RapidOcrEngine`, RapidOCR 3.10 ONNX 경로를 옮김 — `det.py`·`rec.py`)

영역 자르기 → 크기 한계 맞춤 → DB 검출(1024x640 픽셀을 넘으면 원래 해상도로 640 타일마다,
낮은·긴 조각 세로 여백, 짧은 변 64 미만만 늘림, 이진화·윤곽·상자 점수·`pyclipper` 확장, 타일
경계 상자 합치기 — 크기 정책은 `det.py` 맨 위와 `DetConfig`) → 상자마다 펴서 자르기 →
인식(높이 48, 6개씩 묶음, CTC 탐욕 디코드) → 점수 0.5 미만 버림. 방향 분류는 하지 않는다(게임
UI 글자는 바로 서 있다). ONNX 세션은 엔진마다 한 번 만든다(실행당 엔진 하나).

**결과**: 상자 하나가 `OcrLine`(글자·클라이언트 좌표 상자·점수). `text`는 같은 높이에 있는 상자들을
왼→오른으로 띄어 이은 줄(글자마다 나뉜 한글 낱말만 붙임)을 위→아래로 `\n`으로 이은 것,
`confidence`는 상자 점수 평균(엔진 척도, 상자가 없으면 None).

**기한** (M1 2.6): 추론 한 번(`session.run`)은 끊을 수 없다. 시작 전·추론마다 그 직전과 끝난
**바로 뒤**(결과를 후처리에 넘기기 전)에, 그리고 검출 후처리 윤곽 16개마다·타일 상자 합치기
도중·상자 자르기마다 취소와 기한을 확인하고, 기한이 지났으면 결과를 버린다 — 노드 기한이면
`ObservationTimeout`, 설정 기한이면 `capture_timeout`, 전체 기한이면 `DeadlineExceeded`. 그래서
노드 timeout은 최대 추론 한 번만큼 늦는다(추론 한 번 최댓값은 `RapidOcrEngine.max_run_ms`로
잰다). 멈춘 추론은 M0b 하드 종료·복구 경로가 처리한다.

**숫자** (`parse_number`): 천 단위 구분(`,`·공백, 세 자리 묶음)을 빼고 처음 나오는 수(부호·소수점).
없으면 None(노드의 `unreadable`).
"""

from __future__ import annotations

import itertools
import math
import re
import statistics
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

import cv2
import numpy as np

from kookabug_platform.errors import CAPTURE_TIMEOUT, OCR_MODEL_CORRUPT, PlatformError
from kookabug_platform.ocr.det import (
    DEFAULT_CONFIG,
    DbPostProcess,
    DetConfig,
    cut_by_tile,
    det_input,
    fit_bounds,
    merge_tile_boxes,
    pad_vertical,
    rotate_crop,
    tiles,
)
from kookabug_platform.ocr.models import OcrModels, find_models
from kookabug_platform.ocr.rec import CtcDecoder, batches, rec_input

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from kookabug_platform.deadline import ObservationDeadline
    from kookabug_platform.frames import FrameStore
    from kookabug_platform.vision import FrameMeta

__all__ = [
    "DEFAULT_ENGINE",
    "ENGINES",
    "TEXT_SCORE",
    "InferenceSession",
    "Ocr",
    "OcrEngine",
    "OcrLine",
    "OcrResult",
    "OnnxSession",
    "RapidOcrEngine",
    "create_engine",
    "join_lines",
    "parse_number",
]

TEXT_SCORE: Final = 0.5
"""이 점수보다 낮은 상자는 버린다 (RapidOCR 기본값)."""

type Pixels = NDArray[np.uint8]
type Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class OcrLine:
    """검출 상자 하나의 글자. `box`는 (x, y, w, h) — 이미지 또는 클라이언트 좌표(호출에 따라)."""

    text: str
    box: Box
    score: float


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    lines: tuple[OcrLine, ...]
    confidence: float | None
    elapsed_ms: float = 0.0


class OcrEngine(Protocol):
    """OCR 엔진. `kookabug.json` `ocr.engine`으로 고른다 (M1은 `rapidocr` 하나)."""

    name: str

    def read(
        self,
        image: Pixels,
        *,
        region: Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
    ) -> list[OcrLine]:
        """BGR 이미지(의 `region` — 이미지 좌표 x, y, w, h)에서 글자 상자들. 상자는 이미지 좌표."""
        ...


class InferenceSession(Protocol):
    """추론 한 번. 검사에서 바꿔 끼운다(느린 추론 주입)."""

    def run(self, x: NDArray[np.float32]) -> NDArray[np.float32]: ...


class OnnxSession:
    """onnxruntime CPU 세션 (입력·출력 하나)."""

    def __init__(self, path: Path) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 4
        options.enable_cpu_mem_arena = False
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name

    def run(self, x: NDArray[np.float32]) -> NDArray[np.float32]:
        (out,) = self._session.run(None, {self._input: x})
        return np.asarray(out, dtype=np.float32)

    def metadata(self, key: str) -> str | None:
        return self._session.get_modelmeta().custom_metadata_map.get(key)


def _ocr_timeout() -> PlatformError:
    return PlatformError(CAPTURE_TIMEOUT, "OCR이 설정 기한 안에 끝나지 않았다")


def _bgr(image: Pixels) -> Pixels:
    if image.ndim == 2:
        return np.asarray(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    if image.shape[2] == 4:
        return np.asarray(cv2.cvtColor(image, cv2.COLOR_BGRA2BGR), dtype=np.uint8)
    return image


def _clip_region(region: Sequence[int] | None, width: int, height: int) -> Box:
    if region is None:
        return 0, 0, width, height
    x, y, w, h = (int(v) for v in region)
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + w), min(height, y + h)
    return left, top, max(0, right - left), max(0, bottom - top)


class RapidOcrEngine:
    """RapidOCR 모델 + 옮긴 전·후처리. 여러 스레드에서 불러도 된다.

    `models`를 주지 않으면 처음 읽을 때 `find_models()`로 찾는다. 검사는 `det`·`rec`·`characters`를
    직접 줄 수 있다(모델 없이 기한·흐름 검사).
    """

    name = "rapidocr"

    def __init__(
        self,
        models: OcrModels | None = None,
        *,
        det: InferenceSession | None = None,
        rec: InferenceSession | None = None,
        characters: Sequence[str] | None = None,
        det_config: DetConfig = DEFAULT_CONFIG,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.det_config = det_config
        self._models = models
        self._det = det
        self._rec = rec
        self._decoder = CtcDecoder(characters) if characters is not None else None
        self._lock = threading.Lock()
        self._clock = clock
        self._post = DbPostProcess()
        self.max_run_ms = 0.0
        """지금까지 추론 한 번(`run`)의 최댓값 (노드 timeout이 늦을 수 있는 최대)."""

    def load(self) -> None:
        """모델을 찾아 확인하고 세션을 만든다 (처음 한 번). 실행 시작 때 미리 불러도 된다."""
        with self._lock:
            if self._det is not None and self._rec is not None and self._decoder is not None:
                return
            models = self._models or find_models()
            det = OnnxSession(models.det)
            rec = OnnxSession(models.rec)
            chars = rec.metadata("character")
            if not chars:
                raise PlatformError(
                    OCR_MODEL_CORRUPT, f"인식 모델 {models.rec}에 문자 사전(character)이 없다"
                )
            self._models = models
            self._det, self._rec = det, rec
            self._decoder = CtcDecoder(chars.splitlines())

    def _run(
        self,
        session: InferenceSession,
        x: NDArray[np.float32],
        deadline: ObservationDeadline | None,
    ) -> NDArray[np.float32]:
        if deadline is not None:
            deadline.ensure(_ocr_timeout)
        start = self._clock()
        out = session.run(x)
        elapsed = (self._clock() - start) * 1000
        with self._lock:
            self.max_run_ms = max(self.max_run_ms, elapsed)
        if deadline is not None:
            deadline.ensure(_ocr_timeout)  # 끝난 추론의 결과를 쓰기 전에
        return out

    def read(
        self,
        image: Pixels,
        *,
        region: Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
    ) -> list[OcrLine]:
        if deadline is not None:
            deadline.start(_ocr_timeout)
        if self._det is None or self._rec is None or self._decoder is None:
            self.load()
            if deadline is not None:
                deadline.ensure(_ocr_timeout)  # 세션 만들기도 끊을 수 없다
        assert self._det is not None and self._rec is not None and self._decoder is not None
        rx, ry, rw, rh = _clip_region(region, int(image.shape[1]), int(image.shape[0]))
        lines: list[OcrLine] = []
        if rw > 0 and rh > 0:
            area = _bgr(np.ascontiguousarray(image[ry : ry + rh, rx : rx + rw]))
            lines = self._read_area(area, (rx, ry), deadline)
        if deadline is not None:
            deadline.ensure(_ocr_timeout)  # 기한 뒤에 끝난 결과는 버린다
        return lines

    def _large_text(
        self,
        img: Pixels,
        deadline: ObservationDeadline | None,
        check: Callable[[], None] | None,
    ) -> list[tuple[int, NDArray[np.float32], float, bool]]:
        """타일 겹침보다 큰 글자는 타일 경계에서 잘린다. 이미지 전체를 `single_max_pixels`까지
        줄여 한 번 더 검출하고, 원래 크기에서 높이가 `tile_overlap / 2` 이상인 상자만 낸다(작은
        글자는 타일이 찾는다 — 줄인 검출은 작은 글자를 놓치거나 줄을 뭉친다)."""
        assert self._det is not None
        config = self.det_config
        h, w = int(img.shape[0]), int(img.shape[1])
        scale = math.sqrt(config.single_max_pixels / (h * w))
        small = np.asarray(
            cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale)))), dtype=np.uint8
        )
        pred = self._run(self._det, det_input(small, config), deadline)
        boxes, scores = self._post(pred, (int(small.shape[0]), int(small.shape[1])), check)
        ratio = np.array([w / small.shape[1], h / small.shape[0]], dtype=np.float32)
        out: list[tuple[int, NDArray[np.float32], float, bool]] = []
        for box, score in zip(boxes, scores, strict=True):
            full = box * ratio
            if full[:, 1].max() - full[:, 1].min() >= config.tile_overlap / 2:
                out.append((-1, full, score, False))
        return out

    def _read_area(
        self, area: Pixels, at: tuple[int, int], deadline: ObservationDeadline | None
    ) -> list[OcrLine]:
        assert self._det is not None and self._rec is not None and self._decoder is not None
        config = self.det_config
        check = None if deadline is None else (lambda: deadline.ensure(_ocr_timeout))
        h, w = area.shape[:2]
        img, ratio_h, ratio_w = fit_bounds(area, config)
        img_h, img_w = int(img.shape[0]), int(img.shape[1])
        parts = tiles(img_h, img_w, config)
        found: list[tuple[int, NDArray[np.float32], float, bool]] = []
        for index, part in enumerate(parts):
            tx, ty, tw, th = part
            # 낮은·긴 조각의 세로 여백은 타일마다 (이미지 전체에 붙인 뒤 나누면 여백과 글자 띠만
            # 든 타일이 생겨 검출이 타일 전체를 글자로 본다 — 3840x32 한 줄 영역 실측)
            tile, pad = pad_vertical(img[ty : ty + th, tx : tx + tw])
            pred = self._run(self._det, det_input(tile, config), deadline)
            tile_boxes, tile_scores = self._post(pred, tile.shape[:2], check)
            offset = np.array([tx, ty - pad], dtype=np.float32)
            for b, s in zip(tile_boxes, tile_scores, strict=True):
                moved = b + offset
                moved[:, 0] = np.clip(moved[:, 0], tx, tx + tw - 1)
                moved[:, 1] = np.clip(moved[:, 1], ty, ty + th - 1)
                found.append((index, moved, s, cut_by_tile(moved, part, img_h, img_w)))
        if len(parts) > 1:
            found += self._large_text(img, deadline, check)
            boxes, _scores = merge_tile_boxes(found, check)
        else:
            stacked = [b for _i, b, _s, _c in found] or [np.zeros((0, 4, 2), dtype=np.float32)]
            boxes = np.concatenate([s.reshape(-1, 4, 2) for s in stacked]).astype(np.float32)
        if len(boxes) == 0:
            return []
        crops: list[Pixels] = []
        for box in boxes:
            if check is not None:
                check()
            crops.append(rotate_crop(img, box))
        texts: list[tuple[str, float]] = [("", 0.0)] * len(crops)
        for group in batches(crops):
            preds = self._run(self._rec, rec_input([crops[i] for i in group]), deadline)
            for i, decoded in zip(group, self._decoder(preds), strict=True):
                texts[i] = decoded
        lines: list[OcrLine] = []
        for box, (text, score) in zip(boxes, texts, strict=True):
            if not text.strip() or score < TEXT_SCORE:
                continue
            xs = np.clip(box[:, 0] * ratio_w, 0, w)
            ys = np.clip(box[:, 1] * ratio_h, 0, h)
            left, top = int(np.floor(xs.min())), int(np.floor(ys.min()))
            right, bottom = int(np.ceil(xs.max())), int(np.ceil(ys.max()))
            rect = (at[0] + left, at[1] + top, max(1, right - left), max(1, bottom - top))
            lines.append(OcrLine(text.strip(), rect, score))
        return lines


def _rapidocr(options: Mapping[str, Any]) -> OcrEngine:
    unknown = sorted(set(options) - {"det"})
    if unknown:
        raise ValueError(f"rapidocr 엔진에 모르는 설정: {', '.join(unknown)}")
    det = options.get("det", {})
    if not isinstance(det, Mapping):
        raise ValueError("ocr.det는 객체다")
    return RapidOcrEngine(det_config=DetConfig.from_mapping(det))


ENGINES: Final[dict[str, Callable[[Mapping[str, Any]], OcrEngine]]] = {"rapidocr": _rapidocr}
DEFAULT_ENGINE: Final = "rapidocr"


def create_engine(
    name: str = DEFAULT_ENGINE, options: Mapping[str, Any] | None = None
) -> OcrEngine:
    """`kookabug.json` `ocr.engine` 값과 그 엔진 설정(`options`, rapidocr는 `det` = `DetConfig`
    필드)으로 엔진을 만든다. 모르는 이름·설정·잘못된 값은 ValueError."""
    try:
        factory = ENGINES[name]
    except KeyError:
        raise ValueError(f"모르는 OCR 엔진: {name!r} (지원: {', '.join(ENGINES)})") from None
    return factory(options or {})


# ---------------------------------------------------------------- 결과 묶기


def _rows(lines: Sequence[OcrLine]) -> list[list[OcrLine]]:
    """같은 높이(세로 중심 차이 ≤ 낮은 쪽 높이의 절반)에 있는 상자끼리 한 줄, 줄 안은 왼→오른."""
    rows: list[tuple[float, int, list[OcrLine]]] = []  # (첫 상자 세로 중심, 높이, 상자들)
    for line in sorted(lines, key=lambda ln: (ln.box[1] + ln.box[3] / 2, ln.box[0])):
        cy = line.box[1] + line.box[3] / 2
        if rows and abs(cy - rows[-1][0]) <= min(line.box[3], rows[-1][1]) / 2:
            rows[-1][2].append(line)
        else:
            rows.append((cy, line.box[3], [line]))
    return [sorted(row, key=lambda ln: ln.box[0]) for _cy, _h, row in rows]


def _hangul(ch: str) -> bool:
    return "가" <= ch <= "힣"


def _row_text(row: Sequence[OcrLine]) -> str:
    """한 줄의 상자들을 띄어 잇는다. 검출이 한글 낱말을 글자마다 나눈 경우(상자가 맞닿거나 겹치고
    양쪽이 한글 음절)만 붙인다. 상자는 확장(unclip)돼 있어 띄어 쓴 낱말끼리도 겹칠 수 있으므로
    간격만으로는 정하지 않는다(실측: "Gold"|"12,345" 4픽셀 겹침, "번"|"호" 7픽셀 겹침)."""
    parts = [row[0].text]
    for prev, line in itertools.pairwise(row):
        gap = line.box[0] - (prev.box[0] + prev.box[2])
        glued = gap <= 0 and _hangul(prev.text[-1]) and _hangul(line.text[0])
        parts.append(line.text if glued else " " + line.text)
    return "".join(parts)


def join_lines(lines: Sequence[OcrLine], elapsed_ms: float = 0.0) -> OcrResult:
    """상자들 → `OcrResult` (줄 순서로 정렬된 `lines`, `text`, `confidence`)."""
    rows = _rows(lines)
    ordered = tuple(line for row in rows for line in row)
    text = "\n".join(_row_text(row) for row in rows)
    confidence = statistics.fmean(line.score for line in ordered) if ordered else None
    return OcrResult(text, ordered, confidence, elapsed_ms)


_MINUS: Final = chr(0x2212)  # 유니코드 빼기 기호
_NUMBER: Final = re.compile(rf"[+\-{_MINUS}]?(?:\d{{1,3}}(?:[, ]\d{{3}})+|\d+)(?:\.\d+)?")


def parse_number(text: str) -> int | float | None:
    """처음 나오는 수. 천 단위 구분(`,`·공백, 세 자리 묶음)은 뺀다. 소수점이 있으면 float."""
    m = _NUMBER.search(text)
    if m is None:
        return None
    raw = m.group().replace(",", "").replace(" ", "").replace(_MINUS, "-")
    return float(raw) if "." in raw else int(raw)


# ---------------------------------------------------------------- 실행의 OCR


class Ocr:
    """한 실행의 OCR. 저장소(`store`)가 있으면 캡처 ID로 읽는다(작업 중 고정)."""

    def __init__(self, engine: OcrEngine, store: FrameStore | None = None) -> None:
        self.engine = engine
        self.store = store

    def read(
        self,
        pixels: Pixels,
        *,
        region: Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
    ) -> OcrResult:
        """`region`·결과 상자는 이미지 좌표."""
        start = time.perf_counter()
        lines = self.engine.read(pixels, region=region, deadline=deadline)
        return join_lines(lines, (time.perf_counter() - start) * 1000)

    def read_capture(
        self,
        capture_id: int,
        meta: FrameMeta,
        *,
        region: Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
    ) -> OcrResult:
        """저장소의 캡처를 읽는다 (버렸으면 `frame_expired`). `region`·결과 상자는 클라이언트
        좌표 — 영역 캡처면 `meta.origin`만큼 옮긴다."""
        if self.store is None:
            raise RuntimeError("프레임 저장소 없이 만든 Ocr이다")
        if deadline is not None:
            deadline.start(_ocr_timeout)
        ox, oy = meta.origin
        local = None if region is None else (region[0] - ox, region[1] - oy, region[2], region[3])
        with self.store.pinned(capture_id) as (pixels,):
            result = self.read(pixels, region=local, deadline=deadline)
        if (ox, oy) == (0, 0):
            return result
        moved = tuple(
            OcrLine(ln.text, (ln.box[0] + ox, ln.box[1] + oy, ln.box[2], ln.box[3]), ln.score)
            for ln in result.lines
        )
        return OcrResult(result.text, moved, result.confidence, result.elapsed_ms)
