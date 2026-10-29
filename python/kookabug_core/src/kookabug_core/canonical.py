"""정해진 형식으로 JSON 쓰기.

Kookabug가 **새로 쓰거나 편집한 뒤 저장하는** 그래프·설정 파일의 출력 규칙이다. 같은 값이면
언제나 같은 바이트가 나온다. 의미가 바뀌지 않은 저장은 원문 바이트를 그대로 둔다(`save_text`).

- 객체 키는 UTF-16 코드 단위 순으로 정렬한다(JavaScript 기본 정렬과 같다). 배열은 순서 그대로
- 들여쓰기 2칸, 파일 끝 줄바꿈(LF) 하나
- 객체는 항상 펼친다(빈 객체만 `{}`). 배열은 원소가 모두 스칼라이고 그 줄 전체(들여쓰기·키·
  뒤 쉼표 포함)가 `WIDTH`자(UTF-16 코드 단위) 안이면 한 줄 `[1, 2]`, 아니면 펼친다.
  최상위는 항상 펼친다
- 숫자는 JavaScript `JSON.stringify`와 같은 표기다(`1.0` → `1`, `1e-7`, `1.5e+21`). 단, 2^53보다 큰
  정수 값의 실수는 지수 표기(`1e+20`)로 쓴다(다시 읽으면 범위 밖 정수가 되지 않게).
  정수는 ±(2^53-1) 안이어야 한다(`MAX_SAFE_INTEGER`). NaN·Infinity는 쓰지 않는다
- 문자열은 ASCII로 바꾸지 않는다. 짝 없는 서로게이트만 `\\uXXXX`로 쓴다(JavaScript와 같다)
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal
from typing import Any

WIDTH = 100
MAX_SAFE_INTEGER = 2**53 - 1
_INDENT = "  "
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def canonical_dumps(value: Any) -> str:
    return _format(value, level=0, used=0, trailing=0) + "\n"


def is_canonical(text: str) -> bool:
    """`text`가 그 값의 canonical 출력과 바이트까지 같은가."""
    try:
        value = loads_strict(text)
        return canonical_dumps(value) == text
    except TypeError, ValueError:
        return False


def save_text(original: str | None, value: Any) -> str:
    """저장할 텍스트. 원문과 값이 같으면 원문 그대로, 아니면 파일 전체를 canonical로 쓴다."""
    if original is not None:
        try:
            if json_equal(loads_strict(original), value):
                return original
        except ValueError:
            pass
    return canonical_dumps(value)


def loads_strict(text: str) -> Any:
    """JSON 읽기. 같은 키 두 번, NaN·Infinity 토큰, float로 넘치는 수(`1e400`)는 오류."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in items:
            if k in result:
                raise ValueError(f"같은 키가 두 번 있다: {k!r}")
            result[k] = v
        return result

    def constant(name: str) -> Any:
        raise ValueError(f"JSON 숫자가 아니다: {name}")

    def finite(token: str) -> float:
        # 문법상 정상인 1e400도 float로는 Infinity가 된다. 저장할 수 없는 값이므로 읽을 때 막는다
        number = float(token)
        if not math.isfinite(number):
            raise ValueError(f"숫자가 너무 크다 (float 범위 밖): {token}")
        return number

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite)


def json_equal(a: Any, b: Any) -> bool:
    """JSON 값으로서 같은가. 숫자는 값으로 비교(1 == 1.0)하고 bool은 숫자와 구별한다."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _width(text: str) -> int:
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _sort_key(key: str) -> bytes:
    return key.encode("utf-16-be", "surrogatepass")


def _string(text: str) -> str:
    out = json.dumps(text, ensure_ascii=False)
    return _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", out)


def _number(value: int | float) -> str:
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(f"정수가 ±(2^53-1) 밖이다: {value}")
        return str(value)
    if not math.isfinite(value):
        raise ValueError(f"JSON 숫자가 아니다: {value}")
    if value == 0:
        return "0"
    # repr는 값을 되살리는 가장 짧은 십진수다. 이것을 ECMAScript Number::toString 규칙으로 쓴다
    _, digits_tuple, exponent = Decimal(repr(abs(value))).as_tuple()
    assert isinstance(exponent, int)
    digits = "".join(map(str, digits_tuple)).rstrip("0")
    exponent += len(digits_tuple) - len(digits)
    k = len(digits)
    n = exponent + k
    # JS는 1e20을 정수 자릿수로 쓰지만, 다시 읽으면 범위 밖 정수가 되므로 지수 표기로 둔다
    integral = k <= n <= 21
    if integral and abs(value) <= MAX_SAFE_INTEGER:
        text = digits + "0" * (n - k)
    elif not integral and 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        e = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        text = f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
    return ("-" if value < 0 else "") + text


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    raise TypeError(f"JSON 값이 아니다: {type(value).__name__}")


def _is_container(value: Any) -> bool:
    return isinstance(value, dict | list)


def _format(value: Any, level: int, used: int, trailing: int) -> str:
    if not _is_container(value):
        return _scalar(value)
    if not value:
        return "{}" if isinstance(value, dict) else "[]"

    pad = _INDENT * (level + 1)
    lines: list[str] = []
    if isinstance(value, dict):
        keys = list(value)
        for k in keys:
            if not isinstance(k, str):
                raise TypeError(f"객체 키는 문자열이어야 한다: {k!r}")
        keys.sort(key=_sort_key)
        for i, k in enumerate(keys):
            comma = 1 if i < len(keys) - 1 else 0
            prefix = f"{pad}{_string(k)}: "
            body = _format(value[k], level + 1, _width(prefix), comma)
            lines.append(prefix + body + ("," if comma else ""))
        return "{\n" + "\n".join(lines) + "\n" + _INDENT * level + "}"

    if level > 0 and not any(_is_container(v) for v in value):
        flat = "[" + ", ".join(_scalar(v) for v in value) + "]"
        if used + _width(flat) + trailing <= WIDTH:
            return flat
    for i, v in enumerate(value):
        comma = 1 if i < len(value) - 1 else 0
        lines.append(pad + _format(v, level + 1, _width(pad), comma) + ("," if comma else ""))
    return "[\n" + "\n".join(lines) + "\n" + _INDENT * level + "]"
