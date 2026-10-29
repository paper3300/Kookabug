"""판정 순서표 (스키마 v0 2장): `judge()` 표 테스트와 행마다 그래프 실행."""

from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder, make_workspace, subgraph_interface
from helpers.run import Ran, check_ok, run_graph, tk

from kookabug_core.engine import CancelToken, Cause, Facts, judge
from kookabug_core.workspace import Workspace

ERROR = Cause("s1", ("n_boom",), "node_error", "RuntimeError: boom")
CANCEL = Cause("s2", ("n_wait",), "cancelled", "실행이 취소됐다")
FAIL = Cause("s3", ("n_wait",), "fail", "타임아웃")
TEST_FAIL = Cause("s4", ("n_fail",), "test_fail", "막힘")
SKIP = Cause("s5", ("n_skip",), "test_skip", "점검")
PASS = Cause("s6", ("n_pass",), "test_pass", "core.test.pass에 도달했다")

# (id, 사실, 판정, 코드, 원인)
TABLE = [
    # 행마다
    ("row1_error", Facts(error=ERROR), "error", "node_error", ERROR),
    ("row1_cancel", Facts(error=CANCEL), "error", "cancelled", CANCEL),
    ("row2_unhandled_fail", Facts(unhandled_fail=FAIL), "fail", "unhandled_fail", FAIL),
    (
        "row3_test_fail",
        Facts(terminal="fail", terminal_cause=TEST_FAIL),
        "fail",
        "test_fail",
        TEST_FAIL,
    ),
    ("row4_skip", Facts(terminal="skip", terminal_cause=SKIP), "skipped", "test_skip", SKIP),
    ("row5_assert", Facts(assertions_passed=1), "pass", "assertion_passed", None),
    ("row5_test_pass_only", Facts(terminal="pass", terminal_cause=PASS), "pass", "test_pass", None),
    ("row6_nothing", Facts(), "fail", "no_assertion", None),
    # 상위·하위 쌍
    ("error_over_unhandled", Facts(error=ERROR, unhandled_fail=FAIL), "error", "node_error", ERROR),
    (
        "error_over_test_fail",
        Facts(error=ERROR, terminal="fail", terminal_cause=TEST_FAIL),
        "error",
        "node_error",
        ERROR,
    ),
    (
        "error_over_skip",
        Facts(error=ERROR, terminal="skip", terminal_cause=SKIP),
        "error",
        "node_error",
        ERROR,
    ),
    (
        "error_over_pass",
        Facts(error=ERROR, terminal="pass", terminal_cause=PASS, assertions_passed=3),
        "error",
        "node_error",
        ERROR,
    ),
    (
        "cancel_is_error_over_everything",
        Facts(
            error=CANCEL,
            unhandled_fail=FAIL,
            terminal="pass",
            terminal_cause=PASS,
            assertions_passed=2,
        ),
        "error",
        "cancelled",
        CANCEL,
    ),
    (
        "unhandled_over_test_fail",
        Facts(unhandled_fail=FAIL, terminal="fail", terminal_cause=TEST_FAIL),
        "fail",
        "unhandled_fail",
        FAIL,
    ),
    (
        "unhandled_over_skip",
        Facts(unhandled_fail=FAIL, terminal="skip", terminal_cause=SKIP),
        "fail",
        "unhandled_fail",
        FAIL,
    ),
    (
        "unhandled_over_pass",
        Facts(unhandled_fail=FAIL, terminal="pass", terminal_cause=PASS, assertions_passed=2),
        "fail",
        "unhandled_fail",
        FAIL,
    ),
    (
        "test_fail_over_assert_success",
        Facts(terminal="fail", terminal_cause=TEST_FAIL, assertions_passed=2),
        "fail",
        "test_fail",
        TEST_FAIL,
    ),
    (
        "skip_over_assert_success",
        Facts(terminal="skip", terminal_cause=SKIP, assertions_passed=2),
        "skipped",
        "test_skip",
        SKIP,
    ),
    ("assert_success_is_pass", Facts(assertions_passed=2), "pass", "assertion_passed", None),
    (
        "test_pass_with_assert_is_pass",
        Facts(terminal="pass", terminal_cause=PASS, assertions_passed=1),
        "pass",
        "test_pass",
        None,
    ),
]


