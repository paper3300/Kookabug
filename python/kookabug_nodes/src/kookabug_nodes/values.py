"""값 노드: 변수, 비교, 문자열 조합.

비교 규칙(`compare_values`)은 `core.assert.compare`도 같이 쓴다.
"""

import json
from collections.abc import Mapping
from typing import Any, Literal

from kookabug_sdk import OMITTED, Context, Exit, Result, Secret, node

__all__ = [
    "OPS",
    "CompareOp",
    "compare",
    "compare_values",
    "format_template",
    "show",
    "text_format",
    "var_get",
    "var_set",
]

CompareOp = Literal["==", "!=", "<", "<=", ">", ">=", "contains"]
OPS: tuple[str, ...] = ("==", "!=", "<", "<=", ">", ">=", "contains")


# ---------------------------------------------------------------- 비교


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, Secret):
        return "secret"
    return type(value).__name__


def _same(a: object, b: object) -> bool:
    # JSON 값 기준의 같음: bool과 숫자는 다른 값(True != 1), 1과 1.0은 같은 값
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        xs: list[object] = a
        ys: list[object] = b
        return len(xs) == len(ys) and all(_same(x, y) for x, y in zip(xs, ys, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        da: dict[object, object] = a
        db: dict[object, object] = b
        return da.keys() == db.keys() and all(_same(da[k], db[k]) for k in da)
    return type(a) is type(b) and a == b


def compare_values(a: Any, op: str, b: Any) -> bool:
    """`a op b`. 대소 비교는 숫자끼리·문자열끼리만, 아니면 TypeError(→ error).

    `contains`: `a`가 문자열이면 `b`(문자열)가 부분 문자열인지, `a`가 목록이면 `b`와 같은 원소가
    있는지.
    """
    if op == "==":
        return _same(a, b)
    if op == "!=":
        return not _same(a, b)
    if op in ("<", "<=", ">", ">="):
        if not ((_is_number(a) and _is_number(b)) or (isinstance(a, str) and isinstance(b, str))):
            raise TypeError(f"'{op}'는 숫자끼리·문자열끼리만 비교한다 ({_kind(a)} {op} {_kind(b)})")
        if op == "<":
            return a < b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        return a >= b
    if op == "contains":
        if isinstance(a, str) and isinstance(b, str):
            return b in a
        if isinstance(a, list):
            items: list[object] = a
            return any(_same(x, b) for x in items)
        raise TypeError(
            f"'contains'는 문자열 안의 문자열, 목록 안의 원소만 찾는다 ({_kind(a)}, {_kind(b)})"
        )
    raise ValueError(f"모르는 op {op!r}. 가능한 값: {list(OPS)}")


def show(value: object) -> str:
    """메시지용 값 표기. 비밀값은 가린다."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except ValueError:
        return str(value)


@node(
    type="core.logic.compare",
    version=1,
    title="비교",
    category="value",
    pure=True,
    outputs={"result": bool},
)
def compare(ctx: Context, a: Any, op: CompareOp, b: Any) -> dict[str, Any]:
    """`a op b`의 참·거짓. 대소 비교는 숫자끼리·문자열끼리만 된다."""
    return {"result": compare_values(a, op, b)}


# ---------------------------------------------------------------- 문자열 조합


def _has_secret(value: object) -> bool:
    if isinstance(value, Secret):
        return True
    if isinstance(value, list):
        items: list[object] = value
        return any(_has_secret(v) for v in items)
    if isinstance(value, dict):
        mapping: dict[object, object] = value
        return any(_has_secret(v) for v in mapping.values())
    return False


def _plain(value: object) -> object:
    if isinstance(value, Secret):
        return value.reveal()
    if isinstance(value, list):
        items: list[object] = value
        return [_plain(v) for v in items]
    if isinstance(value, dict):
        mapping: dict[object, object] = value
        return {k: _plain(v) for k, v in mapping.items()}
    return value


def _text(value: object) -> str:
    # 그래프 값은 JSON이므로 JSON 표기를 쓴다 (true·null). 문자열·비밀값은 그대로
    if isinstance(value, str):
        return value
    if isinstance(value, Secret):
        return value.reveal()
    if value is None or isinstance(value, bool | int | float | list | dict):
        return json.dumps(_plain(value), ensure_ascii=False, default=str)
    return str(value)


def format_template(template: str, values: Mapping[str, Any]) -> str | Secret:
    """`{이름}`을 `values[이름]`으로 바꾼다. `{{`·`}}`는 중괄호 자체.

    속성·인덱스 접근(`{a.b}`, `{a[0]}`), 형식 지정(`{a:>3}`, `{a:}`, `{a!r}`), 빈 `{}`, 짝 없는
    중괄호는 ValueError. 값 중 하나라도 비밀값이면 결과도 비밀값이다.
    """
    # string.Formatter는 `{a}`와 `{a:}`를 같게 돌려주므로 원문을 직접 읽는다
    parts: list[str] = []
    i = 0
    while i < len(template):
        ch = template[i]
        if template.startswith(("{{", "}}"), i):
            parts.append(ch)
            i += 2
        elif ch == "}":
            raise ValueError(f"template 문법 오류: 짝 없는 '}}' (위치 {i})")
        elif ch == "{":
            end = template.find("}", i + 1)
            if end < 0:
                raise ValueError(f"template 문법 오류: 닫히지 않은 '{{' (위치 {i})")
            name = template[i + 1 : end]
            if not name.isidentifier():
                raise ValueError(
                    f"자리 표시는 {{이름}}만 쓴다 (속성·인덱스·형식 지정 불가): {{{name}}}"
                )
            if name not in values:
                raise KeyError(f"values에 '{name}'이(가) 없다")
            parts.append(_text(values[name]))
            i = end + 1
        else:
            parts.append(ch)
            i += 1
    text = "".join(parts)
    return Secret(text) if _has_secret(dict(values)) else text


@node(
    type="core.text.format",
    version=1,
    title="문자열 조합",
    category="value",
    pure=True,
    outputs={"text": str | Secret},
)
def text_format(ctx: Context, template: str, values: dict[str, Any]) -> dict[str, Any]:
    """`template`의 `{이름}`을 `values`의 값으로 바꾼다. `{{`·`}}`는 중괄호 자체.

    값 중 하나라도 비밀값이면 결과도 비밀값이다.
    """
    return {"text": format_template(template, values)}


# ---------------------------------------------------------------- 변수


@node(
    type="core.var.set",
    version=1,
    title="변수 저장",
    category="value",
    exits=[Exit("done", "ok")],
)
def var_set(ctx: Context, name: str, value: Any) -> Result:
    """호출 프레임 변수에 값을 저장한다."""
    if not name:
        raise ValueError("변수 이름이 비었다")
    ctx.vars.set(name, value)
    return Result.ok("done")


@node(
    type="core.var.get",
    version=1,
    title="변수 읽기",
    category="value",
    pure=True,
    outputs={"value": Any},
)
def var_get(ctx: Context, name: str, default: Any | None = OMITTED) -> dict[str, Any]:
    """호출 프레임 변수를 읽는다. 계산하는 순간의 값이다.

    변수가 없으면 `default`(`null`도 값이다). `default`를 생략했으면 error.
    """
    if ctx.vars.has(name):
        return {"value": ctx.vars.get(name)}
    if default is OMITTED:
        raise KeyError(f"변수 '{name}'이(가) 없다 (default도 없음)")
    return {"value": default}
