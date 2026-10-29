"""서브그래프 호출 (스키마 v0 3장 해설·7장 "서브그래프 호출"): 새 프레임, 기본값, 출구 매핑."""

import json
from pathlib import Path
from typing import Any

from helpers.graphs import GraphBuilder, link, make_workspace, secret, subgraph_interface
from helpers.run import Ran, run_graph, tk

from kookabug_core.workspace import Workspace

SUB = "subgraphs/s.graph.json"


def sub(**interface: Any) -> GraphBuilder:
    return GraphBuilder(
        "subgraph", interface=subgraph_interface(**interface), plugins={"testkit": "0"}
    )


def call_then(
    ws: Workspace,
    inputs: dict[str, Any] | None,
    next: dict[str, str],
    *nodes: tuple[str, str, dict[str, Any]],
) -> Ran:
    g = tk().entry("n_call").call("n_call", SUB, inputs=inputs, next=next)
    for node_id, node_type, node_inputs in nodes:
        g.node(node_id, node_type, inputs=node_inputs)
    return run_graph(ws, g)


def test_call_new_frame_variables_isolated(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    # 서브그래프: 호출한 쪽 변수 y를 읽으면 기본값, x를 2로 바꿔도 호출한 쪽 x는 그대로
    (
        sub(outputs={"seen": "any"})
        .entry("n_set")
        .node("n_set", "core.var.set", inputs={"name": "x", "value": 2}, next={"done": "n_exit"})
        .node("n_get", "core.var.get", inputs={"name": "y", "default": "없음"})
        .exit("n_exit", "done", inputs={"seen": link("n_get.value")})
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_x")
        .node("n_x", "core.var.set", inputs={"name": "x", "value": 1}, next={"done": "n_y"})
        .node("n_y", "core.var.set", inputs={"name": "y", "value": 1}, next={"done": "n_call"})
        .call("n_call", SUB, next={"done": "n_seen"})
        .node(
            "n_seen",
            "core.assert.compare",
            inputs={"a": link("n_call.seen"), "op": "==", "b": "없음"},
            next={"ok": "n_after"},
        )
        .node("n_get_x", "core.var.get", inputs={"name": "x"})
        .node(
            "n_after",
            "core.assert.compare",
            inputs={"a": link("n_get_x.value"), "op": "==", "b": 1},
        )
    )
    ran = run_graph(ws, g)
    assert ran.result.verdict == "pass", ran.result.reason


def _echo_sub(ws: Workspace) -> None:
    (
        sub(inputs={"n": {"default": 7, "type": "int"}}, outputs={"n": "int"})
        .entry("n_exit")
        .exit("n_exit", "done", inputs={"n": link("n_entry.n")})
        .write(ws, SUB)
    )


def test_call_input_default_used(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    _echo_sub(ws)
    ran = call_then(
        ws,
        None,
        {"done": "n_check"},
        ("n_check", "core.assert.compare", {"a": link("n_call.n"), "op": "==", "b": 7}),
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_call")["outputs"] == {"n": 7}


def test_call_input_given_overrides_default(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    _echo_sub(ws)
    ran = call_then(
        ws,
        {"n": 3},
        {"done": "n_check"},
        ("n_check", "core.assert.compare", {"a": link("n_call.n"), "op": "==", "b": 3}),
    )
    assert ran.result.verdict == "pass", ran.result.reason


def _two_way_sub(
    ws: Workspace, outputs: dict[str, Any] | None = None, left_out: dict[str, Any] | None = None
) -> None:
    """입력 `left`가 참이면 공개 출구 `left`, 아니면 `right`."""
    (
        sub(exits={"left": "ok", "right": "ok"}, inputs={"left": "bool"}, outputs=outputs)
        .entry("n_br")
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_entry.left")},
            next={"true": "n_left", "false": "n_right"},
        )
        .exit("n_left", "left", inputs=left_out)
        .exit("n_right", "right")
        .write(ws, SUB)
    )


def test_call_exit_maps_to_caller_exit(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    _two_way_sub(ws)
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, inputs={"left": False}, next={"left": "n_bad", "right": "n_pass"})
        .node("n_bad", "core.test.fail", inputs={"reason": "left로 나감"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g)
    assert ran.result.verdict == "pass"
    end = ran.end("n_call")
    assert (end["status"], end["exit"], end["graph"]) == ("success", "right", SUB)
    assert ran.order() == ["n_entry", "n_call", "n_entry", "n_br", "n_right", "n_pass"]


def test_nullable_output_null_on_other_exit(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    _two_way_sub(
        ws,
        outputs={"message": {"nullable": True, "type": "string"}},
        left_out={"message": "왼쪽"},
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, inputs={"left": False}, next={"left": "n_bad", "right": "n_check"})
        .node("n_bad", "core.test.fail")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_call.message"), "op": "==", "b": None},
        )
    )
    ran = run_graph(ws, g)
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_call")["outputs"] == {"message": None}


def _public_fail_sub(ws: Workspace) -> None:
    (
        sub(exits={"done": "ok", "login_failed": "fail"})
        .entry("n_inner")
        .node(
            "n_inner",
            "testkit.fail_once",
            inputs={"exit": "fail"},
            next={"ok": "n_done", "fail": "n_failed"},
        )
        .exit("n_done", "done")
        .exit("n_failed", "login_failed")
        .write(ws, SUB)
    )


def test_public_fail_exit_not_double_propagated(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    _public_fail_sub(ws)

    # 연결 안 됨: 호출 노드에서 처리되지 않은 fail 하나 (안쪽 n_inner가 따로 올라오지 않는다)
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("fail", "unhandled_fail", ("n_call",))
    assert ran.end("n_inner")["status"] == "fail"  # 안쪽 기록은 남는다

    # 연결함(skip): 안쪽 fail은 공개 exit로 처리됐으므로 판정에 다시 들어가지 않는다
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass", "login_failed": "n_skip"})
        .node("n_pass", "core.test.pass")
        .node("n_skip", "core.test.skip", inputs={"reason": "로그인 실패"})
    )
    ran = run_graph(ws, g)
    assert (ran.result.verdict, ran.result.code) == ("skipped", "test_skip")
    assert ran.end("n_inner")["status"] == "fail"


def test_secret_input_masked_in_events(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    (
        sub(inputs={"password": "secret"})
        .entry("n_log")
        .node(
            "n_log",
            "core.log.message",
            inputs={"text": link("n_entry.password")},
            next={"done": "n_exit"},
        )
        .exit("n_exit", "done")
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, inputs={"password": secret("accounts.qa")}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g, secrets={"accounts.qa": "hunter2"})
    assert ran.result.verdict == "pass"
    dumped = json.dumps(ran.events, ensure_ascii=False)
    assert "hunter2" not in dumped
    inner_entry = [e for e in ran.of("step.start") if e["path"] == ["n_call", "n_entry"]]
    (end,) = [e for e in ran.of("step.end") if e["step"] == inner_entry[0]["step"]]
    assert end["outputs"] == {"password": "***"}
    assert [e["message"] for e in ran.of("log")] == ["***"]
