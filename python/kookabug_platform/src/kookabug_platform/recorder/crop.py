"""녹화 클릭의 target 자르기 (M4 계획 2.6 "자르는 상자"·"유일성 검사"·"클릭 지점", Q4, T6).

1. **경계 추정**: 클릭 점을 품는 윤곽(Canny 닫힌 윤곽·`floodFill` 색 영역) 중 넓이 24x24 이상,
   클라이언트 25% 이하인 가장 작은 것의 바깥 상자 + 여백 4 px
2. 없으면 **고정 크기** `0.12h x 0.06h`(최소 32x24), 클릭 점 가운데. 상자는 클라이언트 안으로 옮긴다
3. **유일성**: 그 템플릿을 같은 프레임 전체에서 찾아 자기 자리 말고 `임계값 - 0.03` 이상 봉우리가
   있으면 1.5배로 두 번까지 넓히고, 그래도 여럿이면 상자 3배 **검색 범위**로 좁힌다. 범위 안에서도
   여럿이면 배지 `same_shape`(검색 범위를 좁히세요)
4. **보호 영역**: 모든 상자(처음·넓힌 것)는 `ProtectionSet.avoid`를 거친다. 유효한 상자를 못
   만들면 target 없이 `secret_overlap`
5. **클릭 지점**: `anchor: center`, `offset` = 클릭 점 - 상자 가운데 (재생은 `offset x 배율`)

프레임은 클라이언트 그림(같은 확정 세대로 검증된 `ClickFrame.client_pixels()`)이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

import cv2
import numpy as np

from kookabug_core.recorder.protect import Box, ProtectionSet
from kookabug_platform.dpi import pixels_to_normalized
from kookabug_platform.recorder.frames import ClickFrame, Unresolved
from kookabug_platform.vision import DEFAULT_THRESHOLD, Pixels, score_peaks

__all__ = [
    "MARGIN",
    "UNIQUE_SLACK",
    "ClickCrop",
    "box_center",
    "click_offset",
    "crop_click",
    "crop_from_frame",
    "estimate_bounds",
    "find_peaks",
    "fit_inside",
    "fixed_box",
    "target_spec",
]

MARGIN: Final = 4
MIN_SIDE: Final = 24
MAX_AREA_RATIO: Final = 0.25
UNIQUE_SLACK: Final = 0.03
"""자기 자리 말고 `임계값 - 0.03` 이상 봉우리가 있으면 유일하지 않다."""
WIDEN: Final = 1.5
WIDEN_TIMES: Final = 2
REGION_SCALE: Final = 3.0


@dataclass(frozen=True, slots=True)
class ClickCrop:
    """클릭 하나의 자르기 결과. `box`가 None이면 target을 못 만듦(`needs_review`)."""

    box: Box | None
    element: Box | None
    """요소 상자 (경계 추정 상자, 고정 크기 대비면 None). 재사용 판정 기준."""
    kind: Literal["bounds", "fixed"] | None
    point: tuple[int, int]
    offset: tuple[float, float] = (0.0, 0.0)
    search_region: Box | None = None
    """검색 범위 (클라이언트 픽셀). 유일하지 않을 때만."""
    same_shape: int = 1
    """검색 범위(없으면 프레임) 안 같은 모양 개수."""
    needs_review: tuple[str, ...] = ()
    badges: tuple[str, ...] = field(default_factory=tuple[str, ...])


def box_center(box: Box) -> tuple[float, float]:
    """`click_point`의 center와 같은 자리 (상자 안 픽셀: 오른쪽 끝은 x + w - 1)."""
    return box[0] + (box[2] - 1) / 2, box[1] + (box[3] - 1) / 2


def click_offset(box: Box, point: tuple[int, int]) -> tuple[float, float]:
    cx, cy = box_center(box)
    return (point[0] - cx, point[1] - cy)


def fit_inside(box: Box, size: tuple[int, int]) -> Box:
    """상자를 클라이언트 안으로 옮긴다 (크기 유지, 클라이언트보다 크면 자른다)."""
    x, y, w, h = box
    w, h = min(w, size[0]), min(h, size[1])
    x = min(max(x, 0), size[0] - w)
    y = min(max(y, 0), size[1] - h)
    return (x, y, w, h)


def fixed_box(size: tuple[int, int], point: tuple[int, int]) -> Box:
    h = size[1]
    w_box = max(32, round(0.12 * h))
    h_box = max(24, round(0.06 * h))
    return fit_inside((point[0] - w_box // 2, point[1] - h_box // 2, w_box, h_box), size)


def _contains(box: Box, point: tuple[int, int]) -> bool:
    return box[0] <= point[0] < box[0] + box[2] and box[1] <= point[1] < box[1] + box[3]


def estimate_bounds(image: Pixels, point: tuple[int, int]) -> Box | None:
    """클릭 점을 품는 가장 작은 쓸 만한 윤곽·색 영역의 바깥 상자 (여백 없이). 없으면 None."""
    height, width = int(image.shape[0]), int(image.shape[1])
    limit = MAX_AREA_RATIO * width * height
    candidates: list[Box] = []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = (int(v) for v in cv2.boundingRect(contour))
        candidates.append((x, y, w, h))
    mask = np.zeros((height + 2, width + 2), np.uint8)
    flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    cv2.floodFill(image.copy(), mask, point, (0, 0, 0), (6, 6, 6), (6, 6, 6), flags)
    ys, xs = np.nonzero(mask[1:-1, 1:-1])
    if xs.size:
        x0, y0 = int(xs.min()), int(ys.min())
        candidates.append((x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1))
    usable = [
        b
        for b in candidates
        # 두 변 모두 24 이상: 단추 안 글자 덩어리(글자 높이 < 24)를 단추로 잡지 않는다
        if _contains(b, point) and b[2] >= MIN_SIDE and b[3] >= MIN_SIDE and b[2] * b[3] <= limit
    ]
    if not usable:
        return None
    return min(usable, key=lambda b: b[2] * b[3])


def _grow(box: Box, factor: float, size: tuple[int, int]) -> Box:
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    w, h = round(box[2] * factor), round(box[3] * factor)
    return fit_inside((round(cx - w / 2), round(cy - h / 2), w, h), size)


def find_peaks(
    image: Pixels, template: Pixels, region: Box | None = None, count: int = 8
) -> list[tuple[float, Box]]:
    """프레임(의 `region`)에서 서로 겹치지 않는 봉우리 `(점수, 상자)` (클라이언트 좌표)."""
    rx, ry, rw, rh = region if region is not None else (0, 0, image.shape[1], image.shape[0])
    area = image[ry : ry + rh, rx : rx + rw]
    th, tw = template.shape[:2]
    return [
        (score, (rx + x, ry + y, tw, th)) for score, (x, y) in score_peaks(area, template, count)
    ]


_OWN: Final = 4
"""자기 자리로 보는 범위 (왼쪽 위 ±4 px)."""


def _other_best(image: Pixels, own: Box) -> float:
    """자기 자리(±4 px) 말고 가장 높은 점수. 겹침 억제를 쓰지 않는다 — 넓힌 상자는 이웃 무늬와
    겹치는 자리에서도 같은 점수가 나와, 겹치는 봉우리를 지우면 그 모호함을 놓친다."""
    x, y, w, h = own
    template = image[y : y + h, x : x + w]
    if template.size == 0 or w > image.shape[1] or h > image.shape[0]:
        return -1.0
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    scores = np.where(np.isfinite(scores), scores, np.float32(1.0))  # 평평한 무늬는 어디서나 같음
    scores[max(0, y - _OWN) : y + _OWN + 1, max(0, x - _OWN) : x + _OWN + 1] = -1.0
    return float(scores.max()) if scores.size else -1.0


def crop_click(
    image: Pixels,
    point: tuple[int, int],
    *,
    protect: ProtectionSet | None = None,
    t_ns: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ClickCrop:
    """클라이언트 그림과 클릭 점 → 자를 상자·검색 범위·오프셋. 규칙은 모듈 설명."""
    size = (int(image.shape[1]), int(image.shape[0]))
    bounds = estimate_bounds(image, point)
    if bounds is not None:
        x, y, w, h = bounds
        box = fit_inside((x - MARGIN, y - MARGIN, w + 2 * MARGIN, h + 2 * MARGIN), size)
        kind: Literal["bounds", "fixed"] = "bounds"
    else:
        box = fixed_box(size, point)
        kind = "fixed"
    guard = protect or ProtectionSet()
    safe = guard.avoid(box, point, t_ns, frame=image)
    if safe is None:
        return ClickCrop(None, bounds, kind, point, needs_review=("secret_overlap",))
    box = first = safe
    floor = threshold - UNIQUE_SLACK
    for attempt in range(WIDEN_TIMES + 1):
        if _other_best(image, box) < floor:
            return ClickCrop(box, bounds, kind, point, click_offset(box, point))
        if attempt == WIDEN_TIMES:
            break
        wider = guard.avoid(_grow(box, WIDEN, size), point, t_ns, frame=image)
        if wider is None or wider == box:
            break
        box = wider
    # 넓혀도 여럿: 처음 상자로 돌아가 그 둘레(3배) 검색 범위로 좁힌다
    box = first
    region = guard.avoid(_grow(box, REGION_SCALE, size), point, t_ns, frame=image) or box
    template = image[box[1] : box[1] + box[3], box[0] : box[0] + box[2]]
    inside = [p for p in find_peaks(image, template, region) if p[0] >= floor]
    same = max(1, len(inside))
    badges = ("same_shape",) if same > 1 else ()
    return ClickCrop(
        box, bounds, kind, point, click_offset(box, point), region, same, badges=badges
    )


def crop_from_frame(
    frame: ClickFrame | Unresolved,
    *,
    protect: ProtectionSet | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> ClickCrop | Unresolved:
    """클릭과 같은 확정 세대로 검증된 프레임에서만 자른다 (M4 계획 2.5 "자르기 조건"). 프레임이
    없거나 세대가 다르면 그대로 돌려준다 — 뒤 프레임으로 대신하지 않는다(`no_frame`·
    `geometry_unresolved`·다시 물을 `pending`). 보호 영역은 그 프레임의 도착 시각으로 본다."""
    if isinstance(frame, Unresolved):
        return frame
    return crop_click(
        np.ascontiguousarray(frame.client_pixels()),
        frame.client_point,
        protect=protect,
        t_ns=frame.entry.arrival_ns,
        threshold=threshold,
    )


def target_spec(
    image_name: str,
    *,
    client_size: tuple[int, int],
    dpi: int,
    offset: tuple[float, float],
    search_region: Box | None = None,
) -> dict[str, object]:
    """target 파일 내용 (`kookabug.target/0`). 임계값·방법은 기본(생략)."""
    spec: dict[str, object] = {
        "format": "kookabug.target/0",
        "image": image_name,
        "click": {"anchor": "center", "offset": [round(offset[0], 1), round(offset[1], 1)]},
        "recorded": {"client_size": [client_size[0], client_size[1]], "dpi": dpi},
    }
    if search_region is not None:
        spec["search"] = {"region": list(pixels_to_normalized(search_region, client_size))}
    return spec
