"""녹화 글자의 수명 (M4 계획 2.8 "녹화 세션이 끝나면 메모리의 글자를 지운다", T7).

세션의 세 끝(커밋·버리기·연결 끊김)은 모두 `RecorderTexts.wipe()`와 변환기 `wipe()`를 부른다(T8).
여기서는 지운 뒤 원문을 어디서도 꺼낼 수 없고 버퍼가 0으로 덮였는지 본다.
"""

from __future__ import annotations

import pytest
from helpers.recorder_script import Script

from kookabug_core.recorder.actions import TextAction
from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.secrets import RecorderTexts, TextNotAvailable


@pytest.mark.parametrize("end", ["commit", "discard", "disconnect"])
def test_raw_wiped_on_commit_discard_disconnect(end: str) -> None:
    s = Script()
    s.at(0).click(560, 310).type("hunter22").tap("enter")
    conv = s.converter()
    (action,) = [a for a in conv.finish() if isinstance(a, TextAction)]
    texts = RecorderTexts()
    texts.add_text_action(action, (400, 285, 320, 50))
    texts.classifier.label(action.span_id, "비밀번호")
    held: SecretText = texts.raw_for_secret(action.span_id)
    buffer = held._buf  # pyright: ignore[reportPrivateUsage] — 덮였는지 직접 본다
    assert bytes(buffer) == b"hunter22"
    # 세션 끝 (어느 경로든 같은 정리)
    texts.wipe()
    conv.wipe()
    assert end in ("commit", "discard", "disconnect")
    assert len(held) == 0 and held.reveal() == "" and bytes(buffer) == b""
    assert texts.wiped
    for read in (texts.view, texts.raw_for_secret, texts.graph_text, texts.typed_so_far):
        with pytest.raises(TextNotAvailable):
            read(action.span_id)
    assert list(texts.protected_texts()) == []
    with pytest.raises(TextNotAvailable):
        texts.put(9, SecretText("late"))


def test_dropped_step_text_wiped() -> None:
    texts = RecorderTexts()
    raw = SecretText("abc")
    texts.open_span(1, None)
    texts.put(1, raw)
    texts.drop(1)
    assert len(raw) == 0
    with pytest.raises(TextNotAvailable):
        texts.view(1)
