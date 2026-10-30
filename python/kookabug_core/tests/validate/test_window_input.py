"""공통 입력 `window`의 실행 전 검증 (MVP 노드 목록 "공통 입력", 구현 계획 M1 2.8).

노드 스키마에 없어도 모든 exec 노드(engine 노드·`core.graph.call` 포함)는 `in.window`를 받는다
(`unknown_input`이 아님). 값은 `window` 핀과 같은 타입 검사를 받는다. 실행기 쪽(그 스텝 ctx·입력
요청의 창, 서브그래프가 이어받는 창)은 runner 연결에서 다룬다.
"""

from __future__ import annotations

from pathlib import Path

from helpers.graphs import (
    GraphBuilder,
    check,
    link,
    make_workspace,
    subgraph_interface,
    without_flow,
)
from testkit import registry_with_testkit

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.registry import Registry
from kookabug_core.validate.pins import COMMON_WINDOW, has_common_window
from kookabug_sdk import Context, Exit, Output, Result, node
from kookabug_sdk.types import WindowRef

GRAPH = "tests/w.graph.json"


@node(
    type="winkit.window.pick",
    version=1,
    title="창 고르기",
    exits=[Exit("found", "ok")],
    outputs={"window": WindowRef, "maybe": Output(WindowRef, nullable=True)},
)
def pick(ctx: Context) -> Result:
    return Result.ok("found", window=WindowRef(1), maybe=None)


@node(type="winkit.window.use", version=1, title="창 바꾸기", exits=[Exit("done", "ok")])
def use(ctx: Context, window: str) -> Result:
    """스스로 `window` 입력(문자열)을 선언한 노드."""
    return Result.ok("done")


def registry() -> Registry:
    reg = registry_with_testkit()
    reg.add_functions("winkit", "0", [pick, use])
    return reg


def where(diags: list[Diagnostic]) -> list[tuple[str, str | None, str | None]]:
    return [(d.code, d.node, d.pointer) for d in diags]


def run(tmp_path: Path, g: GraphBuilder) -> list[Diagnostic]:
    ws = make_workspace(tmp_path)
    return without_flow(check(ws, g.write(ws, GRAPH), registry=registry()))


def graph() -> GraphBuilder:
    return (
        GraphBuilder(plugins={"testkit": "0", "winkit": "0"})
        .entry("n_pick")
        .node("n_pick", "winkit.window.pick", next={"found": "n_tap"})
        .node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 2}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_common_window_input_not_unknown(tmp_path: Path) -> None:
    g = graph()
    assert run(tmp_path, g) == []
    # 연결한 창, nullable 창, null(= 현재 대상 창) 모두 된다
    for value in (link("n_pick.window"), link("n_pick.maybe"), None):
        g.nodes["n_tap"]["in"]["window"] = value
        assert run(tmp_path, g) == [], value
    # 선언에 없는 다른 입력은 그대로 unknown_input
    g.nodes["n_tap"]["in"]["windows"] = None
    assert where(run(tmp_path, g)) == [("unknown_input", "n_tap", "/nodes/n_tap/in/windows")]


def test_common_window_input_type_checked(tmp_path: Path) -> None:
    # 다른 타입 출력(string)을 연결하면 type_mismatch
    g = graph()
    g.node("n_read", "testkit.read_text")
    g.nodes["n_tap"]["in"]["window"] = link("n_read.text")
    assert where(run(tmp_path, g)) == [("type_mismatch", "n_tap", "/nodes/n_tap/in/window")]
    # 없는 출력도 같은 핀으로 검사한다
    g.nodes["n_tap"]["in"]["window"] = link("n_pick.other")
    assert where(run(tmp_path, g)) == [("link_bad_output", "n_tap", "/nodes/n_tap/in/window")]
    # window 핀에 window·nullable window 출력은 되지만, window 출력을 다른 타입 핀에는 못 넣는다
    g.nodes["n_tap"]["in"]["window"] = link("n_pick.window")
    g.nodes["n_tap"]["in"]["x"] = link("n_pick.window")
    assert where(run(tmp_path, g)) == [("type_mismatch", "n_tap", "/nodes/n_tap/in/x")]


def test_common_window_on_all_exec_nodes_not_pure(tmp_path: Path) -> None:
    # engine 노드(흐름·판정)도 exec 노드라 받는다. 순수 노드는 exec가 없어 받지 않는다
    g = graph()
    g.node("n_get", "core.var.get", inputs={"name": "x", "window": None})
    g.node("n_rep", "core.flow.repeat", inputs={"times": 1, "window": None})
    g.nodes["n_pass"]["in"] = {"window": link("n_pick.window")}
    unknown = [d for d in run(tmp_path, g) if d.code in ("unknown_input", "type_mismatch")]
    assert where(unknown) == [("unknown_input", "n_get", "/nodes/n_get/in/window")]


def test_common_window_supported_on_graph_call(tmp_path: Path) -> None:
    # core.graph.call의 in.window = 서브그래프가 이어받을 현재 대상 창 (검수 T8_1 지적 1)
    ws = make_workspace(tmp_path)
    child = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_done")
    child.exit("n_done", "done").write(ws, "subgraphs/child.graph.json")
    parent = (
        GraphBuilder(plugins={"winkit": "0"})
        .entry("n_pick")
        .node("n_pick", "winkit.window.pick", next={"found": "n_call"})
        .call(
            "n_call", "subgraphs/child.graph.json", inputs={"window": None}, next={"done": "n_pass"}
        )
        .node("n_pass", "core.test.pass")
    )
    reg = registry()
    assert check(ws, parent.write(ws, GRAPH), registry=reg) == []
    parent.nodes["n_call"]["in"]["window"] = link("n_pick.window")
    assert check(ws, parent.write(ws, GRAPH), registry=reg) == []
    # 서브그래프 출구 노드에도 (exec 노드) 공통 window가 있다
    child.nodes["n_done"]["in"] = {"window": None}
    child.write(ws, "subgraphs/child.graph.json")
    assert check(ws, parent.write(ws, GRAPH), registry=reg) == []

    # 서브그래프가 `window`라는 입력을 가지면 그 입력이 이긴다 (string)
    named = GraphBuilder("subgraph", interface=subgraph_interface(inputs={"window": "string"}))
    named.entry("n_done").exit("n_done", "done").write(ws, "subgraphs/named.graph.json")
    parent.nodes["n_call"]["config"]["graph"] = "subgraphs/named.graph.json"
    diags = check(ws, parent.write(ws, GRAPH), registry=reg)
    assert where(diags) == [("type_mismatch", "n_call", "/nodes/n_call/in/window")]


def test_node_declaring_window_keeps_its_declaration(tmp_path: Path) -> None:
    reg = registry()
    used = reg.get("winkit.window.use")
    tap = reg.get("testkit.input.tap")
    call = reg.get("core.graph.call")
    assert used is not None and tap is not None and call is not None
    assert not has_common_window(used, {"window": COMMON_WINDOW})
    assert has_common_window(tap, {}) and has_common_window(call, {})
    g = graph()
    g.node("n_use", "winkit.window.use", inputs={"window": "Sample Game"})
    assert run(tmp_path, g) == []
    g.nodes["n_use"]["in"]["window"] = link("n_pick.window")
    assert where(run(tmp_path, g)) == [("type_mismatch", "n_use", "/nodes/n_use/in/window")]
    assert COMMON_WINDOW.type == "window" and not COMMON_WINDOW.required
