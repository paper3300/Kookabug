"""T5 검수(1라운드) 지적의 회귀 검사.

- 기본 정책: 워크스페이스·테스트에 `record`가 없으면 영상은 `failed_only` — pass는 지우고 fail은
  남김
- 인코더 열기 시험이 느리면 그 구간을 `starting` 빈 구간으로 남기고, 그 사이 시작한 게이트 off
  구간은 시험 뒤로 잘라 빈 구간이 겹치지 않는다
- 기록 끈 서브그래프 호출 스텝은 분류 순간부터 off (서브그래프 첫 스텝까지 사이에도 켜지지 않음)
- 녹화 스레드가 더 쓰지 않으면(사용 불가·쓰기 실패) 게이트가 off 구간을 쌓지 않는다
- 실행기가 끝나면 게이트를 닫아 녹화 멈춤 전에 기본 정책으로 다시 켜지지 않는다
"""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import subgraph_interface
from helpers.run import tk
from helpers.runner import RunnerHarness
from helpers.video import go, launch, run_video, segment_lines, write_scenario

from kb_testing.proc import Spawned
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.record.video import (
    INDEX_FILE,
    TEST_ENV,
    VIDEO_DIR,
    EncoderProbe,
    EncoderUnavailable,
    FakeEncoderFactory,
    VideoFrame,
    VideoGate,
    VideoRecorder,
)
from kookabug_sdk.types import WindowRef

SUB = "subgraphs/s.graph.json"


def graph(end: str = "core.test.pass") -> Any:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    g.node("n_a", "core.input.key", inputs=go("a"), next={"done": "n_w"})
    g.node("n_w", "core.flow.delay", inputs={"ms": 800}, next={"done": "n_end"})
    return g.node("n_end", end)


@pytest.mark.process
@pytest.mark.parametrize(("end", "kept"), [("core.test.pass", False), ("core.test.fail", True)])
def test_default_workspace_video_is_failed_only(
    tmp_path: Path, spawned: Spawned, end: str, kept: bool
) -> None:
    scenario = write_scenario(tmp_path / "scenario")
    env = {TEST_ENV: json.dumps({"encoder": "fake"})}
    # 워크스페이스·테스트에 record가 없다
    h = RunnerHarness.make(tmp_path, graph(end), scenario=str(scenario), env_extra=env)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    index = json.loads((h.run_dir / VIDEO_DIR / INDEX_FILE).read_text(encoding="utf-8"))
    files = list((h.run_dir / VIDEO_DIR).glob("seg-*.mp4"))
    if kept:
        assert index["segments"] and files and index["deleted"] == []
        assert {s["mode"] for s in index["segments"]} == {"failed_only"}
    else:
        assert index["segments"] == [] and not files
        assert {d["reason"] for d in index["deleted"]} == {"run_pass"}
    assert done.run_json is not None and done.run_json["video"]["kept"] == (1 if kept else 0)


def test_slow_probe_leaves_starting_gap_and_no_overlap(tmp_path: Path) -> None:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("on")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    factory = FakeEncoderFactory(probe_delay_s=0.8)
    recorder = VideoRecorder(run_dir, gate, platform, factory).start()
    # 시험을 기다리는 동안 게이트가 바뀐다 (창 없음 → 기록)
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=None)
    gate.release("s1")
    gate.hold("s2")
    gate.classify("s2", "on", secret=False, window=game.window)
    time.sleep(1.6)
    gate.release("s2")
    assert recorder.stop()
    lines = segment_lines(run_dir)
    gaps = [line for line in lines if "gap" in line]
    # 시험을 기다리는 동안에도 창이 생긴 뒤 프레임은 모아 쓴다 (R1 F1): starting 빈 구간은 창이
    # 생기기 전 짧은 구간뿐이라 한 칸보다 짧으면 남지 않는다
    for g in gaps:
        if g["gap"] == "starting":
            assert g["t_start"] < g["t_end"]
    spans = sorted(
        [(g["t_start"], g["t_end"]) for g in gaps]
        + [(s["t0"], s["t_end"]) for s in lines if "file" in s]
    )
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert end <= start, spans  # 빈 구간·조각이 겹치지 않는다
    assert any("file" in line for line in lines)