@pytest.mark.parametrize(
    ("facts", "verdict", "code", "cause"),
    [row[1:] for row in TABLE],
    ids=[row[0] for row in TABLE],
)
def test_judge_precedence(facts: Facts, verdict: str, code: str, cause: Cause | None) -> None:
    judgement = judge(facts)
    assert (judgement.verdict, judgement.code, judgement.cause) == (verdict, code, cause)
    assert judgement.reason


def test_no_assertion_reason() -> None:
    assert "검증 없이" in judge(Facts()).reason


# ---------------------------------------------------------------- 그래프 통합

SUB = "subgraphs/s.graph.json"


def ws_(tmp_path: Path) -> Workspace:
    return make_workspace(tmp_path)


def verdict(ran: Ran) -> tuple[str, str, tuple[str, ...] | None]:
    r = ran.result
    return r.verdict, r.code, r.failure_path


def test_row1_node_exception_is_error(tmp_path: Path) -> None:
    g = tk().entry("n_boom").node("n_boom", "testkit.boom", inputs={"message": "펑"})
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("error", "node_error", ("n_boom",))
    assert ran.result.failure_step == ran.step_of("n_boom")
    assert "펑" in ran.result.reason
    end = ran.end("n_boom")
    assert end["status"] == "error"
    assert end["error"]["code"] == "node_error"


def test_row1_error_after_assert_success_still_error(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_boom"})
        .node("n_boom", "testkit.boom")
    )
    ran = run_graph(ws_(tmp_path), g)
    assert ran.end("n_check")["status"] == "success"
    assert verdict(ran) == ("error", "node_error", ("n_boom",))


def test_row1_cancel_is_error(tmp_path: Path) -> None:
    # 검증 성공 → 대기(캡처 직후 취소): 찾았어도 그 스텝이 cancelled, test.pass로 가지 않는다
    token = CancelToken()
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_wait"})
        .node(
            "n_wait", "testkit.observe.wait", inputs={"expect": "lobby"}, next={"found": "n_pass"}
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(
        ws_(tmp_path), g, frames=["lobby.png"], cancel=token, on_capture=lambda n: token.cancel()
    )
    assert ran.end("n_check")["status"] == "success"
    assert verdict(ran) == ("error", "cancelled", ("n_wait",))
    assert ran.end("n_wait")["status"] == "cancelled"
    assert "n_pass" not in ran.order()


def test_row1_error_in_subgraph_propagates(tmp_path: Path) -> None:
    ws = ws_(tmp_path)
    (
        GraphBuilder("subgraph", interface=subgraph_interface(), plugins={"testkit": "0"})
        .entry("n_boom")
        .node("n_boom", "testkit.boom", next={"done": "n_exit"})
        .exit("n_exit", "done")
        .write(ws, SUB)
    )
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g)
    assert verdict(ran) == ("error", "node_error", ("n_call", "n_boom"))
    assert ran.result.failure_step == ran.step_of("n_boom")
    assert ran.end("n_call")["status"] == "error"
    assert ran.order() == ["n_entry", "n_call", "n_entry", "n_boom"]


