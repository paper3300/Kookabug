"""활성 시계·폴링 멈춤·멈춤 기록 (구현 계획 M3 2.2, T2).

멈춘 시간은 노드 기한·전체 기한에서 빠진다(runner 활성 시계 하나를 제어 스레드와 실행기 런타임이
같이 본다). 경과(`duration_ms`)는 실제 시간이고, 멈춤이 있었던 구간은 `active_duration_ms`를 더
남긴다. 코어 노드의 멈출 수 있는 기다림(대기 폴링·`flow.delay`)에서는 일시정지 요청이 바로 먹고,
누르고 있기·워커 노드 실행 중에는 먹지 않는다(다음 확인 지점에서).

실제 runner 프로세스로 돈다. 브레이크포인트·Step은 T3(`test_debugger_steps.py`)이다.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, target
from helpers.m1 import write_target
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of

from kb_testing.proc import Spawned, barrier, wait_until
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine import ExecOptions, RunResult
from kookabug_core.engine.debug import StepPoint
from kookabug_core.record import Journal
from kookabug_core.runner import Controller, Runner, RunSpec, Watchdog
from kookabug_core.runner import run as run_module
from kookabug_core.runner.clock import ActiveClock
from kookabug_core.runner.spec import ControlSpec
from kookabug_core.schema.shape import validator
from kookabug_core.win import current

pytestmark = pytest.mark.process

LOBBY = "targets/lobby.target.json"


# ---------------------------------------------------------------- 도우미


def write_scenario(folder: Path, after_frames: int) -> Path:
    """타이틀 화면이 캡처 `after_frames`번 뒤 저절로 로비로 넘어가는 가짜 장면."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("title", "lobby"):
        shutil.copyfile(FRAMES_DIR / f"{name}.png", folder / f"{name}.png")
    spec = {
        "format": "kookabug.fake-scenario/0",
        "launch": [{"variant": "default"}],
        "process": {"name": "python.exe"},
        "scenes": {"title": "title.png", "lobby": "lobby.png"},
        "start": "title",
        "transitions": [{"after_frames": after_frames, "from": "title", "to": "lobby"}],
        "variants": ["default"],
        "window": {"client_size": [1024, 640], "dpi": 96, "title": "SampleRPG"},
    }
    path = folder / "scenario.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def wait_graph(timeout_ms: int, *, retry: Mapping[str, Any] | None = None) -> GraphBuilder:
    """게임 띄우기 → 로비 대기(코어 폴링 노드) → 통과. 코어 노드만 (워커 없음)."""
    config: dict[str, Any] = {"retry": dict(retry)} if retry is not None else {}
    return (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "game.exe"},
            next={"attached": "n_wait"},
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOBBY), "timeout_ms": timeout_ms},
            config=config,
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def scene_run(tmp_path: Path, graph: GraphBuilder, after_frames: int, **kw: Any) -> RunnerHarness:
    scenario = write_scenario(tmp_path / "scene", after_frames)
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), scenario=str(scenario), **kw)
    write_target(h.ws, LOBBY, image="lobby.png")
    return h


def delay_graph(*delays: int, then: GraphBuilder | None = None) -> GraphBuilder:
    """`flow.delay`를 차례로 (`n_d1`, `n_d2`, …) → 통과."""
    g = then if then is not None else GraphBuilder()
    names = [f"n_d{i + 1}" for i in range(len(delays))]
    g.entry(names[0])
    for i, (name, ms) in enumerate(zip(names, delays, strict=True)):
        following = names[i + 1] if i + 1 < len(names) else "n_pass"
        g.node(name, "core.flow.delay", inputs={"ms": ms}, next={"done": following})
    return g.node("n_pass", "core.test.pass")


def pause_in_poll(h: RunnerHarness, node: str) -> dict[str, Any]:
    """`node`가 시작되면 일시정지를 요청하고, 그 노드의 폴링 확인 지점에서 멈출 때까지 기다린다."""
    h.wait_event("step.start", node=node)
    assert h.pause() == "pausing"
    h.wait_event("debug.pause")
    (event,) = [e for e in h.events() if e["event"] == "debug.pause"]
    assert (event["node"], event["where"], event["reason"]) == (node, "poll", "request"), event
    return event


