"""지난 성공과 화면 비교 (M3 계획 2.8): 두 이미지를 같은 크기 회색조로 줄여 달라진 픽셀 비율과 차이
영역 상자를 낸다.

- 이 실행 증거(PNG, 창 전체 크기)와 기준 실행 썸네일(JPEG, 긴 변 480)은 크기·압축이 다르다. 그래서
  이 실행 이미지 비율대로 긴 변 `WORK_LONG_SIDE`로 둘 다 줄이고(기준 쪽 비율이 다르면 늘여 맞춘다 —
  창 크기 차이는 비교의 "환경"이 따로 보인다) 살짝 흐린 뒤 비교한다. JPEG 잡음·한두 픽셀 어긋남이
  차이로 잡히지 않게 하기 위함이다
- 차이 비율 = 밝기 차이가 `PIXEL_THRESHOLD`를 넘는 픽셀 / 전체 (줄인 크기 기준)
- 영역 상자: 차이 픽셀을 닫기 연산으로 이어 붙인 덩어리의 바깥 사각형, 넓은 것부터 최대
  `MAX_REGIONS`개, 줄인 크기의 `MIN_REGION_RATIO`보다 작은 덩어리는 버린다. 좌표는
  **이 실행 이미지** 좌표다

코어(`record.compare`)는 OpenCV에 기대지 않으므로 daemon이 이 함수를 넘겨 준다.
"""

from __future__ import annotations

from typing import Final

import cv2
import numpy as np

from kookabug_platform.frames import Pixels, decode_image

__all__ = ["MAX_REGIONS", "PIXEL_THRESHOLD", "WORK_LONG_SIDE", "screen_diff"]

WORK_LONG_SIDE: Final = 320
PIXEL_THRESHOLD: Final = 40
"""밝기(0~255) 차이가 이보다 크면 달라진 픽셀."""
MAX_REGIONS: Final = 5
MIN_REGION_RATIO: Final = 0.001
"""줄인 크기 넓이에 대한 최소 덩어리 넓이 비율."""
_CLOSE_KERNEL: Final = 5


def _gray(pixels: Pixels, size: tuple[int, int]) -> Pixels:
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    return np.asarray(cv2.GaussianBlur(small, (3, 3), 0), dtype=np.uint8)


def screen_diff(current: bytes, baseline: bytes) -> tuple[float, list[list[int]]]:
    """(차이 비율 0~1, 차이 영역 `[x, y, w, h]` 목록 — `current` 이미지 좌표). 이미지를 읽을 수
    없으면 ValueError."""
    here = decode_image(current)
    there = decode_image(baseline)
    height, width = int(here.shape[0]), int(here.shape[1])
    scale = min(1.0, WORK_LONG_SIDE / max(width, height))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    a = _gray(here, size)
    b = _gray(there, size)
    mask = (cv2.absdiff(a, b) > PIXEL_THRESHOLD).astype(np.uint8)
    total = int(mask.size)
    ratio = float(np.count_nonzero(mask)) / total if total else 0.0
    kernel = np.ones((_CLOSE_KERNEL, _CLOSE_KERNEL), np.uint8)
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
    min_area = max(1, round(total * MIN_REGION_RATIO))
    boxes: list[tuple[int, list[int]]] = []
    sx, sy = width / size[0], height / size[1]
    for label in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[label])
        if area < min_area:
            continue
        left, top = int(x * sx), int(y * sy)
        right = min(width, round((x + w) * sx))
        bottom = min(height, round((y + h) * sy))
        boxes.append((area, [left, top, max(1, right - left), max(1, bottom - top)]))
    boxes.sort(key=lambda item: item[0], reverse=True)
    return min(1.0, ratio), [box for _, box in boxes[:MAX_REGIONS]]
