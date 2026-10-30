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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kookabug_core.record.artifacts import CaptureMeta, is_reference_image
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.frames import decode_image
from kookabug_platform.ocr.engine import DEFAULT_ENGINE, Ocr, OcrEngine, create_engine
from kookabug_platform.vision import FrameMeta, Pixels, Vision, VisionMatch, diff_pixels
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

__all__ = ["RunEngines", "deadline_of", "frame_meta", "to_match"]


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
        deadline = deadline_of(limits)
        stored = self._stored(image)
        if stored is not None:
            capture_id, meta = stored
            result = self.vision.find_capture(
                capture_id, meta, target, region=_box(region), deadline=deadline
            )
        else:
            pixels = self._pixels(image)
            result = self.vision.find(
                pixels,
                self._file_meta(image, pixels),
                target,
                region=_box(region),
                deadline=deadline,
            )
        return None if result.match is None else to_match(result.match)

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        """두 이미지의 차이 (0~1). `region`이 없으면 두 이미지 전체(크기가 다르면 1.0).

        `region`은 클라이언트 좌표다. 두 관측의 **클라이언트 크기가 다르면 1.0**(창 크기가 바뀜 =
        화면이 안정되지 않음 — 영역을 잘라 보기 전에 판정한다). 같으면 이미지마다 자기 원점(영역
        캡처면 그 영역 왼쪽 위, 파일 이미지는 (0, 0))을 빼서 **같은 클라이언트 영역**의 픽셀끼리
        비교한다 — 두 이미지와 `region`이 모두 겹치는 부분만 본다(겹치는 곳이 없으면 0.0). 파일
        이미지의 클라이언트 크기는 그 이미지 크기다.
        """
        sa, sb = self._stored(a), self._stored(b)
        if region is None and sa is not None and sb is not None:
            return self.vision.diff(sa[0], sb[0])
        if sa is not None and sb is not None:
            assert self.store is not None
            if self.store.identity(sa[0]) == self.store.identity(sb[0]):
                return 0.0  # 같은 프레임·같은 자르기 = 같은 원점의 같은 픽셀
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
            result = reader.read_capture(
                stored[0], stored[1], region=_box(region), deadline=deadline
            )
        else:
            result = reader.read(self._pixels(image), region=_box(region), deadline=deadline)
        hide: Callable[[str], str | Secret] = Secret if sensitive else str
        lines = tuple(
            OcrLine(hide(line.text), Rect(*line.box), line.score) for line in result.lines
        )
        return OcrResult(hide(result.text), lines, result.confidence)