def at(event: Mapping[str, Any]) -> float:
    """이벤트 `t`(UTC) → Unix 초."""
    return datetime.fromisoformat(str(event["t"]).replace("Z", "+00:00")).timestamp()


def kinds(events: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(e["event"]) for e in events]


def assert_schema(h: RunnerHarness, events: Sequence[Mapping[str, Any]]) -> None:
    check = validator("events")
    for event in events:
        errors = [e.message for e in check.iter_errors(event)]
        assert not errors, (event, errors)
    run_json = h.run_json()
    assert run_json is not None
    assert not [e.message for e in validator("run").iter_errors(run_json)]


# ---------------------------------------------------------------- 두 기한


def test_paused_time_excluded_from_run_deadline(tmp_path: Path, spawned: Spawned) -> None:
    # 전체 기한 2초, 첫 경계에서 3초 멈춤 → 재개 → pass (제어 스레드 기한 감시도 활성 시계)
    gate = barrier(tmp_path / "barriers" / "before_validate")
    faults = [{"point": "runner.before_validate", "role": "runner", "action": gate.action}]
    h = RunnerHarness.make(
        tmp_path, delay_graph(300), plugin_modules=(), deadline_ms=2_000, faults=faults
    )
    h.start(spawned)
    gate.wait_ready()
    assert h.pause() == "pausing"  # 실행 전에 요청해 둔다 → 첫 스텝 경계에서 멈춘다
    gate.go()
    h.wait_event("debug.pause")
    time.sleep(3.0)
    assert not h.has_event("cancel.requested")
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["verdict"] == "pass", run_end
    assert done.of("cancel.requested") == []
    (pause,) = done.of("debug.pause")
    assert (pause["where"], pause["reason"], pause["node"]) == ("boundary", "request", "n_entry")
    assert run_end["paused_ms"] >= 2_900
    assert run_end["duration_ms"] > 3_000 > run_end["active_duration_ms"]


def test_paused_time_excluded_from_node_timeout(tmp_path: Path, spawned: Spawned) -> None:
    # 대기 노드 timeout 2초, 폴링 중 3초 멈춤, 로비는 캡처 10번(활성 약 1.5초) 뒤 → found
    h = scene_run(tmp_path, wait_graph(2_000), after_frames=10).start(spawned)
    pause_in_poll(h, "n_wait")
    time.sleep(3.0)
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    _, end = step_of(done.view.events, "n_wait")
    assert end is not None and end["exit"] == "found", end
    assert end["duration_ms"] >= 3_000 and end["active_duration_ms"] < 2_000
    assert end["attempt"] == 1


def test_poll_pause_exceeds_both_deadlines_then_passes(tmp_path: Path, spawned: Spawned) -> None:
    # 검수 M7: 노드 timeout 1초·전체 기한 2초인 실행이 노드 폴링 중 4초 멈춘 뒤에도 pass
    h = scene_run(tmp_path, wait_graph(1_000), after_frames=3, deadline_ms=2_000).start(spawned)
    pause_in_poll(h, "n_wait")
    time.sleep(4.0)
    assert not h.has_event("cancel.requested")
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["verdict"] == "pass", run_end
    _, end = step_of(done.view.events, "n_wait")
    assert end is not None and end["exit"] == "found"
    assert end["duration_ms"] >= 4_000 > 1_000 > end["active_duration_ms"]
    assert run_end["duration_ms"] >= 4_000 > 2_000 > run_end["active_duration_ms"]


def test_deadline_still_fires_on_active_time(tmp_path: Path, spawned: Spawned) -> None:
    # 멈춤이 없으면 기한은 그대로 실제 시간에 맞춰 넘는다
    h = RunnerHarness.make(tmp_path, delay_graph(60_000), plugin_modules=(), deadline_ms=1_500)
    began = time.monotonic()
    done = h.start(spawned).finish()
    assert time.monotonic() - began < 10
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["code"], run_end["cancel_reason"]) == ("deadline_exceeded", "deadline_exceeded")
    assert run_end["paused_ms"] == 0 and run_end["debug_intervened"] is False
    assert run_end["active_duration_ms"] == run_end["duration_ms"]
    _, end = step_of(done.view.events, "n_d1")
    assert end is not None and end["error"]["code"] == "deadline_exceeded"
    assert "active_duration_ms" not in end


