"""핀 타입 문법.

    union := term ("|" term)*
    term  := "list[" union "]" | "dict[str," union "]" | name
    name  := 기본 타입 | <플러그인>.<Type>

공백은 쓰지 않는다. 메타스키마의 `format: kookabug-pin-type`이 이 파서로 검사한다
(정규식으로는 괄호 짝을 맞출 수 없다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn

BUILTIN_TYPES = frozenset(
    {
        "any",
        "bool",
        "float",
        "image",
        "int",
        "match",
        "point",
        "process",
        "rect",
        "secret",
        "string",
        "target",
        "window",
    }
)
_PLUGIN_TYPE = re.compile(r"[a-z][a-z0-9_]*\.[A-Z][A-Za-z0-9_]*")
_NAME = re.compile(r"[A-Za-z0-9_.]+")


class PinTypeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Named:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class ListOf:
    item: PinType

    def __str__(self) -> str:
        return f"list[{self.item}]"


@dataclass(frozen=True, slots=True)
class DictOf:
    value: PinType

    def __str__(self) -> str:
        return f"dict[str,{self.value}]"


@dataclass(frozen=True, slots=True)
class Union:
    options: tuple[PinType, ...]

    def __str__(self) -> str:
        return "|".join(str(o) for o in self.options)


type PinType = Named | ListOf | DictOf | Union


def parse_pin_type(text: str) -> PinType:
    parser = _Parser(text)
    result = parser.union()
    if parser.pos != len(text):
        parser.fail("남은 글자가 있다")
    return result


def is_pin_type(text: object) -> bool:
    if not isinstance(text, str):
        return False
    try:
        parse_pin_type(text)
    except PinTypeError:
        return False
    return True


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def fail(self, why: str) -> NoReturn:
        raise PinTypeError(f"핀 타입 {self.text!r}의 {self.pos}번째 글자: {why}")

    def eat(self, token: str) -> bool:
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def union(self) -> PinType:
        options = [self.term()]
        while self.eat("|"):
            options.append(self.term())
        if len(options) == 1:
            return options[0]
        if len(set(options)) != len(options):
            self.fail("유니온에 같은 타입이 두 번 있다")
        return Union(tuple(options))

    def term(self) -> PinType:
        if self.eat("list["):
            item = self.union()
            if not self.eat("]"):
                self.fail("']'가 없다")
            return ListOf(item)
        if self.eat("dict[str,"):
            value = self.union()
            if not self.eat("]"):
                self.fail("']'가 없다")
            return DictOf(value)
        m = _NAME.match(self.text, self.pos)
        if m is None:
            self.fail("타입 이름이 없다")
        name = m.group()
        if name not in BUILTIN_TYPES and not _PLUGIN_TYPE.fullmatch(name):
            self.fail(f"모르는 타입 {name!r}")
        self.pos = m.end()
        return Named(name)
