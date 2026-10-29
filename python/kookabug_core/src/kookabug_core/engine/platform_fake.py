"""게임 없이 실행하는 가짜 플랫폼과 메모리 artifacts.

- 캡처는 `frames`를 순서대로 준다. 다 쓰면 마지막 프레임을 계속 준다 (화면이 그대로인 것처럼)
- 입력은 실행하지 않고 `input.calls`에 남긴다 (SDK `fake_context`와 같은 `FakeInput`)
- `on_capture(n)`은 n번째 캡처 뒤에 불린다 (캡처 도중 취소 같은 시나리오용)
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from kookabug_core.record.artifacts import artifact_path, image_artifact_path
from kookabug_sdk.testing import FakeInput
from kookabug_sdk.types import Image, Rect, WindowRef

__all__ = ["FakePlatform", "MemoryArtifacts"]


class FakePlatform:
    def __init__(
        self,
        frames: Iterable[Image | str | Path] = (),
        *,
        on_capture: Callable[[int], None] | None = None,
    ) -> None:
        self.frames = [
            f if isinstance(f, Image) else Image(path=Path(f), frame=i)
            for i, f in enumerate(frames)
        ]
        self.captured = 0
        self.captures: list[tuple[WindowRef | None, Rect | None]] = []
        self.on_capture = on_capture
        self._input = FakeInput()

    @property
    def input(self) -> FakeInput:
        return self._input

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        if not self.frames:
            raise RuntimeError("FakePlatform에 frames가 없다")
        frame = self.frames[min(self.captured, len(self.frames) - 1)]
        self.captured += 1
        self.captures.append((window, region))
        if self.on_capture is not None:
            self.on_capture(self.captured)
        return frame


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