def make_runner(tmp_path: Path, deadline_ms: int) -> Runner:
    """시작 순서를 건너뛰고 저널·제어기만 붙인 runner (제어 채널·감독자 없음)."""
    spec = RunSpec(
        run_id="r1",
        run_dir=tmp_path,
        workspace_root=tmp_path,
        graph="tests/t.graph.json",
        control=ControlSpec("unused", b"x" * 32),
        job_name="unused",
        supervisor=current(),
        deadline_ms=deadline_ms,
    )
    runner = Runner(spec)
    runner.watchdog = Watchdog(
        spec.supervisor,
        shutdown_grace_ms=spec.shutdown_grace_ms,
        self_kill_margin_ms=spec.self_kill_margin_ms,
    )
    runner.journal = Journal(runner.folder.events, spec.run_id)
    runner.journal.emit({"event": "run.start"})
    runner.controller = Controller(
        cancel=runner.token,
        watchdog=runner.watchdog,
        pause=runner.pause,
        deadline_at_ms=runner.deadline_at_ms,
        peer=None,
    )
    return runner


def test_control_thread_and_runtime_share_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 제어 스레드의 기한 감시·실행기 런타임의 기한·멈춤 게이트가 같은 활성 시계 하나를 본다
    now = [0]
    monkeypatch.setattr(
        run_module, "ActiveClock", lambda cancel: ActiveClock(cancel, now_ns=lambda: now[0])
    )
    runner = make_runner(tmp_path, deadline_ms=1_000)
    controller = runner.controller
    assert controller is not None
    assert runner.pause.clock is runner.clock and controller.clock is runner.clock
    assert controller.deadline_at_ms == runner.deadline_at_ms == 1_000

    captured: dict[str, Any] = {}

    class _Executor:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

        def run(self, program: Any, options: ExecOptions) -> RunResult:
            captured["options"] = options
            return RunResult("r1", "pass", "pass", "", None, None, [])

    monkeypatch.setattr(run_module, "Executor", _Executor)
    now[0] = 300_000_000  # 300 ms
    runner._run_program(None, None)  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert captured["clock"] is runner.clock
    assert captured["options"].deadline_ms == 700  # 남은 활성 시간 (실행기 전체 기한)

    controller.start()
    try:
        runner.clock.pause()  # 멈춘 동안 실제 시간이 기한을 한참 넘는다
        now[0] = 5_000_000_000
        time.sleep(0.2)
        assert controller.cancel_reason is None
        runner.clock.resume()  # 재개: 활성 시간 300 ms → 기한까지 700 ms 남음
        time.sleep(0.1)
        assert controller.cancel_reason is None
        now[0] += 700_000_000
        wait_until(lambda: controller.cancel_reason == "deadline_exceeded", timeout=2)
    finally:
        controller.stop()
        runner.journal.close()  # pyright: ignore[reportOptionalMemberAccess]


# ---------------------------------------------------------------- 경과 시계


