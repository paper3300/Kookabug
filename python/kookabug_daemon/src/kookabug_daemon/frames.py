"""편집기 정지 화면 캐시 (M2 계획 2.9 "정지 화면 고르기", Q13).

- `target.capture`(창 한 장)·`target.load_image`(PNG)가 만든 정지 화면을 daemon 메모리에 둔다.
  최대 `MAX_FRAMES`(16)장이고, 넘으면 가장 오래 쓰지 않은 것부터 버린다. 버린·모르는 `frame_id`는
  `frame_expired`다. daemon이 바뀌면 옛 `frame_id`는 모두 모르는 번호다
- 픽셀은 클라이언트 영역 전체의 BGR(읽기 전용)이다. 좌표는 이 픽셀의 물리 픽셀이고 원점은 (0, 0)
- 화면에 보일 PNG는 편집기 캐시(`image_cache`)에 `<frame_id>.png`로 쓴다
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from kookabug_core.diagnostics import Diagnostic
from kookabug_daemon.protocol import RequestFailed

if TYPE_CHECKING:
    from kookabug_platform.vision import FrameMeta, Pixels

__all__ = ["MAX_FRAMES", "EditorFrame", "FrameCache", "check_rect"]

MAX_FRAMES: Final = 16


@dataclass(frozen=True, slots=True, eq=False)
class EditorFrame:
    frame_id: str
    pixels: Pixels
    client_size: tuple[int, int]
    dpi: int
    cache: str
    """편집기 캐시의 PNG 이름."""

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    def meta(self) -> FrameMeta:
        """찾기에 넘기는 프레임 정보 (픽셀 = 클라이언트 전체)."""
        from kookabug_platform.vision import FrameMeta

        return FrameMeta(self.client_size, self.dpi, backend="editor")

    def to_json(self) -> dict[str, Any]:
        """계약 `Frame`."""
        return {
            "frame_id": self.frame_id,
            "width": self.width,
            "height": self.height,
            "dpi": self.dpi,
            "client_size": list(self.client_size),
            "image": {"cache": self.cache, "width": self.width, "height": self.height},
        }


def _expired(frame_id: str, why: str) -> RequestFailed:
    text = f"정지 화면 {frame_id!r}이(가) 없다 ({why}). 정지 화면을 다시 고른다"
    diagnostic = Diagnostic("error", "frame_expired", text)
    return RequestFailed("frame_expired", text, diagnostics=[diagnostic.to_dict()])


def check_rect(frame: EditorFrame, rect: Sequence[int], *, what: str = "영역") -> tuple[int, ...]:
    """프레임 안이고 너비·높이가 1 이상인 `(x, y, w, h)`. 아니면 `target_invalid`."""
    x, y, w, h = (int(v) for v in rect)
    if w < 1 or h < 1 or x < 0 or y < 0 or x + w > frame.width or y + h > frame.height:
        text = (
            f"{what} {[x, y, w, h]}이(가) 정지 화면({frame.width}x{frame.height}) 안이 아니거나 "
            "비었다"
        )
        diagnostic = Diagnostic("error", "target_invalid", text, pointer="/crop/rect")
        raise RequestFailed("target_invalid", text, diagnostics=[diagnostic.to_dict()])
    return x, y, w, h


class FrameCache:
    """`frame_id` → 정지 화면. 어느 스레드에서 불러도 된다."""

    def __init__(self, limit: int = MAX_FRAMES) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._frames: OrderedDict[str, EditorFrame] = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    @staticmethod
    def new_id() -> str:
        return f"f_{secrets.token_hex(8)}"

    def add(self, frame: EditorFrame) -> None:
        with self._lock:
            self._frames[frame.frame_id] = frame
            while len(self._frames) > self.limit:
                self._frames.popitem(last=False)

    def get(self, frame_id: str) -> EditorFrame:
        with self._lock:
            frame = self._frames.get(frame_id)
            if frame is not None:
                self._frames.move_to_end(frame_id)
        if frame is None:
            raise _expired(frame_id, f"최근 {self.limit}장만 남는다")
        return frame
