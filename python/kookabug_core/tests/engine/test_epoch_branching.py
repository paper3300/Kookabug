"""재개 뒤 오래된 관측값으로 분기·검증하지 않음 (구현 계획 M3 2.4 "스텝 입력 검사", T4).

디버거로 멈췄다 재개하면 관측 세대가 오른다. 그 전 세대 관측에서 온 값을 입력으로 받은 스텝은 노드를
부르지 않고 처리되지 않은 fail `stale_observation`이다(분기·검증·반복 조건 모두). 옮기기·기록용
코어 노드(`log.message`·`var.set` 등)는 받는다. 멈추지 않은 실행은 M1과 같다.

장면은 예제 게임 `FakeScenario`, OCR은 장면 이름으로 답하는 `SceneEngines`, 멈춤은 같은 스레드의
`Debugger`(runner 멈춤 게이트 흉내)다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.epoch import Debugger, SceneEngines, platform_with, run_debug
from helpers.graphs import GraphBuilder, link, make_workspace
from helpers.m1 import Ran
from helpers.run import tk

TEXTS = {"title": "START", "lobby": "LOBBY"}


def head(first: str) -> GraphBuilder:
    """게임 띄우기 → 글자 읽기(`n_read`) → `first`."""
    return (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_read"})
        .node("n_read", "core.ocr.read", next={"done": first})
    )


def branch_graph() -> GraphBuilder:
    return (
        head("n_br")
        .node(
            "n_cmp",
            "core.logic.compare",
            inputs={"a": link("n_read.text"), "op": "==", "b": "START"},
        )
        .node(
            "n_br",
            "core.flow.branch",
            inputs={"condition": link("n_cmp.result")},
            next={"true": "n_yes", "false": "n_no"},
        )
        .node("n_yes", "core.test.pass")
        .node("n_no", "core.test.fail")
    )


def run(tmp_path: Path, graph: GraphBuilder, dbg: Debugger | None = None) -> Ran:
    platform = platform_with(SceneEngines(texts=dict(TEXTS)))
    return run_debug(make_workspace(tmp_path), graph, platform, dbg)


def assert_stale_at(ran: Ran, node: str) -> dict[str, Any]:
    result = ran.result
    assert (result.verdict, result.code) == ("fail", "unhandled_fail"), result.reason
    assert result.failure_path == (node,)
    end = ran.end(node)
    assert (end["status"], end["exit"], end["outputs"]) == ("fail", None, {})
    assert str(end["message"]).startswith("stale_observation:"), end["message"]
    return end


def test_branch_on_stale_ocr_text_is_stale_observation(tmp_path: Path) -> None:
    ran = run(tmp_path, branch_graph(), Debugger(at={"n_br"}))
    end = assert_stale_at(ran, "n_br")
    assert "'n_read'" in end["message"] and "세대 0 < 지금 1" in end["message"]
    order = [e["node"] for e in ran.of("step.start")]
    assert "n_yes" not in order and "n_no" not in order  # 어느 출구로도 가지 않았다


def test_breakpoint_before_read_reads_fresh_value(tmp_path: Path) -> None:
    """읽기 전에 멈췄으면 읽은 값은 재개 뒤 관측이라 그대로 분기한다 (멈춤 자체가 막지 않음)."""
    ran = run(tmp_path, branch_graph(), Debugger(at={"n_read"}))
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.end("n_br")["exit"] == "true"


def test_assert_compare_on_stale_value_fails_unhandled(tmp_path: Path) -> None:
    g = (
        head("n_check")
        .node(
            "n_check",
            "core.assert.compare",
            inputs={"a": link("n_read.text"), "op": "==", "b": "START"},
            next={"ok": "n_pass", "fail": "n_pass"},  # fail 출구를 연결해도 출구로 나가지 않는다
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_check"}))
    assert_stale_at(ran, "n_check")
    assert "n_pass" not in [e["node"] for e in ran.of("step.start")]


def test_while_condition_on_stale_value_fails(tmp_path: Path) -> None:
    g = (
        head("n_loop")
        .node(
            "n_cmp", "core.logic.compare", inputs={"a": link("n_read.text"), "op": "==", "b": "X"}
        )
        .node(
            "n_loop",
            "core.flow.while",
            inputs={"condition": link("n_cmp.result"), "max_iterations": 3},
            next={"body": "n_body", "done": "n_pass"},
        )
        .node("n_body", "core.flow.delay", inputs={"ms": 1})
        .node("n_pass", "core.test.pass")
    )
    ran = run(tmp_path, g, Debugger(at={"n_loop"}))
    assert_stale_at(ran, "n_loop")


def test_log_and_var_set_accept_stale(tmp_path: Path) -> None:
    g = (
        head("n_log")
        .node(
            "n_log",
            "core.log.message",
            inputs={"text": link("n_read.text")},
            next={"done": "n_set"},
        )
        .node(
            "n_set",
            "core.var.set",
            inputs={"name": "seen", "value": link("n_read.text")},
            next={"done": "n_fail"},
        )
        .node("n_fail", "core.test.fail", inputs={"reason": link("n_read.text")})
    )
    ran = run(tmp_path, g, Debugger(at={"n_log"}))
    result = ran.result
    # test.fail도 사유 글자로 받는다 (예외 목록) — 판정은 그 노드의 fail
    assert (result.verdict, result.code, result.reason) == ("fail", "test_fail", "START")
    assert ran.end("n_log")["status"] == "success"
    assert ran.end("n_set")["status"] == "success"
    assert [e["message"] for e in ran.of("log") if e["node"] == "n_log"] == ["START"]


def test_no_pause_no_change_from_m1(tmp_path: Path) -> None:
    """멈추지 않은 실행은 세대가 0에서 바뀌지 않는다: 판정·이벤트가 디버거 없는 실행과 같다."""
    plain = run(tmp_path / "a", branch_graph())
    debugged = run(tmp_path / "b", branch_graph(), Debugger())
    assert plain.result.verdict == debugged.result.verdict == "pass"
    assert plain.events == debugged.events
