"""반복 실행 (스키마 v0 7장 "반복"·"반복 범위"): 암묵적 귀환, `while` 판단 순서, 범위 출력 무효화,
본문의 fail·error·종료, 대기 중인 fail(G14), 중첩, 이벤트 `iteration`."""

from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder, check, link, make_workspace, subgraph_interface
from helpers.run import Ran, check_ok, run_graph, tk
from testkit import registry_with_testkit
from testkit.nodes import COUNTS

SUB = "subgraphs/s.graph.json"


def trace(ran: Ran) -> list[tuple[str, int | None]]:
    """실행된 (노드, iteration) — step.start 순서."""
    return [(e["node"], e.get("iteration")) for e in ran.of("step.start")]


def exits(ran: Ran, node: str) -> list[str | None]:
    """`node`의 스텝마다 나간 출구."""
    steps = {e["step"] for e in ran.starts(node)}
    return [e["exit"] for e in ran.of("step.end") if e["step"] in steps]


def log(g: GraphBuilder, node_id: str, text: str, done: str | None = None) -> GraphBuilder:
    return g.node(
        node_id, "core.log.message", inputs={"text": text}, next={"done": done} if done else None
    )


def repeat(
    g: GraphBuilder, node_id: str, times: int, body: str | None, done: str | None = None
) -> GraphBuilder:
    next = {k: v for k, v in {"body": body, "done": done}.items() if v is not None}
    return g.node(node_id, "core.flow.repeat", inputs={"times": times}, next=next)


def stop_flag_while(max_iterations: int) -> GraphBuilder:
    """조건 `var.get("stop") == false`, 본문에서 `index >= 2`면 `var.set("stop", true)`."""
    return (
        tk()
        .entry("n_init")
        .node(
            "n_init",
            "core.var.set",
            inputs={"name": "stop", "value": False},
            next={"done": "n_while"},
        )
        .node("n_get", "core.var.get", inputs={"name": "stop"})
        .node(
            "n_cond",
            "core.logic.compare",
            inputs={"a": link("n_get.value"), "op": "==", "b": False},
        )
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": link("n_cond.result"), "max_iterations": max_iterations},
            next={"body": "n_branch", "done": "n_check"},
        )
        .node(
            "n_late",
            "core.logic.compare",
            inputs={"a": link("n_while.index"), "op": ">=", "b": 2},
        )
        .node(
            "n_branch",
            "core.flow.branch",
            inputs={"condition": link("n_late.result")},
            next={"true": "n_stop"},
        )
        .node("n_stop", "core.var.set", inputs={"name": "stop", "value": True})
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )


# ---------------------------------------------------------------- while


def test_while_condition_sees_var_set_in_body(tmp_path: Path) -> None:
    ran = run_graph(make_workspace(tmp_path), stop_flag_while(10))
    assert ran.result.verdict == "pass"
    assert exits(ran, "n_while") == ["body", "body", "body", "done"]
    assert [e["iteration"] for e in ran.starts("n_branch")] == [0, 1, 2]
    assert len(ran.starts("n_stop")) == 1
    assert ran.order()[-1] == "n_check"


def test_while_condition_recomputes_pure_nodes_each_check(tmp_path: Path) -> None:
    # 조건 = count <= 3 (count는 계산될 때마다 1씩 오른다), 빈 본문
    g = (
        tk()
        .entry("n_while")
        .node("n_count", "testkit.pure.count", inputs={"key": "cond"})
        .node("n_cond", "core.logic.compare", inputs={"a": link("n_count.n"), "op": "<=", "b": 3})
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": link("n_cond.result"), "max_iterations": 10},
            next={"done": "n_check"},
        )
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert exits(ran, "n_while") == ["body", "body", "body", "done"]
    assert COUNTS["cond"] == len(ran.starts("n_while")) == 4


def test_while_last_allowed_iteration_satisfied_goes_done_not_limit(tmp_path: Path) -> None:
    # 3회째(마지막 허용 회차)에 조건을 만족시킨다 → 다음 검사에서 조건이 먼저: done
    ran = run_graph(make_workspace(tmp_path), stop_flag_while(3))
    assert ran.result.verdict == "pass"
    assert exits(ran, "n_while") == ["body", "body", "body", "done"]


def test_while_limit_is_fail_exit(tmp_path: Path) -> None:
    # 2회째에야 조건을 만족시킬 수 있는데 한도가 2 → 세 번째 검사에서 limit (연결 안 됨)
    ws = make_workspace(tmp_path)
    ran = run_graph(ws, stop_flag_while(2))
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("fail", "unhandled_fail", ("n_while",))
    assert exits(ran, "n_while") == ["body", "body", "limit"]
    assert ran.of("step.end")[-1]["status"] == "fail"
    assert "max_iterations 2" in r.reason


