"""값 인코딩 (runner ↔ 워커 경계)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk.codec import TAG, CodecError, decode, encode
from kookabug_sdk.types import Image, Match, Point, ProcessRef, Rect, Secret, Target, WindowRef

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