def test_stop_before_probe_done_leaves_starting_gap(tmp_path: Path) -> None:
    gate = VideoGate()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = EncoderProbe(FakeEncoderFactory(probe_delay_s=1.5))
    recorder = VideoRecorder(run_dir, gate, _NoSource(), None, probe=probe).start()
    time.sleep(0.4)
    assert recorder.stop()
    (gap,) = segment_lines(run_dir)
    assert gap["gap"] == "starting" and gap["t_start"] < gap["t_end"]


def test_off_subgraph_call_step_classified_off(tmp_path: Path) -> None:
    states: list[tuple[str, str, str | None]] = []

    class Spy(VideoGate):
        def classify(self, step: str, mode: Any, *, secret: bool, window: WindowRef | None) -> None:
            super().classify(step, mode, secret=secret, window=window)
            view = self.view()
            states.append((step, view.state, view.gap))

    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_call")
    g.call("n_call", SUB, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    sub = tk("subgraph", interface=subgraph_interface(), record={"video": "off"}).entry("n_x")
    sub.exit("n_x", "done")
    import helpers.video as helper

    real = helper.VideoGate
    helper.VideoGate = Spy  # type: ignore[misc]
    try:
        ran = run_video(tmp_path, g, subgraphs={SUB: sub})
    finally:
        helper.VideoGate = real  # type: ignore[misc]
    call, _ = ran.step("n_call")
    (state,) = [s for s in states if s[0] == call["step"]]
    assert state[1:] == ("off", "policy_off")


@pytest.mark.parametrize("dead", ["unavailable", "failed"])
def test_dead_recorder_does_not_accumulate_off_spans(tmp_path: Path, dead: str) -> None:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    window = scenario.launch_game("game.exe").window
    gate = VideoGate()
    gate.set_base("on")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    if dead == "unavailable":
        recorder = VideoRecorder(
            run_dir,
            gate,
            platform,
            FakeEncoderFactory(),
            unavailable=EncoderUnavailable("mf_missing", "주입"),
        ).start()
    else:
        recorder = VideoRecorder(run_dir, gate, platform, FakeEncoderFactory(fail_write=1)).start()
        gate.hold("w")
        gate.classify("w", "on", secret=False, window=window)
    time.sleep(0.6)
    for i in range(5_000):  # 비밀값 스텝이 이어지는 반복
        gate.hold(f"s{i}")
        gate.classify(f"s{i}", "on", secret=True, window=window)
        gate.release(f"s{i}")
    assert len(gate._spans) <= 1  # pyright: ignore[reportPrivateUsage]
    assert recorder.stop()
    assert recorder.status == dead


def test_closed_gate_stops_recording_before_stop(tmp_path: Path) -> None:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("on")
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    factory = FakeEncoderFactory()
    probe = EncoderProbe(factory)
    assert probe.done.wait(5)
    recorder = VideoRecorder(run_dir, gate, platform, factory, probe=probe).start()
    time.sleep(0.7)
    gate.release("s1")  # 실행기가 끝났다 (취소로 비밀값 스텝이 풀린 경우도 같다)
    gate.close()
    closed_at = time.time()
    platform.scenario.apply(game, "key", "f2")  # 판정 뒤 화면이 바뀐다
    time.sleep(0.8)
    assert gate.view().state == "off"
    assert recorder.stop()
    segs = [line for line in segment_lines(run_dir) if "file" in line]
    assert segs
    from datetime import datetime

    assert all(datetime.fromisoformat(s["t_end"]).timestamp() <= closed_at + 0.05 for s in segs)
    written = (run_dir / VIDEO_DIR / segs[-1]["file"]).read_text(encoding="utf-8")
    assert '"marker": "a"' not in written  # 닫은 뒤 장면(a)은 없다


class _NoSource:
    def video_frame(self, window: Any, timeout_ms: int) -> VideoFrame:
        raise RuntimeError("없음")
