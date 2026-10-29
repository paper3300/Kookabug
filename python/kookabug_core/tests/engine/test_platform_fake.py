"""가짜 플랫폼·`FakeClock`·취소·테스트 전체 기한 (한 프로세스 실행)."""

from pathlib import Path

import pytest
from helpers.graphs import make_workspace
from helpers.run import check_ok, run_graph, tk

from kookabug_core.engine import CancelToken, FakeClock
from kookabug_sdk.testing import InputCall
from kookabug_sdk.types import Point


def test_fake_capture_frames_in_order(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_w1")
        .node("n_w1", "testkit.observe.wait", inputs={"expect": "loading"}, next={"found": "n_w2"})
        .node("n_w2", "testkit.observe.wait", inputs={"expect": "lobby"}, next={"found": "n_w3"})
        .node("n_w3", "testkit.observe.wait", inputs={"expect": "lobby"}, next={"found": "n_check"})
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png", "loading.png", "lobby.png"])
    assert ran.result.verdict == "pass"
    # title(안 맞음 → 100ms 쉼) → loading → lobby → 마지막 프레임 반복
    assert [ran.end(n)["outputs"]["match"]["frame"] for n in ("n_w1", "n_w2", "n_w3")] == [1, 2, 2]
    assert ran.platform.captured == 4
    assert ran.clock.now_ms() == 100
    assert ran.end("n_w1")["duration_ms"] == 100


def test_fake_input_recorded(tmp_path: Path) -> None:
    g = (
        tk()
        .entry("n_tap")
        .node("n_tap", "testkit.input.tap", inputs={"x": 3, "y": 4}, next={"done": "n_check"})
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    ran = run_graph(make_workspace(tmp_path), g)
    assert ran.result.verdict == "pass"
    assert ran.platform.input.calls == [InputCall("click", (Point(3, 4),), {"button": "left"})]


def test_undeclared_effect_is_error(tmp_path: Path) -> None:
    # effects를 선언하지 않은 exec 노드의 입력은 실행 ctx에서도 SDK 래퍼(EffectContext)가 막는다
    g = tk().entry("n_sneak").node("n_sneak", "testkit.input.sneak")
    ran = run_graph(make_workspace(tmp_path), g)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "context_violation", ("n_sneak",))
    assert ran.platform.input.calls == []


@pytest.mark.parametrize(
    ("node_type", "inputs"),
    [
        ("core.flow.delay", {"ms": 1000}),
        ("testkit.observe.wait", {"expect": "never", "timeout_ms": 10_000}),
    ],
    ids=["delay", "wait"],
)
def test_deadline_exceeded_is_error(
    tmp_path: Path, node_type: str, inputs: dict[str, object]
) -> None:
    # 노드 타임아웃(timeout fail)보다 테스트 전체 기한이 먼저 끝나면 error (G11)
    g = (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_slow"})
        .node("n_slow", node_type, inputs=inputs)
    )
    ran = run_graph(make_workspace(tmp_path), g, frames=["title.png"], deadline_ms=500)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "deadline_exceeded", ("n_slow",))
    assert ran.clock.now_ms() == 500
    assert ran.end("n_slow")["status"] == "error"


def test_sleep_reaching_deadline_is_exceeded(tmp_path: Path) -> None:
    # 기한 시각에 딱 닿는 것도 초과다 (499ms 쉼은 되고, 남은 1ms를 쉬면 기한)
    g = (
        tk()
        .entry("n_delay")
        .node("n_delay", "core.flow.delay", inputs={"ms": 499}, next={"done": "n_check"})
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_delay2"})
        .node("n_delay2", "core.flow.delay", inputs={"ms": 1})
    )
    ran = run_graph(make_workspace(tmp_path), g, deadline_ms=500)
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "deadline_exceeded", ("n_delay2",))
    assert ran.end("n_delay")["status"] == "success"


def test_cancel_checked_by_node(tmp_path: Path) -> None:
    token = CancelToken()

    def cancel_on_third(n: int) -> None:
        if n == 3:
            token.cancel()

    g = (
        tk()
        .entry("n_wait")
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "lobby", "timeout_ms": 10_000})
    )
    ran = run_graph(
        make_workspace(tmp_path),
        g,
        frames=["title.png"],
        cancel=token,
        on_capture=cancel_on_third,
    )
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "cancelled", ("n_wait",))
    assert ran.platform.captured == 3  # 노드가 다음 폴링 전에 취소를 봤다
    assert ran.end("n_wait")["status"] == "cancelled"
    assert ran.end("n_wait")["error"]["code"] == "cancelled"


def _last_observation():
    """검증 성공 → 마지막 스텝이 관측(찾음, 뒤 연결 없음). 그대로 끝나면 pass다."""
    return (
        tk()
        .entry("n_check")
        .node("n_check", "core.assert.compare", inputs=check_ok(), next={"ok": "n_wait"})
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "lobby"})
    )


def test_cancel_during_final_successful_capture_is_error(tmp_path: Path) -> None:
    # 마지막 스텝의 캡처 중에 생긴 취소는 찾음(성공)으로 확정하지 않는다
    token = CancelToken()
    ran = run_graph(
        make_workspace(tmp_path),
        _last_observation(),
        frames=["lobby.png"],
        cancel=token,
        on_capture=lambda _: token.cancel(),
    )
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "cancelled", ("n_wait",))
    assert ran.end("n_wait")["status"] == "cancelled"


def test_deadline_during_final_successful_capture_is_error(tmp_path: Path) -> None:
    # 캡처하는 동안 시계가 전체 기한을 넘으면 찾았어도 error
    clock = FakeClock()
    ran = run_graph(
        make_workspace(tmp_path),
        _last_observation(),
        frames=["lobby.png"],
        deadline_ms=500,
        clock=clock,
        on_capture=lambda _: clock.advance(501),
    )
    r = ran.result
    assert (r.verdict, r.code, r.failure_path) == ("error", "deadline_exceeded", ("n_wait",))
    assert ran.end("n_wait")["status"] == "error"
