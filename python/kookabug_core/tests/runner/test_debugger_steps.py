"""브레이크포인트·Step·제어 RPC (구현 계획 M3 2.3, T3).

브레이크포인트 열쇠는 (워크스페이스 기준 그래프 경로, 노드 ID)이고 스텝 경계(`step.start` 전)에서만
적중한다. Step 목표는 멈춘 자리의 호출 깊이(`path` 길이)로 정하고, 반복은 깊이를 더하지 않는다.

실제 runner 프로세스로 돈다(코어 노드만, 워커 없음). 멈춤 게이트의 판정 규칙은 같은 프로세스
검사도 한다.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.runner import RunnerHarness, events_of

from kb_testing.proc import Spawned, wait_until
from kookabug_core.engine.cancel import CancelToken
from kookabug_core.engine.debug import Breakpoint, ResumeMode, StepPoint, step_limit
from kookabug_core.runner.clock import ActiveClock
from kookabug_core.runner.control import NotPaused, PauseGate
from kookabug_core.runner.spec import RunSpec
from kookabug_core.schema.shape import validator
from kookabug_core.supervisor import ResumeRefused

TEST = "tests/t.graph.json"
SUB = "subgraphs/s.graph.json"
SUB_IFACE = {"exits": {"done": {"kind": "ok"}}}


# ---------------------------------------------------------------- 도우미


def bp(node: str, graph: str = TEST) -> Breakpoint:
    return Breakpoint(graph, node)


def delays(*names: str, ms: int = 10, then: str = "n_pass") -> GraphBuilder:
    """`flow.delay`를 차례로 → 통과."""
    g = GraphBuilder().entry(names[0])
    for i, name in enumerate(names):
        following = names[i + 1] if i + 1 < len(names) else then
        g.node(name, "core.flow.delay", inputs={"ms": ms}, next={"done": following})
    return g.node("n_pass", "core.test.pass")


def sub_graph() -> GraphBuilder:
    """서브그래프: entry → n_in(delay) → n_in2(delay) → exit done."""
    return (
        GraphBuilder("subgraph", interface=SUB_IFACE)
        .entry("n_in")
        .node("n_in", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_in2"})
        .node("n_in2", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_done"})
        .exit("n_done", "done")
    )


def call_graph(*calls: str) -> GraphBuilder:
    """루트: entry → 호출 노드들(같은 서브그래프) → n_after(delay) → 통과."""
    g = GraphBuilder().entry(calls[0])
    for i, name in enumerate(calls):
        following = calls[i + 1] if i + 1 < len(calls) else "n_after"
        g.call(name, SUB, next={"done": following})
    g.node("n_after", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_pass"})
    return g.node("n_pass", "core.test.pass")


def loop_graph(times: int) -> GraphBuilder:
    """루트: entry → n_loop(repeat) → 본문 n_body·n_body2 → (반복) → n_pass."""
    return (
        GraphBuilder()
        .entry("n_loop")
        .node("n_loop", "core.flow.repeat", inputs={"times": times}, next={"body": "n_body"})
        .node("n_body", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_body2"})
        .node("n_body2", "core.flow.delay", inputs={"ms": 10})
        .node("n_pass", "core.test.pass")
    )


def loop_graph_done(times: int) -> GraphBuilder:
    g = loop_graph(times)
    g.nodes["n_loop"]["next"]["done"] = "n_pass"
    return g


def start(
    tmp_path: Path,
    spawned: Spawned,
    graph: GraphBuilder,
    breakpoints: Sequence[Breakpoint] = (),
    *,
    sub: GraphBuilder | None = None,
) -> RunnerHarness:
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), breakpoints=tuple(breakpoints))
    if sub is not None:
        sub.write(h.ws, SUB)
    return h.start(spawned)


def pauses(h: RunnerHarness) -> list[dict[str, Any]]:
    return [e for e in h.events() if e["event"] == "debug.pause"]


def wait_pause(h: RunnerHarness, n: int) -> dict[str, Any]:
    """`n`번째 `debug.pause`(1부터)를 기다려 돌려준다."""
    wait_until(
        lambda: len(pauses(h)) >= n,
        timeout=30,
        message=lambda: f"debug.pause {n}번째 없음: {pauses(h)}\n{h.stderr()}",
    )
    return pauses(h)[n - 1]


def where(event: dict[str, Any]) -> tuple[str, str, list[str], str]:
    return (event["graph"], event["node"], event["path"], event["reason"])


def drive(h: RunnerHarness, modes: Sequence[ResumeMode]) -> list[tuple[str, str, list[str], str]]:
    """멈출 때마다 `modes`를 차례로 써서 재개한다. 멈춘 자리 목록을 돌려준다."""
    seen: list[tuple[str, str, list[str], str]] = []
    for i, mode in enumerate(modes, start=1):
        event = wait_pause(h, i)
        seen.append(where(event))
        assert h.resume(mode) == "running"
    return seen


def finish_pass(h: RunnerHarness) -> list[dict[str, Any]]:
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    check = validator("events")
    for event in done.view.events:
        assert not [e.message for e in check.iter_errors(event)], event
    return done.view.events


def started_before(events: Sequence[dict[str, Any]], pause: dict[str, Any]) -> list[str]:
    """그 멈춤 전에 `step.start`를 쓴 노드들."""
    return [e["node"] for e in events if e["event"] == "step.start" and e["seq"] < pause["seq"]]


# ---------------------------------------------------------------- 브레이크포인트


def test_breakpoint_hits_before_node_in_root(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, delays("n_d1", "n_d2", "n_d3"), [bp("n_d2")])
    pause = wait_pause(h, 1)
    assert where(pause) == (TEST, "n_d2", ["n_d2"], "breakpoint")
    assert pause["where"] == "boundary"
    # 그 노드의 스텝은 아직 시작하지 않았다 (step.start 전 확인 지점)
    assert not h.has_event("step.start", node="n_d2")
    first = next(e for e in h.events() if e["event"] == "step.start" and e["node"] == "n_d1")
    assert h.has_event("step.end", step=first["step"])
    assert h.resume() == "running"
    events = finish_pass(h)
    assert len(events_of(events, "debug.pause")) == 1
    (resume,) = events_of(events, "debug.resume")
    assert resume["mode"] == "continue" and resume["step"] == pause["step"]
    run_json = h.run_json()
    assert run_json is not None and run_json["debug_intervened"] is True
    assert run_json["pause_count"] == 1


def test_breakpoint_in_subgraph_hits_from_any_caller(tmp_path: Path, spawned: Spawned) -> None:
    # 서브그래프 파일에 건 브레이크포인트는 어느 호출 노드에서 불리든 적중한다
    h = start(
        tmp_path, spawned, call_graph("n_call1", "n_call2"), [bp("n_in", SUB)], sub=sub_graph()
    )
    seen = drive(h, ["continue", "continue"])
    assert seen == [
        (SUB, "n_in", ["n_call1", "n_in"], "breakpoint"),
        (SUB, "n_in", ["n_call2", "n_in"], "breakpoint"),
    ]
    events = finish_pass(h)
    assert len(events_of(events, "debug.pause")) == 2


def test_breakpoint_in_loop_hits_each_iteration(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, loop_graph_done(3), [bp("n_body")])
    seen = drive(h, ["continue", "continue", "continue"])
    assert seen == [(TEST, "n_body", ["n_body"], "breakpoint")] * 3
    events = finish_pass(h)
    paused = events_of(events, "debug.pause")
    assert len(paused) == 3
    # 멈춤마다 바로 뒤 그 노드의 스텝이 회차 0·1·2로 시작한다
    iterations = [
        next(e for e in events if e["event"] == "step.start" and e["step"] == p["step"])[
            "iteration"
        ]
        for p in paused
    ]
    assert iterations == [0, 1, 2]


def test_breakpoint_not_checked_at_poll_point(tmp_path: Path, spawned: Spawned) -> None:
    # 폴링 확인 지점은 일시정지 요청만 본다: 경계에서 멈췄다 재개한 delay 노드가 폴링하는 동안
    # 같은 노드의 브레이크포인트로 다시 멈추지 않는다
    graph = (
        GraphBuilder()
        .entry("n_d1")
        .node("n_d1", "core.flow.delay", inputs={"ms": 600}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = start(tmp_path, spawned, graph, [bp("n_d1")])
    pause = wait_pause(h, 1)
    assert (pause["node"], pause["where"]) == ("n_d1", "boundary")
    assert h.resume() == "running"
    events = finish_pass(h)
    assert len(events_of(events, "debug.pause")) == 1


# ---------------------------------------------------------------- Step


def test_step_over_call_node_skips_inner_steps(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, call_graph("n_call1"), [bp("n_call1")], sub=sub_graph())
    seen = drive(h, ["step_over", "continue"])
    assert seen == [
        (TEST, "n_call1", ["n_call1"], "breakpoint"),
        (TEST, "n_after", ["n_after"], "step"),
    ]
    events = finish_pass(h)
    second = events_of(events, "debug.pause")[1]
    # 서브그래프 안 스텝은 멈추지 않고 모두 지나갔다
    assert {"n_in", "n_in2", "n_done"} <= set(started_before(events, second))
    resumes = events_of(events, "debug.resume")
    assert [r["mode"] for r in resumes] == ["step_over", "continue"]


def test_step_into_call_node_stops_at_subgraph_first_node(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, call_graph("n_call1"), [bp("n_call1")], sub=sub_graph())
    seen = drive(h, ["step_into", "step_into", "continue"])
    assert seen == [
        (TEST, "n_call1", ["n_call1"], "breakpoint"),
        (SUB, "n_entry", ["n_call1", "n_entry"], "step"),
        (SUB, "n_in", ["n_call1", "n_in"], "step"),
    ]
    finish_pass(h)


def test_step_into_non_call_node_is_like_step_over(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, delays("n_d1", "n_d2"), [bp("n_d1")])
    seen = drive(h, ["step_into", "continue"])
    assert seen == [
        (TEST, "n_d1", ["n_d1"], "breakpoint"),
        (TEST, "n_d2", ["n_d2"], "step"),
    ]
    finish_pass(h)


def test_step_out_stops_after_call_returns(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, call_graph("n_call1"), [bp("n_in", SUB)], sub=sub_graph())
    seen = drive(h, ["step_out", "continue"])
    assert seen == [
        (SUB, "n_in", ["n_call1", "n_in"], "breakpoint"),
        (TEST, "n_after", ["n_after"], "step"),
    ]
    events = finish_pass(h)
    second = events_of(events, "debug.pause")[1]
    assert {"n_in2", "n_done"} <= set(started_before(events, second))


def test_step_out_at_top_level_is_continue(tmp_path: Path, spawned: Spawned) -> None:
    h = start(tmp_path, spawned, delays("n_d1", "n_d2", "n_d3"), [bp("n_d1"), bp("n_d3")])
    seen = drive(h, ["step_out", "continue"])
    assert seen == [
        (TEST, "n_d1", ["n_d1"], "breakpoint"),
        (TEST, "n_d3", ["n_d3"], "breakpoint"),
    ]
    finish_pass(h)


def test_step_over_at_loop_stops_at_body_first_node(tmp_path: Path, spawned: Spawned) -> None:
    # 반복은 깊이를 더하지 않는다: 반복 노드에서 step_over → 본문 첫 노드(같은 깊이)
    h = start(tmp_path, spawned, loop_graph_done(2), [bp("n_loop")])
    seen = drive(h, ["step_over", "continue", "continue", "continue"])
    assert seen == [
        (TEST, "n_loop", ["n_loop"], "breakpoint"),
        (TEST, "n_body", ["n_body"], "step"),
        # 둘째 회차·끝(done)으로 돌아온 반복 노드 (브레이크포인트)
        (TEST, "n_loop", ["n_loop"], "breakpoint"),
        (TEST, "n_loop", ["n_loop"], "breakpoint"),
    ]
    finish_pass(h)


def test_breakpoint_before_step_target_wins(tmp_path: Path, spawned: Spawned) -> None:
    # 호출 노드에서 step_over(목표: n_after) → 목표 전에 서브그래프 안 브레이크포인트에서 멈춘다
    h = start(
        tmp_path,
        spawned,
        call_graph("n_call1"),
        [bp("n_call1"), bp("n_in2", SUB)],
        sub=sub_graph(),
    )
    seen = drive(h, ["step_over", "continue"])
    assert seen == [
        (TEST, "n_call1", ["n_call1"], "breakpoint"),
        (SUB, "n_in2", ["n_call1", "n_in2"], "breakpoint"),
    ]
    events = finish_pass(h)
    # 브레이크포인트 멈춤으로 Step 목표는 사라졌다: 그 뒤 continue로 n_after에서 멈추지 않는다
    assert len(events_of(events, "debug.pause")) == 2


def test_step_from_poll_pause_uses_that_step_depth(tmp_path: Path, spawned: Spawned) -> None:
    # 폴링 중 일시정지 → step_over → 다음 경계(같은 깊이)에서 멈춘다
    h = start(tmp_path, spawned, delays("n_d1", "n_d2", ms=3_000))
    h.wait_event("step.start", node="n_d1")
    assert h.pause() == "pausing"
    first = wait_pause(h, 1)
    assert (first["node"], first["where"], first["reason"]) == ("n_d1", "poll", "request")
    assert h.resume("step_over") == "running"
    second = wait_pause(h, 2)
    assert where(second) == (TEST, "n_d2", ["n_d2"], "step")
    assert second["where"] == "boundary"
    h.cancel()
    done = h.finish()
    assert done.run_end is not None and done.run_end["cancel_reason"] == "cancelled"


# ---------------------------------------------------------------- 제어 RPC


def test_breakpoints_updated_mid_run_apply_next_boundary(tmp_path: Path, spawned: Spawned) -> None:
    # 시작 때 n_d3에 걸어 두고, n_d1 실행 중에 [n_d2]로 바꾼다 → n_d2에서만 멈춘다
    graph = (
        GraphBuilder()
        .entry("n_d1")
        .node("n_d1", "core.flow.delay", inputs={"ms": 1_500}, next={"done": "n_d2"})
        .node("n_d2", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_d3"})
        .node("n_d3", "core.flow.delay", inputs={"ms": 10}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = start(tmp_path, spawned, graph, [bp("n_d3")])
    h.wait_event("step.start", node="n_d1")
    assert h.set_breakpoints([bp("n_d2")]) == "running"
    pause = wait_pause(h, 1)
    assert where(pause) == (TEST, "n_d2", ["n_d2"], "breakpoint")
    # 멈춘 동안 바꿔도 된다 (빈 목록) — 다음 경계부터
    assert h.set_breakpoints([]) == "paused"
    assert h.resume() == "running"
    events = finish_pass(h)
    assert len(events_of(events, "debug.pause")) == 1
    sent = [m for d, m in h.messages if d == "send" and m.get("method") == "run.breakpoints"]
    assert [m["params"]["breakpoints"] for m in sent] == [[bp("n_d2").to_json()], []]


def test_resume_without_mode_is_continue(tmp_path: Path, spawned: Spawned) -> None:
    # M0b 호환: params 없는 run.resume은 continue (다음 브레이크포인트까지 그대로 간다)
    h = start(tmp_path, spawned, delays("n_d1", "n_d2", "n_d3"), [bp("n_d1"), bp("n_d3")])
    wait_pause(h, 1)
    assert h.resume() == "running"
    second = wait_pause(h, 2)
    assert (second["node"], second["reason"]) == ("n_d3", "breakpoint")
    assert h.resume() == "running"
    events = finish_pass(h)
    assert [r["mode"] for r in events_of(events, "debug.resume")] == ["continue", "continue"]
    sent = [m for d, m in h.messages if d == "send" and m.get("method") == "run.resume"]
    assert len(sent) == 2 and all("params" not in m for m in sent)


def test_step_resume_when_not_paused_refused(tmp_path: Path, spawned: Spawned) -> None:
    # 멈추지 않은 runner에 Step → 거절(아무것도 바꾸지 않음). continue는 M0b처럼 받는다
    h = start(tmp_path, spawned, delays("n_d1", "n_d2", ms=1_500))
    h.wait_event("step.start", node="n_d1")
    with pytest.raises(ResumeRefused) as caught:
        h.resume("step_over")
    assert caught.value.state == "running"
    assert h.resume() == "running"
    events = finish_pass(h)
    assert events_of(events, "debug.pause") == []
    run_json = h.run_json()
    assert run_json is not None and run_json["debug_intervened"] is False


def test_spec_breakpoints_roundtrip() -> None:
    data = {
        "breakpoints": [
            {"graph": SUB, "node": "n_in"},
            {"graph": TEST, "node": "n_a"},
            {"graph": SUB, "node": "n_in"},
        ]
    }
    spec_json = _spec_json() | data
    spec = RunSpec.from_json(spec_json)
    assert spec.breakpoints == (bp("n_in", SUB), bp("n_a"))
    assert spec.to_json()["breakpoints"] == [
        {"graph": SUB, "node": "n_in"},
        {"graph": TEST, "node": "n_a"},
    ]
    # 없으면 빈 목록 (M0b·M2 사양과 호환)
    assert RunSpec.from_json(_spec_json()).breakpoints == ()


def _spec_json() -> dict[str, Any]:
    return {
        "run_id": "abcd1234",
        "run_dir": "C:/runs/r1",
        "workspace_root": "C:/ws",
        "graph": TEST,
        "control": {"pipe": "p", "key": "0" * 64},
        "job_name": "j",
        "supervisor": {"pid": 1, "created": "1"},
        "deadline_ms": 1000,
        "profile": None,
        "settings": {},
        "plugin_modules": [],
        "platform": {"kind": "none"},
    }


# ---------------------------------------------------------------- 멈춤 게이트 판정 (같은 프로세스)


def point(node: str, *path: str, graph: str = TEST, step: str = "s1") -> StepPoint:
    return StepPoint(step, node, graph, (*path, node))


def test_step_limit_table() -> None:
    assert step_limit("continue", 2) is None
    assert step_limit("step_over", 2) == 2
    assert step_limit("step_out", 2) == 1
    assert step_limit("step_out", 1) is None  # 맨 바깥: continue와 같다
    limit = step_limit("step_into", 1)
    assert limit is not None and limit >= 1 << 20


def test_gate_decides_reason_and_clears_target() -> None:
    token = CancelToken()
    gate = PauseGate(token, ActiveClock(token), [bp("n_b", SUB)])
    emitted: list[dict[str, Any]] = []

    def run(points: list[StepPoint], modes: list[ResumeMode]) -> None:
        resumes = iter(modes)

        def emit(event: Any) -> None:
            emitted.append(dict(event))
            if event["event"] == "debug.pause":
                mode = next(resumes)
                threading.Timer(0.01, lambda: gate.resume(mode)).start()

        for p in points:
            gate.at_boundary(p, emit)

    # 요청 → 경계에서 request. step_over(깊이 1) → 깊이 2 경계는 지나고, 서브그래프 안
    # 브레이크포인트가 목표보다 먼저 적중한다. 그 멈춤에서 continue → 깊이 1 경계는 지나간다
    assert gate.request() == "pausing"
    run(
        [
            point("n_call"),
            point("n_a", "n_call", graph=SUB),
            point("n_b", "n_call", graph=SUB),
            point("n_next"),
        ],
        ["step_over", "continue"],
    )
    paused = [(e["node"], e["reason"]) for e in emitted if e["event"] == "debug.pause"]
    assert paused == [("n_call", "request"), ("n_b", "breakpoint")]
    modes = [e["mode"] for e in emitted if e["event"] == "debug.resume"]
    assert modes == ["step_over", "continue"]
    with pytest.raises(NotPaused):
        gate.resume("step_into")
    assert gate.state == "running"


def test_gate_breakpoint_key_strips_snapshot_prefix() -> None:
    assert point("n_b", graph=f"snapshot/{SUB}").key == bp("n_b", SUB)
    assert Breakpoint.from_json({"graph": f"snapshot/{SUB}", "node": "n_b"}) == bp("n_b", SUB)


def test_gate_poll_ignores_breakpoint_and_step_target() -> None:
    token = CancelToken()
    gate = PauseGate(token, ActiveClock(token), [bp("n_a")])
    emitted: list[Any] = []
    began = time.monotonic()
    gate.at_poll(point("n_a"), emitted.append)  # 요청이 없다: 브레이크포인트로는 멈추지 않는다
    assert emitted == [] and time.monotonic() - began < 0.5
