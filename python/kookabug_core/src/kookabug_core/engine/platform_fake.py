"""게임 없이 실행하는 가짜 플랫폼과 메모리 artifacts.

- 캡처는 `frames`를 순서대로 준다. 다 쓰면 마지막 프레임을 계속 준다 (화면이 그대로인 것처럼)
- 입력은 실행하지 않고 `input.calls`에 남긴다 (SDK `fake_context`와 같은 `FakeInput`)
- `on_capture(n)`은 n번째 캡처 뒤에 불린다 (캡처 도중 취소 같은 시나리오용)
- 프레임 저장소(M1 2.7)와 쓸 때는 `decode`(이미지 바이트 → 픽셀, `kookabug_platform.frames.
  decode_image`)를 준다. 그러면 `capture_staged`가 프레임을 픽셀로 풀어 저장소에 넘기고 노드에는
  참조 이미지를 준다 — 실제 매칭·OCR이 가짜 프레임에서 돈다. 코어는 픽셀 형식을 모른다
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.record.artifacts import (
    CaptureMeta,
    StagedFrame,
    artifact_path,
    image_artifact_path,
    thumbnail_path,
)
from kookabug_sdk.testing import FakeInput
from kookabug_sdk.types import Image, Rect, WindowRef

if TYPE_CHECKING:
    from kookabug_core.engine.context import ObservationLimits

__all__ = ["FAKE_BACKEND", "FakePlatform", "MemoryArtifacts", "stage_frame"]

FAKE_BACKEND: Final = "fake"
"""가짜 플랫폼 캡처의 캡처 방식 이름 (`Match.frame_info.backend`)."""


class FakePlatform:
    def __init__(
        self,
        frames: Iterable[Image | str | Path] = (),
        *,
        on_capture: Callable[[int], None] | None = None,
        decode: Callable[[bytes], Any] | None = None,
    ) -> None:
        self.frames = [
            f if isinstance(f, Image) else Image(path=Path(f), frame=i)
            for i, f in enumerate(frames)
        ]
        self.captured = 0
        self.captures: list[tuple[WindowRef | None, Rect | None]] = []
        self.on_capture = on_capture
        self.decode = decode
        self._decoded: dict[int, Any] = {}
        self._input = FakeInput()

    @property
    def input(self) -> FakeInput:
        return self._input

    def _next(self, window: WindowRef | None, region: Rect | None) -> tuple[int, Image]:
        if not self.frames:
            raise RuntimeError("FakePlatform에 frames가 없다")
        index = min(self.captured, len(self.frames) - 1)
        self.captured += 1
        self.captures.append((window, region))
        if self.on_capture is not None:
            self.on_capture(self.captured)
        return index, self.frames[index]

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        return self._next(window, region)[1]

    def peek_frame(self, window: WindowRef | None) -> Image:
        """지금 보이는 프레임 (차례를 넘기지 않는다 — M8 금지 동작 판정용)."""
        if not self.frames:
            raise RuntimeError("FakePlatform에 frames가 없다")
        return self.frames[min(max(self.captured - 1, 0), len(self.frames) - 1)]

    def capture_staged(
        self,
        window: WindowRef | None,
        region: Rect | None,
        limits: ObservationLimits | None = None,
    ) -> tuple[Image, StagedFrame]:
        """프레임을 픽셀로 풀어 저장소용으로 준다. 같은 프레임·같은 영역이면 같은 키다."""
        if self.decode is None:
            raise RuntimeError("FakePlatform에 decode가 없어 프레임을 저장소에 둘 수 없다")
        index, frame = self._next(window, region)
        return stage_frame(
            ("fake", id(self), index),
            frame,
            self._decoded,
            index,
            self.decode,
            region,
            window=window,
        )


def stage_frame(
    key: object,
    frame: Image,
    cache: dict[int, Any],
    index: int,
    decode: Callable[[bytes], Any],
    region: Rect | None,
    *,
    window: WindowRef | None = None,
    dpi: int = 96,
) -> tuple[Image, StagedFrame]:
    """가짜 프레임 하나를 픽셀로 풀어(`cache[index]`에 한 번만) 저장소용으로 만든다. 같은
    `key`·같은 영역이면 같은 동일성 키다. 관측 조건은 프레임 전체 크기·`dpi`·캡처 방식 `fake`."""
    pixels = cache.get(index)
    if pixels is None:
        if frame.data is not None:
            data = frame.data
        elif frame.path is not None:
            data = frame.path.read_bytes()
        else:
            raise RuntimeError(f"가짜 프레임 {index}에 바이트·파일이 없다")
        pixels = decode(data)
        cache[index] = pixels
    full = (int(pixels.shape[1]), int(pixels.shape[0]))
    box = None
    origin = (0, 0)
    if region is not None:
        box = (region.x, region.y, region.width, region.height)
        origin = (region.x, region.y)
        # 복사본: 뷰는 프레임 전체 할당을 붙잡아 저장소 예산을 속인다
        pixels = pixels[
            region.y : region.y + region.height, region.x : region.x + region.width
        ].copy()
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    image = Image(width=width, height=height, frame=frame.frame)
    meta = CaptureMeta(
        client_size=full,
        dpi=dpi,
        origin=origin,
        backend=FAKE_BACKEND,
        window=window,
        observed_at=time.time(),
        frame=frame.frame,
    )
    return image, StagedFrame((key, box), pixels, meta)


class MemoryArtifacts:
    """artifacts를 메모리에 둔다. 경로는 `FileArtifacts`와 같다(`steps/<스텝>_<이름>`)."""

    def __init__(self) -> None:
        self.saved: dict[str, Image] = {}
        self.texts: dict[str, str] = {}
        self.thumbs: dict[str, bytes] = {}
        """썸네일 (`thumbs/<스텝>.jpg` → JPEG 바이트, M3 2.6)."""

    def save_thumbnail(self, step: str, data: bytes) -> str:
        path = thumbnail_path(step)
        self.thumbs[path] = data
        return path

    def delete_thumbnail(self, rel: str) -> None:
        self.thumbs.pop(rel, None)

    def _taken(self, path: str) -> bool:
        return path in self.saved or path in self.texts

    def save(self, step: str, image: Image, name: str) -> str:
        path = image_artifact_path(step, image, name, self._taken)
        self.saved[path] = image
        return path

    def save_text(self, step: str, name: str, text: str) -> str:
        path = artifact_path(step, name, "", self._taken)
        self.texts[path] = text
        return path
