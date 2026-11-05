"""칸이 그대로 있는가 (M4 계획 2.6, 2차 N4, T6·T7).

예제 `render.py`와 같은 칸 그림(로그인 화면) 위에 값·가림 글자·포커스 테두리·커서를 그려 음성 대조,
로비로 장면이 바뀌는 양성 대조."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from helpers.recorder_script import Script

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.recorder.actions import TextAction
from kookabug_core.recorder.protect import ProtectionSet, SecretRegionOverlap
from kookabug_platform.recorder.crop import crop_click
from kookabug_platform.recorder.presence import FieldPresenceTracker, field_present, scene_changed
from kookabug_platform.recorder.targets import name_for_box

MS = 1_000_000
PASSWORD = (400, 285, 320, 50)
FOCUS = (255, 176, 95)  # render.py FOCUS #5fb0ff (BGR)
TEXT = (248, 244, 242)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


LOGIN = frame("login")
LOBBY = frame("lobby")


def field_state(dots: int, *, focus: bool = True, cursor: bool = False) -> np.ndarray:
    image = LOGIN.copy()
    x, y, w, h = PASSWORD
    if focus:
        cv2.rectangle(image, (x, y), (x + w, y + h), FOCUS, 2)
    for i in range(dots):
        cv2.circle(image, (x + 20 + i * 14, y + h // 2), 5, TEXT, -1, cv2.LINE_AA)
    if cursor:
        cx = x + 20 + dots * 14
        cv2.line(image, (cx, y + 12), (cx, y + h - 12), TEXT, 2)
    return image


def test_value_and_mask_change_keeps_field_and_protection() -> None:
    for dots in (1, 6, 20):
        image = field_state(dots)
        assert field_present(LOGIN, image, PASSWORD) and not scene_changed(LOGIN, image, PASSWORD)


def test_focus_border_change_keeps_field() -> None:
    image = field_state(0, focus=True)
    assert field_present(LOGIN, image, PASSWORD)


def test_cursor_blink_keeps_field() -> None:
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    for i in range(10):
        tracker.observe((i + 1) * 100 * MS, field_state(3, cursor=i % 2 == 0))
    assert tracker.gone_at(1) is None


def test_partial_occlusion_keeps_protection() -> None:
    image = field_state(4)
    cv2.rectangle(image, (640, 250), (900, 360), (72, 53, 43), -1)  # 둘레 오른쪽을 가린 작은 팝업
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    for t in (100, 300, 500):
        tracker.observe(t * MS, image)
    assert tracker.gone_at(1) is None


def test_uncertain_geometry_keeps_protection() -> None:
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    tracker.observe(100 * MS, LOBBY)
    tracker.observe(200 * MS, None)  # 검증 안 된 프레임 (기하 불확실): 확정을 끊는다
    tracker.observe(300 * MS, LOBBY)
    assert tracker.gone_at(1) is None
    tracker.observe(460 * MS, LOBBY)
    assert tracker.gone_at(1) == 300 * MS


def test_scene_change_login_to_lobby_ends_field_and_protection() -> None:
    assert not field_present(LOGIN, LOBBY, PASSWORD) and scene_changed(LOGIN, LOBBY, PASSWORD)
    tracker = FieldPresenceTracker()
    protect = ProtectionSet()
    tracker.register(1, PASSWORD, LOGIN, 0)
    protect.add(1, PASSWORD, 0)
    tracker.observe(1000 * MS, LOBBY)
    gone = tracker.observe(1200 * MS, LOBBY)
    assert gone == [1] and tracker.gone_at(1) == 1000 * MS
    protect.end(1, 1000 * MS)
    assert protect.overlaps(PASSWORD, 1200 * MS, LOBBY)  # 판정기 없으면 끝나도 보호
    protect.absent_in = tracker.absent_in
    assert not protect.overlaps(PASSWORD, 1200 * MS, LOBBY)  # 로비 화면: 칸 없음
    assert protect.overlaps(PASSWORD, 1200 * MS, field_state(3))  # 칸이 다시 보이는 프레임
    assert protect.overlaps(PASSWORD, 1200 * MS, None)  # 프레임 모름


def test_lobby_button_at_same_place_can_be_cropped_after_scene_change() -> None:
    # 양성 대조: 로그인 → 로비. 비밀번호 칸이 있던 자리의 로비 단추(Server 2)는 target이 된다
    tracker, protect = linked(LOGIN)
    tracker.observe(1000 * MS, LOBBY)
    for span in tracker.observe(1200 * MS, LOBBY):
        protect.end(span, tracker.gone_at(span) or 0)
    crop = crop_click(LOBBY, (560, 310), protect=protect, t_ns=1300 * MS)
    assert crop.box is not None and crop.needs_review == ()
    # 같은 보호에서 칸이 다시 보이는 프레임이면 막힌다
    blocked = crop_click(plaintext_field(), (560, 310), protect=protect, t_ns=1400 * MS)
    assert blocked.box is None and blocked.needs_review == ("secret_overlap",)


def linked(reference: np.ndarray) -> tuple[FieldPresenceTracker, ProtectionSet]:
    """세션 연결과 같게: 칸 존재 판정기를 보호 영역의 프레임 판정에 쓴다."""
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, reference, 0)
    protect = ProtectionSet(absent_in=tracker.absent_in)
    protect.add(1, PASSWORD, 0)
    return tracker, protect


def test_absence_needs_two_frames_and_150ms() -> None:
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    assert tracker.observe(100 * MS, LOBBY) == []  # 한 장
    assert tracker.observe(200 * MS, LOBBY) == []  # 두 장이지만 100 ms
    assert tracker.observe(260 * MS, LOBBY) == [1]  # 160 ms
    other = FieldPresenceTracker()
    other.register(1, PASSWORD, LOGIN, 0)
    other.observe(100 * MS, LOBBY)
    other.observe(200 * MS, field_state(2))  # 칸이 다시 보임: 처음부터
    other.observe(300 * MS, LOBBY)
    assert other.observe(400 * MS, LOBBY) == []


def plaintext_field() -> np.ndarray:
    """가려지지 않는 칸에 원문이 보이는 기준 프레임 (review_B2_1 H1 반례)."""
    image = LOGIN.copy()
    cv2.putText(image, "review-pass-42", (410, 318), cv2.FONT_HERSHEY_SIMPLEX, 0.65, TEXT, 2)
    return image


def popup(image: np.ndarray, rect: tuple[int, int, int, int], color=(50, 60, 70)) -> np.ndarray:
    out = image.copy()
    x0, y0, x1, y1 = rect
    cv2.rectangle(out, (x0, y0), (x1, y1), color, -1)
    cv2.putText(
        out, "NOTICE", (x0 + 10, y0 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2
    )
    return out


@pytest.mark.parametrize(
    "rect",
    [
        (50, 100, 390, 540),  # review_B2_1: 라벨·왼쪽 둘레를 가림
        (0, 0, 395, 640),
        (0, 150, 395, 500),
        (50, 150, 395, 400),
        (725, 220, 1000, 400),  # review_B2_2: 오른쪽 둘레
        (350, 340, 800, 580),  # review_B2_2: 아래 둘레
    ],
)
def test_partial_popup_keeps_protection_and_blocks_target(rect) -> None:
    # 칸과 겹치지 않는 팝업이 근거 일부만 가림: 칸 픽셀은 그대로 → 없음으로 확정하지 않고,
    # 끝난 보호로 쳐도 그 프레임은 일부 가림이라 보호한다
    reference = plaintext_field()
    shown = popup(reference, rect)
    assert np.array_equal(reference[285:335, 400:720], shown[285:335, 400:720])
    tracker, protect = linked(reference)
    for t in (100, 300, 500, 2000):
        assert tracker.observe(t * MS, shown) == []
    assert tracker.gone_at(1) is None
    crop = crop_click(shown, (560, 310), protect=protect, t_ns=2000 * MS)
    assert crop.box is None and crop.needs_review == ("secret_overlap",)
    protect.end(1, 100 * MS)  # 끝났다고 해도 프레임 기준
    crop = crop_click(shown, (560, 310), protect=protect, t_ns=2000 * MS)
    assert crop.box is None and crop.needs_review == ("secret_overlap",)


@pytest.mark.parametrize(
    "notice",
    [
        None,  # 값만 바뀐 칸이 다시 보임
        (50, 150, 390, 400),  # review_B2_2: 왼쪽 알림이 남음
        (230, 260, 390, 340),  # review_B2_2: 작은 라벨 알림이 남음
    ],
)
def test_field_back_after_absence_blocks_target(notice) -> None:
    # 큰 대화상자가 칸을 덮어 없음으로 확정·보호 끝 → 대화상자가 닫히고 원문이 남은 칸이 다시 보임
    # (일부 가림 동반) → 그 프레임에서 칸이 없다는 근거가 없으니 target·수동 영역·이름 OCR 차단
    tracker, protect = linked(LOGIN)
    typed = plaintext_field()
    dialog = popup(typed, (50, 150, 800, 500), (85, 75, 65))
    tracker.observe(100 * MS, typed)
    tracker.observe(500 * MS, dialog)
    gone = tracker.observe(800 * MS, dialog)
    assert gone == [1], "불투명 대화상자가 없음으로 확정되는 사전 조건"
    protect.end(1, tracker.gone_at(1) or 0)
    assert not protect.overlaps(PASSWORD, 800 * MS, dialog)  # 덮인 프레임은 칸이 없음
    back = typed if notice is None else popup(typed, notice)
    crop = crop_click(back, (560, 310), protect=protect, t_ns=1100 * MS)
    assert crop.box is None and crop.needs_review == ("secret_overlap",)
    with pytest.raises(SecretRegionOverlap):
        protect.require_clear(PASSWORD, 1100 * MS, back)
    calls: list[object] = []
    name = name_for_box(
        back,
        (397, 282, 325, 55),
        read_text=lambda *a: calls.append(a) or "review-pass-42",
        protect=protect,
        t_ns=1100 * MS,
        raw_texts=[],
        fallback="click_1",
    )
    assert name == "click_1" and calls == []  # 보호 칸과 겹쳐 OCR하지 않음


def text_actions(script: Script, tracker: FieldPresenceTracker) -> list[TextAction]:
    return [a for a in script.run(presence=tracker) if isinstance(a, TextAction)]


def test_long_password_span_not_split_by_field_pixel_changes() -> None:
    s = Script()
    s.at(0).click(560, 310)
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    typed = "abcdefghij0123456789"
    for i, ch in enumerate(typed):
        s.type(ch)
        tracker.observe(s.t, field_state(i + 1, cursor=i % 2 == 0))
        if i in (4, 12):
            s.wait(2500)  # 쉬며 친다
            tracker.observe(s.t, field_state(i + 1, cursor=False))
    s.tap("enter")
    (action,) = text_actions(s, tracker)
    assert action.text.reveal() == typed and action.span_id == 1
    assert tracker.gone_at(1) is None  # 보호도 유지


def test_span_ends_only_on_confirmed_scene_change() -> None:
    tracker = FieldPresenceTracker()
    tracker.register(1, PASSWORD, LOGIN, 0)
    s = Script()
    s.at(0).click(560, 310).type("abc")
    tracker.observe(s.t + 10 * MS, LOBBY)  # 한 장만 바뀜 — 확정 아님
    tracker.observe(s.t + 50 * MS, field_state(3))
    s.wait(300).type("def")
    tracker.observe(s.t + 10 * MS, LOBBY)
    tracker.observe(s.t + 200 * MS, LOBBY)  # 두 장·150 ms 넘음 → 칸 없음 확정
    s.wait(400).type("xyz")
    first, second = text_actions(s, tracker)
    assert first.text.reveal() == "abcdef" and first.span_id == 1
    assert second.text.reveal() == "xyz" and not second.in_field  # 칸 밖 글자 묶음
