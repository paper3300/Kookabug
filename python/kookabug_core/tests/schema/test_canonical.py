import json
import math
from typing import Any

import pytest

import fmt_json
from kb_testing.doc_examples import DocBlock, json_blocks
from kookabug_core.canonical import (
    MAX_SAFE_INTEGER,
    WIDTH,
    canonical_dumps,
    is_canonical,
    json_equal,
    loads_strict,
    save_text,
)

BLOCKS = json_blocks()


@pytest.mark.parametrize("block", BLOCKS, ids=[b.id for b in BLOCKS])
def test_canonical_roundtrip_of_doc_examples_is_byte_identical(block: DocBlock) -> None:
    assert canonical_dumps(json.loads(block.text)) == block.text
    assert is_canonical(block.text)


def test_repo_json_is_canonical() -> None:
    # 메타스키마와 문서 예시 (tools/fmt_json.py --check와 같다)
    for path in fmt_json.targets():
        assert fmt_json.formatted(path) == path.read_text(encoding="utf-8"), path.name


def test_objects_always_expanded_scalar_arrays_inline() -> None:
    value = {"b": [3, 1, {"z": 1, "a": 2}], "a": {"d": [{"y": 0, "x": 0}], "c": [2, "x", None]}}
    assert canonical_dumps(value) == (
        "{\n"
        '  "a": {\n'
        '    "c": [2, "x", null],\n'
        '    "d": [\n'
        "      {\n"
        '        "x": 0,\n'
        '        "y": 0\n'
        "      }\n"
        "    ]\n"
        "  },\n"
        '  "b": [\n'
        "    3,\n"
        "    1,\n"
        "    {\n"
        '      "a": 2,\n'
        '      "z": 1\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def test_canonical_sorts_nested_keys_not_arrays() -> None:
    value = {"b": {"z": 1, "a": 2}, "a": [3, 1, 2]}
    assert canonical_dumps(value) == (
        '{\n  "a": [3, 1, 2],\n  "b": {\n    "a": 2,\n    "z": 1\n  }\n}\n'
    )


def test_key_order_is_utf16_code_units() -> None:
    # U+FFFD(BMP)와 U+1F600(서로게이트 쌍): 코드 포인트 순과 UTF-16 순이 반대다. JS 정렬을 따른다
    value = {"\U0001f600": 1, "\ufffd": 2, "a": 3}
    keys = [
        json.loads("{" + line.rstrip(",") + "}")
        for line in canonical_dumps(value).splitlines()[1:-1]
    ]
    assert [next(iter(k)) for k in keys] == ["a", "\U0001f600", "\ufffd"]


def test_canonical_root_always_expanded_and_empty_containers() -> None:
    assert canonical_dumps({"a": 1}) == '{\n  "a": 1\n}\n'
    assert canonical_dumps([1, 2]) == "[\n  1,\n  2\n]\n"
    assert canonical_dumps({}) == "{}\n"
    assert canonical_dumps({"a": {}, "b": [], "c": [[]]}) == (
        '{\n  "a": {},\n  "b": [],\n  "c": [\n    []\n  ]\n}\n'
    )
    assert canonical_dumps("x") == '"x"\n'


def test_scalar_array_wraps_at_width_counting_indent_key_and_comma() -> None:
    def line_for(n: int, last: bool) -> str:
        value = {"k": ["x" * n]} if last else {"k": ["x" * n], "z": 0}
        return canonical_dumps(value).splitlines()[1]

    fits = WIDTH - len('  "k": [""]')
    assert len(line_for(fits, last=True)) == WIDTH
    assert line_for(fits + 1, last=True) == '  "k": ['
    # 뒤에 쉼표가 붙으면 한 글자 덜 들어간다
    assert line_for(fits, last=False) == '  "k": ['
    assert len(line_for(fits - 1, last=False)) == WIDTH
    # 너비는 UTF-16 코드 단위로 센다 (서로게이트 쌍 문자는 2)
    assert line_for(fits // 2, last=True).endswith("]") is True
    emoji = {"k": ["\U0001f600" * (fits // 2 + 1)]}
    assert canonical_dumps(emoji).splitlines()[1] == '  "k": ['


def test_editing_one_value_changes_one_line() -> None:
    before = {"in": {f"p{i}": 0 for i in range(9)}}
    after = {"in": {**before["in"], "p0": "a" * 80}}
    old, new = canonical_dumps(before).splitlines(), canonical_dumps(after).splitlines()
    assert len(old) == len(new)
    assert [i for i, (a, b) in enumerate(zip(old, new, strict=True)) if a != b] == [2]


# Node `JSON.stringify` 결과 (node v24에서 뽑은 값)
JS_NUMBERS = [
    (0.85, "0.85"),
    (1.0, "1"),
    (-0.0, "0"),
    (1e-7, "1e-7"),
    (1e-6, "0.000001"),
    (0.000001234, "0.000001234"),
    (1e21, "1e+21"),
    (1.5e21, "1.5e+21"),
    (-2.5e-8, "-2.5e-8"),
    (0.1, "0.1"),
    (100.0, "100"),
    (1.25e300, "1.25e+300"),
    (5e-324, "5e-324"),
    (123.456, "123.456"),
    (1e100, "1e+100"),
    (-1e-10, "-1e-10"),
    (9007199254740991.0, "9007199254740991"),
]


@pytest.mark.parametrize(("value", "text"), JS_NUMBERS)
def test_numbers_match_javascript(value: float, text: str) -> None:
    assert canonical_dumps([value]) == f"[\n  {text}\n]\n"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1e20, "1e+20"),
        (9007199254740992.0, "9.007199254740992e+15"),
        (-(2.0**60), "-1.152921504606847e+18"),
    ],
)
def test_big_integral_floats_use_exponent(value: float, text: str) -> None:
    # JS는 정수 자릿수로 쓰지만, 다시 읽으면 범위 밖 정수가 되므로 지수 표기 (정수 범위 계약)
    out = canonical_dumps([value])
    assert out == f"[\n  {text}\n]\n"
    assert json.loads(out) == [value]
    assert canonical_dumps(json.loads(out)) == out


@pytest.mark.parametrize("value", [MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER, 0, -1])
def test_safe_integers_written(value: int) -> None:
    assert canonical_dumps([value]) == f"[\n  {value}\n]\n"


@pytest.mark.parametrize("value", [2**53, 2**53 + 1, -(2**53), 10**20])
def test_unsafe_integers_rejected(value: int) -> None:
    with pytest.raises(ValueError, match="2\\^53"):
        canonical_dumps({"x": value})


def test_strings() -> None:
    assert canonical_dumps(["월드 접속"]) == '[\n  "월드 접속"\n]\n'
    assert canonical_dumps(['a"\\\n\u0001\u2028/']) == '[\n  "a\\"\\\\\\n\\u0001\u2028/"\n]\n'
    # 짝 없는 서로게이트는 JS처럼 이스케이프한다
    assert canonical_dumps(["\ud800x"]) == '[\n  "\\ud800x"\n]\n'


@pytest.mark.parametrize("bad", [math.nan, math.inf, {1: "a"}, (1, 2), {"a": {1, 2}}, b"x"])
def test_canonical_rejects_non_json(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_dumps(bad)


GRAPH: dict[str, Any] = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "layout": {"nodes": {"n_entry": {"x": 0, "y": 0}}},
    "meta": {"tags": ["login", "smoke"], "title": "로그인/월드"},
    "nodes": {"n_entry": {"in": {"r": 0.5, "t": "월드"}, "type": "core.graph.entry", "version": 1}},
    "plugins": {"core": "0.1.0"},
}
CANONICAL = canonical_dumps(GRAPH)

# 다른 도구가 만든 같은 값의 파일들 (모두 비canonical)
EXTERNAL = {
    "json_dumps_indent2": json.dumps(GRAPH, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    "indent4": json.dumps(GRAPH, ensure_ascii=False, sort_keys=True, indent=4) + "\n",
    "compact": json.dumps(GRAPH, ensure_ascii=False, sort_keys=True) + "\n",
    "unsorted": json.dumps(dict(reversed(GRAPH.items())), ensure_ascii=False, indent=2) + "\n",
    "crlf": CANONICAL.replace("\n", "\r\n"),
    "no_final_newline": CANONICAL.rstrip("\n"),
    "trailing_space": CANONICAL.replace("\n", " \n", 1),
    "bom": "\ufeff" + CANONICAL,
    "ascii_escaped": CANONICAL.replace("월드", "\\uc6d4\\ub4dc"),
    "escaped_slash": CANONICAL.replace("로그인/월드", "로그인\\/월드"),
    "int_as_float": CANONICAL.replace('"x": 0', '"x": 0.0'),
    "exponent": CANONICAL.replace('"r": 0.5', '"r": 5e-1'),
    "duplicate_key": CANONICAL.replace('"kind": "test",', '"kind": "test",\n  "kind": "test",'),
}


def test_canonical_fixture_is_canonical() -> None:
    assert is_canonical(CANONICAL)
    assert not is_canonical("not json")
    assert not is_canonical("[\n  NaN\n]\n")


@pytest.mark.parametrize("name", sorted(EXTERNAL))
def test_external_files_not_canonical_and_normalize_idempotently(name: str) -> None:
    text = EXTERNAL[name]
    assert text != CANONICAL
    assert not is_canonical(text)
    if name in ("bom", "duplicate_key"):
        # 읽기부터 거부한다 (BOM은 JSON 텍스트가 아니다, 같은 키는 모호하다)
        with pytest.raises(ValueError):
            loads_strict(text)
        return
    value = loads_strict(text)
    assert json_equal(value, GRAPH)
    once = canonical_dumps(value)
    assert once == CANONICAL
    assert canonical_dumps(loads_strict(once)) == once


def test_save_text_keeps_original_bytes_when_value_unchanged() -> None:
    for name, text in EXTERNAL.items():
        if name in ("bom", "duplicate_key"):
            continue
        value = loads_strict(text)
        # 의미가 같으면 원문 그대로 (다시 쓰지 않는다)
        assert save_text(text, value) == text, name
        # 편집하면 파일 전체를 canonical로
        edited = json.loads(json.dumps(value))
        edited["nodes"]["n_entry"]["in"]["t"] = "로비"
        assert save_text(text, edited) == canonical_dumps(edited)
        assert is_canonical(save_text(text, edited))
    # 읽을 수 없는 원문, 새 파일
    assert save_text("\ufeff" + CANONICAL, GRAPH) == CANONICAL
    assert save_text(None, GRAPH) == CANONICAL


WORKSPACE = '{"format": "kookabug.workspace/0", "settings": {"x": %s}}'


@pytest.mark.parametrize(
    "number",
    ["1e400", "-1e400", "[1, 1e400]", '{"a": [{"b": -1e400}]}', "1.8e308", "NaN", "-Infinity"],
)
def test_loads_strict_rejects_non_finite(number: str) -> None:
    text = WORKSPACE % number
    with pytest.raises(ValueError):
        loads_strict(text)
    assert not is_canonical(text)
    # 원문을 읽을 수 없으므로 원문 보존 대상이 아니다
    assert save_text(text, {"format": "kookabug.workspace/0"}) == canonical_dumps(
        {"format": "kookabug.workspace/0"}
    )


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ("1.7976931348623157e308", 1.7976931348623157e308),
        ("-1.7976931348623157e308", -1.7976931348623157e308),
        ("1.7976931348623158e308", 1.7976931348623157e308),  # 반올림하면 최대값 (유한)
        ("1e308", 1e308),
        ("5e-324", 5e-324),
        ("1e-400", 0.0),  # 아래로 넘치면 0 (유한)
    ],
)
def test_loads_strict_keeps_finite_extremes(token: str, value: float) -> None:
    data = loads_strict(WORKSPACE % token)
    assert data["settings"]["x"] == value
    out = canonical_dumps(data)
    assert loads_strict(out) == data
    assert canonical_dumps(loads_strict(out)) == out


def test_json_equal() -> None:
    assert json_equal({"a": [1, 2.0]}, {"a": [1.0, 2]})
    assert not json_equal({"a": True}, {"a": 1})
    assert not json_equal({"a": 0}, {"a": False})
    assert not json_equal({"a": None}, {})
    assert not json_equal([1, 2], [2, 1])
    assert not json_equal("1", 1)
