from typing import Any

import pytest

from kookabug_nodes.values import compare, text_format, var_get, var_set
from kookabug_sdk import Secret
from kookabug_sdk.pure import PureContextViolation
from kookabug_sdk.testing import fake_context


def run_compare(a: Any, op: str, b: Any) -> bool:
    return compare(fake_context(pure=True), a=a, op=op, b=b).outputs["result"]


@pytest.mark.parametrize(
    ("a", "op", "b", "expected"),
    [
        (1, "==", 1, True),
        (1, "==", 1.0, True),
        (1, "==", 2, False),
        ("a", "==", "a", True),
        (None, "==", None, True),
        ([1, {"k": "v"}], "==", [1, {"k": "v"}], True),
        (True, "==", 1, False),  # bool과 숫자는 다른 값
        ([True], "==", [1], False),
        ("1", "==", 1, False),  # 타입이 다르면 다른 값 (error 아님)
        (1, "!=", 2, True),
        (1, "!=", 1, False),
        ("1", "!=", 1, True),
        (1, "<", 2, True),
        (2, "<", 2, False),
        (2, "<=", 2, True),
        (2.5, ">", 2, True),
        (2, ">", 2, False),
        (2, ">=", 2, True),
        ("abc", "<", "abd", True),
        ("b", ">=", "a", True),
        ("hello world", "contains", "world", True),
        ("hello", "contains", "xyz", False),
        ([1, 2, 3], "contains", 2, True),
        ([1, 2, 3], "contains", 4, False),
        ([True], "contains", 1, False),
        ([{"a": 1}], "contains", {"a": 1}, True),
    ],
)
def test_compare_ops(a: Any, op: str, b: Any, expected: bool) -> None:
    assert run_compare(a, op, b) is expected


@pytest.mark.parametrize(
    ("a", "op", "b"),
    [
        (1, "<", "2"),
        ("a", ">=", 1),
        (True, "<", 2),  # bool은 숫자가 아니다
        (None, ">", 0),
        ([1], "<", [2]),
        (Secret("a"), "<", "b"),
        (1, "contains", 1),
        ("abc", "contains", 1),
        ({"a": 1}, "contains", "a"),
    ],
)
def test_compare_type_mismatch_error(a: Any, op: str, b: Any) -> None:
    with pytest.raises(TypeError):
        run_compare(a, op, b)


def test_compare_unknown_op_error() -> None:
    with pytest.raises(ValueError, match="op"):
        run_compare(1, "=~", 1)


def run_format(template: str, values: dict[str, Any]) -> Any:
    return text_format(fake_context(pure=True), template=template, values=values).outputs["text"]


@pytest.mark.parametrize(
    ("template", "values", "expected"),
    [
        ("골드 {gold}개", {"gold": 30}, "골드 30개"),
        ("{a}-{b}-{a}", {"a": "x", "b": "y"}, "x-y-x"),
        ("{이름} 님", {"이름": "QA"}, "QA 님"),
        ("{{gold}} = {gold}", {"gold": 1}, "{gold} = 1"),
        ("}}{{", {}, "}{"),
        ("값 없음", {"unused": 1}, "값 없음"),
        ("{t} {f} {n} {x}", {"t": True, "f": False, "n": None, "x": 1.5}, "true false null 1.5"),
        ("{xs} {d}", {"xs": [1, "a"], "d": {"k": None}}, '[1, "a"] {"k": null}'),
    ],
)
def test_format_placeholders(template: str, values: dict[str, Any], expected: str) -> None:
    assert run_format(template, values) == expected


@pytest.mark.parametrize(
    "template",
    [
        "{a.b}",
        "{a[0]}",
        "{0}",
        "{}",
        "{a:>3}",
        "{a:}",  # 빈 형식 지정자도 형식 지정이다
        "{a!r}",
        "{a!}",
        "{ a }",
        "{a{b}}",
        "{a",
        "a}",
        "x}}}",
        "{a.__class__}",
    ],
)
def test_format_rejects_attribute_access(template: str) -> None:
    with pytest.raises(ValueError):
        run_format(template, {"a": "x"})


def test_format_missing_value_error() -> None:
    with pytest.raises(KeyError, match="nope"):
        run_format("{nope}", {"a": 1})


def test_format_secret_taints_output() -> None:
    text = run_format("{user}/{pw}", {"user": "qa", "pw": Secret("hunter2")})
    assert isinstance(text, Secret)
    assert text.reveal() == "qa/hunter2"
    assert str(text) == Secret.MASK
    # 쓰지 않은 값이어도, 안쪽(목록) 값이어도 비밀이면 결과가 비밀이다
    assert isinstance(run_format("x", {"pw": Secret("s")}), Secret)
    nested = run_format("{xs}", {"xs": ["a", Secret("s")]})
    assert isinstance(nested, Secret)
    assert nested.reveal() == '["a", "s"]'
    assert isinstance(run_format("{a}", {"a": "plain"}), str)


def test_var_set_get_roundtrip() -> None:
    ctx = fake_context()
    assert var_set(ctx, name="stop", value=[1, 2]).exit == "done"
    assert ctx.vars.values == {"stop": [1, 2]}
    got = var_get(ctx, name="stop").outputs["value"]
    assert got == [1, 2]
    got.append(3)  # 순수 노드가 받은 값은 복사본이다
    assert ctx.vars.values == {"stop": [1, 2]}


@pytest.mark.parametrize("default", [5, None, False, 0, "", [], {}])
def test_var_get_default(default: Any) -> None:
    # 명시적 null을 포함해 준 default는 값이다 (생략과 다르다)
    ctx = fake_context(vars={"x": 0})
    assert var_get.invoke(ctx, {"name": "missing", "default": default}).outputs == {
        "value": default
    }
    assert var_get.invoke(ctx, {"name": "x", "default": default}).outputs == {"value": 0}


def test_var_get_existing_without_default() -> None:
    ctx = fake_context(vars={"x": None})
    assert var_get.invoke(ctx, {"name": "x"}).outputs == {"value": None}


def test_var_get_missing_without_default_error() -> None:
    # default 키가 없을 때만 "기본값 없음"
    with pytest.raises(KeyError, match="missing"):
        var_get.invoke(fake_context(), {"name": "missing"})
    with pytest.raises(KeyError, match="missing"):
        var_get(fake_context(), name="missing")


def test_var_get_default_pin_is_optional_not_null_default() -> None:
    pin = var_get.schema()["inputs"]["default"]
    assert pin == {"nullable": True, "optional": True, "type": "any"}


def test_var_get_is_pure() -> None:
    # 실행기와 같은 PureContext가 걸린다: var.set은 exec 노드에서만
    ctx = fake_context(pure=True)
    with pytest.raises(PureContextViolation):
        var_set(ctx, name="a", value=1)


def test_var_set_empty_name_error() -> None:
    with pytest.raises(ValueError):
        var_set(fake_context(), name="", value=1)
