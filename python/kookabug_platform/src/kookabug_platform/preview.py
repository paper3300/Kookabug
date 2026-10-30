"""`kookabug target test` 미리보기 이미지 (구현 계획 M1 2.11).

프레임 위에 검색 범위(파랑), 최고 후보 상자(찾음 초록·못 찾음 빨강)와 점수·배율·방법, 클릭 지점
십자(찾았을 때), 맨 위 줄에 임계값과 결과를 그린다. `--all-scales`면 다른 후보도 가는 노란 선으로.
글자는 영문·숫자만 쓴다 (`cv2.putText`는 한글을 그리지 못한다).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import cv2
import numpy as np

if TYPE_CHECKING:
    from kookabug_platform.vision import Box, FindResult, FrameMeta, Pixels

__all__ = ["BLUE", "GREEN", "RED", "YELLOW", "render_preview"]

# BGR
BLUE: Final = (255, 128, 0)
GREEN: Final = (0, 200, 0)
RED: Final = (0, 0, 255)
YELLOW: Final = (0, 220, 255)
_FONT: Final = cv2.FONT_HERSHEY_SIMPLEX


def _local(box: Box, origin: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    x, y, w, h = box
    x, y = x - origin[0], y - origin[1]
    return (x, y), (x + max(w, 1) - 1, y + max(h, 1) - 1)


def _label(image: Pixels, text: str, at: tuple[int, int], color: tuple[int, int, int]) -> None:
    (tw, th), base = cv2.getTextSize(text, _FONT, 0.5, 1)
    x = min(max(at[0], 0), max(0, image.shape[1] - tw - 4))
    y = min(max(at[1], th + 4), image.shape[0] - base - 2)
    cv2.rectangle(image, (x, y - th - 4), (x + tw + 4, y + base), (0, 0, 0), cv2.FILLED)
    cv2.putText(image, text, (x + 2, y - 2), _FONT, 0.5, color, 1, cv2.LINE_AA)


def render_preview(
    pixels: Pixels, meta: FrameMeta, result: FindResult, *, show_all: bool = False
) -> Pixels:
    """미리보기 픽셀 (BGR 새 배열)."""
    if pixels.ndim == 2:
        image = np.asarray(cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    else:
        image = np.array(pixels[:, :, :3], dtype=np.uint8, copy=True)
    origin = meta.origin
    top_left, bottom_right = _local(result.search, origin)
    cv2.rectangle(image, top_left, bottom_right, BLUE, 2)
    if show_all:
        for candidate in result.candidates:
            if candidate is not result.best:
                a, b = _local(candidate.rect, origin)
                cv2.rectangle(image, a, b, YELLOW, 1)
    best = result.best
    if best is not None:
        color = GREEN if result.found else RED
        a, b = _local(best.rect, origin)
        cv2.rectangle(image, a, b, color, 2)
        text = f"{best.score:.3f} x{best.scale:.2f} {best.method}"
        if best.reason:
            text += f" ({best.reason})"
        _label(image, text, (a[0], a[1] - 4), color)
    if result.match is not None:
        cx, cy = result.match.click[0] - origin[0], result.match.click[1] - origin[1]
        cv2.drawMarker(image, (cx, cy), GREEN, cv2.MARKER_CROSS, 24, 2)
    verdict = "FOUND" if result.found else "NOT FOUND"
    header = f"{verdict}  threshold {result.threshold:.2f}  expected x{result.expected_scale:.2f}"
    _label(image, header, (4, 20), GREEN if result.found else RED)
    return image
