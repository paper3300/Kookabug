"""녹화는 비밀값 칸을 가리지 않는다 (UX11 B, 2026-11-16 사용자 결정 — 로컬 툴).

자동 클릭 자르기·넓히기·검색 범위·대기 자르기·이름용 OCR이 비밀번호 칸과 겹쳐도 그대로 쓰고, 칸
픽셀을 바꾸지 않는다. 비밀번호 입력을 `$secret` 참조로 바꾸는 분류는 그대로다
(`kookabug_core/tests/recorder`·`test_recorder_secret_classify.py`)."""

from __future__ import annotations

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.recorder.protect import boxes_overlap
from kookabug_platform.recorder.crop import crop_click
from kookabug_platform.recorder.targets import name_for_box
from kookabug_platform.recorder.waits import wait_crop

PASSWORD = (400, 285, 320, 50)
"""예제 로그인 화면의 비밀번호 칸."""


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


def contains(box: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    return box[0] <= point[0] < box[0] + box[2] and box[1] <= point[1] < box[1] + box[3]


def test_click_on_secret_field_crops_it_unmasked() -> None:
    image = frame("login")
    # 비밀번호 칸에 글자를 그려 둔다 (칸에 값이 보이는 프레임)
    cv2.putText(image, "hunter22", (420, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2)
    before = image.copy()
    crop = crop_click(image, (560, 310))
    assert crop.box is not None and crop.needs_review == ()
    assert contains(crop.box, (560, 310)) and boxes_overlap(crop.box, PASSWORD)
    # 자른 그림은 원본 그대로 (칸을 가리지 않고, 원본 프레임도 바꾸지 않는다)
    assert np.array_equal(image, before)


def test_wait_crop_may_cover_secret_field() -> None:
    a = frame("login")
    b = a.copy()
    cv2.rectangle(b, (380, 270), (900, 360), (60, 90, 160), -1)  # 비밀번호 칸을 덮는 패널
    cv2.putText(b, "NOTICE", (720, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (250, 250, 250), 2)
    box = wait_crop(a, b, (380, 270, 521, 91))
    assert box is not None and boxes_overlap(box, PASSWORD)


def test_ocr_name_reads_secret_region_as_is() -> None:
    image = frame("login")
    calls: list[tuple[int, int, int, int]] = []

    def read(_image: np.ndarray, box: tuple[int, int, int, int]) -> str | None:
        calls.append(box)
        return {(428, 376, 167, 63): "로그인", (390, 280, 100, 60): "hunter22"}.get(box)

    assert name_for_box(image, (428, 376, 167, 63), read_text=read, fallback="click_4") == "로그인"
    # 비밀번호 칸도 읽고, 읽은 글자를 그대로 이름으로 쓴다
    name = name_for_box(image, (390, 280, 100, 60), read_text=read, fallback="click_4")
    assert name == "hunter22" and (390, 280, 100, 60) in calls
    assert name_for_box(image, (0, 0, 50, 50), read_text=read, fallback="click_4") == "click_4"
    assert name_for_box(image, (0, 0, 50, 50), read_text=None, fallback="click_4") == "click_4"
