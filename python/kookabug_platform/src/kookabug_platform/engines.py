"""실행의 찾기·비교·OCR 엔진 (구현 계획 M1 2.5·2.6·2.7, runner 연결 T9).

runner(`WindowsPlatform`·가짜 플랫폼)와 가짜 ctx(`fake_engines`)가 같이 쓴다. 코어 플랫폼
프로토콜(`ObservingPlatform`: `find`·`diff`·`read_text`)을 구현하고 결과를 SDK 값(`Match`·
`OcrResult`)으로 바꾼다.

- **이미지**: 참조 이미지(`capture_id`만)는 프레임 저장소의 픽셀과 그 캡처의 관측 조건
  (`CaptureMeta`: 클라이언트 크기·DPI·원점·창·관측 시각)으로, 바이트·파일 이미지는 풀어서
  (이미지 크기·96 DPI, 파일은 한 번만 푼다) 찾는다
- **좌표**: `region`·결과 상자는 클라이언트 좌표. 영역 캡처면 원점만큼 옮긴다
- **기한**: `ObservationLimits` → `ObservationDeadline`(설정 기한 = `capture_timeout`, 노드 기한 =
  `ObservationTimeout`, 전체 기한 = `DeadlineExceeded`)
- **`Match`**: `frame_info`(캡처 방식·크기·DPI·캡처 번호·관측 시각), `target`(target 이름 =
  워크스페이스 기준 경로 — 재검증의 다시 찾기가 읽는다), `click`(target 클릭 지점), `window`(캡처한
  창)
- **`sensitive`**: OCR 글자(전체·줄)를 `Secret`으로
- OCR 엔진은 처음 읽을 때 만든다(모델 찾기·해시 확인). 없으면 그때 `ocr_model_missing`
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.record.artifacts import (
    CANDIDATES_KEPT,
    CaptureMeta,
    EvidenceCandidate,
    FindEvidence,
    is_reference_image,
)
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.frames import decode_image
from kookabug_platform.ocr.engine import DEFAULT_ENGINE, Ocr, OcrEngine, create_engine
from kookabug_platform.vision import (
    Candidate,
    FindResult,
    FrameMeta,
    Pixels,
    Vision,
    VisionMatch,
    diff_pixels,
)
from kookabug_sdk.types import (
    FrameRef,
    Image,
    Match,
    OcrLine,
    OcrResult,
    Point,
    Rect,
    Secret,
    Target,
)

if TYPE_CHECKING:
    from kookabug_core.engine.context import ObservationLimits
    from kookabug_platform.frames import FrameStore

__all__ = ["RunEngines", "deadline_of", "find_evidence", "frame_meta", "to_match"]


def deadline_of(limits: ObservationLimits | None) -> ObservationDeadline | None:
    if limits is None:
        return None
    return ObservationDeadline(
        limits.config_ms, node_ms=limits.node_ms, run_ms=limits.run_ms, check=limits.check
    )


def frame_meta(meta: CaptureMeta, capture_id: int | None) -> FrameMeta:
    return FrameMeta(
        client_size=meta.client_size,
        dpi=meta.dpi,
        origin=meta.origin,
        backend=meta.backend,
        capture_id=capture_id,
        observed_at=meta.observed_at,
        frame=meta.frame,
        window=meta.window,
    )


def to_match(found: VisionMatch) -> Match:
    info = found.frame_info
    x, y, w, h = found.rect
    return Match(
        rect=Rect(x, y, w, h),
        score=found.score,
        window=found.window,
        frame=found.frame,
        scale=found.scale,
        method=found.method,
        frame_info=FrameRef(
            backend=info.backend,
            client_size=info.client_size,
            dpi=info.dpi,
            capture_id=info.capture_id,
            observed_at=info.observed_at,
        ),
        target=found.target,
        click=Point(*found.click),
    )


SAME_PLACE_IOU: Final = 0.3
"""두 후보 상자가 이만큼 넘게 겹치면 같은 자리로 본다 (점수 높은 것만 남긴다)."""


def iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def distinct_places(candidates: Iterable[Candidate], count: int) -> list[Candidate]:
    """점수 순으로 서로 다른 자리 최대 `count`개 (겹치는 후보는 점수 높은 것 하나만)."""
    kept: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: c.score, reverse=True):
        if all(iou(c.rect, k.rect) <= SAME_PLACE_IOU for k in kept):
            kept.append(c)
            if len(kept) == count:
                break
    return kept


def find_evidence(
    result: FindResult | Iterable[Candidate],
    target: str,
    origin: tuple[int, int] = (0, 0),
    *,
    threshold: float | None = None,
    capture_id: int | None = None,
) -> FindEvidence:
    """찾기 결과 → 매칭 후보 증거: 서로 다른 자리 점수 상위 3개(상자는 이미지 좌표)와 임계값.
    방법·배율별 최고점은 대개 같은 자리의 배율 변형이라 겹치는 것은 하나로 줄인다."""
    ox, oy = origin
    if isinstance(result, FindResult):
        threshold = float(result.threshold)
        candidates: Iterable[Candidate] = result.candidates
    else:
        candidates = result
    top = distinct_places(candidates, CANDIDATES_KEPT)
    return FindEvidence(
        target=target,
        threshold=float(threshold if threshold is not None else 0.0),
        candidates=tuple(
            EvidenceCandidate(
                (c.rect[0] - ox, c.rect[1] - oy, c.rect[2], c.rect[3]),
                round(float(c.score), 4),
                round(float(c.scale), 4),
            )
            for c in top
        ),
        capture_id=capture_id,
    )


def _box(region: Rect | None) -> tuple[int, int, int, int] | None:
    return None if region is None else (region.x, region.y, region.width, region.height)


def _area(pixels: Pixels, origin: tuple[int, int]) -> tuple[int, int, int, int]:
    """이미지가 덮는 클라이언트 영역 `(x, y, w, h)`."""
    return origin[0], origin[1], int(pixels.shape[1]), int(pixels.shape[0])


def _intersect(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


class RunEngines:
    """한 실행의 비전·OCR. `store`가 있으면 참조 이미지를 그 저장소로 읽는다. 여러 스레드에서
    불러도 된다."""

    def __init__(
        self,
        store: FrameStore | None = None,
        *,
        ocr_engine: str = DEFAULT_ENGINE,
        ocr_options: Mapping[str, Any] | None = None,
        ocr: OcrEngine | None = None,
    ) -> None:
        self.store = store
        self.vision = Vision(store)
        self._ocr_name = ocr_engine
        self._ocr_options = dict(ocr_options or {})
        self._ocr: Ocr | None = None if ocr is None else Ocr(ocr, store)
        self._lock = threading.Lock()
        self._files: dict[Path, Pixels] = {}

    # ------------------------------------------------------------ 이미지

    def _stored(self, image: Image) -> tuple[int, FrameMeta] | None:
        if self.store is None or not is_reference_image(image):
            return None
        assert image.capture_id is not None
        meta = self.store.meta(image.capture_id)
        if meta is None:
            meta = CaptureMeta(client_size=(image.width, image.height), frame=image.frame)
        return image.capture_id, frame_meta(meta, image.capture_id)

    def _pixels(self, image: Image) -> Pixels:
        """바이트·파일 이미지의 픽셀 (파일은 한 번만 푼다)."""
        if image.data is not None:
            return decode_image(image.data)
        if image.path is None:
            raise ValueError("픽셀이 없는 이미지다 (저장소 없는 참조 이미지)")
        path = Path(image.path)
        with self._lock:
            cached = self._files.get(path)
        if cached is not None:
            return cached
        pixels = decode_image(path.read_bytes())
        with self._lock:
            return self._files.setdefault(path, pixels)

    def _file_meta(self, image: Image, pixels: Pixels) -> FrameMeta:
        return FrameMeta(
            client_size=(int(pixels.shape[1]), int(pixels.shape[0])),
            frame=image.frame,
            capture_id=image.capture_id,
        )

    # ------------------------------------------------------------ 찾기·비교

    def find(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        limits: ObservationLimits | None = None,
    ) -> Match | None:
        return self.find_report(image, target, region=region, limits=limits)[0]

    def find_report(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        limits: ObservationLimits | None = None,
    ) -> tuple[Match | None, FindEvidence]:
        """찾기 + 매칭 후보 증거 (서로 다른 자리 상위 3개·임계값, M3 2.6). 후보 상자는 찾은 이미지
        좌표다(클라이언트 좌표에서 그 이미지 원점을 뺀 것).

        찾기마다 내는 후보는 시도(방법·배율)별 최고점을 자리로 줄인 것이고, 저장소 캡처면 증거를
        남길 때 한 번 `refine`이 가장 높은 시도의 점수 지도에서 겹침 억제로 서로 다른 자리 봉우리를
        다시 고른다 — 찾기 경로의 비용은 그대로다."""
        deadline = deadline_of(limits)
        stored = self._stored(image)
        if stored is not None:
            capture_id, meta = stored
            result = self.vision.find_capture(
                capture_id, meta, target, region=_box(region), deadline=deadline
            )
        else:
            pixels = self._pixels(image)
            meta = self._file_meta(image, pixels)
            result = self.vision.find(pixels, meta, target, region=_box(region), deadline=deadline)
        found = None if result.match is None else to_match(result.match)
        evidence = find_evidence(result, target.name, meta.origin, capture_id=image.capture_id)
        best = result.best
        if stored is None or best is None:
            return found, evidence
        capture_id, meta = stored
        threshold = float(result.threshold)

        def refine() -> FindEvidence:
            peaks = self.vision.peaks_capture(
                capture_id,
                meta,
                target,
                scale=best.scale,
                method=best.method,
                region=_box(region),
                count=CANDIDATES_KEPT,
            )
            if not peaks:
                return evidence
            return find_evidence(
                peaks, target.name, meta.origin, threshold=threshold, capture_id=capture_id
            )

        return found, replace(evidence, refine=refine)

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        """두 이미지의 차이 (0~1). `region`이 없으면 두 이미지 전체(크기가 다르면 1.0).

        `region`은 클라이언트 좌표다. 두 관측의 **클라이언트 크기가 다르면 1.0**(창 크기가 바뀜 =
        화면이 안정되지 않음 — 영역을 잘라 보기 전에 판정한다). 같으면 이미지마다 자기 원점(영역
        캡처면 그 영역 왼쪽 위, 파일 이미지는 (0, 0))을 빼서 **같은 클라이언트 영역**의 픽셀끼리
        비교한다 — 두 이미지와 `region`이 모두 겹치는 부분만 본다. **겹치는 곳이 없으면 1.0**(비교할
        픽셀이 없는 영역을 "같다"로 보면 화면 밖 영역이 늘 멈춘 화면이 된다 — 같은 프레임이어도).
        파일 이미지의 클라이언트 크기는 그 이미지 크기다.
        """
        sa, sb = self._stored(a), self._stored(b)
        if region is None and sa is not None and sb is not None:
            return self.vision.diff(sa[0], sb[0])
        same = False
        if sa is not None and sb is not None:
            assert self.store is not None
            # 같은 프레임·같은 자르기 = 같은 원점의 같은 픽셀 (영역이 겹치는지는 아래에서 본다)
            same = self.store.identity(sa[0]) == self.store.identity(sb[0])
        with contextlib.ExitStack() as stack:
            pa, oa, client_a = self._view(a, sa, stack)
            pb, ob, client_b = self._view(b, sb, stack)
            if region is None:
                return diff_pixels(pa, pb)
            if tuple(client_a) != tuple(client_b):
                return 1.0
            common = _intersect(
                _intersect(_box(region) or (0, 0, 0, 0), _area(pa, oa)), _area(pb, ob)
            )
            x, y, w, h = common
            if w == 0 or h == 0:
                return 1.0
            if same:
                return 0.0
            ca = pa[y - oa[1] : y - oa[1] + h, x - oa[0] : x - oa[0] + w]
            cb = pb[y - ob[1] : y - ob[1] + h, x - ob[0] : x - ob[0] + w]
            return diff_pixels(ca, cb)

    def _view(
        self,
        image: Image,
        stored: tuple[int, FrameMeta] | None,
        stack: contextlib.ExitStack,
    ) -> tuple[Pixels, tuple[int, int], tuple[int, int]]:
        """이미지의 픽셀(저장소면 비교하는 동안 고정), 원점, 관측의 클라이언트 크기."""
        if stored is None:
            pixels = self._pixels(image)
            return pixels, (0, 0), (int(pixels.shape[1]), int(pixels.shape[0]))
        assert self.store is not None
        (pixels,) = stack.enter_context(self.store.pinned(stored[0]))
        return pixels, stored[1].origin, stored[1].client_size

    # ------------------------------------------------------------ OCR

    def _reader(self) -> Ocr:
        with self._lock:
            if self._ocr is None:
                self._ocr = Ocr(create_engine(self._ocr_name, self._ocr_options), self.store)
            return self._ocr

    def read_text(
        self,
        image: Image,
        *,
        region: Rect | None = None,
        sensitive: bool = False,
        limits: ObservationLimits | None = None,
    ) -> OcrResult:
        deadline = deadline_of(limits)
        reader = self._reader()
        stored = self._stored(image)
        if stored is not None:
            meta = stored[1]
            result = reader.read_capture(stored[0], meta, region=_box(region), deadline=deadline)
        else:
            pixels = self._pixels(image)
            meta = self._file_meta(image, pixels)
            result = reader.read(pixels, region=_box(region), deadline=deadline)
        hide: Callable[[str], str | Secret] = Secret if sensitive else str
        lines = tuple(
            OcrLine(hide(line.text), Rect(*line.box), line.score) for line in result.lines
        )
        seen = FrameRef(meta.backend, meta.client_size, meta.dpi, meta.capture_id, meta.observed_at)
        return OcrResult(hide(result.text), lines, result.confidence, meta.window, seen)