def test_durations_are_wall_clock_for_parent_child_and_attempts(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 검수 M7: 호출 스텝·자식 스텝·재시도 attempt.end의 duration_ms는 멈춘 시간을 포함한 실제
    # 경과, active_duration_ms는 뺀 값. 첫 시도(timeout 600 ms) 폴링 중 1.5초 멈춤 → 첫 시도
    # timeout → 둘째 시도에서 found
    inner = (
        GraphBuilder("subgraph", interface={"exits": {"done": {"kind": "ok"}}})
        .entry("n_wait")
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOBBY), "timeout_ms": 600},
            config={"retry": {"max_attempts": 2}},
            next={"found": "n_done"},
        )
        .exit("n_done", "done")
    )
    root = (
        GraphBuilder()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_call"}
        )
        .call("n_call", "subgraphs/wait.graph.json", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    # 첫 시도(600 ms, 100 ms 폴링)는 캡처 7번까지 — 로비는 9번째 캡처 = 둘째 시도
    h = scene_run(tmp_path, root, after_frames=8)
    inner.write(h.ws, "subgraphs/wait.graph.json")
    h.start(spawned)
    pause_in_poll(h, "n_wait")
    time.sleep(1.5)
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    events = done.view.events
    _, call = step_of(events, "n_call")
    _, wait = step_of(events, "n_wait")
    assert call is not None and wait is not None
    assert wait["attempt"] == 2 and wait["exit"] == "found"
    (attempt,) = done.of("attempt.end")
    assert attempt["exit"] == "timeout"
    (resume,) = done.of("debug.resume")
    paused = resume["paused_ms"]
    assert paused >= 1_400
    # 실제 경과에는 멈춘 시간이 들고, 멈춘 시간을 뺀 경과는 그만큼 짧다
    assert attempt["duration_ms"] >= paused
    for end in (call, wait):
        assert end["duration_ms"] >= paused
        assert end["duration_ms"] - end["active_duration_ms"] >= paused - 50
    # 멈춤이 없었던 스텝에는 active_duration_ms가 없다
    _, launch = step_of(events, "n_launch")
    assert launch is not None and "active_duration_ms" not in launch
    assert_schema(h, events)


# ---------------------------------------------------------------- 확인 지점


def test_poll_pause_only_on_request_not_breakpoint(tmp_path: Path, spawned: Spawned) -> None:
    # 폴링 확인 지점은 일시정지 요청만 본다 (브레이크포인트·Step 목표는 경계에서만 — T3).
    # 요청이 없으면 기다림은 멈추지 않고, 요청이 오면 그 노드 안(다음 경계가 아니라)에서 멈춘다
    h = RunnerHarness.make(tmp_path, delay_graph(300, 5_000), plugin_modules=()).start(spawned)
    pause = pause_in_poll(h, "n_d2")
    events = h.events()
    start2, end2 = step_of(events, "n_d2")
    assert end2 is None and pause["step"] == start2["step"]
    assert pause["path"] == ["n_d2"] and pause["graph"] == "tests/t.graph.json"
    _, end1 = step_of(events, "n_d1")
    assert end1 is not None and "active_duration_ms" not in end1  # n_d1에서는 멈추지 않았다
    assert h.pause() == "paused"
    h.resume()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert len(done.of("debug.pause")) == 1


def test_worker_node_not_paused_mid_call(tmp_path: Path, spawned: Spawned) -> None:
    # 워커 노드 실행 중 요청 → 그 노드는 끝까지 돌고(워커의 ctx.sleep은 확인 지점이 아니다) 다음
    # 경계에서 멈춘다
    signal = tmp_path / "gate.signal"
    graph = (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    h.wait_log("gate")
    assert h.pause() == "pausing"
    time.sleep(0.5)  # 워커 노드는 그사이 ctx.sleep을 여러 번 지난다
    assert not h.has_event("debug.pause") and h.pause() == "pausing"
    signal.touch()
    h.wait_event("debug.pause")
    events = h.events()
    (pause,) = [e for e in events if e["event"] == "debug.pause"]
    _, gate_end = step_of(events, "n_gate")
    assert gate_end is not None and events.index(gate_end) < events.index(pause)
    assert (pause["node"], pause["where"]) == ("n_pass", "boundary")
    h.resume()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass"


def test_pause_request_during_key_hold_confirmed_after_release(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 검수 M1: 누르고 있기 중 요청 → 키를 뗀 뒤(input.up) 다음 확인 지점에서 멈춘다
    graph = (
        GraphBuilder()
        .entry("n_key")
        .node(
            "n_key",
            "core.input.key",
            inputs={"keys": "a", "hold_ms": 1_000},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=()).start(spawned)
    h.wait_event("input.down")
    assert h.pause() == "pausing"
    h.wait_event("debug.pause")
    events = h.events()
    (down,) = [e for e in events if e["event"] == "input.down"]
    (up,) = [e for e in events if e["event"] == "input.up"]
    (pause,) = [e for e in events if e["event"] == "debug.pause"]
    assert events.index(up) < events.index(pause)
    assert (pause["node"], pause["where"]) == ("n_pass", "boundary")
    assert at(up) - at(down) >= 0.95  # 누르고 있기는 줄지 않았다
    h.resume()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass"
    ops = [line["op"] for line in h.fake_inputs() if line["by"] == "runner"]
    assert ops == ["down", "up"]


def test_pause_during_long_delay_confirmed_within_100ms(tmp_path: Path, spawned: Spawned) -> None:
    # 검수 M1: flow.delay 4초 중 요청 → 100 ms 안에 debug.pause(where: poll), 1초 멈춘 뒤 재개하면
    # 남은 활성 시간만 기다린다
    h = RunnerHarness.make(tmp_path, delay_graph(4_000), plugin_modules=()).start(spawned)
    h.wait_event("step.start", node="n_d1")
    time.sleep(0.3)
    asked = time.time()
    assert h.pause() == "pausing"
    h.wait_event("debug.pause")
    (pause,) = [e for e in h.events() if e["event"] == "debug.pause"]
    assert (pause["where"], pause["node"]) == ("poll", "n_d1")
    assert at(pause) - asked < 0.1, at(pause) - asked
    time.sleep(1.0)
    h.resume()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    _, end = step_of(done.view.events, "n_d1")
    assert end is not None and end["status"] == "success"
    (resume,) = done.of("debug.resume")
    assert resume["paused_ms"] >= 950
    # 활성 경과는 delay 그대로(멈춘 1초를 더 기다리지 않음), 실제 경과는 멈춘 만큼 길다
    assert 3_950 <= end["active_duration_ms"] <= 4_500, end
    assert end["duration_ms"] >= end["active_duration_ms"] + resume["paused_ms"] - 50


# ---------------------------------------------------------------- 취소·기록·임대권


def test_cancel_while_paused_wins_over_resume(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, delay_graph(10_000), plugin_modules=()).start(spawned)
    pause_in_poll(h, "n_d1")
    assert h.peer is not None
    cancel = h.peer.request("run.cancel")
    resume = h.peer.request("run.resume")
    assert cancel.result(5)["state"] == "cancelling"
    assert resume.result(5)["state"] == "cancelling"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["code"] == "cancelled"
    assert done.of("debug.resume") == []
    _, end = step_of(done.view.events, "n_d1")
    assert end is not None and end["status"] == "cancelled"
    assert "active_duration_ms" in end  # 멈춘 구간이 든 스텝


def test_pause_records_active_duration_and_run_json_fields(
    tmp_path: Path, spawned: Spawned
) -> None:
    h = RunnerHarness.make(tmp_path, delay_graph(1_500, 200), plugin_modules=()).start(spawned)
    pause = pause_in_poll(h, "n_d1")
    time.sleep(1.0)
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    events = done.view.events
    start1, end1 = step_of(events, "n_d1")
    _, end2 = step_of(events, "n_d2")
    assert pause == {**pause, "step": start1["step"], "graph": "tests/t.graph.json"}
    assert pause["path"] == ["n_d1"]
    (resume,) = done.of("debug.resume")
    assert (resume["step"], resume["mode"]) == (start1["step"], "continue")
    assert 950 <= resume["paused_ms"] < 3_000
    assert "epoch" not in resume  # 관측 세대는 T4
    assert end1 is not None and end2 is not None
    assert end1["duration_ms"] - end1["active_duration_ms"] >= resume["paused_ms"] - 50
    assert "active_duration_ms" not in end2
    run_end = done.run_end
    assert run_end is not None
    assert run_end["debug_intervened"] is True
    assert run_end["paused_ms"] == resume["paused_ms"]
    assert run_end["active_duration_ms"] == run_end["duration_ms"] - run_end["paused_ms"]
    run_json = done.run_json
    assert run_json is not None
    assert run_json["pause_count"] == 1 and run_json["debug_intervened"] is True
    for key in ("paused_ms", "active_duration_ms"):
        assert run_json[key] == run_end[key]
    assert_schema(h, events)


def test_unpaused_run_records_zero_pause(tmp_path: Path, spawned: Spawned) -> None:
    done = RunnerHarness.make(tmp_path, delay_graph(50), plugin_modules=()).start(spawned).finish()
    assert done.exit_code == 0
    run_end, run_json = done.run_end, done.run_json
    assert run_end is not None and run_json is not None
    assert (run_end["paused_ms"], run_end["debug_intervened"]) == (0, False)
    assert run_end["active_duration_ms"] == run_end["duration_ms"]
    assert (run_json["pause_count"], run_json["paused_ms"], run_json["debug_intervened"]) == (
        0,
        0,
        False,
    )
    steps = [e for e in done.view.events if e["event"] != "run.end"]
    assert not [e for e in steps if "active_duration_ms" in e]


def lease_graph() -> GraphBuilder:
    """키를 한 번 누르고(입력 임대권 필요) 긴 delay에서 멈출 수 있는 그래프."""
    return (
        GraphBuilder()
        .entry("n_key")
        .node("n_key", "core.input.key", inputs={"keys": "a"}, next={"done": "n_d1"})
        .node("n_d1", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_paused_run_keeps_lease(tmp_path: Path, spawned: Spawned) -> None:
    h = RunnerHarness.make(tmp_path, lease_graph(), plugin_modules=()).start(spawned)
    pause_in_poll(h, "n_d1")
    time.sleep(1.0)
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is False
    assert lease["owner"]["run_id"] == h.run_dir.name.rsplit("_", 1)[1]
    assert h.pause() == "paused"
    h.cancel()
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True


@pytest.mark.parametrize("how", ["cancel", "supervisor_lost"])
def test_cancel_and_supervisor_loss_while_paused_finish_within_real_grace(
    tmp_path: Path, spawned: Spawned, how: str
) -> None:
    # 검수 M7: 멈춘 채 취소·감독자 사망 → 마무리 유예는 실제 시간(활성 시계가 멈춰 있어도 늘지
    # 않는다), 키는 떼였고 임대권은 깨끗하게 놓였다
    grace_ms = 2_000
    h = RunnerHarness.make(
        tmp_path,
        lease_graph(),
        plugin_modules=(),
        shutdown_grace_ms=grace_ms,
        dummy_supervisor=how == "supervisor_lost",
        hard_stop=how == "cancel",
    ).start(spawned)
    pause_in_poll(h, "n_d1")
    time.sleep(1.0)
    began = time.monotonic()
    if how == "cancel":
        assert h.cancel() == "cancelling"
    else:
        h.kill_supervisor()
    done = h.finish(recover_record=how == "cancel")
    assert time.monotonic() - began < grace_ms / 1000 + 3
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["finalized_by"] == "runner"
    expected = "cancelled" if how == "cancel" else "supervisor_lost"
    assert run_end["cancel_reason"] == expected and run_end["code"] == "cancelled"
    assert run_end["debug_intervened"] is True and run_end["paused_ms"] >= 950
    assert done.of("debug.resume") == []
    ops = [line["op"] for line in h.fake_inputs() if line["by"] == "runner"]
    assert ops.count("down") == ops.count("up")
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True


def test_step_point_depth() -> None:
    point = StepPoint("s3", "n_wait", "subgraphs/wait.graph.json", ("n_call", "n_wait"))
    assert point.depth == 2
    assert point.to_event() == {
        "step": "s3",
        "node": "n_wait",
        "graph": "subgraphs/wait.graph.json",
        "path": ["n_call", "n_wait"],
    }


def test_active_clock_freezes_while_paused() -> None:
    now = [10_000_000]
    clock = ActiveClock(now_ns=lambda: now[0])
    assert clock.now_ms() == 10 and clock.pauses == 0
    clock.pause()
    now[0] += 2_000_000_000
    assert clock.now_ms() == 10 and clock.paused and clock.paused_ms == 2_000
    clock.pause()  # 이미 멈춰 있으면 그대로 (횟수도 그대로)
    assert clock.pauses == 1
    assert clock.resume() == 2_000 and not clock.paused
    now[0] += 5_000_000
    assert clock.now_ms() == 15 and clock.paused_ms == 2_000
    assert clock.resume() == 0  # 멈춰 있지 않으면 0


def test_active_clock_reads_from_other_threads() -> None:
    clock = ActiveClock()
    clock.pause()
    seen: list[int] = []
    reader = threading.Thread(target=lambda: seen.extend(clock.now_ms() for _ in range(3)))
    reader.start()
    reader.join(5)
    assert len(set(seen)) == 1  # 멈춘 동안은 어느 스레드에서 읽어도 같은 값
    clock.resume()
