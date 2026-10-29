"""핀 타입과 Python 타입 힌트 → 핀 타입 문자열 변환.

| 핀 타입 | Python |
|---|---|
| `bool`, `int`, `float`, `string` | `bool`, `int`, `float`, `str` |
| `secret`, `target`, `match`, `rect`, `point`, `image`, `window`, `process` | 아래 클래스 |
| `list[T]`, `dict[str,T]` | `list[T]`, `dict[str, T]` |
| `any` | `Any` |
| `A|B` | `A | B` |
| `<플러그인>.<Type>` | `@plugin_type("<플러그인>.<Type>")`를 붙인 클래스 |

맨 바깥의 `| None`은 nullable, `Literal[...]`은 enum이 된다.
"""

from __future__ import annotations

import re
import types as _pytypes
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, final

__all__ = [
    "Image",
    "Match",
    "PinTypeDeclError",
    "Point",
    "ProcessRef",
    "Rect",
    "Secret",
    "Target",
    "WindowRef",
    "pin_type",
    "plugin_type",
]


@final
class Secret:
    """비밀값. `str()`·`repr()`·`format()`에는 가려진 값만 나온다. 값은 `reveal()`로 꺼낸다."""

    __slots__ = ("_value",)
    MASK: Final = "***"

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"Secret에는 str만 담는다: {type(value).__name__}")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __str__(self) -> str:
        return self.MASK

    def __repr__(self) -> str:
        return f"Secret({self.MASK!r})"

    def __format__(self, format_spec: str) -> str:
        return self.MASK

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash((Secret, self._value))


@dataclass(frozen=True, slots=True)
class Rect:
    """클라이언트 영역 기준 사각형 (픽셀)."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Point:
        return Point(self.x + self.width // 2, self.y + self.height // 2)


@dataclass(frozen=True, slots=True)
class Point:
    """클라이언트 영역 기준 점 (픽셀)."""

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class WindowRef:
    handle: int
    title: str = ""


@dataclass(frozen=True, slots=True)
class ProcessRef:
    pid: int
    name: str = ""


@dataclass(frozen=True, slots=True)
class Image:
    """캡처 프레임이나 이미지 파일. `frame`은 캡처 프레임 번호.

    `capture_id`는 러너가 `ctx.capture` 때 붙이는 실행 안 번호다. 노드는 만들지 않는다. 기록 정책이
    "얻을 때 스크린샷이 허용됐는가"를 이것으로 찾으므로, 복사·출력·워커 경계를 넘어도 유지된다.
    값 비교에는 들지 않는다.
    """

    width: int = 0
    height: int = 0
    path: Path | None = None
    frame: int | None = None
    data: bytes | None = field(default=None, repr=False)
    capture_id: int | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class Match:
    """찾기 결과: 위치, 점수, 창, 캡처 프레임 번호."""

    rect: Rect
    score: float
    window: WindowRef | None = None
    frame: int | None = None


@dataclass(frozen=True, slots=True)
class Target:
    """`*.target.json` 하나. `spec`은 파일 내용 그대로."""

    name: str
    path: Path | None = None
    spec: Mapping[str, Any] = field(default_factory=dict)


_PLUGIN_TYPE_NAME = re.compile(r"^[a-z][a-z0-9_]*\.[A-Z][A-Za-z0-9_]*$")


def plugin_type[T: type](name: str) -> typing.Callable[[T], T]:
    """플러그인 고유 핀 타입으로 등록한다. 예: `@plugin_type("unreal.ActorRef")`."""
    if not _PLUGIN_TYPE_NAME.match(name):
        raise ValueError(f"플러그인 타입 이름은 '<플러그인>.<Type>' 형식이다: {name!r}")

    def mark(cls: T) -> T:
        cls.__kookabug_type__ = name  # type: ignore[attr-defined]
        return cls

    return mark


_BUILTIN: Final[dict[object, str]] = {
    bool: "bool",
    int: "int",
    float: "float",
    str: "string",
    Any: "any",
    Secret: "secret",
    Target: "target",
    Match: "match",
    Rect: "rect",
    Point: "point",
    Image: "image",
    WindowRef: "window",
    ProcessRef: "process",
}


class PinTypeDeclError(TypeError):
    """핀 타입으로 바꿀 수 없는 타입 힌트."""


@dataclass(frozen=True, slots=True)
class PinTypeInfo:
    type: str
    nullable: bool = False
    enum: tuple[Any, ...] | None = None


def pin_type(hint: object) -> str:
    """타입 힌트 → 핀 타입 문자열. 예: `str | Secret` → `string|secret`."""
    info = describe(hint)
    if info.nullable or info.enum is not None:
        raise PinTypeDeclError(f"None·Literal은 핀 선언에서만 쓴다: {hint!r}")
    return info.type


def describe(hint: object) -> PinTypeInfo:
    """핀 선언용 해석. 맨 바깥 `| None` → nullable, `Literal[...]` → enum."""
    options = _union_options(hint)
    nullable = type(None) in options
    options = [o for o in options if o is not type(None)]
    if not options:
        raise PinTypeDeclError("None만으로는 핀 타입이 될 수 없다")
    if all(typing.get_origin(o) is typing.Literal for o in options):
        values = tuple(v for o in options for v in typing.get_args(o))
        kinds = {_literal_type(v) for v in values}
        if len(kinds) != 1:
            raise PinTypeDeclError(f"Literal 값은 한 타입이어야 한다: {values!r}")
        return PinTypeInfo(kinds.pop(), nullable, tuple(dict.fromkeys(values)))
    return PinTypeInfo(_union_text(options), nullable)


def _union_options(hint: object) -> list[object]:
    if typing.get_origin(hint) in (typing.Union, _pytypes.UnionType):
        return [o for arg in typing.get_args(hint) for o in _union_options(arg)]
    if hint is None:
        return [type(None)]
    return [hint]


def _union_text(options: list[object]) -> str:
    return "|".join(dict.fromkeys(_term(o) for o in options))


def _term(hint: object) -> str:
    if hint is None or hint is type(None):
        raise PinTypeDeclError("None(nullable)은 핀 타입 맨 바깥에서만 쓸 수 있다")
    origin = typing.get_origin(hint)
    args = typing.get_args(hint)
    if origin in (typing.Union, _pytypes.UnionType):
        return _union_text(_union_options(hint))
    if origin is typing.Literal:
        raise PinTypeDeclError("Literal은 핀 타입 맨 바깥에서만 쓸 수 있다")
    if hint is list or origin is list:
        item = args[0] if args else Any
        return f"list[{_union_text(_union_options(item))}]"
    if hint is dict or origin is dict:
        key, value = args if args else (str, Any)
        if key is not str:
            raise PinTypeDeclError(f"dict 키는 str만 된다: {hint!r}")
        return f"dict[str,{_union_text(_union_options(value))}]"
    try:
        builtin = _BUILTIN.get(hint)
    except TypeError:
        builtin = None
    if builtin is not None:
        return builtin
    name = getattr(hint, "__kookabug_type__", None)
    if isinstance(name, str):
        return name
    raise PinTypeDeclError(
        f"핀 타입으로 쓸 수 없는 타입: {hint!r} (플러그인 타입은 @plugin_type으로 등록한다)"
    )


def _literal_type(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "string"
    raise PinTypeDeclError(f"Literal 값은 str·int·bool만 된다: {value!r}")
