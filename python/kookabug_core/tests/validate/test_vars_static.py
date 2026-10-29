from pathlib import Path

from helpers.graphs import GraphBuilder, check, link, make_workspace, subgraph_interface


def test_var_never_set_warning(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = (
        GraphBuilder()
        .entry("n_set")
        .node("n_set", "core.var.set", inputs={"name": "stop", "value": True})
        .node("n_get_ok", "core.var.get", inputs={"name": "stop"})
        .node("n_get_typo", "core.var.get", inputs={"name": "stopp"})
        .node("n_get_default", "core.var.get", inputs={"name": "count", "default": 0})
        # 이름이 연결이면 정적으로 알 수 없어 경고하지 않는다
        .node("n_get_dyn", "core.var.get", inputs={"name": link("n_get_ok.value")})
    )
    diags = check(ws, g.write(ws, "tests/v.graph.json"))
    assert [(d.code, d.severity, d.node, d.pointer) for d in diags] == [
        ("var_never_set", "warning", "n_get_default", "/nodes/n_get_default/in/name"),
        ("var_never_set", "warning", "n_get_typo", "/nodes/n_get_typo/in/name"),
    ]


def test_var_set_in_other_graph_does_not_count(tmp_path: Path) -> None:
    # 서브그래프는 새 프레임이라 호출한 쪽 변수를 이어받지 않는다
    ws = make_workspace(tmp_path)
    (
        GraphBuilder("subgraph", interface=subgraph_interface(outputs={"v": "any"}))
        .entry("n_exit")
        .node("n_get", "core.var.get", inputs={"name": "stop"})
        .exit("n_exit", "done", inputs={"v": link("n_get.value")})
        .write(ws, "subgraphs/s.graph.json")
    )
    g = (
        GraphBuilder()
        .entry("n_set")
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "stop", "value": True},
            next={"done": "n_call"},
        )
        .call("n_call", "subgraphs/s.graph.json", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    diags = check(ws, g.write(ws, "tests/v.graph.json"))
    assert [(d.code, d.file, d.node) for d in diags] == [
        ("var_never_set", "subgraphs/s.graph.json", "n_get")
    ]