# ---------------------------------------------------------------- repeat


def test_repeat_runs_times_with_index(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 3, "n_set", "n_check")
    g.node("n_set", "core.var.set", inputs={"name": "last", "value": link("n_loop.index")})
    g.node("n_last", "core.var.get", inputs={"name": "last"})
    g.node("n_check", "core.assert.compare", inputs={"a": link("n_last.value"), "op": "==", "b": 2})
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    loop_ends = [
        e for e in ran.of("step.end") if e["step"] in {s["step"] for s in ran.starts("n_loop")}
    ]
    assert [(e["exit"], e["outputs"]) for e in loop_ends] == [
        ("body", {"index": 0}),
        ("body", {"index": 1}),
        ("body", {"index": 2}),
        ("done", {}),
    ]
    assert len(ran.starts("n_set")) == 3


def test_repeat_zero_times_goes_done(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 0, "n_body", "n_check")
    log(g, "n_body", "본문")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert ran.order() == ["n_entry", "n_loop", "n_check"]
    assert exits(ran, "n_loop") == ["done"]


@pytest.mark.parametrize("changed", [-1, "다른 용도로 쓴 변수", 100])
def test_repeat_limit_fixed_on_entry(tmp_path: Path, changed: object) -> None:
    # count=2 → repeat(times=var.get(count)) → 본문이 count를 바꾼다. 한도는 들어올 때의 2 그대로
    # (돌아올 때 한도 입력을 다시 계산·대조하지 않으므로 -1·문자열도 오류가 아니다)
    g = (
        tk()
        .entry("n_init")
        .node(
            "n_init", "core.var.set", inputs={"name": "count", "value": 2}, next={"done": "n_loop"}
        )
        .node("n_get", "core.var.get", inputs={"name": "count"})
        .node(
            "n_loop",
            "core.flow.repeat",
            inputs={"times": link("n_get.value")},
            next={"body": "n_set", "done": "n_pass"},
        )
        .node("n_set", "core.var.set", inputs={"name": "count", "value": changed})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert (ran.result.verdict, ran.result.code) == ("pass", "test_pass")
    assert exits(ran, "n_loop") == ["body", "body", "done"]


def test_while_limit_fixed_on_entry(tmp_path: Path) -> None:
    # max_iterations=var.get(max)=3, 본문이 max를 문자열로 바꾼다 → 그래도 3회 후 limit
    g = (
        tk()
        .entry("n_init")
        .node(
            "n_init", "core.var.set", inputs={"name": "max", "value": 3}, next={"done": "n_while"}
        )
        .node("n_get", "core.var.get", inputs={"name": "max"})
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": True, "max_iterations": link("n_get.value")},
            next={"body": "n_set", "limit": "n_pass"},
        )
        .node("n_set", "core.var.set", inputs={"name": "max", "value": "x"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert (ran.result.verdict, ran.result.code) == ("pass", "test_pass")
    assert exits(ran, "n_while") == ["body", "body", "body", "limit"]


def test_loop_reentry_computes_only_condition(tmp_path: Path) -> None:
    # 한도 입력의 순수 노드는 들어올 때 한 번, condition의 순수 노드는 검사마다
    g = (
        tk()
        .entry("n_while")
        .node("n_lim", "testkit.pure.count", inputs={"key": "lim"})
        .node("n_count", "testkit.pure.count", inputs={"key": "cond"})
        .node("n_cond", "core.logic.compare", inputs={"a": link("n_count.n"), "op": "<=", "b": 2})
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": link("n_cond.result"), "max_iterations": link("n_lim.n")},
            next={"done": "n_check", "limit": "n_pass"},
        )
        .node("n_check", "core.assert.compare", inputs=check_ok())
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g)
    # 한도 1(첫 계산값): 1회차 본문 → 조건 n=2 참, 이미 1회 → limit
    assert exits(ran, "n_while") == ["body", "limit"]
    assert (COUNTS["lim"], COUNTS["cond"]) == (1, 2)


# ---------------------------------------------------------------- 본문의 fail·error·종료


def test_body_unhandled_fail_stops_loop_and_propagates(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 3, "n_f", "n_pass")
    g.node("n_f", "testkit.fail_once", inputs={"exit": "fail"})
    g.node("n_pass", "core.test.pass")
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("fail", "unhandled_fail", ("n_f",))
    assert ran.order() == ["n_entry", "n_loop", "n_f"]


def test_body_error_stops_loop(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 3, "n_boom", "n_pass")
    g.node("n_boom", "testkit.boom")
    g.node("n_pass", "core.test.pass")
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "node_error", ("n_boom",))
    assert ran.order() == ["n_entry", "n_loop", "n_boom"]


def test_body_fail_branch_logged_then_end_is_not_recovery(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 3, "n_f", "n_pass")
    g.node("n_f", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_log"})
    log(g, "n_log", "실패 기록")
    g.node("n_pass", "core.test.pass")
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code) == ("fail", "unhandled_fail")
    assert r.failure_step == ran.step_of("n_f")
    assert [e["message"] for e in ran.of("log")] == ["실패 기록"]  # 처리는 실행된다
    assert ran.order() == ["n_entry", "n_loop", "n_f", "n_log"]  # 다음 회차 없음


def _pending_before_loop(end_of_body: str | None) -> GraphBuilder:
    """`n_a.fail(연결) → repeat(times=2) → 로그 → (end_of_body)`."""
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_loop"})
    )
    repeat(g, "n_loop", 2, "n_log", "n_pass")
    log(g, "n_log", "본문", end_of_body)
    g.node("n_pass", "core.test.pass")
    if end_of_body is not None:
        g.node(end_of_body, "core.test.skip", inputs={"reason": "본문에서 건너뜀"})
    return g


