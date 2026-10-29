from typing import Any, Literal

import pytest

from kookabug_core.schema.pintype import is_pin_type
from kookabug_sdk.types import (
    Image,
    Match,
    PinTypeDeclError,
    Point,
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowRef,
    describe,
    pin_type,
    plugin_type,
)


@plugin_type("unreal.ActorRef")
class ActorRef:
    pass


def test_secret_masked_in_str_repr_format() -> None:
    s = Secret("hunter2")
    rendered = [
        str(s),
        repr(s),
        f"{s}",
        f"{s!r}",
        f"{s:>20}",
        "%s" % s,  # noqa: UP031
        "{}".format(s),  # noqa: UP032
        repr([s]),
        str({"pw": s}),
    ]
    for text in rendered:
        assert "hunter2" not in text
        assert "***" in text
    with pytest.raises(TypeError):
        Secret(123)  # type: ignore[arg-type]


def test_secret_reveal() -> None:
    s = Secret("hunter2")
    assert s.reveal() == "hunter2"
    assert s == Secret("hunter2")
    assert s != Secret("other")
    assert s != "hunter2"
    assert len({s, Secret("hunter2")}) == 1


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        (bool, "bool"),
        (int, "int"),
        (float, "float"),
        (str, "string"),
        (Any, "any"),
        (Secret, "secret"),
        (Target, "target"),
        (Match, "match"),
        (Rect, "rect"),
        (Point, "point"),
        (Image, "image"),
        (WindowRef, "window"),
        (ProcessRef, "process"),
        (ActorRef, "unreal.ActorRef"),
        (str | Secret, "string|secret"),
        (Secret | str | Secret, "secret|string"),
        (list[int], "list[int]"),
        (list, "list[any]"),
        (dict[str, int], "dict[str,int]"),
        (list[dict[str, int]], "list[dict[str,int]]"),
        (dict[str, list[str | Secret]], "dict[str,list[string|secret]]"),
        (list[ActorRef] | int, "list[unreal.ActorRef]|int"),
    ],
)
def test_pin_type_strings(hint: object, expected: str) -> None:
    assert pin_type(hint) == expected
    assert is_pin_type(expected)  # core 메타스키마 문법과 같다


@pytest.mark.parametrize(
    "hint",
    [object, dict[int, str], list[int | None], None, bytes, Literal["a"] | int],
)
def test_pin_type_rejects(hint: object) -> None:
    with pytest.raises(PinTypeDeclError):
        describe(hint)


def test_describe_nullable_and_literal_enum() -> None:
    assert describe(int | None).nullable
    assert describe(int | None).type == "int"
    info = describe(Literal["info", "warn", "error"])
    assert (info.type, info.enum, info.nullable) == ("string", ("info", "warn", "error"), False)
    assert describe(Literal[1, 2] | None).nullable
    with pytest.raises(PinTypeDeclError, match="한 타입"):
        describe(Literal["a", 1])
    with pytest.raises(PinTypeDeclError):
        pin_type(int | None)  # nullable은 핀 선언에서만


def test_plugin_type_name_checked() -> None:
    with pytest.raises(ValueError, match=r"<플러그인>\.<Type>"):
        plugin_type("ActorRef")
