# 이 파일은 RapidOCR v3.10.0(`rapidocr/ch_ppocr_det/utils.py`·`main.py`·`utils/process_img.py`,
# Copyright (c) 2021 RapidOCR Authors, 그 바탕은 Copyright (c) 2020 PaddlePaddle Authors)를 옮겨
# 고친 것이다. 원본과 같이 Apache License 2.0을 따른다 (`NOTICE` 참고).
# 바꾼 점: Shapely 다각형 넓이·둘레를 `cv2.contourArea`·`cv2.arcLength`로, 상자 정렬은 아래
# `engine`이 줄 단위로 다시 하므로 빼고, 설정 객체 대신 `DetConfig`, 검출 입력 짧은 변 한계
# 736 → 64, 큰 이미지는 타일로 나눠 검출, 크기 계산이 0이 되지 않게, 후처리 중 취소 확인.
"""DB 문자 검출: 전처리(크기 맞춤·정규화·타일)와 후처리(이진화·윤곽·상자 점수·확장).

**검출 크기 정책** (`DetConfig`, 기본값은 실측 — T7 2라운드)

- 검출 모델(PP-OCRv6 det small)은 입력 픽셀이 많으면 작은 글자를 놓친다. 단색 바탕에 작은
  글자(약 12픽셀 높이) 하나를 임의 위치에 그려 본 결과(각 8~10번) 640x640·768x768·960x544·
  1024x640은 9~10/10, 896x896은 3~10/10, 1024x1024는 0~2/10, 1280x720은 0~3/8, 1600x900·
  1920x1080은 0/8 (큰 글자도 1920x1080에서 1/8). 줄여서 넣으면 글자가 더 작아져 더 놓친다
- 그래서 픽셀 수가 `single_max_pixels`(1024x640)를 넘는 이미지는 원래 해상도 그대로
  `tile_side`(640) 정사각 타일로 나눠(겹침 `tile_overlap` 128) 타일마다 검출하고, 타일 경계에서
  잘린 상자와 겹친 곳의 같은 상자는 합친다(`merge_tile_boxes`). 640 타일은 픽셀당 비용도 가장
  낮다(검출 한 번 약 70 ms)
- 짧은 변이 `limit_side_len`(64)보다 작을 때만 검출 입력을 늘린다(RapidOCR 기본 736은 작은 영역을
  열 배 넘게 키워 1초 넘게 걸리고 글자가 깨짐 — PaddleOCR 3.x 검출 기본값)
- 긴 변이 `max_side_len`(4096)을 넘으면(8K 등) 그만큼 줄인다. 4K는 줄이지 않는다
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Final

import cv2
import numpy as np
import pyclipper

if TYPE_CHECKING:
    from numpy.typing import NDArray

# pyclipper는 타입 정보가 없는 확장 모듈이다
_clipper: Any = pyclipper

__all__ = [
    "DEFAULT_CONFIG",
    "DbPostProcess",
    "DetConfig",
    "cut_by_tile",
    "det_input",
    "fit_bounds",
    "merge_tile_boxes",
    "pad_vertical",
    "rotate_crop",
    "tiles",
]

# RapidOCR `config.yaml` Det 기본값
THRESH: Final = 0.3
BOX_THRESH: Final = 0.5
MAX_CANDIDATES: Final = 1000
UNCLIP_RATIO: Final = 1.6
MIN_SIZE: Final = 3
# Global 기본값: 전처리 짧은 변 하한과 세로 여백
MIN_SIDE_LEN: Final = 30
MIN_HEIGHT: Final = 30
WIDTH_HEIGHT_RATIO: Final = 8
# 검출 입력은 32의 배수다. 어느 변도 이보다 작게 만들지 않는다
STRIDE: Final = 32
# 후처리 중 이 개수의 윤곽마다 취소·기한을 본다
CHECK_EVERY: Final = 16
# 다른 타일의 두 상자를 합치는 가로 겹침 (좁은 쪽 너비 대비, 둘 다 잘리지 않았을 때)
MERGE_OVERLAP: Final = 0.3
# 타일 안쪽 경계에서 이 픽셀 안에 닿은 상자는 잘린 조각으로 본다
CUT_MARGIN: Final = 2
# 합친 뒤 더 큰 상자 안에 넓이의 이만큼이 들면 버린다
CONTAINED: Final = 0.7
# 타일 상자 합치기 중 취소·기한 확인 간격 (상자 쌍 비교 수, 든 상자 판정 수)
MERGE_CHECK_EVERY: Final = 256
CONTAIN_CHECK_EVERY: Final = 64
# 든 상자 판정의 격자 색인 칸 크기 (픽셀)
GRID: Final = 128

type Image = NDArray[np.uint8]
type Boxes = NDArray[np.float32]  # (N, 4, 2): 왼위·오른위·오른아래·왼아래
type Tile = tuple[int, int, int, int]  # x, y, w, h


@dataclass(frozen=True, slots=True)
class DetConfig:
    """검출 크기 설정. `kookabug.json` `ocr.det`(선택)로 바꿀 수 있다 (`from_mapping`)."""

    limit_side_len: int = 64
    """짧은 변이 이보다 작을 때만 검출 입력을 늘린다."""
    max_side_len: int = 4096
    """긴 변이 이보다 크면 줄인다."""
    single_max_pixels: int = 1024 * 640
    """픽셀 수가 이 이하면 한 번에 검출, 넘으면 타일로 나눈다."""
    tile_side: int = 640
    """타일 한 변."""
    tile_overlap: int = 128
    """이웃 타일이 겹치는 픽셀. 이보다 짧은 글자는 어느 한 타일에 통째로 들어간다."""

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"ocr.det.{f.name}는 정수다: {value!r}")
        if not STRIDE <= self.limit_side_len <= self.max_side_len:
            raise ValueError(f"ocr.det.limit_side_len은 {STRIDE}~max_side_len 사이다")
        if self.tile_side < 256 or self.tile_side % STRIDE:
            raise ValueError(f"ocr.det.tile_side는 256 이상, {STRIDE}의 배수다")
        if not 0 <= self.tile_overlap <= self.tile_side // 2:
            raise ValueError("ocr.det.tile_overlap은 0~tile_side/2 사이다")
        if self.max_side_len < self.tile_side:
            raise ValueError("ocr.det.max_side_len은 tile_side 이상이다")
        if self.single_max_pixels < self.tile_side * self.tile_side:
            raise ValueError("ocr.det.single_max_pixels는 tile_side² 이상이다")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DetConfig:
        """설정 객체에서. 모르는 키·잘못된 값은 ValueError."""
        names = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - names)
        if unknown:
            raise ValueError(f"ocr.det에 모르는 키: {', '.join(unknown)}")
        return cls(**dict(data))


DEFAULT_CONFIG: Final = DetConfig()


def _round32(value: float) -> int:
    """32의 배수로 반올림하되 `STRIDE`보다 작게 하지 않는다 (0이 되면 resize가 깨진다)."""
    return max(STRIDE, int(round(value / STRIDE) * STRIDE))


def _u8(image: Any) -> Image:
    """opencv 결과(`MatLike`)를 uint8 배열 타입으로 (값은 이미 uint8이다)."""
    return np.asarray(image, dtype=np.uint8)


def fit_bounds(img: Image, config: DetConfig = DEFAULT_CONFIG) -> tuple[Image, float, float]:
    """긴 변이 `max_side_len`을 넘으면 줄이고, 짧은 변이 `MIN_SIDE_LEN`보다 작으면 늘린다
    (늘려서 긴 변이 한계를 넘으면 늘리지 않는다 — 아주 가는 이미지). 크기를 바꾸면 32의 배수로.
    돌려주는 비율은 원래 크기 / 새 크기 (세로, 가로)."""
    h, w = img.shape[:2]
    ratio = min(1.0, config.max_side_len / max(h, w))
    if min(h, w) * ratio < MIN_SIDE_LEN:
        up = MIN_SIDE_LEN / min(h, w)
        if max(h, w) * up <= config.max_side_len:
            ratio = up
    if ratio == 1.0:
        return img, 1.0, 1.0
    nh, nw = _round32(h * ratio), _round32(w * ratio)
    return _u8(cv2.resize(img, (nw, nh))), h / nh, w / nw


def pad_vertical(img: Image) -> tuple[Image, int]:
    """아주 낮거나 아주 긴 줄 이미지는 위아래에 검은 여백을 붙인다 (검출이 줄을 놓치지 않게).
    너비가 `STRIDE`보다 좁으면 오른쪽에도 붙인다(좌표는 그대로). 돌려주는 값은 위 여백 픽셀."""
    h, w = img.shape[:2]
    pad = 0
    if h <= MIN_HEIGHT or w / h > WIDTH_HEIGHT_RATIO:
        new_h = max(int(w / WIDTH_HEIGHT_RATIO), MIN_HEIGHT) * 2
        pad = int(abs(new_h - h) / 2)
    right = max(0, STRIDE - w)
    if pad or right:
        border = cv2.copyMakeBorder(img, pad, pad, 0, right, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        img = _u8(border)
    return img, pad


def tiles(height: int, width: int, config: DetConfig = DEFAULT_CONFIG) -> list[Tile]:
    """검출 타일. 세로 여백(`pad_vertical`)을 붙인 뒤의 픽셀 수가 `single_max_pixels` 이하면
    이미지 전체 하나. 아니면 각 축을 `tile_side` 조각으로 고르게 나누고 이웃 조각은
    `tile_overlap` 이상 겹친다(축 길이가 `tile_side` 이하면 그 축은 나누지 않는다). 여백은 타일마다
    붙인다 — 3840x32 한 줄은 여백을 붙이면 3840x960이라 640x32 조각 여덟으로 나눈다."""
    padded = height
    if height <= MIN_HEIGHT or width / height > WIDTH_HEIGHT_RATIO:
        padded = max(height, max(int(width / WIDTH_HEIGHT_RATIO), MIN_HEIGHT) * 2)
    if padded * width <= config.single_max_pixels:
        return [(0, 0, width, height)]

    def starts(length: int) -> list[tuple[int, int]]:
        side = config.tile_side
        if length <= side:
            return [(0, length)]
        n = -(-(length - config.tile_overlap) // (side - config.tile_overlap))
        n = max(n, 2)
        return [(round(i * (length - side) / (n - 1)), side) for i in range(n)]

    return [(x, y, tw, th) for y, th in starts(height) for x, tw in starts(width)]


def det_input(img: Image, config: DetConfig = DEFAULT_CONFIG) -> NDArray[np.float32]:
    """검출 모델 입력 (1, 3, H, W). 짧은 변이 `limit_side_len`보다 작으면 늘리되 긴 변은
    `max_side_len`을 넘지 않게, 두 변 모두 32의 배수(32 이상)로."""
    h, w = img.shape[:2]
    ratio = config.limit_side_len / min(h, w) if min(h, w) < config.limit_side_len else 1.0
    ratio = min(ratio, max(1.0, config.max_side_len / max(h, w)))
    resized = cv2.resize(img, (_round32(w * ratio), _round32(h * ratio)))
    x = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
    return np.ascontiguousarray(x.transpose(2, 0, 1)[np.newaxis], dtype=np.float32)


class DbPostProcess:
    """확률 지도 → 사각형 상자 (원래 이미지 좌표)."""

    dilation_kernel: Final = np.array([[1, 1], [1, 1]], dtype=np.uint8)

    def __call__(
        self,
        pred: NDArray[np.float32],
        shape: tuple[int, int],
        check: Callable[[], None] | None = None,
    ) -> tuple[Boxes, list[float]]:
        """`check`는 윤곽 `CHECK_EVERY`개마다 불린다(취소·기한이면 예외를 던진다)."""
        src_h, src_w = shape
        prob = pred[0, 0]
        mask = _u8(cv2.dilate((prob > THRESH).astype(np.uint8), self.dilation_kernel))
        boxes, scores = self._boxes(prob, mask, src_w, src_h, check)
        return self._filter(boxes, scores, src_h, src_w)

    def _boxes(
        self,
        prob: NDArray[np.float32],
        bitmap: NDArray[np.uint8],
        dest_w: int,
        dest_h: int,
        check: Callable[[], None] | None,
    ) -> tuple[list[NDArray[np.float32]], list[float]]:
        height, width = bitmap.shape
        contours, _ = cv2.findContours(bitmap * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes: list[NDArray[np.float32]] = []
        scores: list[float] = []
        for index, contour in enumerate(contours[:MAX_CANDIDATES]):
            if check is not None and index % CHECK_EVERY == 0:
                check()
            points, sside = _mini_box(contour)
            if sside < MIN_SIZE:
                continue
            score = _box_score_fast(prob, points)
            if score < BOX_THRESH:
                continue
            expanded = _unclip(points)
            if expanded is None:
                continue
            box, sside = _mini_box(expanded)
            if sside < MIN_SIZE + 2:
                continue
            box[:, 0] = np.clip(np.round(box[:, 0] / width * dest_w), 0, dest_w)
            box[:, 1] = np.clip(np.round(box[:, 1] / height * dest_h), 0, dest_h)
            boxes.append(box)
            scores.append(score)
        return boxes, scores

    @staticmethod
    def _filter(
        boxes: list[NDArray[np.float32]], scores: list[float], img_h: int, img_w: int
    ) -> tuple[Boxes, list[float]]:
        kept: list[NDArray[np.float32]] = []
        kept_scores: list[float] = []
        for box, score in zip(boxes, scores, strict=True):
            box = _order_clockwise(box)
            box[:, 0] = np.clip(np.trunc(box[:, 0]), 0, img_w - 1)
            box[:, 1] = np.clip(np.trunc(box[:, 1]), 0, img_h - 1)
            if (
                int(np.linalg.norm(box[0] - box[1])) <= 3
                or int(np.linalg.norm(box[0] - box[3])) <= 3
            ):
                continue
            kept.append(box)
            kept_scores.append(score)
        if not kept:
            return np.zeros((0, 4, 2), dtype=np.float32), []
        return np.stack(kept).astype(np.float32), kept_scores


def _mini_box(contour: Any) -> tuple[NDArray[np.float32], float]:
    rect = cv2.minAreaRect(contour)
    pts = sorted(cv2.boxPoints(rect).tolist(), key=lambda p: p[0])
    i1, i4 = (0, 1) if pts[1][1] > pts[0][1] else (1, 0)
    i2, i3 = (2, 3) if pts[3][1] > pts[2][1] else (3, 2)
    box = np.array([pts[i1], pts[i2], pts[i3], pts[i4]], dtype=np.float32)
    return box, float(min(rect[1]))


def _box_score_fast(prob: NDArray[np.float32], box: NDArray[np.float32]) -> float:
    h, w = prob.shape[:2]
    xmin = int(np.clip(np.floor(box[:, 0].min()), 0, w - 1))
    xmax = int(np.clip(np.ceil(box[:, 0].max()), 0, w - 1))
    ymin = int(np.clip(np.floor(box[:, 1].min()), 0, h - 1))
    ymax = int(np.clip(np.ceil(box[:, 1].max()), 0, h - 1))
    mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
    shifted = box - np.array([xmin, ymin], dtype=np.float32)
    cv2.fillPoly(mask, [shifted.reshape(-1, 2).astype(np.int32)], 1)
    return float(cv2.mean(prob[ymin : ymax + 1, xmin : xmax + 1], mask)[0])


def _unclip(box: NDArray[np.float32]) -> NDArray[np.float32] | None:
    """상자를 넓이·둘레 비로 바깥으로 넓힌다 (DB 논문의 unclip). 넓힌 다각형이 없으면 None."""
    area = abs(float(cv2.contourArea(box)))
    length = float(cv2.arcLength(box, True))
    if length == 0:
        return None
    distance = area * UNCLIP_RATIO / length
    offset = _clipper.PyclipperOffset()
    offset.AddPath(box.tolist(), _clipper.JT_ROUND, _clipper.ET_CLOSEDPOLYGON)
    paths = offset.Execute(distance)
    if not paths:
        return None
    return np.array(paths[0], dtype=np.float32).reshape(-1, 1, 2)


def _order_clockwise(pts: NDArray[np.float32]) -> NDArray[np.float32]:
    xs = pts[np.argsort(pts[:, 0]), :]
    left = xs[:2][np.argsort(xs[:2, 1])]
    right = xs[2:][np.argsort(xs[2:, 1])]
    (tl, bl), (tr, br) = left, right
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _rect_quad(x0: float, y0: float, x1: float, y1: float) -> NDArray[np.float32]:
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)


def cut_by_tile(box: NDArray[np.float32], tile: Tile, height: int, width: int) -> bool:
    """상자가 타일의 안쪽 경계(이미지 가장자리가 아닌 변)에 닿았나 — 경계에서 잘린 조각이다."""
    tx, ty, tw, th = tile
    x0, y0 = float(box[:, 0].min()), float(box[:, 1].min())
    x1, y1 = float(box[:, 0].max()), float(box[:, 1].max())
    return (
        (tx > 0 and x0 <= tx + CUT_MARGIN)
        or (tx + tw < width and x1 >= tx + tw - 1 - CUT_MARGIN)
        or (ty > 0 and y0 <= ty + CUT_MARGIN)
        or (ty + th < height and y1 >= ty + th - 1 - CUT_MARGIN)
    )


def merge_tile_boxes(
    found: Sequence[tuple[int, NDArray[np.float32], float, bool]],
    check: Callable[[], None] | None = None,
) -> tuple[Boxes, list[float]]:
    """여러 타일의 상자(타일 번호, 이미지 좌표 사각형, 점수, 경계에서 잘림)를 합친다.

    **다른 타일**에서 온 두 상자가 같은 줄에 있고(세로 겹침 ≥ 낮은 쪽 높이의 절반) 가로로
    겹치면, 둘 중 하나가 타일 경계에서 잘린 조각이거나 가로 겹침이 좁은 쪽 너비의
    `MERGE_OVERLAP` 이상일 때 두 상자를 감싸는 축 정렬 사각형 하나로 합친다. 겹친 곳에서 두 타일이
    같은 글자를 찾은 것, 경계에서 잘린 조각과 통째로 든 상자, 경계를 지나는 긴 줄의 조각들이다.
    잘리지 않은 상자끼리 조금 겹친 것은 합치지 않는다(확장된 상자는 띄어 쓴 이웃 낱말과도 몇 픽셀
    겹친다). 같은 타일 안의 상자끼리는 합치지 않는다(한 번의 검출이 나눈 낱말은 그대로 둔다).
    합친 뒤 더 큰 상자 안에 넓이의 `CONTAINED` 이상이 든 상자는 그 상자에 넣는다(한 타일은 줄
    통째로, 다른 타일은 낱말마다 찾은 경우 — 큰 상자를 조각까지 넓힌다).

    계산은 가로 시작점으로 정렬해 가로로 겹칠 수 있는 이웃만 비교하고(합쳐지는 것이 없을 때까지
    되풀이), 든 상자 판정은 격자 색인으로 겹칠 수 있는 상자만 본다. `check`는 비교
    `MERGE_CHECK_EVERY`번·든 상자 판정 `CONTAIN_CHECK_EVERY`번마다 불린다(취소·기한이면 예외).
    """
    items = [_Merged({tile}, _bounds(box), score, cut) for tile, box, score, cut in found]
    count = 0

    def tick(every: int) -> None:
        nonlocal count
        count += 1
        if check is not None and count % every == 0:
            check()

    changed = True
    while changed:
        changed = False
        if check is not None:
            check()
        order = sorted((it for it in items if it.alive), key=lambda it: it.rect[0])
        for i, a in enumerate(order):
            if not a.alive:
                continue
            for b in order[i + 1 :]:
                # 가로 시작점 순서라 a의 끝(합칠수록 늘어남)을 넘은 뒤로는 겹칠 상자가 없다
                if b.rect[0] >= a.rect[2]:
                    break
                tick(MERGE_CHECK_EVERY)
                if b.alive and _mergeable(a, b):
                    a.absorb(b)
                    changed = True
    # 더 큰 상자 안에 거의 다 든 상자(다른 타일이 같은 줄을 낱말마다 나눠 찾은 조각)는 그 상자에
    # 넣는다 — 버리지 않고 큰 상자를 조각까지 넓혀, 삐져나온 끝 글자를 잃지 않는다
    alive = sorted((it for it in items if it.alive), key=lambda it: it.area, reverse=True)
    grid: dict[tuple[int, int], list[_Merged]] = {}
    kept: list[_Merged] = []
    for item in alive:
        tick(CONTAIN_CHECK_EVERY)
        cells = _cells(item.rect)
        seen: set[int] = set()
        host: _Merged | None = None
        for cell in cells:
            for other in grid.get(cell, ()):
                if id(other) in seen:
                    continue
                seen.add(id(other))
                if _intersection(item.rect, other.rect) >= CONTAINED * max(1e-6, item.area):
                    host = other
                    break
            if host is not None:
                break
        if host is None:
            kept.append(item)
            for cell in cells:
                grid.setdefault(cell, []).append(item)
            continue
        before = set(_cells(host.rect))
        host.absorb(item)
        for cell in _cells(host.rect):
            if cell not in before:
                grid.setdefault(cell, []).append(host)
    if not kept:
        return np.zeros((0, 4, 2), dtype=np.float32), []
    return (
        np.stack([_rect_quad(*it.rect) for it in kept]).astype(np.float32),
        [it.score for it in kept],
    )


@dataclass(slots=True)
class _Merged:
    tiles: set[int]
    rect: list[float]  # x0, y0, x1, y1
    score: float
    cut: bool
    alive: bool = True

    @property
    def area(self) -> float:
        r = self.rect
        return (r[2] - r[0]) * (r[3] - r[1])

    def absorb(self, other: _Merged) -> None:
        a, b = self.rect, other.rect
        self.rect = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
        self.tiles |= other.tiles
        self.score = max(self.score, other.score)
        self.cut = self.cut or other.cut
        other.alive = False


def _mergeable(x: _Merged, y: _Merged) -> bool:
    if x.tiles & y.tiles:
        return False
    a, b = x.rect, y.rect
    overlap_y = min(a[3], b[3]) - max(a[1], b[1])
    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
    low = min(a[3] - a[1], b[3] - b[1])
    if overlap_x <= 0 or overlap_y < low / 2:
        return False
    # 높이가 크게 다른 상자(다른 줄·경계 조각에서 나온 덩어리)와는 합치지 않는다.
    # 위아래로 잘린 조각은 합치지 않아도 아래 "거의 다 든 상자"로 큰 상자에 들어간다
    if max(a[3], b[3]) - min(a[1], b[1]) > 1.5 * low:
        return False
    narrow = min(a[2] - a[0], b[2] - b[0])
    return x.cut or y.cut or overlap_x >= MERGE_OVERLAP * narrow


def _bounds(box: NDArray[np.float32]) -> list[float]:
    xs, ys = box[:, 0], box[:, 1]
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def _intersection(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _cells(rect: list[float]) -> list[tuple[int, int]]:
    x0, y0 = int(rect[0] // GRID), int(rect[1] // GRID)
    x1, y1 = int(rect[2] // GRID), int(rect[3] // GRID)
    return [(cx, cy) for cy in range(y0, y1 + 1) for cx in range(x0, x1 + 1)]


def rotate_crop(img: Image, points: NDArray[np.float32]) -> Image:
    """기울어진 사각형을 펴서 자른다. 세로로 긴(높이/너비 ≥ 1.5) 조각은 90° 돌린다."""
    crop_w = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
    crop_h = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
    crop_w, crop_h = max(crop_w, 1), max(crop_h, 1)
    dst = np.array([[0, 0], [crop_w, 0], [crop_w, crop_h], [0, crop_h]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(points.astype(np.float32), dst)
    out = cv2.warpPerspective(
        img, m, (crop_w, crop_h), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC
    )
    if out.shape[0] / out.shape[1] >= 1.5:
        out = np.rot90(out)
    return np.ascontiguousarray(out, dtype=np.uint8)