def test_pending_fail_before_loop_stops_at_first_body_end(tmp_path: Path) -> None:
    # 반복 밖에서 생긴 대기 중인 fail도 본문 끝에서 반복을 멈춘다 (G14)
    ran = run_graph(make_workspace(tmp_path), _pending_before_loop(None))
    r = ran.result
    assert (r.verdict, r.code) == ("fail", "unhandled_fail")
    assert r.failure_step == ran.step_of("n_a")
    assert ran.order() == ["n_entry", "n_a", "n_loop", "n_log"]  # 2회차 step.start 없음
    assert exits(ran, "n_loop") == ["body"]


def test_pending_fail_before_loop_resolved_by_terminal_in_body(tmp_path: Path) -> None:
    ran = run_graph(make_workspace(tmp_path), _pending_before_loop("n_skip"))
    r = ran.result
    assert (r.verdict, r.code) == ("skipped", "test_skip")
    assert ran.order() == ["n_entry", "n_a", "n_loop", "n_log", "n_skip"]


def test_body_terminal_ends_test_and_loop(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 3, "n_check", "n_fail")
    g.node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_pass"})
    g.node("n_pass", "core.test.pass")
    g.node("n_fail", "core.test.fail", inputs={"reason": "반복이 끝까지 돌았다"})
    ran = run_graph(make_workspace(tmp_path), g)
    assert (ran.result.verdict, ran.result.code) == ("pass", "test_pass")
    assert ran.order() == ["n_entry", "n_loop", "n_check", "n_pass"]


