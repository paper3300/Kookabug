"""관측 재시도 (스키마 v0 6장 "재시도"): 출구 확정 전 재시도, `attempt.end`, 입력 재계산 없음,
노드 기한·전체 기한, error·취소 즉시 전파, 다른 스텝의 확정 결과 보존."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace
from helpers.run import Ran, check_ok, run_graph, tk
from testkit.nodes import COUNTS, SEEN

from kookabug_core.engine import CancelToken, FakeClock, InProcessInvoker
from kookabug_core.ir import Node
from kookabug_core.registry import NodeDef
from kookabug_sdk import Context, Result


def retry(max_attempts: int, on: list[str] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"max_attempts": max_attempts}
    if on is not None:
        config["on"] = on
    return {"retry": config}


def wait(
    g: GraphBuilder,
    node_id: str,
    *,
    attempts: int | None = None,
    timeout_ms: int = 0,
    found: str | None = None,
) -> GraphBuilder:
    """`testkit.observe.wait`(lobby 프레임을 기다림). `timeout_ms` 0이면 캡처 한 번이 시도 하나."""
    return g.node(
        node_id,
        "testkit.observe.wait",
        inputs={"expect": "lobby", "timeout_ms": timeout_ms},
        config=retry(attempts) if attempts is not None else None,
        next={"found": found} if found else None,
    )


def flaky(
    g: GraphBuilder, node_id: str, script: list[str], config: dict[str, Any], **inputs: Any
) -> GraphBuilder:
    return g.node(
        node_id,
        "testkit.observe.flaky",
        inputs={"script": script, **inputs},
        config=config,
        next={"found": "n_check"},
    ).node("n_check", "core.assert.compare", inputs=check_ok())


def attempts_of(ran: Ran, node: str) -> list[dict[str, Any]]:
    step = ran.step_of(node)
    return [e for e in ran.of("attempt.end") if e["step"] == step]


def test_retry_records_attempt_end_then_success(tmp_path: Path) -> None:
    g = wait(tk().entry("n_wait"), "n_wait", attempts=3, found="n_check")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png", "lobby.png"])
    assert ran.result.verdict == "pass"
    assert len(ran.starts("n_wait")) == 1  # 시도마다 새 스텝이 아니다
    (first,) = attempts_of(ran, "n_wait")
    assert set(first) == {
        "attempt",
        "duration_ms",
        "event",
        "exit",
        "message",
        "outputs",
        "run",
        "status",
        "step",
    }
    assert (first["attempt"], first["exit"], first["status"], first["outputs"]) == (
        1,
        "timeout",
        "fail",
        {},
    )
    end = ran.end("n_wait")
    assert (end["attempt"], end["exit"], end["status"], end["retried"]) == (
        2,
        "found",
        "success",
        True,
    )
    # attempt.end는 그 스텝의 step.end보다 먼저 남는다
    events = ran.events
    assert events.index(first) < events.index(end)
    assert ran.platform.captured == 2


def test_retry_exhausted_final_fail_exit(tmp_path: Path) -> None:
    g = wait(tk().entry("n_wait"), "n_wait", attempts=3)
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png"])
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("fail", "unhandled_fail", ("n_wait",))
    assert [e["attempt"] for e in attempts_of(ran, "n_wait")] == [1, 2]
    end = ran.end("n_wait")
    assert (end["attempt"], end["exit"], end["status"]) == (3, "timeout", "fail")
    assert "retried" not in end
    assert ran.platform.captured == 3


def test_retry_only_on_listed_exits(tmp_path: Path) -> None:
    # 노드는 timeout·missing을 재시도할 수 있게 선언했지만 그래프는 timeout만 켰다
    ws = make_workspace(tmp_path)
    g = flaky(tk().entry("n_obs"), "n_obs", ["missing", "found"], retry(3, ["timeout"]))
    ran = run_graph(ws, g)
    r = ran.result
    assert (r.verdict, r.failure_path) == ("fail", ("n_obs",))
    assert (ran.end("n_obs")["exit"], ran.end("n_obs")["attempt"]) == ("missing", 1)
    assert ran.of("attempt.end") == []
    assert COUNTS["flaky"] == 1

    # 대조: 목록에 있는 출구는 재시도한다
    COUNTS.clear()
    g = flaky(tk().entry("n_obs"), "n_obs", ["timeout", "found"], retry(3, ["timeout"]))
    ran = run_graph(ws, g)
    assert ran.result.verdict == "pass"
    assert (ran.end("n_obs")["exit"], ran.end("n_obs")["attempt"]) == ("found", 2)


def test_retry_on_omitted_uses_declared_exits(tmp_path: Path) -> None:
    # config.retry.on을 생략하면 노드 스키마의 retry.on 전부
    g = flaky(tk().entry("n_obs"), "n_obs", ["missing", "timeout", "found"], retry(3))
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert [e["exit"] for e in attempts_of(ran, "n_obs")] == ["missing", "timeout"]


def test_retry_default_single_attempt(tmp_path: Path) -> None:
    g = wait(tk().entry("n_wait"), "n_wait", found="n_check")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png", "lobby.png"])
    r = ran.result
    assert (r.verdict, r.failure_path) == ("fail", ("n_wait",))
    assert ran.of("attempt.end") == []
    assert ran.end("n_wait")["attempt"] == 1
    assert ran.platform.captured == 1


def test_retry_error_propagates_without_retry(tmp_path: Path) -> None:
    g = flaky(tk().entry("n_obs"), "n_obs", ["boom", "found"], retry(3))
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "node_error", ("n_obs",))
    assert COUNTS["flaky"] == 1
    assert ran.of("attempt.end") == []
    assert (ran.end("n_obs")["status"], ran.end("n_obs")["attempt"]) == ("error", 1)


def test_retry_error_on_later_attempt_keeps_attempt_number(tmp_path: Path) -> None:
    g = flaky(tk().entry("n_obs"), "n_obs", ["timeout", "boom", "found"], retry(3))
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code) == ("error", "node_error")
    assert [e["attempt"] for e in attempts_of(ran, "n_obs")] == [1]
    assert (ran.end("n_obs")["status"], ran.end("n_obs")["attempt"]) == ("error", 2)


def test_retry_cancel_propagates_without_retry(tmp_path: Path) -> None:
    token = CancelToken()
    g = wait(tk().entry("n_wait"), "n_wait", attempts=3)
    ran = run_graph(
        make_workspace(tmp_path),
        g,
        frames=["title.png"],
        cancel=token,
        on_capture=lambda _: token.cancel(),
    )
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "cancelled", ("n_wait",))
    assert ran.platform.captured == 1
    assert ran.of("attempt.end") == []
    assert (ran.end("n_wait")["status"], ran.end("n_wait")["attempt"]) == ("cancelled", 1)


def test_retry_inputs_not_recomputed(tmp_path: Path) -> None:
    g = tk().entry("n_obs").node("n_count", "testkit.pure.count", inputs={"key": "in"})
    flaky(
        g,
        "n_obs",
        ["timeout", "timeout", "found"],
        retry(3),
        seen=link("n_count.n"),
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert COUNTS["flaky"] == 3
    assert COUNTS["in"] == 1  # 순수 노드는 스텝 시작 때 한 번만
    assert ran.end("n_obs")["outputs"] == {"seen": 1}


@pytest.mark.parametrize("interrupt", ["cancel", "deadline"])
def test_interrupt_between_attempts_does_not_invoke_again(tmp_path: Path, interrupt: str) -> None:
    # 첫 attempt.end를 받은 싱크가 취소하거나 시계를 기한까지 보낸다 → 두 번째 시도를 부르지 않는다
    clock = FakeClock()
    token = CancelToken()

    class Interrupt:
        def emit(self, event: Mapping[str, Any]) -> None:
            if event["event"] == "attempt.end":
                if interrupt == "cancel":
                    token.cancel()
                else:
                    clock.advance(100)

    g = flaky(tk().entry("n_obs"), "n_obs", ["timeout", "found"], retry(2))
    ran = run_graph(
        make_workspace(tmp_path), g, clock=clock, cancel=token, deadline_ms=100, sink=Interrupt()
    )
    r = ran.result
    code = "cancelled" if interrupt == "cancel" else "deadline_exceeded"
    assert (r.verdict, r.code, r.failure_path) == ("error", code, ("n_obs",))
    assert COUNTS["flaky"] == 1
    end = ran.end("n_obs")
    assert end["status"] == ("cancelled" if interrupt == "cancel" else "error")
    assert end["attempt"] == 2  # 두 번째 시도에 들어가려다 멈췄다
    assert "retried" not in end


def test_interrupt_after_successful_retry_has_no_retried_mark(tmp_path: Path) -> None:
    # 두 번째 시도가 found로 돌아온 직후(확정 전) 취소 → 성공이 아니므로 retried 표시 없음
    token = CancelToken()

    class CancelAfterSecond(InProcessInvoker):
        def invoke(
            self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
        ) -> Result:
            result = super().invoke(nodedef, node, ctx, inputs)
            if COUNTS["flaky"] == 2:
                token.cancel()
            return result

    g = flaky(tk().entry("n_obs"), "n_obs", ["timeout", "found"], retry(2))
    ran = run_graph(make_workspace(tmp_path), g, cancel=token, invoker=CancelAfterSecond())
    assert (ran.result.verdict, ran.result.code) == ("error", "cancelled")
    end = ran.end("n_obs")
    assert (end["status"], end["attempt"]) == ("cancelled", 2)
    assert "retried" not in end


def test_retry_preserves_nested_input_values(tmp_path: Path) -> None:
    # 첫 시도가 받은 중첩 목록을 고쳐도 다음 시도는 스텝 시작 때 값을 받는다
    g = (
        tk()
        .entry("n_obs")
        .node(
            "n_obs",
            "testkit.observe.consume",
            inputs={"targets": [[1, 2]]},
            config=retry(2),
            next={"found": "n_check"},
        )
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert SEEN == [[[1, 2]], [[1, 2]]]


def test_retry_new_node_deadline_but_test_deadline_unchanged(tmp_path: Path) -> None:
    def build() -> GraphBuilder:
        return wait(tk().entry("n_wait"), "n_wait", attempts=2, timeout_ms=1000)

    # 시도마다 노드 기한(1000ms)을 새로 준다: 두 시도가 각각 1000ms
    ran = run_graph(make_workspace(tmp_path / "a"), build(), frames=["title.png"])
    (first,) = attempts_of(ran, "n_wait")
    assert first["duration_ms"] == 1000
    end = ran.end("n_wait")
    assert (end["attempt"], end["exit"], end["duration_ms"]) == (2, "timeout", 2000)
    assert ran.clock.now_ms() == 2000

    # 전체 기한은 늘리지 않는다: 1500ms에서 두 번째 시도 도중 error
    ran = run_graph(make_workspace(tmp_path / "b"), build(), frames=["title.png"], deadline_ms=1500)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "deadline_exceeded", ("n_wait",))
    assert ran.clock.now_ms() == 1500
    assert (ran.end("n_wait")["status"], ran.end("n_wait")["attempt"]) == ("error", 2)


def test_intermediate_attempts_excluded_from_verdict(tmp_path: Path) -> None:
    # 중간 시도의 timeout(연결 안 된 fail 출구)은 처리되지 않은 fail이 아니다
    g = wait(tk().entry("n_wait"), "n_wait", attempts=2, found="n_check")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png", "lobby.png"])
    r = ran.result
    assert (r.verdict, r.code, r.failure_step) == ("pass", "assertion_passed", None)
    assert [e["exit"] for e in attempts_of(ran, "n_wait")] == ["timeout"]


def _pending_then_retry(end: str | None) -> GraphBuilder:
    """`n_a.fail(연결) → n_wait(관측 재시도 후 성공) → (end)`."""
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_wait"})
    )
    wait(g, "n_wait", attempts=3, found=end)
    if end is not None:
        g.node(end, "core.test.pass")
    return g


def test_retry_does_not_clear_earlier_pending_fail(tmp_path: Path) -> None:
    ran = run_graph(
        make_workspace(tmp_path), _pending_then_retry(None), frames=["title.png", "lobby.png"]
    )
    r = ran.result
    assert (r.verdict, r.code) == ("fail", "unhandled_fail")
    assert r.failure_step == ran.step_of("n_a")
    assert (ran.end("n_wait")["status"], ran.end("n_wait")["retried"]) == ("success", True)


def test_retry_after_pending_fail_resolved_by_terminal(tmp_path: Path) -> None:
    ran = run_graph(
        make_workspace(tmp_path), _pending_then_retry("n_pass"), frames=["title.png", "lobby.png"]
    )
    assert (ran.result.verdict, ran.result.code) == ("pass", "test_pass")
    assert len(attempts_of(ran, "n_wait")) == 1


def test_retry_in_loop_records_iteration(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_loop")
        .node("n_loop", "core.flow.repeat", inputs={"times": 1}, next={"body": "n_wait"})
    )
    wait(g, "n_wait", attempts=2, found="n_check")
    g.node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png", "lobby.png"])
    assert ran.result.verdict == "pass"
    assert [e["iteration"] for e in attempts_of(ran, "n_wait")] == [0]


def test_retry_not_allowed_without_validation_is_error(tmp_path: Path) -> None:
    # 검증을 건너뛴 그래프의 방어: retry never 노드에 config.retry
    g = (
        tk()
        .entry("n_f")
        .node(
            "n_f",
            "testkit.fail_once",
            inputs={"exit": "timeout"},
            config=retry(3, ["timeout"]),
        )
    )
    ran = run_graph(make_workspace(tmp_path), g, validate=False)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "retry_not_allowed", ("n_f",))
