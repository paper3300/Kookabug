"""파일 종류별 형식 검사.

메타스키마(`schema/json/*.schema.json`)를 jsonschema로 그대로 써서 오류를 `Diagnostic` 목록으로
바꾼다. 오류 위치는 JSON pointer로 준다. 의미 검증(연결·타입·흐름)은 여기서 하지 않는다.

메타스키마의 `pattern`은 JSON Schema 규정대로 ECMA-262 정규식이다. Python `re`의 `$`는 끝 줄바꿈
앞에서도 맞으므로 `$`를 문자열 끝(`\\Z`)으로 바꿔 검사한다 (에디터의 JS 검사기와 같은 결과).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Sequence
from functools import cache
from importlib import resources
from typing import Any, Literal, get_args

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from referencing import Registry, Resource

from kookabug_core.canonical import MAX_SAFE_INTEGER
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema.pintype import PinTypeError, parse_pin_type

# events는 events.jsonl 한 줄, rpc는 파이프 프레임 본문 하나(둘 다 format 없음)라 kind를 직접 준다
SchemaKind = Literal[
    "graph", "target", "workspace", "local", "node-schema", "events", "run", "user-settings", "rpc"
]
KINDS: tuple[SchemaKind, ...] = get_args(SchemaKind)
FORMAT_TO_KIND: dict[str, SchemaKind] = {
    "kookabug.graph/0": "graph",
    "kookabug.local/0": "local",
    "kookabug.nodes/0": "node-schema",
    "kookabug.run/0": "run",
    "kookabug.target/0": "target",
    "kookabug.user-settings/0": "user-settings",
    "kookabug.workspace/0": "workspace",
}
SPECIAL_VALUE_KEYS = ("$link", "$literal", "$secret", "$setting", "$target")
_MIXED_MESSAGE = (
    "특수 값 객체에는 $ 키 하나만 둔다. $로 시작하는 키를 가진 일반 객체는 $literal로 감싼다"
)

FORMAT_CHECKER = FormatChecker(formats=())


@FORMAT_CHECKER.checks("kookabug-pin-type", raises=PinTypeError)
def _check_pin_type(value: object) -> bool:
    if isinstance(value, str):
        parse_pin_type(value)
    return True


@cache
def ecma_regex(pattern: str) -> re.Pattern[str]:
    """ECMA-262 정규식을 Python으로: 문자 클래스·이스케이프 밖의 `$`를 `\\Z`로 바꾼다.

    메타스키마는 `^`·`$`·클래스·반복·그룹만 쓴다 (`\\d`·lookaround 등 차이 나는 문법은 쓰지 않는다).
    """
    out: list[str] = []
    i, in_class = 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            out.append(pattern[i : i + 2])
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "$":
            ch = r"\Z"
        out.append(ch)
        i += 1
    return re.compile("".join(out))


def _ecma_pattern(
    validator: Any, pattern: str, instance: Any, schema: Any
) -> Iterator[ValidationError]:
    if validator.is_type(instance, "string") and not ecma_regex(pattern).search(instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


_Validator = validators.extend(Draft202012Validator, {"pattern": _ecma_pattern})


def schema_id(kind: SchemaKind) -> str:
    return f"urn:kookabug:{kind}:0"


@cache
def metaschema(kind: SchemaKind) -> dict[str, Any]:
    """패키지에 들어 있는 메타스키마 (읽기 전용으로 다룰 것)."""
    if kind not in KINDS:
        raise ValueError(f"모르는 파일 종류: {kind!r}")
    text = resources.files("kookabug_core.schema").joinpath(f"json/{kind}.schema.json")
    return json.loads(text.read_text(encoding="utf-8"))


@cache
def _registry() -> Registry:
    return Registry().with_resources(
        (schema_id(k), Resource.from_contents(metaschema(k))) for k in KINDS
    )


@cache
def validator(kind: SchemaKind, ref: str | None = None) -> Draft202012Validator:
    """메타스키마 검사기. `ref`(예: `#/$defs/RetryConfig`)를 주면 그 부분 스키마로 검사한다."""
    schema = metaschema(kind) if ref is None else {"$ref": schema_id(kind) + ref}
    return _Validator(schema, registry=_registry(), format_checker=FORMAT_CHECKER)


def kind_of(data: object) -> SchemaKind | None:
    """`format` 값으로 파일 종류를 고른다."""
    if isinstance(data, dict):
        fmt = data.get("format")
        if isinstance(fmt, str):
            return FORMAT_TO_KIND.get(fmt)
    return None


def check_shape(
    data: Any,
    kind: SchemaKind | None = None,
    *,
    file: str | None = None,
    ref: str | None = None,
) -> list[Diagnostic]:
    """형식 검사. 문제가 없으면 빈 목록.

    `kind`를 생략하면 `format` 값으로 고른다. `ref`는 부분 스키마 검사용이다.
    """
    if kind is None:
        kind = kind_of(data)
        if kind is None:
            return [
                Diagnostic(
                    "error",
                    "format_unknown",
                    "format 값으로 파일 종류를 알 수 없다. 가능한 값: " + ", ".join(FORMAT_TO_KIND),
                    file=file,
                    pointer="/format" if isinstance(data, dict) else "",
                )
            ]

    graph_kind = kind if ref is None else None
    found: dict[tuple[str, str, str], Diagnostic] = {}
    for top in validator(kind, ref).iter_errors(data):
        for error in _leaves(top):
            for diag in _diagnose(error, graph_kind, file):
                found.setdefault((diag.pointer or "", diag.code, diag.message), diag)
    for path, code, message in _bad_numbers(data, []):
        diag = Diagnostic(
            "error",
            code,
            message,
            file=file,
            node=_node_of(path, graph_kind),
            pointer=_pointer(path),
        )
        found.setdefault((diag.pointer or "", diag.code, diag.message), diag)

    # 핀 타입은 정규식(다른 언어용 대략 검사)과 문법 검사가 같이 걸린다. 문법 쪽만 남긴다
    pin_type_pointers = {d.pointer for d in found.values() if d.code == "invalid_pin_type"}
    diags = [
        d
        for d in found.values()
        if not (d.code == "pattern_mismatch" and d.pointer in pin_type_pointers)
    ]
    return sorted(diags, key=lambda d: (d.pointer or "", d.code, d.message))


def _bad_numbers(value: Any, path: list[str | int]) -> Iterator[tuple[list[str | int], str, str]]:
    """JSON에 쓸 수 없거나 JavaScript가 정확히 다루지 못하는 수.

    - 정수 |n| > 2^53-1 → `number_out_of_range` (유한한 실수는 제한하지 않는다)
    - NaN·±Infinity → `number_not_finite`. 파일에서 읽으면 `loads_strict`가 먼저 거부하므로,
      프로그램이 직접 넘긴 값(에이전트·에디터가 만든 dict)에서만 나온다
    """
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            message = f"정수 {value}는 ±(2^53-1) 밖이다. 이 범위를 넘는 수는 문자열로 쓴다"
            yield path, "number_out_of_range", message
    elif isinstance(value, float):
        if not math.isfinite(value):
            yield path, "number_not_finite", f"{value}는 JSON 숫자가 아니다 (NaN·Infinity)"
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _bad_numbers(v, [*path, k])
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _bad_numbers(v, [*path, i])


def _node_of(path: Sequence[str | int], kind: SchemaKind | None) -> str | None:
    if kind == "graph" and len(path) >= 2 and path[0] == "nodes":
        return str(path[1])
    return None


def _leaves(error: ValidationError) -> list[ValidationError]:
    """anyOf·oneOf 오류를 실제로 맞춰 보려던 갈래의 오류로 바꾼다.

    같은 값에 대한 `type` 오류만 낸 갈래와 바로 아래 필드의 `const`(종류 표시, 예: 이벤트의
    `event`)가 틀린 갈래는 "다른 모양을 위한 갈래"이므로 버리고, 남은 갈래 중
    오류가 가장 깊은 곳을 가리키는 갈래를 고른다. 깊이가 같으면 `type` 오류가 적은 갈래
    (모양은 맞고 값만 틀린 쪽), 그다음 오류가 적은 갈래를 고른다.
    """
    if error.validator not in ("anyOf", "oneOf") or not error.context:
        return [error]
    branches: dict[int, list[ValidationError]] = {}
    for sub in error.context:
        index = sub.relative_schema_path[0]
        if isinstance(index, int):
            branches.setdefault(index, []).append(sub)
    relevant = {
        i: errs
        for i, errs in branches.items()
        if not all(e.validator == "type" and not e.relative_path for e in errs)
        and not any(e.validator == "const" and len(e.relative_path) == 1 for e in errs)
    }
    if not relevant:
        return _unknown_tag(error, branches) or [error]

    def rank(i: int) -> tuple[int, int, int, int]:
        errs = relevant[i]
        depth = max(len(e.relative_path) for e in errs)
        type_errors = sum(e.validator == "type" for e in errs)
        return (-depth, type_errors, len(errs), i)

    best = min(relevant, key=rank)
    return [leaf for sub in relevant[best] for leaf in _leaves(sub)]


def _unknown_tag(
    error: ValidationError, branches: dict[int, list[ValidationError]]
) -> list[ValidationError]:
    """모든 갈래가 같은 종류 표시 필드의 `const`에서 틀렸으면 그 필드의 `enum` 오류 하나로 바꾼다
    (모르는 이벤트 종류를 "가능한 값" 목록과 함께 알린다)."""
    tags: dict[str, list[Any]] = {}
    instance: Any = None
    for errs in branches.values():
        tag = next((e for e in errs if e.validator == "const" and len(e.relative_path) == 1), None)
        if tag is None:
            return []
        tags.setdefault(str(tag.relative_path[0]), []).append(tag.validator_value)
        instance = tag.instance
    if len(tags) != 1:
        return []
    key, values = next(iter(tags.items()))
    return [
        ValidationError(
            f"{instance!r} is not one of {values!r}",
            validator="enum",
            validator_value=sorted(values),
            instance=instance,
            path=[*error.absolute_path, key],
        )
    ]


def _pointer(path: Sequence[str | int]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in path)


def _short(value: object, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _diagnose(
    error: ValidationError, kind: SchemaKind | None, file: str | None
) -> list[Diagnostic]:
    path = list(error.absolute_path)
    node = _node_of(path, kind)

    def diag(code: str, message: str, at: Sequence[str | int] = path) -> Diagnostic:
        return Diagnostic("error", code, message, file=file, node=node, pointer=_pointer(at))

    v, inst = error.validator, error.instance
    value: Any = error.validator_value

    if "propertyNames" in error.relative_schema_path:
        # instance는 키 이름이고 path는 그 키를 가진 객체다
        key = str(inst)
        at = [*path, key]
        if kind == "graph" and path == ["nodes"]:
            node = key
        special = v == "enum" and list(value) == list(SPECIAL_VALUE_KEYS)
        if special and not key.startswith("$"):
            # $ 키와 일반 키가 섞인 객체. maxProperties 오류와 같은 진단으로 합친다
            return [diag("special_value_mixed", _MIXED_MESSAGE)]
        if special:
            return [
                diag(
                    "special_value_unknown",
                    f"모르는 특수 값 {key!r}. 쓸 수 있는 것: {', '.join(SPECIAL_VALUE_KEYS)}. "
                    "$로 시작하는 키를 가진 일반 객체는 $literal로 감싼다",
                    at,
                )
            ]
        if v == "pattern":
            return [diag("invalid_key", f"키 {key!r}가 형식에 맞지 않는다 (규칙 {value})", at)]
        return [diag("invalid_key", f"키 {key!r}를 쓸 수 없다: {error.message}", at)]

    match v:
        case "required":
            assert isinstance(inst, dict)
            return [
                diag("missing_field", f"필수 필드 {k!r}가 없다") for k in value if k not in inst
            ]
        case "additionalProperties":
            assert isinstance(inst, dict)
            known = error.schema.get("properties", {}) if isinstance(error.schema, dict) else {}
            return [
                diag("unknown_field", f"알 수 없는 필드 {k!r}", [*path, k])
                for k in inst
                if k not in known
            ]
        case "maxProperties" if isinstance(inst, dict) and any(
            isinstance(k, str) and k.startswith("$") for k in inst
        ):
            return [diag("special_value_mixed", _MIXED_MESSAGE)]
        case "type":
            return [diag("wrong_type", f"{_short(inst)}의 타입이 틀렸다. 기대: {value}")]
        case "const":
            return [diag("invalid_value", f"{_short(inst)} 대신 {_short(value)}이어야 한다")]
        case "enum":
            allowed = ", ".join(_short(x) for x in value)
            return [diag("invalid_value", f"{_short(inst)}는 쓸 수 없다. 가능한 값: {allowed}")]
        case "pattern":
            return [diag("pattern_mismatch", f"{_short(inst)}가 형식에 맞지 않는다 (규칙 {value})")]
        case "format":
            why = str(error.cause) if error.cause else error.message
            return [diag("invalid_pin_type", why)]
        case "minimum" | "maximum" | "minItems" | "maxItems" | "minLength" | "minProperties":
            return [diag("out_of_range", _range_message(v, value))]
        case "uniqueItems":
            return [diag("duplicate_item", "배열에 같은 항목이 두 번 있다")]
        case "not":
            present = sorted(_required_names(value) & set(inst)) if isinstance(inst, dict) else []
            if present:
                names = ", ".join(repr(n) for n in present)
                return [diag("not_allowed", f"이 경우에는 {names} 필드를 둘 수 없다")]
            return [diag("not_allowed", "이 조합은 허용되지 않는다")]
        case _:
            return [diag("shape_invalid", error.message)]


def _required_names(schema: object) -> set[str]:
    """`not` 안의 `required`·`anyOf[required]`에 적힌 필드 이름."""
    if not isinstance(schema, dict):
        return set()
    names = {n for n in schema.get("required", []) if isinstance(n, str)}
    for sub in schema.get("anyOf", []):
        names |= _required_names(sub)
    return names


def _range_message(keyword: str, limit: object) -> str:
    return {
        "minimum": f"{limit} 이상이어야 한다",
        "maximum": f"{limit} 이하여야 한다",
        "minItems": f"항목이 {limit}개 이상이어야 한다",
        "maxItems": f"항목이 {limit}개 이하여야 한다",
        "minLength": f"{limit}글자 이상이어야 한다",
        "minProperties": f"키가 {limit}개 이상이어야 한다",
    }[keyword]
