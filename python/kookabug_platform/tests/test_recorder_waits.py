"""대기 추론 (M4 계획 2.7, 검수 M2, T6): 앞 동작 직전(A) ↔ 이 동작 직전(B) 비교 + 전이 기록.

"동작 뒤 300 ms 프레임"을 쓰지 않으므로 패널이 200 ms에 뜨고 키가 1200 ms에 와도 대기가 생기고,
바로 다음 입력(100 ms)이 와도 그 입력의 결과가 섞이지 않는다(B는 그 입력 **직전** 프레임).
"""

from __future__ import annotations

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR
from kookabug_platform.recorder.waits import changed_box, infer_wait

MS = 1_000_000
ACCOUNT = (400, 205, 320, 50)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


LOGIN = frame("login")


def with_panel(base: np.ndarray) -> np.ndarray:
    image = base.copy()
    cv2.rectangle(image, (700, 60), (980, 180), (72, 53, 43), -1)
    cv2.rectangle(image, (700, 60), (980, 180), (117, 88, 74), 3)
    cv2.putText(image, "BAG", (790, 135), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (242, 244, 248), 3)
    return image


def test_panel_appears_200ms_then_key_at_1200ms_gets_wait() -> None:
    plan = infer_wait(
        LOGIN, with_panel(LOGIN), prev_t_ns=0, t_ns=1200 * MS, last_change_ns=200 * MS,
        next_kind="key",
    )  # fmt: skip
    assert plan.decision.kind == "image_wait" and plan.decision.timeout_ms == 10_000
    assert plan.box is not None
    x, y, w, h = plan.box
    assert x >= 690 and x + w <= 990 and y >= 50 and y + h <= 190  # 패널 자리


def test_transition_800ms() -> None:
    plan = infer_wait(
        LOGIN, with_panel(LOGIN), prev_t_ns=0, t_ns=5000 * MS, last_change_ns=4000 * MS,
        next_kind="text",
    )  # fmt: skip
    assert plan.decision.kind == "image_wait" and plan.decision.timeout_ms == 12_000


def test_next_input_within_300ms_not_confused() -> None:
    # 앞 동작 100 ms 뒤 다음 입력: 그 직전 프레임은 아직 같은 화면 — 그 뒤에 생길 변화를 대기로
    # 앞당기지 않는다
    plan = infer_wait(LOGIN, LOGIN.copy(), prev_t_ns=0, t_ns=100 * MS, last_change_ns=None,
                      next_kind="key")  # fmt: skip
    assert plan.decision.kind == "none"


def test_transient_change_returning_no_wait() -> None:
    # 전이 기록에는 변화가 있었지만(툴팁이 떴다 사라짐) B는 A와 같다
    plan = infer_wait(LOGIN, LOGIN.copy(), prev_t_ns=0, t_ns=900 * MS, last_change_ns=500 * MS,
                      next_kind="key")  # fmt: skip
    assert plan.decision.kind == "none"


def test_no_change_no_wait() -> None:
    image = LOGIN.copy()
    image[10:12, 10:12] = 255  # 0.5% 이하 변화
    assert infer_wait(LOGIN, image, prev_t_ns=0, t_ns=MS, last_change_ns=None,
                      next_kind="key").decision.kind == "none"  # fmt: skip


def test_click_target_visible_before_transition_gets_region_wait() -> None:
    plan = infer_wait(
        LOGIN, with_panel(LOGIN), prev_t_ns=0, t_ns=1500 * MS, last_change_ns=300 * MS,
        next_kind="click", click_found_in=lambda image: True,
    )  # fmt: skip
    assert plan.decision.kind == "image_wait" and plan.box is not None


def test_click_target_appearing_needs_no_wait_node() -> None:
    b = with_panel(LOGIN)
    plan = infer_wait(
        LOGIN, b, prev_t_ns=0, t_ns=1500 * MS, last_change_ns=300 * MS, next_kind="click",
        click_found_in=lambda image: image is b,
    )  # fmt: skip
    assert plan.decision.kind == "none" and plan.box is None
    assert plan.decision.timeout_ms == 10_000  # image.click이 기다리는 시간


def test_unresolvable_region_falls_back_delay_needs_review() -> None:
    noise = np.full_like(LOGIN, 200)  # 화면 전체가 한 색으로 바뀜 — 평평해 기다릴 조각이 없다
    plan = infer_wait(LOGIN, noise, prev_t_ns=0, t_ns=1200 * MS, last_change_ns=900 * MS,
                      next_kind="key")  # fmt: skip
    assert plan.decision.kind == "delay" and plan.decision.ms == 1350
    assert plan.decision.needs_review == ("wait_target_unknown",)
    assert plan.box is None


def test_option_off_emits_delay() -> None:
    plan = infer_wait(
        LOGIN, with_panel(LOGIN), prev_t_ns=0, t_ns=1200 * MS, last_change_ns=200 * MS,
        next_kind="key", option_on=False,
    )  # fmt: skip
    assert plan.decision.kind == "delay" and plan.decision.ms == 1200 and plan.box is None


def test_click_into_field_then_type_no_wait() -> None:
    b = LOGIN.copy()
    x, y, w, h = ACCOUNT
    cv2.rectangle(b, (x, y), (x + w, y + h), (255, 176, 95), 2)  # 포커스 테두리만 바뀜
    assert changed_box(LOGIN, b) is not None
    plan = infer_wait(LOGIN, b, prev_t_ns=0, t_ns=900 * MS, last_change_ns=50 * MS,
                      next_kind="text", field_box=ACCOUNT)  # fmt: skip
    assert plan.decision.kind == "none"
