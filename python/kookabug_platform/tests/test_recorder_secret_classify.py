"""비밀번호 칸 판정의 화면 근거 (M4 계획 2.8, C6, T7): 예제 로그인 화면을 실제 OCR로 읽는다.

라벨("비밀번호")·가림 글자(●)·일반 긍정 근거(친 글자가 칸에 보임)·Tab으로 옮겨 간 포커스 테두리.
가림 글자 그림은 원(●)을 게임 글자 크기·간격(반지름 7, 18 px)으로 그린다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.recorder.classify import SpanClassifier
from kookabug_core.recorder.fields import SecretText
from kookabug_platform.ocr import models as m
from kookabug_platform.ocr.engine import RapidOcrEngine
from kookabug_platform.recorder.evidence import (
    ReadText,
    field_text,
    label_text,
    ocr_reader,
    tab_field_box,
)

ACCOUNT = (400, 205, 320, 50)
PASSWORD = (400, 285, 320, 50)
FOCUS = (255, 176, 95)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


LOGIN = frame("login")


@pytest.fixture(scope="module")
def read(ocr_models: Path) -> Iterator[ReadText]:
    engine = RapidOcrEngine(m.find_models(dirs=[ocr_models]))
    engine.load()
    yield ocr_reader(engine)


def masked(count: int) -> np.ndarray:
    image = LOGIN.copy()
    for i in range(count):
        cv2.circle(image, (420 + i * 18, 310), 7, (248, 244, 242), -1, cv2.LINE_AA)
    return image


def test_sample_login_password_by_label(read: ReadText) -> None:
    c = SpanClassifier()
    c.open(1, PASSWORD)
    c.open(2, ACCOUNT)
    c.label(1, label_text(read, LOGIN, PASSWORD))
    c.label(2, label_text(read, LOGIN, ACCOUNT))
    assert c.get(1).secret_by == {"label"}
    assert c.get(2).secret_by == set()


def test_sample_login_password_by_mask(read: ReadText) -> None:
    c = SpanClassifier()
    c.open(1, None)  # 칸 상자를 몰라도 가림 글자는 근거다 (OCR은 클릭 상자로)
    c.mask(1, field_text(read, masked(9), PASSWORD), 9)
    assert c.get(1).secret_by == {"mask"}
    # 친 글자 수와 많이 다르면 근거가 아니다
    other = SpanClassifier()
    other.open(1, None)
    other.mask(1, field_text(read, masked(9), PASSWORD), 3)
    assert other.get(1).secret_by == set()


def test_account_field_ordinary_only_with_positive_ocr(read: ReadText) -> None:
    typed = LOGIN.copy()
    cv2.putText(
        typed, "qa_tester_01", (414, 238), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (248, 244, 242), 2
    )
    final = SecretText("qa_tester_01")
    c = SpanClassifier()
    c.open(1, ACCOUNT)
    c.close(1, final=final)
    c.label(1, label_text(read, LOGIN, ACCOUNT))
    assert c.state(1) == "pending"
    c.final(1, field_text(read, typed, ACCOUNT), final)
    assert c.state(1) == "ordinary"
    # 칸에 아무것도 안 보이면(바로 사라짐 등) 일반으로 확정하지 않는다
    empty = SpanClassifier()
    empty.open(1, ACCOUNT)
    empty.close(1, final=final)
    empty.label(1, label_text(read, LOGIN, ACCOUNT))
    empty.final(1, field_text(read, LOGIN, ACCOUNT), final)
    assert empty.state(1) == "needs_review"


def test_tab_into_password_field_box_from_focus_change() -> None:
    before = LOGIN.copy()
    x, y, w, h = ACCOUNT
    cv2.rectangle(before, (x, y), (x + w, y + h), FOCUS, 2)
    after = LOGIN.copy()
    x, y, w, h = PASSWORD
    cv2.rectangle(after, (x, y), (x + w, y + h), FOCUS, 2)
    box = tab_field_box(before, after)
    assert box is not None
    assert abs(box[0] - PASSWORD[0]) <= 2 and abs(box[1] - PASSWORD[1]) <= 2
    assert abs(box[2] - PASSWORD[2]) <= 4 and abs(box[3] - PASSWORD[3]) <= 4
    # 포커스 테두리가 옮겨 가지 않았으면(같은 그림) 못 정한다 → field_box_unknown
    assert tab_field_box(before, before) is None
