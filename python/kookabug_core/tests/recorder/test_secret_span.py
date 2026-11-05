"""입력 칸 구간 단위 비밀 판정 (M4 계획 2.8, 검수 H2, T7). 변환기 동작 → 판정 → 노출 규칙.

화면 근거(라벨·가림 글자·끝난 뒤 OCR)는 판정 작업이 OCR 글자로 알려 주는 것을 흉내 낸다. 실제
OCR로 예제 로그인 화면을 읽는 검사는 `kookabug_platform/tests/test_recorder_secret_classify.py`.
"""

from __future__ import annotations

import json

import pytest
from helpers.recorder_script import Script

from kookabug_core.recorder.actions import TextAction
from kookabug_core.recorder.classify import RevealNotConfirmed
from kookabug_core.recorder.secrets import RecorderTexts, TextNotAvailable

ACCOUNT = (400, 205, 320, 50)
PASSWORD = (400, 285, 320, 50)
MASK6 = "●●●●●●"


def text_actions(script: Script) -> list[TextAction]:
    return [a for a in script.run() if isinstance(a, TextAction)]


def box_for(action: TextAction) -> tuple[int, int, int, int] | None:
    if action.anchor is None:
        return None
    x, y = action.anchor
    for box in (ACCOUNT, PASSWORD):
        if box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]:
            return box
    return None


def judge(texts: RecorderTexts, action: TextAction, box: object = "auto") -> int:
    field = box_for(action) if box == "auto" else box
    texts.add_text_action(action, field)  # pyright: ignore[reportArgumentType]
    return action.span_id


def no_raw(value: object, raw: str) -> None:
    assert raw not in json.dumps(value, ensure_ascii=False)
    assert raw not in repr(value)


def test_split_password_long_pause_one_secret_span() -> None:
    s = Script()
    s.at(0).click(560, 310).type("abc").wait(3000).type("def").tap("enter")
    (action,) = text_actions(s)
    texts = RecorderTexts()
    span = judge(texts, action)
    # 앞 묶음 근거(가림 글자 3개)가 뒤까지: 구간 하나가 비밀값
    texts.classifier.mask(span, "●●●", 3)
    texts.classifier.label(span, None)
    texts.classifier.final(span, MASK6, action.text)  # 누적 길이 6
    assert texts.state(span) == "secret"
    view = texts.view(span)
    assert view == {"text_state": "secret", "text_len": 6, "secret_key": None}
    no_raw(view, "abcdef")


def test_mask_counts_cumulative_length_not_burst() -> None:
    texts = RecorderTexts()
    texts.open_span(1, PASSWORD)
    texts.classifier.mask(1, "●●●", 6)  # 3개만 보임 — 누적 6과 다름
    assert texts.classifier.get(1).secret_by == set()
    texts.classifier.mask(1, "●●●●●●", 6)
    assert texts.classifier.get(1).secret_by == {"mask"}


def test_click_then_wait_3s_then_type_label_still_applies() -> None:
    s = Script()
    s.at(0).click(560, 310).wait(3000).type("hunter22").tap("tab")
    (action,) = text_actions(s)
    texts = RecorderTexts()
    span = judge(texts, action)
    texts.classifier.label(span, "비밀번호")  # 구간 시작 직전 프레임의 라벨 — 시간 제한 없음
    assert texts.state(span) == "secret"


def test_tab_into_password() -> None:
    s = Script()
    s.at(0).click(560, 230).type("qa_tester_01").tap("tab").type("pw1234").tap("enter")
    account, password = text_actions(s)
    assert password.start_kind == "tab"
    texts = RecorderTexts()
    a = judge(texts, account)
    p = judge(texts, password, PASSWORD)  # Tab 직전·직후 프레임으로 정한 칸 상자
    texts.classifier.label(a, "계정")
    texts.classifier.final(a, "qa_tester_01", account.text)
    texts.classifier.label(p, "비밀번호")
    assert texts.state(a) == "ordinary" and texts.state(p) == "secret"
    # Tab 칸 상자를 못 정하면 확인 필요
    texts.open_span(99, None)
    texts.classifier.close(99, final=password.text)
    assert texts.state(99) == "needs_review"
    assert texts.classifier.get(99).review_reasons == ("field_box_unknown",)


def test_backspace_and_ctrl_a_retype_stays_secret() -> None:
    s = Script()
    s.at(0).click(560, 310).type("wrong").combo("ctrl", "a").type("abx").tap("backspace").type("c")
    (action,) = text_actions(s)
    assert action.clear is True
    texts = RecorderTexts()
    span = judge(texts, action)
    texts.classifier.mask(span, "●●●●●", 5)
    texts.classifier.final(span, "●●●", action.text)
    assert texts.state(span) == "secret"
    assert texts.view(span)["text_len"] == 3


def test_enter_right_after_last_char_field_vanishes() -> None:
    s = Script()
    s.at(0).click(560, 310).type("secret1").tap("enter")
    (action,) = text_actions(s)
    # 구간 중간 프레임에 가림 글자가 찍혔다 → 칸이 바로 사라져도 비밀값
    texts = RecorderTexts()
    span = judge(texts, action)
    texts.classifier.label(span, None)
    texts.classifier.mask(span, "●●●●", 4)
    texts.classifier.no_final_frame(span)
    assert texts.state(span) == "secret"
    # 근거가 하나도 없으면 일반으로 확정하지 않는다
    other = RecorderTexts()
    span = judge(other, action)
    other.classifier.label(span, None)
    other.classifier.no_final_frame(span)
    assert other.state(span) == "needs_review"
    assert other.classifier.get(span).review_reasons == ("no_evidence",)


