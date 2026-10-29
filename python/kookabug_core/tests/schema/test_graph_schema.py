import json
import math
from typing import Any

import pytest

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import check_shape
from kookabug_core.schema.models.graph import Graph
from kookabug_core.schema.pintype import ListOf, Named, PinTypeError, Union, parse_pin_type


def minimal_test() -> dict[str, Any]:
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_entry": {"next": {"start": "n_pass"}, "type": "core.graph.entry", "version": 1},
            "n_pass": {"in": {"reason": "ok"}, "type": "core.test.pass", "version": 1},
        },
        "plugins": {"core": "0.1.0"},
    }


def with_input(value: Any) -> dict[str, Any]:
    graph = minimal_test()
    graph["nodes"]["n_pass"]["in"] = {"value": value}
    return graph


def codes(diags: list[Diagnostic]) -> list[tuple[str, str | None]]:
    return [(d.code, d.pointer) for d in diags]


VALUE = "/nodes/n_pass/in/value"


def test_minimal_test_graph_valid() -> None:
    graph = minimal_test()
    assert check_shape(graph) == []
    assert check_shape(graph, "graph") == []
    model = Graph.model_validate(graph)
    assert model.kind == "test"
    assert set(model.nodes) == {"n_entry", "n_pass"}


def test_format_selects_kind_and_unknown_format_is_reported() -> None:
    assert codes(check_shape({"format": "kookabug.graph/9"})) == [("format_unknown", "/format")]
    assert codes(check_shape([1])) == [("format_unknown", "")]
    # 종류를 정해 주면 format 값이 틀린 것을 그대로 알린다
    bad = minimal_test() | {"format": "kookabug.target/0"}
    assert codes(check_shape(bad, "graph")) == [("invalid_value", "/format")]


def test_subgraph_requires_interface() -> None:
    graph = minimal_test() | {"kind": "subgraph"}
    diags = check_shape(graph)
    assert codes(diags) == [("missing_field", "")]
    assert "interface" in diags[0].message

    graph["interface"] = {"exits": {"success": {"kind": "ok"}}}
    assert check_shape(graph) == []

    # 서브그래프의 끝은 공개 exit이므로 출구가 하나 이상 필요하다
    graph["interface"] = {"exits": {}}
    assert codes(check_shape(graph)) == [("out_of_range", "/interface/exits")]
    graph["interface"] = {"inputs": {}}
    assert codes(check_shape(graph)) == [("missing_field", "/interface")]


def test_unknown_node_field_rejected() -> None:
    graph = minimal_test()
    graph["nodes"]["n_pass"]["bogus"] = 1
    diags = check_shape(graph)
    assert codes(diags) == [("unknown_field", "/nodes/n_pass/bogus")]
    assert diags[0].node == "n_pass"
    assert "bogus" in diags[0].message

    graph = minimal_test() | {"edges": []}
    assert codes(check_shape(graph)) == [("unknown_field", "/edges")]

    # config는 노드마다 다르므로 모르는 키를 형식 단계에서 막지 않는다
    graph = minimal_test()
    graph["nodes"]["n_pass"]["config"] = {"anything": {"$foo": 1}}
    assert check_shape(graph) == []


def test_missing_node_type_and_version() -> None:
    graph = minimal_test()
    graph["nodes"]["n_pass"] = {"title": "x"}
    assert codes(check_shape(graph)) == [
        ("missing_field", "/nodes/n_pass"),
        ("missing_field", "/nodes/n_pass"),
    ]
    graph["nodes"]["n_pass"] = {"type": "Core.Test", "version": 0}
    assert codes(check_shape(graph)) == [
        ("pattern_mismatch", "/nodes/n_pass/type"),
        ("out_of_range", "/nodes/n_pass/version"),
    ]


@pytest.mark.parametrize(
    "value",
    [
        {"$link": "n_entry.account"},
        {"$target": "targets/login/account_field.target.json"},
        {"$setting": "game.executable"},
        {"$secret": "accounts.qa_tester_01"},
        {"$literal": {"$link": "not.a.link"}},
    ],
)
def test_special_values_allowed(value: dict[str, Any]) -> None:
    assert check_shape(with_input(value)) == []


def test_special_values_closed_list() -> None:
    diags = check_shape(with_input({"$foo": "x"}))
    assert codes(diags) == [("special_value_unknown", VALUE + "/$foo")]
    assert "$literal" in diags[0].message
    # 오타도 모르는 태그로 잡힌다 (조용히 일반 객체가 되지 않는다)
    assert codes(check_shape(with_input({"$lnik": "n_entry.account"}))) == [
        ("special_value_unknown", VALUE + "/$lnik")
    ]


