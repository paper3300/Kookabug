"""구조·값·타입 검사. 코드마다 최소 그래프 하나로 진단 코드·위치를 정확히 비교한다."""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import (
    GraphBuilder,
    check,
    check_program,
    link,
    make_workspace,
    secret,
    setting,
    subgraph_interface,
    target,
    without_flow,
    write_target,
)
from testkit import registry_with_testkit

from kookabug_core.codes import CODES
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema.pintype import parse_pin_type
from kookabug_core.validate.context import ValidationContext
from kookabug_core.validate.types import assignable
from kookabug_core.workspace import Workspace

GRAPH = "tests/a.graph.json"
SUB = "subgraphs/s.graph.json"


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.node, d.pointer) for d in diags]


def run(tmp_path: Path, g: GraphBuilder, rel: str = GRAPH, **ws_kw: Any) -> list[Diagnostic]:
    ws = make_workspace(tmp_path, **ws_kw)
    diags = check(ws, g.write(ws, rel), registry=registry_with_testkit(), secrets={"pw": "x"})
    return without_flow(diags)


def valid() -> GraphBuilder:
    """진단이 없는 기준 그래프. 각 테스트는 여기서 하나만 망가뜨린다."""
    return (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_wait")
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "title"}, next={"found": "n_set"})
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "seen", "value": link("n_wait.match")},
            next={"done": "n_check"},
        )
        .node("n_get", "core.var.get", inputs={"name": "seen"})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_get.value"), "op": "!=", "b": None},
            next={"ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def test_valid_graph_has_no_diagnostics(tmp_path: Path) -> None:
    assert run(tmp_path, valid()) == []


def test_code_table_covers_plan_codes() -> None:
    # 구현 계획 M0a T5 "검증 규칙"의 코드 전부
    plan = {
        *("entry_count", "unknown_node_type", "node_version_mismatch", "plugin_not_declared"),
        *("unknown_input", "missing_required_input", "unknown_exit", "dangling_next"),
        *("config_invalid", "kind_folder_mismatch"),
        *("setting_missing", "setting_null", "secret_missing", "target_missing"),
        *("target_invalid", "link_bad_node", "link_bad_output", "type_mismatch"),
        *("call_target_missing", "call_target_not_subgraph", "call_cycle", "call_depth"),
        *("terminal_in_subgraph", "graph_exit_in_test", "exit_name_unknown"),
        *("exit_missing_required_output", "interface_exit_unused"),
        *("retry_not_allowed", "retry_exit_not_allowed", "retry_max_attempts", "var_never_set"),
    }
    assert plan <= set(CODES)
    warnings = {c for c, info in CODES.items() if info.severity == "warning"}
    assert warnings == {
        *("kind_folder_mismatch", "interface_exit_unused", "var_never_set"),
        "unconnected_ok_exit",  # T6
    }


# ---------------------------------------------------------------- 구조


@pytest.mark.parametrize("count", [0, 2])
def test_entry_count(tmp_path: Path, count: int) -> None:
    g = valid()
    if count == 0:
        del g.nodes["n_entry"]
    else:
        g.entry("n_wait", node_id="n_entry2")
    assert where(run(tmp_path, g)) == [("entry_count", None, "/nodes")]


def test_unknown_node_type(tmp_path: Path) -> None:
    g = valid().node("n_x", "core.flow.teleport")
    assert where(run(tmp_path, g)) == [("unknown_node_type", "n_x", "/nodes/n_x/type")]


def test_node_version_mismatch(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["version"] = 2
    g.nodes["n_set"]["in"]["bogus"] = 1  # 버전이 다르면 핀 검사는 하지 않는다
    assert where(run(tmp_path, g)) == [("node_version_mismatch", "n_set", "/nodes/n_set/version")]


def test_plugin_not_declared(tmp_path: Path) -> None:
    g = valid()
    del g.plugins["testkit"]
    assert where(run(tmp_path, g)) == [("plugin_not_declared", "n_wait", "/nodes/n_wait/type")]


def test_unknown_input(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["in"]["timeout_ms"] = 1000  # G13: 기다리지 않는 노드에는 없는 입력
    assert where(run(tmp_path, g)) == [("unknown_input", "n_set", "/nodes/n_set/in/timeout_ms")]


def test_missing_required_input(tmp_path: Path) -> None:
    g = valid()
    del g.nodes["n_wait"]["in"]["expect"]
    diags = run(tmp_path, g)
    assert where(diags) == [("missing_required_input", "n_wait", "/nodes/n_wait/in")]
    assert "'expect'" in diags[0].message


def test_optional_and_default_inputs_not_required(tmp_path: Path) -> None:
    # var.get.default는 optional, observe.wait.timeout_ms는 기본값이 있다
    g = valid()
    assert "default" not in g.nodes["n_get"]["in"]
    assert "timeout_ms" not in g.nodes["n_wait"]["in"]
    assert run(tmp_path, g) == []


def test_input_invalid(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_check"]["in"]["op"] = "=~"
    g.node("n_rep", "core.flow.repeat", inputs={"times": -1})
    diags = run(tmp_path, g)
    assert where(diags) == [
        ("input_invalid", "n_check", "/nodes/n_check/in/op"),
        ("input_invalid", "n_rep", "/nodes/n_rep/in/times"),
    ]


def test_unknown_exit(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["next"]["missing"] = "n_pass"
    g.nodes["n_pass"]["next"] = {"done": "n_set"}  # 종료 노드는 출구가 없다
    assert where(run(tmp_path, g)) == [
        ("unknown_exit", "n_pass", "/nodes/n_pass/next/done"),
        ("unknown_exit", "n_wait", "/nodes/n_wait/next/missing"),
    ]


def test_pure_node_has_no_exits(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_get"]["next"] = {"done": "n_pass"}
    assert where(run(tmp_path, g)) == [("unknown_exit", "n_get", "/nodes/n_get/next/done")]


def test_exec_into_pure(tmp_path: Path) -> None:
    # 순수 노드는 exec 핀이 없다: exec 흐름이 순수 노드로 들어가면 오류 (스키마 v0 7장)
    g = (
        GraphBuilder()
        .entry("n_cmp")
        .node("n_cmp", "core.logic.compare", inputs={"a": 1, "op": "==", "b": 1})
        .node("n_check", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    )
    g.nodes["n_check"]["next"] = {"ok": "n_cmp", "fail": "n_check2"}
    g.node("n_check2", "core.var.get", inputs={"name": "x", "default": 0})
    diags = run(tmp_path, g)
    assert where([d for d in diags if d.severity == "error"]) == [
        ("exec_into_pure", "n_check", "/nodes/n_check/next/fail"),
        ("exec_into_pure", "n_check", "/nodes/n_check/next/ok"),
        ("exec_into_pure", "n_entry", "/nodes/n_entry/next/start"),
    ]


def choose(config: dict[str, Any] | None, next: dict[str, str]) -> GraphBuilder:
    return (
        GraphBuilder(plugins={"testkit": "0"})
        .entry("n_choose")
        .node("n_choose", "testkit.flow.choose", config=config, next=next)
        .node("n_pass", "core.test.pass")
    )


def test_dynamic_exits_use_config_default(tmp_path: Path) -> None:
    # config를 생략하면 기본값(["done"])으로 출구를 만든다. 명시한 것과 핀·진단이 같아야 한다
    results = []
    for i, config in enumerate([None, {"exits": ["done"]}]):
        ws = make_workspace(tmp_path / str(i))
        rel = choose(config, {"done": "n_pass", "typo": "n_pass"}).write(ws, GRAPH)
        program, diags = check_program(ws, rel, registry=registry_with_testkit())
        graph = program.graphs[GRAPH]
        ctx = ValidationContext(program, registry_with_testkit())
        pins = ctx.pins(graph, graph.nodes["n_choose"])
        assert pins is not None and pins.exits is not None
        results.append((sorted(pins.exits), where(diags)))
    assert (
        results[0]
        == results[1]
        == (
            ["done", "failed"],
            [("unknown_exit", "n_choose", "/nodes/n_choose/next/typo")],
        )
    )


def test_dynamic_exits_given_config_replaces_default(tmp_path: Path) -> None:
    g = choose({"exits": ["left", "right"]}, {"left": "n_pass", "done": "n_pass"})
    assert where(run(tmp_path, g)) == [("unknown_exit", "n_choose", "/nodes/n_choose/next/done")]


def test_dynamic_exit_names_must_be_unique_and_not_fixed(tmp_path: Path) -> None:
    g = choose({"exits": ["done", "done", "failed", "Bad"]}, {"done": "n_pass"})
    assert where(run(tmp_path, g)) == [
        ("config_invalid", "n_choose", "/nodes/n_choose/config/exits/1"),
        ("config_invalid", "n_choose", "/nodes/n_choose/config/exits/2"),
        ("config_invalid", "n_choose", "/nodes/n_choose/config/exits/3"),
    ]


def test_dangling_next(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_check"]["next"]["ok"] = "n_gone"
    assert where(run(tmp_path, g)) == [("dangling_next", "n_check", "/nodes/n_check/next/ok")]


def test_config_invalid(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["config"] = {"colour": "red"}
    g.node("n_call", "core.graph.call")  # config.graph 필수
    g.node("n_exit", "core.graph.exit", config={"exit": 3})
    diags = [d for d in run(tmp_path, g) if d.code == "config_invalid"]
    assert where(diags) == [
        ("config_invalid", "n_call", "/nodes/n_call/config"),
        ("config_invalid", "n_exit", "/nodes/n_exit/config/exit"),
        ("config_invalid", "n_set", "/nodes/n_set/config/colour"),
    ]


def test_retry_key_is_not_config_invalid(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["config"] = {"retry": {"max_attempts": 2}}
    assert run(tmp_path, g) == []


@pytest.mark.parametrize(
    ("rel", "kind"), [("subgraphs/t.graph.json", "test"), ("tests/s.graph.json", "subgraph")]
)
def test_kind_folder_mismatch(tmp_path: Path, rel: str, kind: str) -> None:
    if kind == "test":
        g = valid()
    else:
        g = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_exit")
        g.exit("n_exit", "done")
    diags = run(tmp_path, g, rel)
    assert [(d.code, d.severity, d.pointer) for d in diags] == [
        ("kind_folder_mismatch", "warning", "/kind")
    ]


def test_other_folders_have_no_kind_rule(tmp_path: Path) -> None:
    assert run(tmp_path, valid(), "misc/a.graph.json") == []


# ---------------------------------------------------------------- 값


def test_setting_missing(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["in"]["expect"] = setting("ui.title")
    assert where(run(tmp_path, g)) == [("setting_missing", "n_wait", "/nodes/n_wait/in/expect")]


def test_setting_null(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["in"]["expect"] = setting("ui.title")
    diags = run(tmp_path, g, settings={"ui.title": None})
    assert where(diags) == [("setting_null", "n_wait", "/nodes/n_wait/in/expect")]


def test_setting_value_is_type_checked(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["in"]["expect"] = setting("ui.title")
    diags = run(tmp_path, g, settings={"ui.title": 3})
    assert where(diags) == [("type_mismatch", "n_wait", "/nodes/n_wait/in/expect")]


def test_secret_missing(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["in"]["value"] = secret("nope")
    assert where(run(tmp_path, g)) == [("secret_missing", "n_set", "/nodes/n_set/in/value")]


def test_target_missing(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["in"]["value"] = {"list": [target("targets/none.target.json")]}
    assert where(run(tmp_path, g)) == [("target_missing", "n_set", "/nodes/n_set/in/value/list/0")]


def test_target_invalid(tmp_path: Path) -> None:
    write_target(tmp_path, "targets/a.target.json", match={"threshold": 3})
    g = valid()
    g.nodes["n_set"]["in"]["value"] = target("targets/a.target.json")
    diags = run(tmp_path, g)
    assert where(diags) == [("target_invalid", "n_set", "/nodes/n_set/in/value")]
    assert "/match/threshold" in diags[0].message


def test_link_bad_node(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["in"]["value"] = link("n_nowhere.match")
    assert where(run(tmp_path, g)) == [("link_bad_node", "n_set", "/nodes/n_set/in/value")]


def test_link_bad_output(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_set"]["in"]["value"] = link("n_wait.matches")
    g.nodes["n_check"]["in"]["b"] = {"x": [link("n_entry.anything")]}  # 테스트 entry는 출력 없음
    assert where(run(tmp_path, g)) == [
        ("link_bad_output", "n_check", "/nodes/n_check/in/b/x/0"),
        ("link_bad_output", "n_set", "/nodes/n_set/in/value"),
    ]


# ---------------------------------------------------------------- 타입


def test_type_mismatch(tmp_path: Path) -> None:
    g = valid()
    g.nodes["n_wait"]["in"]["timeout_ms"] = "1s"  # 상수
    g.nodes["n_wait"]["in"]["poll_ms"] = 1.5  # float → int 안 됨
    g.node("n_branch", "core.flow.branch", inputs={"condition": link("n_wait.match")})  # 연결
    g.node("n_rep", "core.flow.repeat", inputs={"times": None})  # nullable 아님
    assert where(run(tmp_path, g)) == [
        ("type_mismatch", "n_branch", "/nodes/n_branch/in/condition"),
        ("type_mismatch", "n_rep", "/nodes/n_rep/in/times"),
        ("type_mismatch", "n_wait", "/nodes/n_wait/in/poll_ms"),
        ("type_mismatch", "n_wait", "/nodes/n_wait/in/timeout_ms"),
    ]


def test_type_mismatch_inside_containers(tmp_path: Path) -> None:
    g = valid()
    # text.format.values는 dict[str,any]: 안쪽은 아무것이나, 바깥은 dict여야 한다
    g.node("n_fmt", "core.text.format", inputs={"template": "{a}", "values": [1]})
    g.node("n_fmt2", "core.text.format", inputs={"template": "{a}", "values": {"a": secret("pw")}})
    assert where(run(tmp_path, g)) == [("type_mismatch", "n_fmt", "/nodes/n_fmt/in/values")]


def sub_with_types(source: str, sink: str, ws: Workspace) -> None:
    """entry 출력(`source`) → exit 입력(`sink`)을 잇는 서브그래프."""
    iface = subgraph_interface(inputs={"x": source}, outputs={"y": sink})
    (
        GraphBuilder("subgraph", interface=iface)
        .entry("n_exit")
        .exit("n_exit", "done", inputs={"y": link("n_entry.x")})
        .write(ws, SUB)
    )


def test_secret_to_string_pin_rejected(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_with_types("secret", "string", ws)
    g = valid()
    g.nodes["n_set"]["in"]["value"] = 1
    g.node("n_log", "testkit.read_text", inputs={"text": secret("pw")})  # $secret → string
    g.write(ws, GRAPH)
    diags = check(ws, GRAPH, registry=registry_with_testkit(), secrets={"pw": "x"})
    diags = without_flow(diags)
    assert where(diags) == [("type_mismatch", "n_log", "/nodes/n_log/in/text")]
    assert "secret" in diags[0].message

    diags = check(ws, SUB, registry=registry_with_testkit())
    assert where(diags) == [("type_mismatch", "n_exit", "/nodes/n_exit/in/y")]
    assert "비밀값" in diags[0].message


def test_secret_to_string_or_secret_pin_allowed(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub_with_types("secret", "string|secret", ws)
    assert check(ws, SUB, registry=registry_with_testkit()) == []
    g = valid().node("n_log", "core.log.message", inputs={"text": secret("pw")})
    g.write(ws, GRAPH)
    assert check(ws, GRAPH, registry=registry_with_testkit(), secrets={"pw": "x"}) == []


@pytest.mark.parametrize(
    ("source", "sink", "ok"),
    [
        ("int", "int", True),
        ("int", "float", True),
        ("float", "int", False),
        ("bool", "int", False),
        ("string", "any", True),
        ("secret", "any", True),
        ("any", "int", True),
        ("secret", "string", False),
        ("string", "secret", False),
        ("secret", "string|secret", True),
        ("string|secret", "string", False),
        ("string|secret", "string|secret", True),
        ("int|string", "float|string", True),
        ("list[int]", "list[float]", True),
        ("list[float]", "list[int]", False),
        ("list[int]", "list[any]", True),
        ("list[secret]", "list[string]", False),
        ("dict[str,int]", "dict[str,any]", True),
        ("dict[str,int]", "list[int]", False),
        ("list[dict[str,int]]", "list[dict[str,float]]", True),
        ("target", "target", True),
        ("target", "string", False),
        ("unreal.ActorRef", "unreal.ActorRef", True),
        ("unreal.ActorRef", "unreal.Other", False),
    ],
)
def test_link_type_rules(tmp_path: Path, source: str, sink: str, ok: bool) -> None:
    assert assignable(parse_pin_type(source), parse_pin_type(sink)) is ok
    ws = make_workspace(tmp_path)
    sub_with_types(source, sink, ws)
    diags = check(ws, SUB, registry=registry_with_testkit())
    assert [d.code for d in diags] == ([] if ok else ["type_mismatch"])


def test_null_constant_only_for_nullable_or_any(tmp_path: Path) -> None:
    g = valid()
    g.node("n_fail", "core.test.fail", inputs={"reason": None})  # nullable string
    g.node("n_cmp", "core.logic.compare", inputs={"a": None, "op": "==", "b": [None]})  # any
    assert run(tmp_path, g) == []


def test_interface_input_default_type_checked(tmp_path: Path) -> None:
    iface = subgraph_interface(inputs={"n": {"type": "int", "default": "x"}})
    g = GraphBuilder("subgraph", interface=iface).entry("n_exit").exit("n_exit", "done")
    diags = run(tmp_path, g, SUB)
    assert where(diags) == [("type_mismatch", None, "/interface/inputs/n/default")]