def test_reenter_same_field_inherits_secret() -> None:
    s = Script()
    s.at(0).click(560, 310).type("abc").tap("tab").at(2000).click(560, 310).type("def")
    first, second = text_actions(s)
    texts = RecorderTexts()
    a = judge(texts, first)
    texts.classifier.label(a, "비밀번호")
    b = judge(texts, second)
    assert texts.classifier.get(b).secret_by == {"inherited"}
    assert texts.state(b) == "secret"
    # 칸이 없음으로 확정된 뒤(장면 전환) 같은 자리 칸은 상속하지 않는다
    texts.classifier.scene_changed(PASSWORD)
    texts.open_span(50, PASSWORD)
    assert texts.classifier.get(50).secret_by == set()


def test_no_evidence_is_needs_review_not_ordinary() -> None:
    s = Script()
    s.at(0).click(560, 230).type("maybe").tap("enter")
    (action,) = text_actions(s)
    texts = RecorderTexts()
    span = judge(texts, action)
    texts.classifier.label(span, "계정")
    texts.classifier.final(span, None, action.text)  # OCR이 아무것도 못 읽음
    assert texts.state(span) == "needs_review"
    assert "text" not in texts.view(span)


def test_steps_has_no_text_while_pending() -> None:
    s = Script()
    s.at(0).click(560, 230).type("qa_tester_01").tap("enter")
    (action,) = text_actions(s)
    texts = RecorderTexts()
    span = judge(texts, action)
    assert texts.state(span) == "pending"  # 라벨·끝난 뒤 OCR이 아직
    view = texts.view(span)
    assert view == {"text_state": "pending", "text_len": 12}
    no_raw(view, "qa_tester_01")
    with pytest.raises(TextNotAvailable):
        texts.graph_text(span)
    texts.classifier.label(span, "계정")
    texts.classifier.final(span, "qa_tester_01", action.text)
    assert texts.view(span)["text"] == "qa_tester_01"
    assert texts.graph_text(span) == "qa_tester_01"


def test_commit_refused_while_pending_or_review() -> None:
    texts = RecorderTexts()
    for span_id, box in ((1, ACCOUNT), (2, PASSWORD), (3, ACCOUNT)):
        texts.open_span(span_id, box)
    from kookabug_core.recorder.fields import SecretText

    for span_id, raw in ((1, "id"), (2, "pw"), (3, "x")):
        texts.put(span_id, SecretText(raw))
        texts.classifier.close(span_id, final=SecretText(raw))
    blocked = texts.commit_blocked()
    assert blocked is not None and blocked.code == "classification_pending"
    assert blocked.spans == (1, 2, 3)
    texts.classifier.label(1, "계정")
    texts.classifier.final(1, "id", SecretText("id"))
    texts.classifier.label(2, "비밀번호")
    texts.classifier.label(3, None)
    texts.classifier.no_final_frame(3)
    blocked = texts.commit_blocked()
    assert blocked is not None and blocked.code == "text_review_required" and blocked.spans == (3,)
    assert texts.commit_blocked([1, 2]) == texts.commit_blocked([2, 1])
    blocked = texts.commit_blocked([1, 2])
    assert blocked is not None and blocked.code == "secret_unresolved" and blocked.spans == (2,)
    texts.set_secret_key(2, "accounts.qa_password")
    assert texts.commit_blocked([1, 2]) is None
    assert texts.graph_text(2) == {"$secret": "accounts.qa_password"}


def test_reveal_requires_confirm() -> None:
    texts = RecorderTexts()
    from kookabug_core.recorder.fields import SecretText

    texts.open_span(1, PASSWORD)
    texts.put(1, SecretText("not-a-secret"))
    texts.classifier.close(1, final=SecretText("not-a-secret"))
    texts.classifier.label(1, "비밀번호")
    assert texts.state(1) == "secret"
    with pytest.raises(RevealNotConfirmed):
        texts.confirm_ordinary(1, confirm_reveal=False)
    assert texts.state(1) == "secret" and "text" not in texts.view(1)
    texts.confirm_ordinary(1, confirm_reveal=True)
    view = texts.view(1)
    assert view == {
        "text_state": "ordinary",
        "text_len": 12,
        "text": "not-a-secret",
        "reveal_confirmed": True,
    }
    # 사람이 다시 비밀값으로
    texts.mark_secret(1)
    assert texts.state(1) == "secret" and "text" not in texts.view(1)


def test_manual_mark_hotkey_marks_span() -> None:
    s = Script()
    s.at(0).click(560, 230).type("abc").combo("ctrl", "shift", "p").type("d").tap("enter")
    (action,) = text_actions(s)
    assert action.marked_secret
    texts = RecorderTexts()
    span = judge(texts, action)
    assert texts.state(span) == "secret"
    assert texts.classifier.get(span).secret_by == {"marked"}


def test_win32_password_hint_is_secret_from_first_key() -> None:
    s = Script()
    s.at(0).click(560, 310)
    s.type("pw")
    for event_id, obs in s.obs.items():
        if any(e["event_id"] == event_id and e["kind"] == "key_down" for e in s.events):
            obs["focus_password"] = True
    s.tap("enter")
    (action,) = text_actions(s)
    assert action.password_hint is True
    texts = RecorderTexts()
    span = judge(texts, action)
    assert texts.classifier.get(span).secret_by == {"win32"}
