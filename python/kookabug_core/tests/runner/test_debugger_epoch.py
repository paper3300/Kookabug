"""실제 runner의 관측 세대 연결 (구현 계획 M3 2.4, T4).

runner 멈춤 게이트가 재개할 때 올리는 세대를 실행기가 같이 본다: 워커 노드가 캡처해 낸 값을
브레이크포인트 뒤(재개 뒤)의 일반 스텝이 받으면 `stale_observation`이고, `debug.resume.epoch`가 그
세대다. 멈추지 않은 같은 실행은 통과한다. (세부 규칙은 `engine/test_epoch_*`·
`inputs/test_revalidate_epoch`)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.graphs import link
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, wait_until
from kookabug_core.engine.debug import Breakpoint

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"


def graph() -> object:
    return (
        tk()
        .entry("n_wait")
        .node("n_wait", "testkit.observe.wait", inputs={"expect": "a"}, next={"found": "n_use"})
        .node(
            "n_use",
            "testkit.epoch.use",
            inputs={"value": link("n_wait.match")},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def harness(tmp_path: Path, breakpoints: tuple[Breakpoint, ...]) -> RunnerHarness:
    h = RunnerHarness.make(tmp_path, graph(), breakpoints=breakpoints)  # type: ignore[arg-type]
    h.frames = [h.frame("a")]
    return h


def test_resume_epoch_makes_captured_output_stale(tmp_path: Path, spawned: Spawned) -> None:
    h = harness(tmp_path, (Breakpoint(TEST, "n_use"),)).start(spawned)
    wait_until(
        lambda: h.has_event("debug.pause"),
        timeout=60,
        message=lambda: f"debug.pause 없음\n{h.stderr()}",
    )
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    (resume,) = done.of("debug.resume")
    assert resume["epoch"] == 1
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["verdict"], run_end["code"], run_end["failure_path"]) == (
        "fail",
        "unhandled_fail",
        ["n_use"],
    )
    _, end = step_of(done.view.events, "n_use")
    assert end is not None and str(end["message"]).startswith("stale_observation:")


def test_same_run_without_pause_passes(tmp_path: Path, spawned: Spawned) -> None:
    done = harness(tmp_path, ()).start(spawned).finish()
    assert done.exit_code == 0
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
