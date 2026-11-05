"""글자 원문은 `SecretText` 안에만 (M4 계획 2.8, T5 — 엄격 항목: 비밀값 유출)."""

from __future__ import annotations

import copy
import json
import logging
import pickle

import pytest
from helpers.recorder_script import Script

from kookabug_core.recorder.actions import TextAction
from kookabug_core.recorder.fields import SecretText

PASSWORD = "sample-pass-01"


def test_secret_text_never_in_repr_or_json(caplog: pytest.LogCaptureFixture) -> None:
    s = Script()
    s.at(0).click(500, 300).type(PASSWORD)
    conv = s.converter()
    actions = conv.finish()
    (text,) = [a for a in actions if isinstance(a, TextAction)]
    assert text.text.reveal() == PASSWORD  # 원문은 reveal로만
    dumps = [
        repr(actions),
        str(actions),
        repr(text),
        f"{text}",
        f"{text.text}",
        "%s %r" % (text, text.text),  # noqa: UP031
        json.dumps([a.to_json() for a in actions]),
        repr(conv.__dict__),
        repr(conv._items),  # pyright: ignore[reportPrivateUsage]
    ]
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("kb.test").info("step %s / %r", text, text.text)
    dumps.append(caplog.text)
    for dump in dumps:
        assert PASSWORD not in dump
        assert "sample-" not in dump and "pass-01" not in dump
    assert text.to_json()["text_len"] == len(PASSWORD) and "text" not in text.to_json()


def test_open_span_and_pending_keys_do_not_leak_in_repr() -> None:
    s = Script()
    s.at(0).click(500, 300).type(PASSWORD)
    conv = s.converter()  # 아직 닫지 않음
    assert PASSWORD not in repr(conv.__dict__)
    assert "_Stroke(…)" in repr(conv._span._strokes) if conv._span else True  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]


def test_secret_text_not_picklable_copyable_and_wipes() -> None:
    secret = SecretText("abc")
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(TypeError):
        copy.copy(secret)
    with pytest.raises(TypeError):
        json.dumps(secret)
    secret.wipe()
    assert len(secret) == 0 and secret.reveal() == ""


def test_converter_wipe_clears_texts() -> None:
    s = Script()
    s.at(0).click(500, 300).type("abc")
    conv = s.converter()
    (text,) = [a for a in conv.finish() if isinstance(a, TextAction)]
    conv.wipe()
    assert text.text.reveal() == "" and conv.actions() == []