@pytest.mark.parametrize(
    "value",
    [
        {"$link": "n_entry.account", "x": 1},
        {"x": 1, "$target": "targets/a.target.json"},
        {"$link": "n_entry.account", "$secret": "a.b"},
    ],
)
def test_dollar_key_mixed_with_plain_keys_rejected(value: dict[str, Any]) -> None:
    diags = check_shape(with_input(value))
    assert codes(diags) == [("special_value_mixed", VALUE)]
    assert "$literal" in diags[0].message


def test_literal_content_not_inspected() -> None:
    inner = {"$foo": [1, {"$link": "bad..link"}], "x": {"$target": 3}, "$link": None}
    assert check_shape(with_input({"$literal": inner})) == []
    for anything in (None, 1, "s", [], {}, [{"$x": 1}]):
        assert check_shape(with_input({"$literal": anything})) == []


def test_plain_values_allowed() -> None:
    for value in (None, True, 3, 0.5, "text", [], {}, [1, "a", None], {"a": {"b": [1]}}):
        assert check_shape(with_input(value)) == []


def test_nested_special_values_allowed() -> None:
    value = {
        "error": {"$target": "targets/login/error_popup.target.json"},
        "lobby": {"$link": "n_entry.lobby"},
        "list": [{"$setting": "game.server"}, [{"$secret": "a.b"}]],
        "deep": {"a": {"b": {"$literal": {"$x": 1}}}},
    }
    graph = with_input(value)
    graph["nodes"]["n_pass"]["in"] = {"targets": value}
    assert check_shape(graph) == []

    # 안쪽의 잘못된 특수 값도 정확한 위치로 알린다
    graph["nodes"]["n_pass"]["in"] = {"targets": {"error": {"$target": "x.png"}}}
    assert codes(check_shape(graph)) == [
        ("pattern_mismatch", "/nodes/n_pass/in/targets/error/$target")
    ]
    graph["nodes"]["n_pass"]["in"] = {"targets": [[{"$bad": 1}]]}
    assert codes(check_shape(graph)) == [
        ("special_value_unknown", "/nodes/n_pass/in/targets/0/0/$bad")
    ]


def test_node_id_with_dot_rejected() -> None:
    graph = minimal_test()
    graph["nodes"]["n.pass"] = graph["nodes"].pop("n_pass")
    graph["nodes"]["n_entry"]["next"] = {"start": "n.pass"}
    graph["layout"] = {"nodes": {"n.pass": {"x": 0, "y": 0}}}
    diags = check_shape(graph)
    assert codes(diags) == [
        ("invalid_key", "/layout/nodes/n.pass"),
        ("invalid_key", "/nodes/n.pass"),
        ("pattern_mismatch", "/nodes/n_entry/next/start"),
    ]
    assert diags[1].node == "n.pass"


@pytest.mark.parametrize("node_id", ["n_a", "N1", "_x", "n-1", "a" * 64])
def test_node_id_allowed(node_id: str) -> None:
    graph = minimal_test()
    graph["nodes"][node_id] = graph["nodes"].pop("n_pass")
    graph["nodes"]["n_entry"]["next"] = {"start": node_id}
    assert check_shape(graph) == []


@pytest.mark.parametrize("node_id", ["1a", "-a", "a b", "a" * 65, ""])
def test_node_id_rejected(node_id: str) -> None:
    graph = minimal_test()
    graph["nodes"][node_id] = graph["nodes"].pop("n_pass")
    assert ("invalid_key", f"/nodes/{node_id}") in codes(check_shape(graph))


@pytest.mark.parametrize("link", ["n_wait_title.match", "n-1.out_2", "_a._b"])
def test_link_format_allowed(link: str) -> None:
    assert check_shape(with_input({"$link": link})) == []


@pytest.mark.parametrize(
    "link", ["n_wait_title", "n_a.", ".match", "a.b.c", "a.Match", "a b.c", "a.b c", ""]
)
def test_link_format(link: str) -> None:
    assert codes(check_shape(with_input({"$link": link}))) == [
        ("pattern_mismatch", VALUE + "/$link")
    ]


PIN_TYPES_OK = [
    "list[dict[str,int]]",
    "string|secret",
    "unreal.ActorRef",
    "any",
    "list[string|secret]",
    "dict[str,list[unreal.ActorRef]]|int",
    "list[list[list[list[float]]]]",
]
PIN_TYPES_BAD = [
    "list[",
    "foo",
    "list[int",
    "list[int]]",
    "list[]",
    "dict[str, int]",
    "dict[int,str]",
    "string|",
    "|string",
    "string|string",
    "Unreal.ActorRef",
    "unreal.actorRef",
    "list",
    "",
]