def test_row2_unconnected_fail_exit(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_wait"})
        .node("n_wait", "testkit.fail_once", inputs={"exit": "timeout"})
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_wait",))
    end = ran.end("n_wait")
    assert (end["status"], end["exit"]) == ("fail", "timeout")


def test_row2_connected_fail_branch_ends_without_terminal(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_wait")
        .node("n_wait", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_log"})
        .node("n_log", "core.log.message", inputs={"text": "실패 기록"})
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_wait",))
    assert ran.result.failure_step == ran.step_of("n_wait")
    assert [e["message"] for e in ran.of("log")] == ["실패 기록"]
    assert ran.end("n_log")["status"] == "success"


def _fail_sub(ws: Workspace, *, public_fail: bool) -> None:
    """`n_inner`가 fail로 나가는 서브그래프. `public_fail`이면 그 fail을 공개 exit로 낸다."""
    exits = {"done": "ok", "login_failed": "fail"} if public_fail else {"done": "ok"}
    g = (
        GraphBuilder(
            "subgraph", interface=subgraph_interface(exits=exits), plugins={"testkit": "0"}
        )
        .entry("n_inner")
        .node(
            "n_inner",
            "testkit.fail_once",
            inputs={"exit": "fail"},
            next={"ok": "n_done", "fail": "n_failed"} if public_fail else {"ok": "n_done"},
        )
        .exit("n_done", "done")
    )
    if public_fail:
        g.exit("n_failed", "login_failed")
    g.write(ws, SUB)


def test_row2_subgraph_inner_unhandled_fail_path(tmp_path: Path) -> None:
    ws = ws_(tmp_path)
    _fail_sub(ws, public_fail=False)
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g)
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_call", "n_inner"))
    end = ran.end("n_call")
    assert (end["status"], end["exit"]) == ("fail", None)
    assert "n_pass" not in ran.order()


def test_row2_call_unconnected_public_fail_exit(tmp_path: Path) -> None:
    ws = ws_(tmp_path)
    _fail_sub(ws, public_fail=True)
    g = (
        tk()
        .entry("n_call")
        .call("n_call", SUB, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    ran = run_graph(ws, g)
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_call",))
    assert ran.result.failure_step == ran.step_of("n_call")
    end = ran.end("n_call")
    assert (end["status"], end["exit"]) == ("fail", "login_failed")


def test_row3_test_fail_after_assert_success(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_fail"})
        .node("n_fail", "core.test.fail", inputs={"reason": "막힘"})
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("fail", "test_fail", ("n_fail",))
    assert ran.result.reason == "막힘"


def test_row4_skip_after_assert_success(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_skip"})
        .node("n_skip", "core.test.skip", inputs={"reason": "점검"})
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("skipped", "test_skip", ("n_skip",))
    assert ran.result.reason == "점검"


def test_row4_fail_branch_to_skip(tmp_path: Path) -> None:
    # 문서의 점검 사례: fail 출구(점검)를 skip 종료 노드로 연결 → skipped
    g = (
        tk()
        .entry("n_login")
        .node(
            "n_login",
            "testkit.fail_once",
            inputs={"exit": "fail"},
            next={"fail": "n_skip", "ok": "n_check"},
        )
        .node("n_skip", "core.test.skip", inputs={"reason": "서버 점검 중"})
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("skipped", "test_skip", ("n_skip",))
    assert ran.end("n_login")["status"] == "fail"


def test_row5_assert_success_then_end(tmp_path: Path) -> None:
    g = tk().entry("n_check").node("n_check", "core.assert.compare", inputs=check_ok())
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("pass", "assertion_passed", None)
    assert ran.result.failure_step is None


def test_row5_test_pass_without_assert(tmp_path: Path) -> None:
    g = tk().entry("n_pass").node("n_pass", "core.test.pass")
    assert verdict(run_graph(ws_(tmp_path), g)) == ("pass", "test_pass", None)


def test_row5_fail_branch_to_test_pass(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_wait")
        .node(
            "n_wait",
            "testkit.fail_once",
            inputs={"exit": "fail"},
            next={"fail": "n_pass", "ok": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    assert verdict(run_graph(ws_(tmp_path), g)) == ("pass", "test_pass", None)


def test_row6_no_assertion_is_fail_with_reason(tmp_path: Path) -> None:
    g = tk().entry("n_tap").node("n_tap", "testkit.input.tap", inputs={"x": 1, "y": 1})
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("fail", "no_assertion", None)
    assert "검증 없이" in ran.result.reason
    assert ran.result.failure_step is None


def test_assertion_fail_exit_is_not_counted_as_success(tmp_path: Path) -> None:
    # 검증 노드가 fail 출구로 나가면 검증 성공(5행)이 아니다. 그 분기가 종료 노드 없이 끝나면 2행
    g = (
        tk()
        .entry("n_check")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 2},
            next={"fail": "n_log"},
        )
        .node("n_log", "core.log.message", inputs={"text": "다름"})
    )
    ran = run_graph(ws_(tmp_path), g)
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_check",))
    assert "1 == 2" in ran.result.reason


def test_pending_fail_survives_later_successful_steps(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_a")
        .node("n_a", "testkit.fail_once", inputs={"exit": "fail"}, next={"fail": "n_b"})
        .node("n_b", "core.log.message", inputs={"text": "B"}, next={"done": "n_c"})
        .node("n_c", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(ws_(tmp_path), g)
    assert ran.end("n_b")["status"] == ran.end("n_c")["status"] == "success"
    assert verdict(ran) == ("fail", "unhandled_fail", ("n_a",))
    assert ran.result.failure_step == ran.step_of("n_a")
