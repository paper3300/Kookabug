"""비밀 판정의 화면 근거 (M4 계획 2.8 "비밀 근거" 2·3, Tab 칸 상자, T7). 판정 규칙은
`kookabug_core.recorder.classify`.

- **라벨 띠**: 칸 상자 왼쪽(왼쪽으로 상자 너비, 높이 1.5배)과 위(높이 1.5배) — 구간 시작 직전 프레임
- **칸 OCR**: 칸 상자 안 (가림 글자·일반 긍정 근거)
- **Tab으로 들어온 칸 상자**: Tab 직전·직후 프레임 차이에서 포커스 테두리가 옮겨 간 사각형.
  새로 칠해진 쪽(테두리 채도가 올라간 쪽)이 하나일 때만, 아니면 None(`field_box_unknown`)

OCR 결과 글자는 판정에만 쓰고 저장·로그에 남기지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import cv2
import numpy as np

from kookabug_core.recorder.protect import Box
from kookabug_platform.recorder.crop import fit_inside
from kookabug_platform.vision import Pixels

__all__ = ["ReadText", "field_text", "label_bands", "label_text", "ocr_reader", "tab_field_box"]

type ReadText = Callable[[Pixels, Box], str | None]
"""OCR: 클라이언트 그림·상자 → 글자 (못 읽으면 None)."""

_MIN_W: Final = 24
_MIN_H: Final = 16


def ocr_reader(engine: object) -> ReadText:
    """`OcrEngine`(`read(image, region=…)` → 줄들) → `ReadText` (줄을 공백으로 잇는다)."""
    read = getattr(engine, "read")  # noqa: B009 — 프로토콜만 안다

    def run(image: Pixels, box: Box) -> str | None:
        lines = read(image, region=box)
        text = " ".join(line.text for line in lines).strip()
        return text or None

    return run


def label_bands(box: Box, size: tuple[int, int]) -> list[Box]:
    x, y, w, h = box
    band_h = round(h * 1.5)
    left = fit_inside((x - w, y - round(h * 0.25), w, band_h), size)
    top = fit_inside((x, y - band_h, w, band_h), size)
    return [b for b in (left, top) if b[2] > 0 and b[3] > 0 and (b[0] < x or b[1] < y)]


def label_text(read: ReadText, image: Pixels, box: Box) -> str | None:
    size = (int(image.shape[1]), int(image.shape[0]))
    texts = [t for band in label_bands(box, size) if (t := read(image, band))]
    return " ".join(texts) or None


def field_text(read: ReadText, image: Pixels, box: Box) -> str | None:
    size = (int(image.shape[1]), int(image.shape[0]))
    return read(image, fit_inside(box, size))


def _saturation(image: Pixels, box: Box) -> float:
    """상자 둘레(두께 3) 픽셀의 평균 채도."""
    x, y, w, h = box
    hsv = cv2.cvtColor(image[y : y + h, x : x + w], cv2.COLOR_BGR2HSV)
    ring = np.ones((h, w), dtype=bool)
    ring[3:-3, 3:-3] = False
    return float(hsv[:, :, 1][ring].mean()) if ring.any() else 0.0


def tab_field_box(before: Pixels, after: Pixels) -> Box | None:
    """Tab 직전·직후 프레임의 포커스 테두리가 새로 칠해진 칸 상자. 하나로 못 정하면 None."""
    if before.shape != after.shape:
        return None
    changed = (np.abs(before.astype(np.int16) - after.astype(np.int16)).max(axis=2) > 24).astype(
        np.uint8
    )
    changed = cv2.dilate(changed, np.ones((3, 3), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(changed)
    boxes: list[Box] = []
    for i in range(1, count):
        x, y, w, h = (int(v) for v in stats[i][:4])
        if w >= _MIN_W and h >= _MIN_H:
            boxes.append((x, y, w, h))
    gained = [b for b in boxes if _saturation(after, b) - _saturation(before, b) > 10]
    if len(gained) != 1:
        return None
    x, y, w, h = gained[0]
    return (x + 1, y + 1, max(1, w - 2), max(1, h - 2))  # 넓힌 1 px을 되돌림
