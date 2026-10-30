"""게임 없이 실행하는 가짜 플랫폼과 메모리 artifacts.

- 캡처는 `frames`를 순서대로 준다. 다 쓰면 마지막 프레임을 계속 준다 (화면이 그대로인 것처럼)
- 입력은 실행하지 않고 `input.calls`에 남긴다 (SDK `fake_context`와 같은 `FakeInput`)
- `on_capture(n)`은 n번째 캡처 뒤에 불린다 (캡처 도중 취소 같은 시나리오용)
- 프레임 저장소(M1 2.7)와 쓸 때는 `decode`(이미지 바이트 → 픽셀, `kookabug_platform.frames.
  decode_image`)를 준다. 그러면 `capture_staged`가 프레임을 픽셀로 풀어 저장소에 넘기고 노드에는
  참조 이미지를 준다 — 실제 매칭·OCR이 가짜 프레임에서 돈다. 코어는 픽셀 형식을 모른다
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from kookabug_core.record.artifacts import StagedFrame, artifact_path, image_artifact_path
from kookabug_sdk.testing import FakeInput
from kookabug_sdk.types import Image, Rect, WindowRef

__all__ = ["FakePlatform", "MemoryArtifacts"]


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

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None
    ) -> tuple[Image, StagedFrame]:
        """프레임을 픽셀로 풀어 저장소용으로 준다. 같은 프레임·같은 영역이면 같은 키다."""
        if self.decode is None:
            raise RuntimeError("FakePlatform에 decode가 없어 프레임을 저장소에 둘 수 없다")
        index, frame = self._next(window, region)
        pixels = self._decoded.get(index)
        if pixels is None:
            if frame.data is not None:
                data = frame.data
            elif frame.path is not None:
                data = frame.path.read_bytes()
            else:
                raise RuntimeError(f"가짜 프레임 {index}에 바이트·파일이 없다")
            pixels = self.decode(data)
            self._decoded[index] = pixels
        box = None
        if region is not None:
            box = (region.x, region.y, region.width, region.height)
            # 복사본: 뷰는 프레임 전체 할당을 붙잡아 저장소 예산을 속인다
            pixels = pixels[
                region.y : region.y + region.height, region.x : region.x + region.width
            ].copy()
        height, width = int(pixels.shape[0]), int(pixels.shape[1])
        image = Image(width=width, height=height, frame=frame.frame)
        return image, StagedFrame(("fake", index, box), pixels)


class MemoryArtifacts:
    """artifacts를 메모리에 둔다. 경로는 `FileArtifacts`와 같다(`steps/<스텝>_<이름>`)."""

    def __init__(self) -> None:
        self.saved: dict[str, Image] = {}
        self.texts: dict[str, str] = {}

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
