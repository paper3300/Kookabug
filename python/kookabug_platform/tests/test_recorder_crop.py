"""녹화 클릭의 target 자르기 (M4 계획 2.6, Q4, T6): 경계 추정·고정 크기·유일성·넓히기·검색 범위·
클릭 지점 왕복·세대가 다르면 자르지 않음."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR
from kookabug_platform.recorder.crop import (
    ClickCrop,
    crop_click,
    crop_from_frame,
    target_spec,
)
from kookabug_platform.recorder.frames import Unresolved, pre_click
from kookabug_platform.recorder.geometry import Geometry
from kookabug_platform.recorder.scripted_frames import ScriptFrameSource, png_scenes
from kookabug_platform.vision import FrameMeta, TargetImage, TargetSpec, Vision

MS = 1_000_000
S = 1_000_000_000

# 예제 게임 단추 (layout.py, 1024x640 기준)
START = (412, 380, 200, 64)
LOGIN = (432, 380, 160, 56)
ENTER = (412, 420, 200, 60)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


def inside(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[0] + outer[2] >= inner[0] + inner[2]
        and outer[1] + outer[3] >= inner[1] + inner[3]
    )


@pytest.mark.parametrize(
    ("scene", "button", "point"),
    [
        ("title", START, (512, 412)),
        ("title", START, (470, 400)),
        ("login", LOGIN, (512, 408)),
        ("lobby", ENTER, (512, 450)),
    ],
)
def test_crop_bounds_button_on_sample_frames(scene, button, point) -> None:
    image = frame(scene)
    crop = crop_click(image, point)
    assert crop.kind == "bounds" and crop.box is not None and crop.element is not None
    # 단추를 담고 (경계 추정은 1 px 안쪽일 수 있어 여백 4 px로 덮는다) 클라이언트 25% 이하
    assert inside(crop.box, (button[0] + 1, button[1] + 1, button[2] - 2, button[3] - 2))
    assert crop.box[2] * crop.box[3] <= 0.25 * image.shape[0] * image.shape[1]
    assert crop.needs_review == () and crop.search_region is None


def test_fixed_size_fallback_on_flat_area() -> None:
    image = np.full((640, 1024, 3), 60, np.uint8)
    cv2.circle(image, (900, 100), 30, (200, 200, 200), -1)
    crop = crop_click(image, (300, 300))
    assert crop.kind == "fixed" and crop.element is None and crop.box is not None
    # 고정 크기 0.12h x 0.06h(77x38)에서 시작한다 (평평해 유일하지 않으면 넓힌다)
    assert inside(crop.box, (300 - 77 // 2, 300 - 38 // 2, 77, 38))
    edge = crop_click(image, (2, 2))
    assert edge.box is not None and edge.box[:2] == (0, 0)  # 클라이언트 안으로 옮김


def pattern_frame() -> np.ndarray:
    """같은 무늬 단추 셋 (가로로 나란히) + 줄마다 다른 표시가 없는 화면."""
    image = np.full((640, 1024, 3), (40, 36, 28), np.uint8)
    for x in (100, 420, 740):
        cv2.rectangle(image, (x, 300), (x + 160, 356), (48, 168, 240), -1)
        cv2.putText(image, "OK", (x + 55, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    return image


def test_ambiguous_widens_then_search_region() -> None:
    image = pattern_frame()
    crop = crop_click(image, (500, 328))
    assert crop.box is not None and crop.search_region is not None
    assert crop.same_shape == 1 and crop.badges == ()  # 범위 안에서는 하나
    # 넓혀도 무늬가 같아 검색 범위로 좁혔다: 범위는 클릭한 단추를 담고 다른 단추는 담지 않는다
    rx, _, rw, _ = crop.search_region
    assert rx <= 420 and rx + rw >= 580
    assert not inside(crop.search_region, (100, 300, 160, 56))
    assert not inside(crop.search_region, (740, 300, 160, 56))
    # 같은 무늬를 바짝 붙이면 범위 안에서도 여럿 → 배지
    tight = np.full((640, 1024, 3), (40, 36, 28), np.uint8)
    for x in (400, 470, 540):
        cv2.rectangle(tight, (x, 300), (x + 60, 340), (48, 168, 240), -1)
    crowded = crop_click(tight, (500, 320))
    assert crowded.same_shape > 1 and crowded.badges == ("same_shape",)


def roundtrip(image: np.ndarray, crop: ClickCrop, scale: float, tmp: Path) -> tuple[int, int]:
    assert crop.box is not None
    x, y, w, h = crop.box
    spec_data = target_spec(
        "t.png",
        client_size=(1024, 640),
        dpi=96,
        offset=crop.offset,
        search_region=crop.search_region,
    )
    vision = Vision()
    path = tmp / "t.png"
    vision.put_image(TargetImage.of_pixels(image[y : y + h, x : x + w], path))
    click = spec_data["click"]
    assert isinstance(click, dict)
    spec = TargetSpec(
        "t",
        path,
        offset=(float(click["offset"][0]), float(click["offset"][1])),
        recorded_size=(1024, 640),
        recorded_dpi=96,
    )
    shown = image
    if scale != 1.0:
        size = (round(1024 * scale), round(640 * scale))
        shown = np.asarray(cv2.resize(image, size, interpolation=cv2.INTER_LINEAR), np.uint8)
    result = vision.find(shown, FrameMeta((shown.shape[1], shown.shape[0])), spec)
    assert result.match is not None, result.best
    return result.match.click


@pytest.mark.parametrize("scale", [1.0, 1.25])
@pytest.mark.parametrize(("scene", "point"), [("title", (470, 400)), ("login", (512, 408))])
def test_click_offset_roundtrip(scene, point, scale, tmp_path: Path) -> None:
    image = frame(scene)
    crop = crop_click(image, point)
    click = roundtrip(image, crop, scale, tmp_path)
    expected = (point[0] * scale, point[1] * scale)
    assert abs(click[0] - expected[0]) <= 2 and abs(click[1] - expected[1]) <= 2


def geometry(origin=(100, 50), client=(1024, 640), dpi=96) -> Geometry:
    fw, fh = client[0] + 2, client[1] + 31
    return Geometry((origin[0], origin[1], fw, fh), (origin[0] + 1, origin[1] + 30), client, dpi)


def test_mismatched_generation_no_crop() -> None:
    g = geometry()
    src = ScriptFrameSource(g, "title", png_scenes(FRAMES_DIR), frame_lag_ns=30 * MS)
    new = geometry(client=(800, 500))
    src.schedule_geometry(1 * S, new, notify_ns=1 * S)
    src.schedule_frame(1030 * MS)
    src.advance_to(2 * S)
    # 크기가 바뀐 직후 클릭: 앞 세대 프레임으로 자르지 않고 뒤 프레임으로 소급하지도 않는다
    got = crop_from_frame(pre_click(src.ring, src.geometry, 1010 * MS, new.to_screen((400, 300))))
    assert got == Unresolved("geometry_unresolved")
    # 같은 확정 세대면 자른다
    ok = crop_from_frame(pre_click(src.ring, src.geometry, 500 * MS, g.to_screen((512, 412))))
    assert isinstance(ok, ClickCrop) and ok.kind == "bounds" and ok.point == (512, 412)
    # 첫 프레임 전 클릭은 no_frame
    early = crop_from_frame(pre_click(src.ring, src.geometry, -1, g.to_screen((5, 5))))
    assert early == Unresolved("no_frame")
