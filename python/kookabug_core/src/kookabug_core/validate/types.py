"""타입 검사: `in` 값(상수·특수 값·연결)이 입력 핀 타입에 맞는가 (`type_mismatch`), 상수가 핀의
선택지·범위 안인가 (`input_invalid`). config 값은 `structure`가 같은 함수로 검사한다.

연결 규칙 (출력 타입 → 입력 타입):
- 정확히 같음. `int` → `float`은 된다 (반대는 안 됨)
- `any` 입력은 무엇이든 받는다 (`secret` 포함). `any` 출력은 어디에나 연결된다 (값은 실행 때 확인)
- 유니온 출력은 모든 항이 입력에 맞아야 한다. 유니온 입력은 항 하나에 맞으면 된다
- `list[A]` → `list[B]`, `dict[str,A]` → `dict[str,B]`는 원소 타입 규칙을 그대로 따른다
- `secret`은 `secret`을 포함한 핀(`secret`, `string|secret`, `any`)에만 연결된다 (G9)

상수: `null`은 nullable 핀이나 `any`만, `$secret`은 `secret`, `$target`은 `target`. 구조 타입
(`match`·`rect`·`image` 등)과 플러그인 타입의 상수 모양은 아직 보지 않는다 (M1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import cache
from typing import Any

from kookabug_core.diagnostics import json_pointer
from kookabug_core.ir import LinkRef, Unresolved
from kookabug_core.registry import InputDecl
from kookabug_core.schema.pintype import DictOf, ListOf, Named, PinType, Union, parse_pin_type
from kookabug_core.validate.context import ValidationContext
from kookabug_sdk import Secret
from kookabug_sdk.types import Target

__all__ = ["assignable", "check", "pin_type", "value_problems"]

ANY = Named("any")
type LinkType = Callable[[LinkRef], PinType | None]
type Problem = tuple[tuple[str | int, ...], str, str]


@cache
def pin_type(text: str) -> PinType:
    return parse_pin_type(text)


def assignable(src: PinType, dst: PinType) -> bool:
    """`src` 타입 출력을 `dst` 타입 입력에 연결할 수 있는가."""
    if isinstance(src, Union):
        return all(assignable(o, dst) for o in src.options)
    if isinstance(dst, Union):
        return any(assignable(src, o) for o in dst.options)
    if dst == ANY or src == ANY:
        return True
    if isinstance(src, Named) and isinstance(dst, Named):
        return src.name == dst.name or (src.name, dst.name) == ("int", "float")
    if isinstance(src, ListOf) and isinstance(dst, ListOf):
        return assignable(src.item, dst.item)
    if isinstance(src, DictOf) and isinstance(dst, DictOf):
        return assignable(src.value, dst.value)
    return False


def _named_fits(value: Any, name: str) -> bool:
    match name:
        case "any":
            return True
        case "bool":
            return isinstance(value, bool)
        case "int":
            return isinstance(value, int) and not isinstance(value, bool)
        case "float":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "string":
            return isinstance(value, str)
        case "secret":
            return isinstance(value, Secret)
        case "target":
            return isinstance(value, Target)
        case _:
            return value is not None and not isinstance(value, Secret | Target)


def _fits(value: Any, t: PinType, link_type: LinkType) -> bool:
    if isinstance(value, Unresolved):
        return True
    if isinstance(value, LinkRef):
        src = link_type(value)
        return src is None or assignable(src, t)
    if isinstance(t, Union):
        return any(_fits(value, o, link_type) for o in t.options)
    if t == ANY:
        return True
    if isinstance(t, ListOf):
        return isinstance(value, list) and all(_fits(v, t.item, link_type) for v in value)
    if isinstance(t, DictOf):
        return isinstance(value, dict) and all(_fits(v, t.value, link_type) for v in value.values())
    return _named_fits(value, t.name)


def _show(value: Any) -> str:
    if isinstance(value, Secret):
        return "$secret 값"
    if isinstance(value, Target):
        return f"$target '{value.name}'"
    if isinstance(value, LinkRef):
        return f"$link '{value}'"
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _type_problems(
    value: Any, t: PinType, path: tuple[str | int, ...], link_type: LinkType
) -> Iterator[Problem]:
    if isinstance(value, Unresolved):
        return
    if isinstance(value, LinkRef):
        src = link_type(value)
        if src is not None and not assignable(src, t):
            why = " (비밀값은 secret을 포함한 핀에만 연결한다)" if _has_secret(src) else ""
            yield (
                path,
                "type_mismatch",
                f"{_show(value)}({src})을(를) {t} 입력에 연결할 수 없다{why}",
            )
        return
    if isinstance(t, Union) or t == ANY:
        if not _fits(value, t, link_type):
            yield path, "type_mismatch", f"{_show(value)}은(는) {t} 타입이 아니다"
        return
    if isinstance(t, ListOf):
        if not isinstance(value, list):
            yield path, "type_mismatch", f"{_show(value)}은(는) {t} 타입이 아니다"
            return
        for i, v in enumerate(value):
            yield from _type_problems(v, t.item, (*path, i), link_type)
        return
    if isinstance(t, DictOf):
        if not isinstance(value, dict):
            yield path, "type_mismatch", f"{_show(value)}은(는) {t} 타입이 아니다"
            return
        for k, v in value.items():
            yield from _type_problems(v, t.value, (*path, k), link_type)
        return
    if not _named_fits(value, t.name):
        why = " (비밀값은 secret을 포함한 핀에만 넣는다)" if isinstance(value, Secret) else ""
        yield path, "type_mismatch", f"{_show(value)}은(는) {t} 타입이 아니다{why}"


def _has_secret(t: PinType) -> bool:
    if isinstance(t, Named):
        return t.name == "secret"
    if isinstance(t, Union):
        return any(_has_secret(o) for o in t.options)
    if isinstance(t, ListOf):
        return _has_secret(t.item)
    return _has_secret(t.value)


def value_problems(
    value: Any, decl: InputDecl, link_type: LinkType, path: tuple[str | int, ...] = ()
) -> list[Problem]:
    """값 하나를 핀 선언과 대조한다. (경로, 코드, 메시지) 목록."""
    if value is None:
        if decl.nullable or _fits(None, pin_type(decl.type), link_type):
            return []
        return [(path, "type_mismatch", f"null은 {decl.type} 타입이 아니다 (nullable 핀이 아님)")]
    problems = list(_type_problems(value, pin_type(decl.type), path, link_type))
    if problems or isinstance(value, LinkRef | Unresolved):
        return problems
    return [(path, "input_invalid", m) for m in _constraint_problems(value, decl)]


def _constraint_problems(value: Any, decl: InputDecl) -> Iterator[str]:
    if decl.enum is not None and not any(_same(value, e) for e in decl.enum):
        allowed = ", ".join(repr(e) for e in decl.enum)
        yield f"{_show(value)}은(는) 쓸 수 없다. 가능한 값: {allowed}"
    if isinstance(value, int | float) and not isinstance(value, bool):
        if decl.minimum is not None and value < decl.minimum:
            yield f"{value}은(는) {decl.minimum} 이상이어야 한다"
        if decl.maximum is not None and value > decl.maximum:
            yield f"{value}은(는) {decl.maximum} 이하여야 한다"
    if decl.min_items is not None and isinstance(value, list) and len(value) < decl.min_items:
        yield f"항목이 {decl.min_items}개 이상이어야 한다"


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():

        def link_type(ref: LinkRef, graph: Any = graph) -> PinType | None:
            producer = graph.nodes.get(ref.node)
            pins = None if producer is None else ctx.pins(graph, producer)
            if pins is None or pins.outputs is None or ref.output not in pins.outputs:
                return None
            return pin_type(pins.outputs[ref.output].type)

        for node in graph.nodes.values():
            pins = ctx.pins(graph, node)
            if pins is None or pins.inputs is None:
                continue
            for pin, value in node.inputs.items():
                decl = pins.inputs.get(pin)
                if decl is None:
                    continue
                for path, code, message in value_problems(value, decl, link_type, (pin,)):
                    pointer = json_pointer("nodes", node.id, "in", *path)
                    ctx.report(code, f"입력 '{pin}': {message}", graph, node.id, pointer)

        interface = graph.interface or {}
        for name, decl in interface.get("inputs", {}).items():
            if "default" not in decl:
                continue
            spec = InputDecl(name, decl["type"])
            for _, code, message in value_problems(decl["default"], spec, link_type):
                pointer = json_pointer("interface", "inputs", name, "default")
                ctx.report(
                    code, f"interface 입력 '{name}'의 기본값: {message}", graph, None, pointer
                )