def graph_with_input_type(pin_type: str) -> dict[str, Any]:
    graph = minimal_test() | {"kind": "subgraph"}
    graph["interface"] = {
        "exits": {"done": {"kind": "ok"}},
        "inputs": {"a": {"type": pin_type}},
        "outputs": {"b": {"nullable": True, "type": pin_type}},
    }
    return graph


@pytest.mark.parametrize("pin_type", PIN_TYPES_OK)
def test_pin_type_grammar(pin_type: str) -> None:
    assert check_shape(graph_with_input_type(pin_type)) == []
    assert str(parse_pin_type(pin_type)) == pin_type


@pytest.mark.parametrize("pin_type", PIN_TYPES_BAD)
def test_pin_type_grammar_rejects(pin_type: str) -> None:
    diags = check_shape(graph_with_input_type(pin_type))
    assert codes(diags) == [
        ("invalid_pin_type", "/interface/inputs/a/type"),
        ("invalid_pin_type", "/interface/outputs/b/type"),
    ]
    with pytest.raises(PinTypeError):
        parse_pin_type(pin_type)


def test_pin_type_parse_tree() -> None:
    assert parse_pin_type("list[string|secret]") == ListOf(
        Union((Named("string"), Named("secret")))
    )


def test_record_field_shape() -> None:
    graph = minimal_test()
    graph["record"] = {"screenshots": "off", "video": "off"}
    graph["nodes"]["n_pass"]["record"] = {"video": "failed_only"}
    assert check_shape(graph) == []

    graph["record"] = {"screenshots": "failed_only", "video": "sometimes", "audio": "off"}
    graph["nodes"]["n_pass"]["record"] = "off"
    assert codes(check_shape(graph)) == [
        ("wrong_type", "/nodes/n_pass/record"),
        ("unknown_field", "/record/audio"),
        ("invalid_value", "/record/screenshots"),
        ("invalid_value", "/record/video"),
    ]


def test_retry_config_shape() -> None:
    graph = minimal_test()
    config = graph["nodes"]["n_pass"]["config"] = {"retry": {"max_attempts": 2, "on": ["timeout"]}}
    assert check_shape(graph) == []
    config["retry"] = {"max_attempts": 0, "on": [], "delay": 1}
    assert codes(check_shape(graph)) == [
        ("unknown_field", "/nodes/n_pass/config/retry/delay"),
        ("out_of_range", "/nodes/n_pass/config/retry/max_attempts"),
        ("out_of_range", "/nodes/n_pass/config/retry/on"),
    ]
    config["retry"] = {"on": ["timeout", "timeout"]}
    assert codes(check_shape(graph)) == [
        ("missing_field", "/nodes/n_pass/config/retry"),
        ("duplicate_item", "/nodes/n_pass/config/retry/on"),
    ]


def _newline_case(case: str, end: str) -> tuple[dict[str, Any], tuple[str, str]]:
    graph = minimal_test()
    node = graph["nodes"]["n_pass"]
    match case:
        case "node_id":
            graph["nodes"][f"n_pass{end}"] = graph["nodes"].pop("n_pass")
            graph["nodes"]["n_entry"]["next"] = {}
            return graph, ("invalid_key", f"/nodes/n_pass{end}")
        case "input_name":
            node["in"] = {f"text{end}": "sample"}
            return graph, ("invalid_key", f"/nodes/n_pass/in/text{end}")
        case "node_type":
            node["type"] += end
            return graph, ("pattern_mismatch", "/nodes/n_pass/type")
        case "link":
            node["in"] = {"text": {"$link": f"n_entry.value{end}"}}
            return graph, ("pattern_mismatch", "/nodes/n_pass/in/text/$link")
        case _:
            node["in"] = {"text": {"$setting": f"game.server{end}"}}
            return graph, ("pattern_mismatch", "/nodes/n_pass/in/text/$setting")