def test_body_graph_exit_ends_subgraph_and_loop(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    sub = GraphBuilder("subgraph", interface=subgraph_interface()).entry("n_loop")
    repeat(sub, "n_loop", 3, "n_log", "n_exit")
    log(sub, "n_log", "안쪽", "n_exit")
    sub.exit("n_exit", "done").write(ws, SUB)
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_check"})
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(ws, g)
    assert ran.result.verdict == "pass"
    assert [tuple(e["path"]) for e in ran.of("step.start")] == [
        ("n_entry",),
        ("n_call",),
        ("n_call", "n_entry"),
        ("n_call", "n_loop"),
        ("n_call", "n_log"),
        ("n_call", "n_exit"),
        ("n_check",),
    ]


# ---------------------------------------------------------------- 범위 출력


def _read_previous_iteration() -> GraphBuilder:
    """1회차에 `n_make`가 값을 만들고, 2회차에 `n_read`가 그 값을 읽는다 (지난 반복 출력)."""
    g = repeat(tk().entry("n_loop"), "n_loop", 2, "n_branch", "n_pass")
    g.node("n_later", "core.logic.compare", inputs={"a": link("n_loop.index"), "op": ">", "b": 0})
    g.node(
        "n_branch",
        "core.flow.branch",
        inputs={"condition": link("n_later.result")},
        next={"false": "n_make", "true": "n_read"},
    )
    g.node("n_make", "testkit.fail_once", inputs={"exit": "ok", "value": 7})
    g.node(
        "n_read",
        "core.assert.compare",
        inputs={"a": link("n_make.value"), "op": "==", "b": 7},
    )
    g.node("n_pass", "core.test.pass")
    return g


def test_runtime_previous_iteration_output_read_is_error(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    ran = run_graph(ws, _read_previous_iteration(), validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "link_missing", ("n_read",))
    assert ran.end("n_make")["status"] == "success"  # 1회차에는 만들었다
    assert ran.starts("n_read")[0]["iteration"] == 1
    assert "지난 반복" in r.reason


def test_runtime_body_output_after_done_is_error(tmp_path: Path) -> None:
    # done 뒤(범위 밖)에서 본문 출력 읽기: 정적 검사가 막고, 건너뛰면 실행기도 막는다
    g = repeat(tk().entry("n_loop"), "n_loop", 2, "n_make", "n_read")
    g.node("n_make", "testkit.fail_once", inputs={"exit": "ok", "value": 7})
    g.node("n_read", "core.assert.compare", inputs={"a": link("n_make.value"), "op": "==", "b": 7})
    ws = make_workspace(tmp_path)
    ran = run_graph(ws, g, validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "link_missing", ("n_read",))
    diags = check(ws, "tests/t.graph.json", registry=registry_with_testkit())
    assert [(d.code, d.node) for d in diags if d.severity == "error"] == [
        ("link_out_of_scope", "n_read")
    ]


# ---------------------------------------------------------------- 중첩


def _nested() -> GraphBuilder:
    """바깥 2회, 안쪽 3회. 바깥 본문: n_a → 안쪽 반복(본문 n_b, done → n_c)."""
    g = repeat(tk().entry("n_outer"), "n_outer", 2, "n_a", "n_check")
    log(g, "n_a", "바깥", "n_inner")
    repeat(g, "n_inner", 3, "n_b", "n_c")
    log(g, "n_b", "안쪽")
    log(g, "n_c", "안쪽 끝")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    return g


def test_nested_inner_body_end_returns_to_inner_loop(tmp_path: Path) -> None:
    ran = run_graph(make_workspace(tmp_path), _nested())
    assert ran.result.verdict == "pass"
    order = ran.order()
    # 안쪽 본문(n_b)이 끝나면 늘 안쪽 반복 노드로 돌아간다
    assert all(order[i + 1] == "n_inner" for i, n in enumerate(order) if n == "n_b")
    assert exits(ran, "n_inner") == ["body", "body", "body", "done"] * 2
    assert exits(ran, "n_outer") == ["body", "body", "done"]


def test_nested_inner_done_continues_outer_body_then_returns_to_outer(tmp_path: Path) -> None:
    ran = run_graph(make_workspace(tmp_path), _nested())
    assert ran.result.verdict == "pass"

    def one_outer(i: int) -> list[tuple[str, int | None]]:
        # 안쪽 반복 노드는 바깥 회차, 안쪽 본문은 안쪽 회차. 안쪽 done 뒤 n_c는 바깥 본문
        return [
            ("n_a", i),
            ("n_inner", i),
            ("n_b", 0),
            ("n_inner", i),
            ("n_b", 1),
            ("n_inner", i),
            ("n_b", 2),
            ("n_inner", i),
            ("n_c", i),
            ("n_outer", None),
        ]

    assert trace(ran) == [
        ("n_entry", None),
        ("n_outer", None),
        *one_outer(0),
        *one_outer(1),
        ("n_check", None),
    ]


def _branch_on_outer_index(g: GraphBuilder, first: str, later: str) -> GraphBuilder:
    g.node("n_later", "core.logic.compare", inputs={"a": link("n_outer.index"), "op": ">", "b": 0})
    return g.node(
        "n_branch",
        "core.flow.branch",
        inputs={"condition": link("n_later.result")},
        next={"false": first, "true": later},
    )


def test_outer_next_iteration_invalidates_inner_scope_outputs(tmp_path: Path) -> None:
    # 바깥 1회차: 안쪽 반복 본문이 n_make 실행. 바깥 2회차: n_read가 안쪽 범위 출력을 읽음 → error
    g = repeat(tk().entry("n_outer"), "n_outer", 2, "n_branch", "n_pass")
    _branch_on_outer_index(g, "n_inner", "n_read")
    repeat(g, "n_inner", 1, "n_make")
    g.node("n_make", "testkit.fail_once", inputs={"exit": "ok", "value": 7})
    g.node("n_read", "core.assert.compare", inputs={"a": link("n_make.value"), "op": "==", "b": 7})
    g.node("n_pass", "core.test.pass")
    ran = run_graph(make_workspace(tmp_path), g, validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "link_missing", ("n_read",))
    assert ran.starts("n_read")[0]["iteration"] == 1
    assert len(ran.starts("n_make")) == 1


def _outer_obs_inner_read(after_inner: bool) -> GraphBuilder:
    """바깥 본문: n_obs(값 = 바깥 index) → 안쪽 반복 2회(본문이 n_obs를 읽음) → done → n_after."""
    g = repeat(tk().entry("n_outer"), "n_outer", 2, "n_obs", "n_pass")
    g.node(
        "n_obs",
        "testkit.fail_once",
        inputs={"exit": "ok", "value": link("n_outer.index")},
        next={"ok": "n_inner"},
    )
    repeat(g, "n_inner", 2, "n_in_check", "n_after" if after_inner else None)
    g.node(
        "n_in_check",
        "core.assert.compare",
        inputs={"a": link("n_obs.value"), "op": "==", "b": link("n_outer.index")},
    )
    if after_inner:
        g.node(
            "n_after",
            "core.assert.compare",
            inputs={"a": link("n_obs.value"), "op": "==", "b": link("n_outer.index")},
        )
    g.node("n_pass", "core.test.pass")
    return g


def test_outer_body_output_readable_in_inner_loop(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    ran = run_graph(ws, _outer_obs_inner_read(after_inner=False))
    assert ran.result.verdict == "pass"
    checks = [
        e for e in ran.of("step.end") if e["step"] in {s["step"] for s in ran.starts("n_in_check")}
    ]
    assert [e["status"] for e in checks] == ["success"] * 4
    assert len(ran.starts("n_obs")) == 2


def test_inner_next_iteration_keeps_outer_outputs(tmp_path: Path) -> None:
    # 안쪽 회차가 넘어가도(그리고 안쪽 done 뒤에도) 바깥 본문 출력은 그대로 읽힌다
    ws = make_workspace(tmp_path)
    ran = run_graph(ws, _outer_obs_inner_read(after_inner=True))
    assert ran.result.verdict == "pass"
    assert [e["iteration"] for e in ran.starts("n_in_check")] == [0, 1, 0, 1]
    assert [e["iteration"] for e in ran.starts("n_after")] == [0, 1]


# ---------------------------------------------------------------- 기록·프레임·기한


def test_iteration_field_in_events(tmp_path: Path) -> None:
    g = repeat(tk().entry("n_loop"), "n_loop", 2, "n_body", "n_check")
    log(g, "n_body", "본문")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g)
    starts = ran.starts("n_body")
    assert [e["iteration"] for e in starts] == [0, 1]
    assert len({e["step"] for e in starts}) == 2  # 반복마다 새 스텝 ID
    body_steps = {e["step"]: e["iteration"] for e in starts}
    ends = [e for e in ran.of("step.end") if e["step"] in body_steps]
    assert [e["iteration"] for e in ends] == [0, 1]
    # 반복 노드 자신과 반복 밖 스텝에는 없다
    assert all("iteration" not in e for e in ran.starts("n_loop") + ran.starts("n_check"))


def test_subgraph_call_in_loop_new_frame_each_iteration(tmp_path: Path) -> None:
    # 서브그래프가 변수 seen을 보고 세운다. 프레임을 다시 쓰면 2회차에 seen이 이미 true
    ws = make_workspace(tmp_path)
    (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_check")
        .node("n_seen", "core.var.get", inputs={"name": "seen", "default": False})
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_seen.value"), "op": "==", "b": False},
            next={"ok": "n_set"},
        )
        .node(
            "n_set", "core.var.set", inputs={"name": "seen", "value": True}, next={"done": "n_exit"}
        )
        .exit("n_exit", "done")
        .write(ws, SUB)
    )
    g = repeat(tk().entry("n_loop"), "n_loop", 2, "n_call", "n_pass")
    g.call("n_call", SUB)
    g.node("n_pass", "core.test.pass")
    ran = run_graph(ws, g)
    assert (ran.result.verdict, ran.result.code) == ("pass", "test_pass")
    calls = ran.starts("n_call")
    assert [e["iteration"] for e in calls] == [0, 1]
    inner = [e for e in ran.of("step.start") if e["path"] == ["n_call", "n_check"]]
    assert [e["parent"] for e in inner] == [c["step"] for c in calls]
    assert all("iteration" not in e for e in inner)  # 새 프레임에는 반복이 없다


def test_loop_respects_test_deadline(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_while")
        .node(
            "n_while",
            "core.flow.while",
            inputs={"condition": True, "max_iterations": 1000},
            next={"body": "n_delay", "done": "n_pass"},
        )
        .node("n_delay", "core.flow.delay", inputs={"ms": 100})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(make_workspace(tmp_path), g, deadline_ms=550)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "deadline_exceeded", ("n_delay",))
    assert ran.clock.now_ms() == 550
    assert len(ran.starts("n_delay")) == 6
