"""보호 영역이 모든 target 내보내기·이름에 걸린다 (M4 계획 2.6 "비밀값 보호 영역", 검수 M6, T6).

자동 클릭 자르기·넓히기·검색 범위·대기 자르기·이름용 OCR.
수동 영역 거부는 코어 `test_protect.py`."""

from __future__ import annotations

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import ProtectionSet, boxes_overlap
from kookabug_platform.recorder.crop import crop_click
from kookabug_platform.recorder.targets import name_for_box
from kookabug_platform.recorder.waits import wait_crop

MS = 1_000_000
T = 2000 * MS
PASSWORD = (400, 285, 320, 50)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


def protect(box: tuple[int, int, int, int]) -> ProtectionSet:
    p = ProtectionSet()
    p.add(1, box, 1000 * MS)
    return p


def contains(box: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    return box[0] <= point[0] < box[0] + box[2] and box[1] <= point[1] < box[1] + box[3]


def test_auto_crop_shrinks_off_secret_field() -> None:
    image = frame("title")
    secret = (380, 330, 260, 52)  # 시작 단추(380~444) 위쪽과 겹치는 칸
    plain = crop_click(image, (512, 412))
    assert plain.box is not None and boxes_overlap(plain.box, secret)
    crop = crop_click(image, (512, 412), protect=protect(secret), t_ns=T)
    assert crop.box is not None and not boxes_overlap(crop.box, secret)
    assert contains(crop.box, (512, 412)) and crop.needs_review == ()
    # 구간 시작 전 프레임이면 보호하지 않는다
    before = crop_click(image, (512, 412), protect=protect(secret), t_ns=500 * MS)
    assert before.box == plain.box


def pattern_frame() -> np.ndarray:
    image = np.full((640, 1024, 3), (40, 36, 28), np.uint8)
    for x in (100, 420, 740):
        cv2.rectangle(image, (x, 300), (x + 160, 356), (48, 168, 240), -1)
        cv2.putText(image, "OK", (x + 55, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    return image


def test_widen_never_includes_secret_field() -> None:
    image = pattern_frame()
    secret = (380, 220, 260, 60)  # 가운데 단추 바로 위
    crop = crop_click(image, (500, 328), protect=protect(secret), t_ns=T)
    assert crop.box is not None and not boxes_overlap(crop.box, secret)
    if crop.search_region is not None:
        assert not boxes_overlap(crop.search_region, secret)
    free = crop_click(image, (500, 328))
    assert free.search_region is not None and boxes_overlap(free.search_region, secret)


def test_wait_crop_excludes_secret_field() -> None:
    a = frame("login")
    b = a.copy()
    cv2.rectangle(b, (380, 270), (900, 360), (60, 90, 160), -1)  # 비밀번호 칸을 덮는 패널
    cv2.putText(b, "NOTICE", (720, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (250, 250, 250), 2)
    region = (380, 270, 521, 91)
    free = wait_crop(a, b, region)
    assert free is not None and boxes_overlap(free, PASSWORD)
    box = wait_crop(a, b, region, protect=protect(PASSWORD), t_ns=T)
    assert box is None or not boxes_overlap(box, PASSWORD)


def test_no_valid_target_marks_needs_review() -> None:
    image = frame("login")
    crop = crop_click(image, (560, 310), protect=protect(PASSWORD), t_ns=T)  # 비밀 칸에 다시 클릭
    assert crop.box is None and crop.needs_review == ("secret_overlap",)


def test_ocr_name_not_from_secret_region_and_not_containing_secret() -> None:
    image = frame("login")
    calls: list[tuple[int, int, int, int]] = []

    def read(_image: np.ndarray, box: tuple[int, int, int, int]) -> str | None:
        calls.append(box)
        return {(428, 376, 167, 63): "로그인", (0, 0, 50, 50): "hunter22"}.get(box, "x")

    p = protect(PASSWORD)
    secrets = [SecretText("hunter22")]
    kw = {"read_text": read, "protect": p, "t_ns": T, "raw_texts": secrets, "fallback": "click_4"}
    assert name_for_box(image, (428, 376, 167, 63), **kw) == "로그인"
    assert name_for_box(image, (390, 280, 100, 60), **kw) == "click_4"  # 보호 영역: OCR 안 함
    assert (390, 280, 100, 60) not in calls
    assert name_for_box(image, (0, 0, 50, 50), **kw) == "click_4"  # 원문을 품은 글자