@pytest.mark.parametrize("end", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("case", ["node_id", "input_name", "node_type", "link", "setting"])
def test_identifier_with_trailing_newline_rejected(case: str, end: str) -> None:
    graph, expected = _newline_case(case, end)
    assert codes(check_shape(graph)) == [expected]


@pytest.mark.parametrize("case", ["node_id", "input_name", "node_type", "link", "setting"])
def test_identifier_without_newline_parses_into_model(case: str) -> None:
    graph, _ = _newline_case(case, "")
    assert check_shape(graph) == []
    Graph.model_validate(graph)


def test_trailing_newline_rejected_in_other_files() -> None:
    workspace = {"format": "kookabug.workspace/0", "settings": {"game.server\n": 1}}
    assert codes(check_shape(workspace)) == [("invalid_key", "/settings/game.server\n")]
    local = {"format": "kookabug.local/0", "settings": {"a\n": 1}}
    assert codes(check_shape(local)) == [("invalid_key", "/settings/a\n")]
    nodes = {
        "format": "kookabug.nodes/0",
        "nodes": [{"exits": [], "title": "t", "type": "core.x\n", "version": 1}],
        "plugin": {"id": "core\n", "version": "0.1.0"},
    }
    assert codes(check_shape(nodes)) == [
        ("pattern_mismatch", "/nodes/0/type"),
        ("pattern_mismatch", "/plugin/id"),
    ]
    # 문자열 중간·앞의 줄바꿈도 (원래부터) 거부된다
    graph = graph_with_input_type("string\n")
    assert ("invalid_pin_type", "/interface/inputs/a/type") in codes(check_shape(graph))


@pytest.mark.parametrize(
    "number", [2**53 - 1, -(2**53 - 1), 1.0, 1e20, 1e300, 9007199254740993.0, -2.5e-8, 0]
)
def test_numbers_inside_safe_range_or_float_allowed(number: Any) -> None:
    graph = with_input({"n": number, "list": [number]})
    graph["layout"] = {"nodes": {"n_pass": {"x": number, "y": 0}}}
    assert check_shape(graph) == []


@pytest.mark.parametrize("number", [2**53, 2**53 + 1, -(2**53), 10**30])
def test_integer_out_of_safe_range_rejected(number: int) -> None:
    graph = with_input({"n": number, "list": [1, number]})
    graph["nodes"]["n_pass"]["config"] = {"limit": number}
    graph["layout"] = {"nodes": {"n_pass": {"x": number, "y": 0}}}
    diags = check_shape(graph)
    assert codes(diags) == [
        ("number_out_of_range", "/layout/nodes/n_pass/x"),
        ("number_out_of_range", "/nodes/n_pass/config/limit"),
        ("number_out_of_range", "/nodes/n_pass/in/value/list/1"),
        ("number_out_of_range", "/nodes/n_pass/in/value/n"),
    ]
    assert diags[1].node == "n_pass"
    assert "2^53" in diags[0].message


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_non_finite_numbers_from_program_rejected(bad: float) -> None:
    # 파일은 loads_strict가 막고, 프로그램이 직접 넘긴 dict는 형식 검사가 막는다
    graph = with_input({"n": bad, "list": [1.5, bad]})
    graph["nodes"]["n_pass"]["config"] = {"limit": bad}
    graph["layout"] = {"nodes": {"n_pass": {"x": bad, "y": 0}}}
    diags = check_shape(graph)
    assert codes(diags) == [
        ("number_not_finite", "/layout/nodes/n_pass/x"),
        ("number_not_finite", "/nodes/n_pass/config/limit"),
        ("number_not_finite", "/nodes/n_pass/in/value/list/1"),
        ("number_not_finite", "/nodes/n_pass/in/value/n"),
    ]
    assert diags[1].node == "n_pass"
    settings = {"format": "kookabug.workspace/0", "settings": {"a": {"b": [bad]}}}
    assert codes(check_shape(settings)) == [("number_not_finite", "/settings/a/b/0")]
    # 유한한 최대값은 그대로 통과
    assert check_shape(with_input(1.7976931348623157e308)) == []


def test_integer_range_from_json_text() -> None:
    # 원문 JSON에서 읽은 값 기준: 정수 표기만 제한하고, 실수·지수 표기는 그대로 허용한다
    for text, ok in [
        ("9007199254740991", True),
        ("9007199254740992", False),
        ("9007199254740993", False),
        ("-9007199254740992", False),
        ("1.0", True),
        ("1e20", True),
        ("9007199254740993.0", True),
    ]:
        graph = with_input(json.loads(text))
        assert (check_shape(graph) == []) is ok, text
    for kind, data in [
        ("target", {"format": "kookabug.target/0", "image": "a.png", "recorded": {"dpi": 2**53}}),
        ("workspace", {"format": "kookabug.workspace/0", "settings": {"a": 2**60}}),
        ("local", {"format": "kookabug.local/0", "settings": {"a": [-(2**60)]}}),
    ]:
        assert {d.code for d in check_shape(data)} == {"number_out_of_range"}, kind


def test_diagnostics_carry_file_and_sorted() -> None:
    graph = minimal_test()
    graph["nodes"]["n_pass"]["zzz"] = 1
    graph["nodes"]["n_entry"]["aaa"] = 1
    diags = check_shape(graph, file="tests/a.graph.json")
    assert [d.pointer for d in diags] == ["/nodes/n_entry/aaa", "/nodes/n_pass/zzz"]
    assert {d.file for d in diags} == {"tests/a.graph.json"}
    assert {d.severity for d in diags} == {"error"}
