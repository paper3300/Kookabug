"""값 인코딩 (runner ↔ 워커 경계)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk.codec import (
    TAG,
    CodecError,
    decode,
    decode_message,
    encode,
    encode_message,
)
from kookabug_sdk.types import (
    FrameRef,
    Image,
    Match,
    OcrLine,
    OcrResult,
    Point,
    ProcessRef,
    Rect,
    Secret,
    SecretMessage,
    Target,
    WindowInfo,
    WindowRef,
    message_with_secrets,
)

BOUND = WindowRef(0x1234, "게임", pid=4321, process_created="133700000000000000", binding="b3")
FRAME_REF = FrameRef("wgc", (1280, 720), 144, capture_id=17, observed_at=1761800000.25)
FULL_MATCH = Match(
    Rect(10, 20, 30, 40),
    0.91,
    BOUND,
    frame=5,
    scale=1.05,
    method="template_multiscale",
    frame_info=FRAME_REF,
    target="targets/title/start.target.json",
    click=Point(25, 40),
)

SAMPLES: dict[str, Any] = {
    "secret": Secret("pw-원문"),
    "rect": Rect(1, 2, 30, 40),
    "point": Point(-3, 4),
    "window": WindowRef(0x1234, "게임"),
    "process": ProcessRef(77, "game.exe"),
    "image_path": Image(640, 480, path=Path("frames/a.png"), frame=3, capture_id=9),
    "image_data": Image(2, 1, data=b"\x00\xff\x10"),
    "image_empty": Image(),
    "match": Match(Rect(0, 0, 5, 5), 0.75, WindowRef(1, "w"), frame=2),
    "match_bare": Match(Rect(0, 0, 1, 1), 1.0),
    "target": Target("start", Path("targets/start.target.json"), {"image": "a.png", "n": [1]}),
    "nested": {"list": [Rect(0, 0, 1, 1), {"s": Secret("x")}], "n": None, "f": 1.5, "b": True},
    "window_bound": BOUND,
    "match_full": FULL_MATCH,
    "window_info": WindowInfo(
        BOUND, "게임", "game.exe", "GameWnd", (1280, 720), (-1920, 40), 144, fullscreen=True
    ),
    "ocr_result": OcrResult(
        "Gold 12,345\n인벤토리",
        (
            OcrLine("Gold 12,345", Rect(5, 6, 70, 20), 0.97),
            OcrLine("인벤토리", Rect(5, 30, 60, 20), 0.9),
        ),
        0.935,
    ),
    "ocr_empty": OcrResult(""),
    "ocr_secret": OcrResult(Secret("pw"), (OcrLine(Secret("pw"), Rect(0, 0, 9, 9), 0.8),), 0.8),
}


def wire(value: Any) -> Any:
    """인코딩 → JSON 텍스트 → 디코딩 (파이프를 지나는 것과 같다)."""
    return decode(json.loads(json.dumps(encode(value))))


@pytest.mark.parametrize("name", SAMPLES)
def test_roundtrip_each_sdk_type(name: str) -> None:
    value = SAMPLES[name]
    back = wire(value)
    assert back == value
    assert type(back) is type(value)
    if isinstance(value, Image):
        # capture_id는 값 비교에 들지 않으므로 따로 본다 (기록 정책이 이것으로 캡처를 찾는다)
        assert back.capture_id == value.capture_id
        assert back.data == value.data


def test_tuple_becomes_list_and_json_values_unchanged() -> None:
    assert encode((1, "a", [None])) == [1, "a", [None]]
    plain = {"a": [1, 2.5, None, True, "한글"], "b": {}}
    assert encode(plain) == plain
    assert decode(plain) == plain


def test_secret_stays_secret_masked_in_repr() -> None:
    encoded = encode({"pw": Secret("pw-원문"), "items": [Secret("둘째")]})
    # 로그로 찍혀도 가린 값만
    assert "pw-원문" not in repr(encoded) and "pw-원문" not in str(encoded)
    assert "둘째" not in repr(encoded)
    # 파이프로는 원문이 간다 (워커가 노드에 Secret을 줘야 한다)
    assert "pw-원문" in json.dumps(encoded, ensure_ascii=False)
    back = decode(json.loads(json.dumps(encoded)))
    assert isinstance(back["pw"], Secret) and back["pw"].reveal() == "pw-원문"
    assert repr(back["pw"]) == "Secret('***')"
    assert isinstance(back["items"][0], Secret)


def test_secret_message_keeps_both_texts_masked_in_repr() -> None:
    # P1 검수 A2-1: 비밀값 메시지는 가린 글·원문을 둘 다 경계 너머로 (runner가 정책으로 고른다)
    message = message_with_secrets(lambda show: f"read={show(Secret('원문-값'))}")
    assert isinstance(message, SecretMessage)
    encoded = encode_message(message)
    assert "원문-값" not in repr(encoded) and "원문-값" not in str(encoded)
    assert "원문-값" in json.dumps(encoded, ensure_ascii=False)
    back = decode_message(json.loads(json.dumps(encoded)))
    assert back == SecretMessage("read=***", "read=원문-값")
    with pytest.raises(CodecError):
        decode_message({TAG: "secret_message", "masked": "x"})
    # 메시지 필드의 다른 모양: 없음·문자열·비밀값
    assert decode_message(encode_message(None)) is None
    assert decode_message(encode_message("평문")) == "평문"
    assert decode_message(encode_message(Secret("s"))) == Secret("s")
    with pytest.raises(CodecError):
        decode_message({"a": 1})


@pytest.mark.parametrize(
    "value",
    [
        SecretMessage("read=***", "read=원문"),
        {"details": {"message": SecretMessage("read=***", "read=원문")}},
        [SecretMessage("a", "b")],
    ],
    ids=["top", "nested", "list"],
)
def test_secret_message_rejected_as_value(value: Any) -> None:
    # P1 검수 A3-1: 메시지 필드 전용 — 노드 출력·변수 같은 값으로는 경계를 넘지 못한다
    with pytest.raises(CodecError, match="SecretMessage"):
        encode(value)
    with pytest.raises(CodecError):
        decode({"details": {TAG: "secret_message", "masked": "a", "raw": "b"}})


def test_user_dict_with_kb_key_escaped() -> None:
    user = {TAG: "secret", "value": "x"}
    encoded = encode(user)
    assert encoded == {TAG: "dict", "value": {TAG: "secret", "value": "x"}}
    back = wire(user)
    assert back == user and not isinstance(back, Secret)
    nested = {"outer": {TAG: 1, "inner": {TAG: "rect"}}}
    assert wire(nested) == nested


@pytest.mark.parametrize(
    "data",
    [
        {TAG: "nope"},
        {TAG: 3},
        {TAG: "rect", "x": 1, "y": 2, "width": 3},
        {TAG: "rect", "x": 1, "y": 2, "width": 3, "height": 4, "extra": 0},
        {TAG: "rect", "x": "1", "y": 2, "width": 3, "height": 4},
        {TAG: "secret", "value": 1},
        {TAG: "dict", "value": [1]},
        {
            TAG: "image",
            "width": 1,
            "height": 1,
            "path": None,
            "frame": None,
            "data": "%%%",
            "capture_id": None,
        },
        {TAG: "match", "rect": {"x": 0}, "score": 1, "window": None, "frame": None},
        # M0b 모양의 창·매칭 (새 필드 없음)
        {TAG: "window", "handle": 1, "title": "w"},
        {
            TAG: "match",
            "rect": {TAG: "rect", "x": 0, "y": 0, "width": 1, "height": 1},
            "score": 1,
            "window": None,
            "frame": None,
        },
        {**encode(FULL_MATCH), "frame_info": {"backend": "wgc"}},
        {**encode(FULL_MATCH), "click": {"x": 1, "y": 2}},
        {**encode(FULL_MATCH), "scale": True},
        {TAG: "ocr_result", "text": "a", "lines": [{"text": "a"}], "confidence": None},
        {TAG: "ocr_result", "text": 3, "lines": [], "confidence": None},
        {**encode(SAMPLES["window_info"]), "client_size": [1, 2, 3]},
        {**encode(SAMPLES["window_info"]), "minimized": 0},
    ],
)
def test_unknown_tag_rejected(data: dict[str, Any]) -> None:
    with pytest.raises(CodecError):
        decode(data)
    with pytest.raises(CodecError):
        decode({"wrapped": [data]})


@pytest.mark.parametrize("value", [object(), {1: "x"}, b"bytes", {1, 2}])
def test_unsupported_value_rejected(value: Any) -> None:
    with pytest.raises(CodecError):
        encode(value)


def test_window_ref_new_fields_roundtrip() -> None:
    encoded = encode(BOUND)
    assert encoded == {
        TAG: "window",
        "handle": 0x1234,
        "title": "게임",
        "pid": 4321,
        "process_created": "133700000000000000",
        "binding": "b3",
    }
    back = wire(BOUND)
    assert (back.pid, back.process_created, back.binding) == (4321, "133700000000000000", "b3")
    # 바인딩이 다르면 다른 창이다 (같은 HWND 값을 다시 쓴 창)
    assert back != WindowRef(0x1234, "게임", pid=4321, process_created="133700000000000000")
    # 바인딩 없는 값(다른 실행·플러그인이 만든 것)도 오간다
    assert wire(WindowRef(7)) == WindowRef(7, "", 0, "", "")


def test_match_frame_info_roundtrip_and_excluded_from_eq() -> None:
    back = wire(FULL_MATCH)
    assert back == FULL_MATCH
    assert back.frame_info == FRAME_REF  # 값 비교에 들지 않으므로 따로 본다
    assert (back.scale, back.method, back.target) == (
        1.05,
        "template_multiscale",
        "targets/title/start.target.json",
    )
    assert back.click_point == Point(25, 40)
    # frame_info만 다른 두 매칭은 같은 값이다 (다시 캡처한 같은 결과)
    recaptured = dataclasses.replace(FULL_MATCH, frame_info=FrameRef("wgc", (1280, 720), 144, 99))
    assert recaptured == FULL_MATCH
    assert dataclasses.replace(FULL_MATCH, frame_info=None) == FULL_MATCH
    assert wire(Match(Rect(0, 0, 4, 6), 1.0)).frame_info is None
    # click이 없으면 클릭 지점은 rect 중심
    assert Match(Rect(0, 0, 4, 6), 1.0).click_point == Point(2, 3)
    # 그 밖의 새 필드는 값 비교에 든다
    assert Match(Rect(0, 0, 4, 6), 1.0, scale=2.0) != Match(Rect(0, 0, 4, 6), 1.0)


def test_reference_image_without_data() -> None:
    # 실제 캡처는 픽셀 없는 참조 이미지: 크기·frame·capture_id만 경계를 넘는다
    ref = Image(1920, 1080, frame=42, capture_id=7)
    encoded = encode(ref)
    assert encoded["data"] is None and encoded["path"] is None
    assert len(json.dumps(encoded)) < 200
    back = wire(ref)
    assert back == ref and back.capture_id == 7 and back.data is None and back.path is None


def test_ocr_result_secret_text_stays_secret() -> None:
    encoded = encode(SAMPLES["ocr_secret"])
    assert "pw" not in repr(encoded)
    back = wire(SAMPLES["ocr_secret"])
    assert isinstance(back.text, Secret) and isinstance(back.lines[0].text, Secret)
    assert back.lines[0].text.reveal() == "pw"


def test_ocr_result_observation_roundtrip_and_excluded_from_eq() -> None:
    """OCR 결과의 캡처 시점 관측(창·`frame_info`)이 경계를 넘어도 남는다 (줄 `Match` 재검증용)."""
    seen = FrameRef("wgc", (1024, 640), 96, capture_id=7, observed_at=12.5)
    result = OcrResult("a", (OcrLine("a", Rect(0, 0, 9, 9), 0.8),), 0.8, BOUND, seen)
    back = wire(result)
    assert back.window == BOUND and back.frame_info == seen
    assert back == OcrResult("a", (OcrLine("a", Rect(0, 0, 9, 9), 0.8),), 0.8, BOUND)
