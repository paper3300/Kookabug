"""OCR 검출 크기 정책·타일·상자 합치기·설정 (구현 계획 M1 2.6, T7 2라운드). 모델 없이 돈다."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from kookabug_platform.ocr import det
from kookabug_platform.ocr.det import DetConfig, merge_tile_boxes, tiles
from kookabug_platform.ocr.engine import RapidOcrEngine, create_engine


def quad(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)


def rects(boxes: np.ndarray) -> list[tuple[int, int, int, int]]:
    return sorted(
        (int(b[:, 0].min()), int(b[:, 1].min()), int(b[:, 0].max()), int(b[:, 1].max()))
        for b in boxes
    )


@pytest.mark.parametrize(
    "shape",
    [(32, 3840), (1, 3840), (8, 4096), (3840, 1), (1, 1), (2, 3), (16, 2000), (5000, 9000)],
)
def test_sizes_never_zero(shape: tuple[int, int]) -> None:
    # 긴 한 줄·아주 가는 영역에서도 크기 계산이 0이 되어 resize가 깨지지 않는다 (검수 T7_1 2번)
    img = np.zeros((*shape, 3), dtype=np.uint8)
    fitted, ratio_h, ratio_w = det.fit_bounds(img)
    assert fitted.shape[0] > 0 and fitted.shape[1] > 0 and ratio_h > 0 and ratio_w > 0
    assert max(fitted.shape[:2]) <= max(DetConfig().max_side_len, max(shape))
    for tx, ty, tw, th in tiles(fitted.shape[0], fitted.shape[1]):
        padded, _pad = det.pad_vertical(fitted[ty : ty + th, tx : tx + tw])
        assert padded.shape[1] >= det.STRIDE
        assert padded.shape[0] * padded.shape[1] <= max(DetConfig().single_max_pixels, th * tw)
        x = det.det_input(padded)
        assert x.shape[2] >= det.STRIDE and x.shape[3] >= det.STRIDE
        assert x.shape[2] % det.STRIDE == 0 and x.shape[3] % det.STRIDE == 0
        assert max(x.shape[2:]) <= DetConfig().max_side_len


def test_fit_bounds_keeps_4k_and_shrinks_8k() -> None:
    four_k = np.zeros((2160, 3840, 3), dtype=np.uint8)
    assert det.fit_bounds(four_k)[0] is four_k  # 4K는 줄이지 않는다
    eight_k = np.zeros((4320, 7680, 3), dtype=np.uint8)
    out, rh, rw = det.fit_bounds(eight_k)
    assert max(out.shape[:2]) <= 4096 and rh > 1 and rw > 1


def test_tiles_cover_image_with_overlap() -> None:
    cfg = DetConfig()
    assert tiles(640, 1024) == [(0, 0, 1024, 640)]  # 1024x640 픽셀까지는 한 번에
    for h, w in ((1080, 1920), (2160, 3840), (1400, 1400), (700, 3000)):
        parts = tiles(h, w)
        assert len(parts) > 1
        covered = np.zeros((h, w), dtype=bool)
        for x, y, tw, th in parts:
            assert min(x, y) >= 0 and x + tw <= w and y + th <= h
            assert tw <= cfg.tile_side and th <= cfg.tile_side
            covered[y : y + th, x : x + tw] = True
        assert covered.all()
        xs = sorted({x for x, _y, _w, _h in parts})
        for a, b in itertools.pairwise(xs):
            assert a + cfg.tile_side - b >= cfg.tile_overlap  # 이웃 타일 겹침
    assert len(tiles(1080, 1920)) == 8
    assert len(tiles(2160, 3840)) == 32
    # 낮고 긴 한 줄은 여백을 붙인 크기로 판단해 가로로 나눈다
    assert [(x, w) for x, _y, w, _h in tiles(32, 3840)][:2] == [(0, 640), (457, 640)]
    assert {(y, h) for _x, y, _w, h in tiles(32, 3840)} == {(0, 32)}


def test_merge_duplicate_and_cut_pieces_across_tiles() -> None:
    boxes, scores = merge_tile_boxes(
        [
            # 겹친 곳의 같은 글자: 두 타일이 같은 상자
            (0, quad(500, 100, 600, 130), 0.9, False),
            (1, quad(501, 101, 600, 131), 0.8, False),
            # 경계에서 잘린 조각과 통째로 든 상자
            (0, quad(560, 300, 639, 330), 0.7, True),
            (1, quad(560, 300, 700, 330), 0.9, False),
            # 경계를 지나는 긴 줄의 두 조각 (조금만 겹쳐도 잘린 조각이면 합친다)
            (0, quad(300, 500, 639, 530), 0.9, True),
            (1, quad(600, 500, 1000, 530), 0.9, True),
        ]
    )
    assert rects(boxes) == [(300, 500, 1000, 530), (500, 100, 600, 131), (560, 300, 700, 330)]
    assert sorted(scores) == [0.9, 0.9, 0.9]


def test_merge_keeps_separate_words_and_lines() -> None:
    boxes, _ = merge_tile_boxes(
        [
            # 띄어 쓴 이웃 낱말: 확장된 상자가 4픽셀 겹쳐도 합치지 않는다
            (0, quad(71, 32, 135, 63), 1.0, False),
            (1, quad(131, 32, 216, 62), 1.0, False),
            # 위아래 다른 줄: 몇 픽셀 겹쳐도 합치지 않는다
            (0, quad(300, 200, 500, 230), 1.0, False),
            (1, quad(300, 227, 500, 257), 1.0, False),
            # 경계 조각에서 나온 키 큰 덩어리는 글자 줄과 합치지 않는다
            (2, quad(772, 646, 1096, 1079), 0.5, True),
            (3, quad(1070, 818, 1475, 935), 0.8, False),
            # 같은 타일 안의 상자끼리는 합치지 않는다
            (4, quad(2000, 50, 2100, 80), 1.0, False),
            (4, quad(2050, 50, 2150, 80), 1.0, False),
        ]
    )
    assert len(boxes) == 8


def test_merge_drops_pieces_inside_merged_line() -> None:
    # 한 타일은 줄 통째로, 다른 타일은 낱말마다: 낱말 조각은 버린다 ("점검 안내점검" 중복)
    boxes, _ = merge_tile_boxes(
        [
            (11, quad(1913, 729, 2010, 767), 0.8, True),
            (12, quad(1956, 732, 2025, 765), 0.9, False),
            (12, quad(1914, 731, 1971, 765), 0.9, False),
        ]
    )
    assert rects(boxes) == [(1913, 729, 2025, 767)]


def test_det_config_validated_and_from_mapping() -> None:
    cfg = DetConfig()
    assert (cfg.limit_side_len, cfg.max_side_len, cfg.single_max_pixels) == (64, 4096, 655360)
    assert (cfg.tile_side, cfg.tile_overlap) == (640, 128)
    assert DetConfig.from_mapping({"limit_side_len": 736}).limit_side_len == 736
    for bad in (
        {"limit_side_len": 0},
        {"limit_side_len": 64.0},
        {"tile_side": 100},
        {"tile_side": 650},
        {"tile_overlap": 400},
        {"max_side_len": 512},
        {"single_max_pixels": 1000},
        {"tile_overlap": True},
    ):
        with pytest.raises(ValueError):
            DetConfig.from_mapping(bad)
    with pytest.raises(ValueError, match="모르는 키"):
        DetConfig.from_mapping({"limit": 64})

    engine = create_engine("rapidocr", {"det": {"tile_side": 768, "tile_overlap": 192}})
    assert isinstance(engine, RapidOcrEngine)
    assert engine.det_config == DetConfig(tile_side=768, tile_overlap=192)
    assert isinstance(create_engine(), RapidOcrEngine)
    with pytest.raises(ValueError, match="모르는 설정"):
        create_engine("rapidocr", {"rec": {}})
    with pytest.raises(ValueError, match="객체"):
        create_engine("rapidocr", {"det": 64})
