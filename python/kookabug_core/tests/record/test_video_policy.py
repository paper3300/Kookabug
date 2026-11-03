"""영상 정책·게이트·격자·조각·보관 (구현 계획 M3 2.5, T5). 가짜 인코더(`FakeEncoderFactory`)가
칸마다 장면 표시를 적으므로 "그 장면이 어떤 조각에도 없음"을 칸 단위로 대조한다.

- 게이트는 열린 스텝 스택 전체를 본다 (검수 H1): 비밀값을 받은 호출 아래 모든 스텝 구간에 영상 없음
- `step.start` 전 보류 차단 (2차 N1): 분류 전 새 픽셀 없음, 스텝마다 조각을 자르지 않음, 이벤트 순서
  그대로. 입력 계산 실패도 그 스텝의 `step.start`·`step.end`·실패 위치가 남는다 (실제 runner)
- 5 fps 격자 (검수 M3): 늦은 캡처는 직전 프레임 반복, off에서 조각을 닫음, 2초 넘게 반복이면 닫음
- 보관 (사용자 결정 U5): `failed_only`는 pass·사용자 취소에 지우고 fail·error에 남김, `on`은 늘 남김
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import link, secret, subgraph_interface
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of
from helpers.video import (
    SCENES,
    VIDEO_ON_REDACT,
    Blocker,
    go,
    launch,
    on_event,
    run_video,
    segment_lines,
    switch,
    wait_slots,
    write_scenario,
)

from kb_testing.proc import Spawned, wait_until
from kookabug_core.engine.debug import Breakpoint
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.record.finalize import finalize_video
from kookabug_core.record.video import (
    FRAME_MS,
    TEST_ENV,
    FakeEncoderFactory,
    VideoFrame,
    VideoGate,
    VideoRecorder,
    stamp,
)

TEST_GRAPH = "tests/t.graph.json"
SUB = "subgraphs/s.graph.json"
INNER = "subgraphs/inner.graph.json"
DELAY = 600
PW = {"acc.pw": "hunter2"}
"""장면 하나를 보여 주는 시간 (ms). 칸 3장이 넘는다."""


def show(g: Any, node: str, scene: str, then: str, *, ms: int = DELAY, **kw: Any) -> Any:
    """`node`: 장면을 바꾸는 키 → `node`_w: 기다림 → `then`."""
    g.node(node, "core.input.key", inputs=go(scene), next={"done": f"{node}_w"}, **kw)
    return g.node(f"{node}_w", "core.flow.delay", inputs={"ms": ms}, next={"done": then})


def test_policy_off_subgraph_has_no_frames_in_video(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_call")
    g.call("n_call", SUB, next={"done": "n_b"})
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    sub = tk("subgraph", interface=subgraph_interface(), record={"video": "off"}).entry("n_c")
    show(sub, "n_c", "c", "n_back")
    show(sub, "n_back", "idle", "n_x", ms=0)
    sub.exit("n_x", "done")
    ran = run_video(tmp_path, g, subgraphs={SUB: sub})
    assert ran.result.verdict == "pass", ran.result.reason
    markers = ran.markers()
    assert {"a", "b"} <= markers
    assert "c" not in markers
    # 서브그래프 구간 시각에는 어떤 조각의 칸도 없다
    start, end = ran.span("n_call")
    for seg in ran.segments():
        assert seg["t_end"] <= start or seg["t0"] >= end, (seg, start, end)
    (gap,) = [g for g in ran.gaps() if g["gap"] == "policy_off"]
    assert gap["step"] == ran.step("n_call")[0]["step"]


def _secret_tree(tmp_path: Path) -> Any:
    """비밀값을 받은 호출 → (비밀값을 직접 받는 자식 / 일반 대기 자식 / 중첩 호출의 대기 자식)."""
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_call")
    g.call("n_call", SUB, inputs={"pw": secret("acc.pw")}, next={"done": "n_b"})
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    sub = tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"})).entry("n_c")
    # 비밀값을 직접 받는 자식 (스크린샷도 남기려 한다)
    sub.node("n_c", "core.input.key", inputs=go("c"), next={"done": "n_shot"})
    sub.node(
        "n_shot",
        "testkit.shot",
        inputs={"save": True, "value": link("n_entry.pw")},
        next={"done": "n_d"},
    )
    show(sub, "n_d", "d", "n_inner")  # 비밀값을 받지 않는 대기 자식
    sub.call("n_inner", INNER, next={"done": "n_back"})
    show(sub, "n_back", "idle", "n_x", ms=0)
    sub.exit("n_x", "done")
    inner = tk("subgraph", interface=subgraph_interface()).entry("n_e")
    show(inner, "n_e", "e", "n_shot2")
    inner.node("n_shot2", "testkit.shot", inputs={"save": True}, next={"done": "n_x"})
    inner.exit("n_x", "done")
    return g, {SUB: sub, INNER: inner}


def test_secret_call_blocks_video_for_whole_call_subtree(tmp_path: Path) -> None:
    g, subs = _secret_tree(tmp_path)
    ran = run_video(tmp_path, g, subgraphs=subs, secrets=PW, ws_record=VIDEO_ON_REDACT)
    assert ran.result.verdict == "pass", ran.result.reason
    markers = ran.markers()
    assert {"a", "b"} <= markers
    assert not ({"c", "d", "e"} & markers), markers
    start, end = ran.span("n_call")
    for seg in ran.segments():
        assert seg["t_end"] <= start or seg["t0"] >= end, (seg, start, end)
    (gap,) = [g for g in ran.gaps() if g["gap"] == "secret_input"]
    assert gap["step"] == ran.step("n_call")[0]["step"]


def test_secret_call_screenshot_exception_unchanged(tmp_path: Path) -> None:
    # 영상 차단은 스택에서 따로 센다: 비밀값을 받지 않는 안쪽 스텝의 스크린샷은 M1 규칙대로 남는다
    g, subs = _secret_tree(tmp_path)
    ran = run_video(tmp_path, g, subgraphs=subs, secrets=PW, ws_record=VIDEO_ON_REDACT)
    _, shot = ran.step("n_shot")
    assert shot is not None and shot["outputs"]["saved"] is None
    assert [o["reason"] for o in shot["omitted"]] == ["secret_input"]
    _, shot2 = ran.step("n_shot2")
    assert shot2 is not None and shot2["outputs"]["saved"] is not None
    assert "omitted" not in shot2


def test_secret_call_fail_evidence_still_saved(tmp_path: Path) -> None:
    # 호출 스텝의 실패 증거는 호출 노드의 비밀값 입력으로 막지 않는다 (M1 T12) — 영상만 막힌다
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_call")
    g.call("n_call", SUB, inputs={"pw": secret("acc.pw")})
    sub = tk(
        "subgraph", interface=subgraph_interface(exits={"bad": "fail"}, inputs={"pw": "secret"})
    ).entry("n_c")
    show(sub, "n_c", "c", "n_shot", ms=300)
    sub.node("n_shot", "testkit.shot", next={"done": "n_x"})
    sub.exit("n_x", "bad")
    ran = run_video(tmp_path, g, subgraphs={SUB: sub}, secrets=PW, ws_record=VIDEO_ON_REDACT)
    assert ran.result.verdict == "fail"
    _, call = ran.step("n_call")
    assert call is not None
    assert any(a.endswith("_fail.png") for a in call.get("artifacts", ())), call
    assert "c" not in ran.markers()


def test_child_end_or_exception_does_not_reopen_parent_block(tmp_path: Path) -> None:
    # 자식 스텝이 끝나거나 예외로 닫혀도(잡힌 실패 분기 포함) 비밀값 호출이 열려 있으면 off
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_call")
    g.call("n_call", SUB, inputs={"pw": secret("acc.pw")}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    sub = tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"})).entry("n_c")
    show(sub, "n_c", "c", "n_fail")
    # 자식이 fail 출구로 끝나고(연결된 분기) 그 뒤에도 호출 안에서 장면이 이어진다
    sub.node(
        "n_fail",
        "testkit.fail_once",
        inputs={"exit": "fail"},
        next={"fail": "n_d", "ok": "n_d", "timeout": "n_d"},
    )
    show(sub, "n_d", "d", "n_back")
    show(sub, "n_back", "idle", "n_x", ms=0)
    sub.exit("n_x", "done")
    ran = run_video(tmp_path, g, subgraphs={SUB: sub}, secrets=PW, ws_record=VIDEO_ON_REDACT)
    assert not ({"c", "d"} & ran.markers())
    # 게이트 단위: 자식이 예외로 닫혀도 부모 차단은 그대로
    gate = VideoGate()
    gate.set_base("on")
    gate.hold("s1")
    gate.classify("s1", "on", secret=True, window=None)
    gate.hold("s2")
    gate.classify("s2", "on", secret=False, window=None)
    gate.release("s2")  # 자식이 (예외로) 닫힘
    view = gate.view()
    assert (view.state, view.gap, view.step) == ("off", "secret_input", "s1")
    gate.release("s1")
    assert gate.view().gap != "secret_input"


def test_pending_gate_blocks_new_pixels_until_classified(tmp_path: Path) -> None:
    # 스텝의 step.start 직후(분류 전) 장면이 바뀌고 0.6초 머문다.
    # - 비밀값 스텝(n_secret, 장면 c): c는 어디에도 없고, 빈 구간은 그 스텝의 step.start부터
    # - 일반 스텝(n_plain, 장면 d): 보류 칸은 보류 전 프레임(b) 반복, 조각은 잘리지 않음
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_secret")
    g.node("n_secret", "testkit.shot", inputs={"value": secret("acc.pw")}, next={"done": "n_b"})
    show(g, "n_b", "b", "n_plain")
    g.node("n_plain", "testkit.sleep", inputs={"ms": 0}, next={"done": "n_wait"})
    g.node("n_wait", "core.flow.delay", inputs={"ms": 400}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")

    def to(scene: str, hold: float = 0.0) -> Any:
        def action(platform: ScenarioPlatform, gate: VideoGate) -> None:
            switch(platform, scene)
            time.sleep(hold)

        return action

    def recording(segments: int) -> Any:
        # 녹화 시작·차단이 풀린 뒤 첫 칸이 늦으면(느린 러너) 비밀값·일반 스텝 앞에 조각이 없어 아래
        # 검사가 빈다 — 그 앞 장면 스텝 끝(아직 스택에 있다, 게이트 기록)에서 조각을 기다린다
        def action(platform: ScenarioPlatform, gate: VideoGate) -> None:
            wait_slots(tmp_path / "run", segments)

        return action

    ran = run_video(
        tmp_path,
        g,
        secrets=PW,
        ws_record=VIDEO_ON_REDACT,
        hooks=[
            on_event("step.end", "n_a", recording(1)),
            on_event("step.start", "n_secret", to("c", 0.6)),
            on_event("step.end", "n_secret", to("idle")),  # 아직 스택에 있다 (게이트 off)
            on_event("step.end", "n_b", recording(2)),
            on_event("step.start", "n_plain", to("d", 0.6)),
        ],
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert "c" not in ran.markers()
    start, _ = ran.span("n_secret")
    (gap,) = [g for g in ran.gaps() if g["gap"] == "secret_input"]
    assert gap["t_start"] <= start
    before = [s for s in ran.segments() if s["t0"] < start]
    assert before and before[-1]["t_end"] <= start
    # 일반 스텝의 보류: 보류 전 프레임(b)을 반복하고, 그 뒤 d가 이어서 같은 조각에 들어간다
    plain, _ = ran.span("n_plain")
    (seg,) = [s for s in ran.segments() if s["t0"] < plain < s["t_end"]]
    lines = ran.written[seg["file"]]
    frames = _frames(ran.run_dir, seg["file"])
    held = [
        (line["marker"], frame["repeat"])
        for line, frame in zip(lines, frames, strict=True)
        if plain < _slot_at(seg, frame["slot"]) <= _shift(plain, 0.35)
    ]
    assert held and all(item == ("b", True) for item in held), held
    assert "d" in {line["marker"] for line in lines}


def _slot_at(seg: dict[str, Any], slot: int) -> str:
    from datetime import datetime

    t0 = datetime.fromisoformat(seg["t0"]).timestamp()
    return stamp(t0 + slot * FRAME_MS / 1000)


def _shift(t: str, seconds: float) -> str:
    from datetime import datetime

    return stamp(datetime.fromisoformat(t).timestamp() + seconds)


def _frames(run_dir: Path, segment: str) -> list[dict[str, Any]]:
    path = run_dir / "video" / segment.replace(".mp4", ".frames.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_pending_gate_does_not_split_segments_for_normal_steps(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_loop")
    g.node(
        "n_loop", "core.flow.repeat", inputs={"times": 40}, next={"body": "n_d", "done": "n_pass"}
    )
    g.node("n_d", "core.flow.delay", inputs={"ms": 30})
    g.node("n_pass", "core.test.pass")
    ran = run_video(tmp_path, g)
    assert ran.result.verdict == "pass", ran.result.reason
    assert len(ran.of("step.start")) > 80
    assert len(ran.segments()) == 1, ran.segments()
    assert ran.segments()[0]["frames"] >= 5


def test_event_order_unchanged_step_start_before_input_eval(tmp_path: Path) -> None:
    def graph() -> Any:
        g = tk().entry("n_launch")
        launch(g, "n_launch", "n_a")
        show(g, "n_a", "a", "n_set", ms=0)
        g.node("n_get", "core.var.get", inputs={"name": "x"})
        g.node("n_set", "core.var.set", inputs={"name": "x", "value": 7}, next={"done": "n_log"})
        g.node("n_log", "core.log.message", inputs={"text": link("n_get.value")})
        return g

    # 입력 계산 실패(var.get(any) → string 핀의 type_mismatch)까지 같은 순서
    ran = run_video(tmp_path / "v", graph())
    plain = run_video(tmp_path / "p", graph(), video=False)
    assert ran.result.code == plain.result.code == "type_mismatch"

    def shape(events: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return [(e["event"], e.get("step"), e.get("node")) for e in events]

    assert shape(ran.events) == shape(plain.events)


def test_secret_input_step_has_no_frames(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_secret")
    g.node(
        "n_secret",
        "testkit.sleep",
        inputs={"ms": DELAY, "value": secret("acc.pw")},
        next={"done": "n_back"},
    )
    show(g, "n_back", "b", "n_pass")
    g.node("n_pass", "core.test.pass")

    def at_start(platform: ScenarioPlatform, gate: VideoGate) -> None:
        switch(platform, "c")

    def at_end(platform: ScenarioPlatform, gate: VideoGate) -> None:
        switch(platform, "idle")

    ran = run_video(
        tmp_path,
        g,
        secrets=PW,
        ws_record=VIDEO_ON_REDACT,
        hooks=[
            on_event("step.start", "n_secret", at_start),
            on_event("step.end", "n_secret", at_end),
        ],
    )
    assert "c" not in ran.markers()
    start, end = ran.span("n_secret")
    for seg in ran.segments():
        assert seg["t_end"] <= start or seg["t0"] >= end, (seg, start, end)
    assert any(g["gap"] == "secret_input" for g in ran.gaps())


def test_gate_closed_before_step_start_drops_inflight_frame(tmp_path: Path) -> None:
    # 녹화 스레드가 프레임을 가져오는 중에 비밀값 스텝이 시작·분류되고 장면이 바뀐다
    # → 그 프레임을 버린다
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    source = Blocker(platform)
    gate = VideoGate()
    gate.set_base("on")
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorder = VideoRecorder(run_dir, gate, source, FakeEncoderFactory()).start()
    time.sleep(0.5)  # 조각을 연다 (idle)
    source.armed.set()
    assert source.entered.wait(5)
    gate.release("s1")
    gate.hold("s2")  # step.start 전 보류
    switch(platform, "c")  # 가져오는 중에 장면이 바뀐다
    gate.classify("s2", "on", secret=True, window=game.window)
    source.release.set()  # 가져오기가 끝나 c를 돌려준다 → 버려야 한다
    time.sleep(0.5)
    switch(platform, "idle")
    gate.release("s2")
    time.sleep(0.4)
    assert recorder.stop()
    markers = {line["marker"] for lines in _fake(run_dir).values() for line in lines}
    assert "c" not in markers and "idle" in markers


def _fake(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    from helpers.video import fake_lines

    return fake_lines(run_dir)


def test_paused_span_not_recorded(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_b")
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    holder: dict[str, Any] = {}

    def before(point: Any) -> None:
        if point.node != "n_b":
            return
        gate: VideoGate = holder["gate"]
        platform: ScenarioPlatform = holder["platform"]
        gate.set_paused(True, point.step)  # 디버거 멈춤 동안 사람이 게임을 만진다
        switch(platform, "c")
        time.sleep(0.6)
        switch(platform, "a")
        gate.set_paused(False, point.step)

    def grab(event: dict[str, Any], platform: ScenarioPlatform, gate: VideoGate) -> None:
        holder.update(platform=platform, gate=gate)

    ran = run_video(tmp_path, g, hooks=[grab], before_step=before)
    assert ran.result.verdict == "pass", ran.result.reason
    assert "c" not in ran.markers()
    (paused,) = [g for g in ran.gaps() if g["gap"] == "paused"]
    assert paused["step"] == ran.step("n_b")[0]["step"]


def test_gaps_recorded_with_reasons(tmp_path: Path) -> None:
    g = tk().entry("n_a0")
    # 창을 정하기 전 → no_window, 구간 끄기 → policy_off, 비밀값 → secret_input
    g.node("n_a0", "core.flow.delay", inputs={"ms": 300}, next={"done": "n_launch"})
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off")
    g.node(
        "n_off",
        "core.flow.delay",
        inputs={"ms": 400},
        next={"done": "n_secret"},
        record={"video": "off"},
    )
    g.node(
        "n_secret",
        "testkit.sleep",
        inputs={"ms": 400, "value": secret("acc.pw")},
        next={"done": "n_b"},
    )
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    ran = run_video(tmp_path, g, secrets=PW, ws_record=VIDEO_ON_REDACT)
    reasons = [gap["gap"] for gap in ran.gaps()]
    assert reasons[:1] == ["no_window"], reasons
    assert "policy_off" in reasons and "secret_input" in reasons
    for gap in ran.gaps():
        assert gap["t_start"] <= gap["t_end"]
    assert ran.index is not None
    assert [g["gap"] for g in ran.index["gaps"]] == sorted(reasons, key=lambda r: reasons.index(r))


# ---------------------------------------------------------------- 격자 (검수 M3)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def mono(self) -> float:
        return self.now

    def wall(self) -> float:
        return self.now + 1_700_000_000.0


def test_grid_fills_late_captures_with_repeat(tmp_path: Path) -> None:
    from kookabug_core.record.video import _Segment  # pyright: ignore[reportPrivateUsage]

    clock = _Clock()
    gate = VideoGate(mono=clock.mono, wall=clock.wall)
    recorder = VideoRecorder(tmp_path, gate, _NoSource(), FakeEncoderFactory())
    recorder.dir.mkdir()
    t0 = clock.now

    def frame(marker: str, at: float) -> VideoFrame:
        return VideoFrame(None, (8, 8), clock.wall() if at < 0 else at, marker)

    # 캡처가 0.0·0.2·0.8·1.0초에 도착 → 칸 0~5: A B B(반복) B(반복) C D
    seg = _Segment(recorder, 1, "on", "w", (8, 8), t0, frame("A", -1))
    for delay, marker in ((0.2, "B"), (0.8, "C"), (1.0, "D")):
        clock.now = t0 + delay
        seg.offer(frame(marker, -1), clock.now)
    clock.now = t0 + 1.2
    line = seg.close(clock.now)
    assert line is not None and line["frames"] == 6
    written = [json.loads(x) for x in seg.part.with_name("seg-0001.mp4").read_text().splitlines()]
    assert [w["marker"] for w in written] == ["A", "B", "B", "B", "C", "D"]
    frames = _frames(tmp_path, "seg-0001.mp4")
    assert [f["slot"] for f in frames] == [0, 1, 2, 3, 4, 5]
    assert [f["repeat"] for f in frames] == [False, False, True, True, False, False]
    assert line["t0"] == stamp(clock.wall() - 1.2)
    assert line["t_end"] == stamp(clock.wall() - 1.2 + 6 * FRAME_MS / 1000)


class _NoSource:
    def video_frame(self, window: Any, timeout_ms: int) -> VideoFrame:
        raise RuntimeError("없음")


def test_gate_off_closes_segment_no_gap_inside(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off")
    g.node(
        "n_off",
        "core.flow.delay",
        inputs={"ms": 500},
        next={"done": "n_b"},
        record={"video": "off"},
    )
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    ran = run_video(tmp_path, g)
    segs = ran.segments()
    assert len(segs) >= 2
    (off,) = [g for g in ran.gaps() if g["gap"] == "policy_off"]
    for seg in segs:
        # 조각 안에 빈 구간이 없다: 칸 수 = (t_end - t0) / 200ms, 빈 구간과 겹치지 않음
        frames = _frames(ran.run_dir, seg["file"])
        assert [f["slot"] for f in frames] == list(range(seg["frames"]))
        assert seg["t_end"] <= off["t_start"] or seg["t0"] >= off["t_end"], (seg, off)


class _Flaky:
    """처음 몇 장은 주고 그 뒤 `fail_after`초 동안 실패하는 출처."""

    def __init__(self, inner: Any, fail_from: float, fail_until: float) -> None:
        self.inner = inner
        self.fail_from = fail_from
        self.fail_until = fail_until
        self.started = time.monotonic()

    def video_frame(self, window: Any, timeout_ms: int) -> VideoFrame:
        t = time.monotonic() - self.started
        if self.fail_from <= t < self.fail_until:
            raise TimeoutError("캡처 지연")
        return self.inner.video_frame(window, timeout_ms)


def test_capture_missed_over_2s_closes_segment(tmp_path: Path) -> None:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("on")
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    source = _Flaky(platform, 0.6, 3.4)
    recorder = VideoRecorder(run_dir, gate, source, FakeEncoderFactory()).start()
    time.sleep(4.2)
    assert recorder.stop()
    lines = segment_lines(run_dir)
    segs = [line for line in lines if "file" in line]
    missed = [line for line in lines if line.get("gap") == "capture_missed"]
    assert len(segs) == 2 and len(missed) == 1, lines
    assert segs[0]["t_end"] <= missed[0]["t_start"] <= missed[0]["t_end"] <= segs[1]["t0"]
    # 닫은 조각의 반복은 2초(10칸)를 조금 넘는 데서 끝난다
    frames = _frames(run_dir, segs[0]["file"])
    tail = 0
    for f in reversed(frames):
        if not f["repeat"]:
            break
        tail += 1
    assert 10 <= tail <= 13, frames


# ---------------------------------------------------------------- 보관 (사용자 결정 U5)


def _simple(*, end: str = "core.test.pass", ms: int = DELAY) -> Any:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_end", ms=ms)
    return g.node("n_end", end)


def test_failed_only_deleted_on_pass(tmp_path: Path) -> None:
    ran = run_video(tmp_path, _simple(), ws_record={"video": "failed_only"})
    assert ran.result.verdict == "pass"
    assert ran.index is not None
    assert ran.index["segments"] == [] and ran.index["status"] == "recorded"
    assert {d["reason"] for d in ran.index["deleted"]} == {"run_pass"}
    assert not list((ran.run_dir / "video").glob("seg-*"))


@pytest.mark.parametrize(
    ("end", "verdict"), [("core.test.fail", "fail"), ("testkit.boom", "error")]
)
def test_failed_only_kept_on_fail_and_error(tmp_path: Path, end: str, verdict: str) -> None:
    ran = run_video(tmp_path, _simple(end=end), ws_record={"video": "failed_only"})
    assert ran.result.verdict == verdict
    assert ran.index is not None and ran.index["deleted"] == []
    kept = ran.index["segments"]
    assert kept and all(s["mode"] == "failed_only" for s in kept)
    for seg in kept:
        assert (ran.run_dir / "video" / seg["file"]).exists()


def test_user_cancel_deletes_failed_only(tmp_path: Path) -> None:
    ran = run_video(
        tmp_path,
        _simple(),
        ws_record={"video": "failed_only"},
        run_end={"verdict": "error", "code": "cancelled", "cancel_reason": "cancelled"},
    )
    assert ran.index is not None and ran.index["segments"] == []
    assert {d["reason"] for d in ran.index["deleted"]} == {"run_cancelled"}
    # 기한 초과는 error라 남긴다
    again = finalize_video(ran.run_dir, {"verdict": "error", "cancel_reason": "deadline_exceeded"})
    assert again is not None and again["segments"] == []  # 이미 지운 것은 되살아나지 않는다


def test_on_segments_always_kept(tmp_path: Path) -> None:
    ran = run_video(tmp_path, _simple(), ws_record={"video": "on"})
    assert ran.index is not None and ran.index["deleted"] == []
    assert ran.index["segments"] and all(s["mode"] == "on" for s in ran.index["segments"])


@pytest.mark.parametrize("ws_video", [None, "failed_only"])
def test_lower_layer_on_cannot_loosen_workspace_default(
    tmp_path: Path, ws_video: str | None
) -> None:
    # T5 재검수 Low: 기본 failed_only는 워크스페이스 층이다. 테스트·노드에 `video: on`을 써도
    # 아래 층은 더 세게만 바꿀 수 있어 pass 실행의 조각은 지워진다(스키마 6장 "워크스페이스 정책").
    # 성공 실행 영상을 남기려면 워크스페이스에서 on을 명시한다
    g = tk(record={"video": "on"}).entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_end", record={"video": "on"})
    g.node("n_end", "core.test.pass")
    ws_record = None if ws_video is None else {"video": ws_video}
    ran = run_video(tmp_path, g, ws_record=ws_record)
    assert ran.result.verdict == "pass"
    assert ran.written  # 녹화는 했고
    assert ran.index is not None and ran.index["segments"] == []
    assert {d["reason"] for d in ran.index["deleted"]} == {"run_pass"}
    # 워크스페이스가 on이면 같은 그래프의 조각이 남는다
    kept = run_video(tmp_path / "on", g, ws_record={"video": "on"})
    assert kept.index is not None and kept.index["segments"]
    assert all(s["mode"] == "on" for s in kept.index["segments"])


def test_mixed_modes_split_segments(tmp_path: Path) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_b")
    g.node(
        "n_b",
        "core.input.key",
        inputs=go("b"),
        next={"done": "n_b_w"},
        record={"video": "failed_only"},
    )
    g.node(
        "n_b_w",
        "core.flow.delay",
        inputs={"ms": DELAY},
        next={"done": "n_c"},
        record={"video": "failed_only"},
    )
    show(g, "n_c", "c", "n_pass")
    g.node("n_pass", "core.test.pass")
    ran = run_video(tmp_path, g)
    modes = [s["mode"] for s in ran.segments()]
    assert "on" in modes and "failed_only" in modes
    assert ran.index is not None
    # pass: failed_only 조각만 지운다
    assert all(s["mode"] == "on" for s in ran.index["segments"])
    assert {d["mode"] for d in ran.index["deleted"]} == {"failed_only"}
    for name, lines in ran.written.items():
        mode = next(s["mode"] for s in ran.segments() if s["file"] == name)
        if mode == "failed_only":
            assert {line["marker"] for line in lines} <= {"a", "b"}


def test_segment_rotates_on_60s_and_resize(tmp_path: Path) -> None:
    from kookabug_core.record.video import SEGMENT_SLOTS, _Segment  # pyright: ignore[reportPrivateUsage]

    clock = _Clock()
    gate = VideoGate(mono=clock.mono, wall=clock.wall)
    recorder = VideoRecorder(tmp_path, gate, _NoSource(), FakeEncoderFactory())
    recorder.dir.mkdir()
    first = VideoFrame(None, (8, 8), clock.wall(), "A")
    recorder._seg = _Segment(recorder, 1, "on", "w", (8, 8), clock.now, first)  # pyright: ignore[reportPrivateUsage]
    recorder._next_index = 2  # pyright: ignore[reportPrivateUsage]
    # 61초 동안 칸마다 새 프레임
    for k in range(1, 305):
        clock.now += FRAME_MS / 1000
        recorder._seg.offer(VideoFrame(None, (8, 8), clock.wall(), "A"), clock.now)  # pyright: ignore[reportPrivateUsage,reportOptionalMemberAccess]
        recorder._rotate()  # pyright: ignore[reportPrivateUsage]
        del k
    lines = segment_lines(tmp_path)
    assert len(lines) == 1 and lines[0]["frames"] == SEGMENT_SLOTS
    nxt = recorder._seg  # pyright: ignore[reportPrivateUsage]
    assert nxt is not None and nxt.index == 2
    assert stamp(recorder.wall_of(nxt.t0)) == lines[0]["t_end"]  # 같은 격자로 이어짐
    # 크기가 바뀌면 닫고 새 조각
    window = scenario_window(tmp_path)
    gate.set_base("on")
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=window)
    view = gate.view()
    recorder._take(VideoFrame(None, (16, 8), clock.wall(), "B"), view, clock.now + 0.1)  # pyright: ignore[reportPrivateUsage]
    lines = segment_lines(tmp_path)
    assert len(lines) == 2 and lines[1]["size"] == [8, 8]
    assert recorder._seg is not None and recorder._seg.size == (16, 8)  # pyright: ignore[reportPrivateUsage]


def scenario_window(tmp_path: Path) -> Any:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    return scenario.launch_game("game.exe").window


def test_encoder_write_failure_does_not_fail_run(tmp_path: Path) -> None:
    ran = run_video(tmp_path, _simple(ms=1500), factory=FakeEncoderFactory(fail_write=3))
    assert ran.result.verdict == "pass"
    assert ran.index is not None
    assert (ran.index["status"], ran.index.get("reason")) == ("failed", "write_failed")
    # 쓰다 만 조각은 중단 조각으로 지워진다
    assert {d["reason"] for d in ran.index["deleted"]} == {"interrupted"}
    assert not list((ran.run_dir / "video").glob("seg-*"))


def test_scenes_are_distinct() -> None:
    assert len(set(SCENES)) == len(SCENES)


def test_recorder_does_not_advance_scenario_frames(tmp_path: Path) -> None:
    # 녹화는 장면 표의 캡처 차례(after_frames)를 세지 않는다 (녹화 때문에 전이가 바뀌지 않게)
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    before = game.state.captures
    for _ in range(5):
        platform.video_frame(game.window, 100)
    assert game.state.captures == before


# ------------------------------------------------ 입력 계산 실패 (2차 N1, 실제 runner)


def _harness(tmp_path: Path, g: Any, **kw: Any) -> RunnerHarness:
    scenario = write_scenario(tmp_path / "scenario")
    env = {TEST_ENV: json.dumps({"encoder": "fake"}), "KOOKABUG_SECRET_ACC_PW": "hunter2"}
    return RunnerHarness.make(tmp_path, g, scenario=str(scenario), env_extra=env, **kw)


def _assert_failure_step(done: Any, node: str, code: str) -> dict[str, Any]:
    run_end = done.run_end
    assert run_end is not None and run_end["code"] == code, run_end
    start, end = step_of(done.view.events, node)
    assert end is not None, "입력 계산 실패 스텝에 step.end가 없다"
    assert run_end["failure_step"] == start["step"]
    assert run_end["failure_path"] == [node]
    return end


@pytest.mark.process
def test_input_eval_failure_records_error_step_and_failure_step(
    tmp_path: Path, spawned: Spawned
) -> None:
    def graph() -> Any:
        g = tk().entry("n_launch")
        launch(g, "n_launch", "n_sec")
        # 비밀값을 받은 스텝(게이트 off) 뒤에 입력 계산이 실패하는 스텝
        g.node(
            "n_sec",
            "testkit.sleep",
            inputs={"ms": 0, "value": secret("acc.pw")},
            next={"done": "n_set"},
        )
        g.node("n_get", "core.var.get", inputs={"name": "x"})
        g.node("n_set", "core.var.set", inputs={"name": "x", "value": 7}, next={"done": "n_log"})
        # var.get(any) → string 핀: 정적 검증은 통과하고 입력 계산에서 type_mismatch
        return g.node("n_log", "core.log.message", inputs={"text": link("n_get.value")})

    done = _harness(tmp_path, graph()).start(spawned).finish()
    assert done.exit_code == 0
    end = _assert_failure_step(done, "n_log", "type_mismatch")
    assert end["status"] == "error" and end["error"]["code"] == "type_mismatch"
    assert done.run_json is not None and done.run_json["video"]["status"] in ("recorded", "none")
    # 같은 그래프를 한 프로세스에서: 실패 스텝이 닫히면 게이트 보류도 풀린다
    ran = run_video(tmp_path / "inproc", graph(), secrets=PW, ws_record=VIDEO_ON_REDACT)
    assert ran.result.code == "type_mismatch"
    view = ran.gate.view()
    assert view.state != "pending" and view.gap != "secret_input"


@pytest.mark.process
def test_pure_node_eval_failure_records_error_step(tmp_path: Path, spawned: Spawned) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_br")
    g.node("n_cmp", "core.logic.compare", inputs={"a": 1, "op": "<", "b": "x"})
    g.node(
        "n_br",
        "core.flow.branch",
        inputs={"condition": link("n_cmp.result")},
        next={"true": "n_pass", "false": "n_pass"},
    )
    g.node("n_pass", "core.test.pass")
    done = _harness(tmp_path, g).start(spawned).finish()
    assert done.exit_code == 0
    end = _assert_failure_step(done, "n_br", "node_error")
    assert end["status"] == "error"


@pytest.mark.process
def test_stale_pure_var_get_after_resume_records_stale_step(
    tmp_path: Path, spawned: Spawned
) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_cap")
    g.node("n_cap", "core.screen.capture", next={"done": "n_set"})
    g.node("n_get", "core.var.get", inputs={"name": "img"})
    g.node(
        "n_set",
        "core.var.set",
        inputs={"name": "img", "value": link("n_cap.image")},
        next={"done": "n_use"},
    )
    g.node("n_use", "testkit.epoch.use", inputs={"value": link("n_get.value")})
    h = _harness(tmp_path, g, breakpoints=(Breakpoint(TEST_GRAPH, "n_use"),)).start(spawned)
    wait_until(lambda: h.has_event("debug.pause"), timeout=60, message=lambda: h.stderr())
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    end = _assert_failure_step(done, "n_use", "unhandled_fail")
    assert str(end["message"]).startswith("stale_observation:")
    # 멈춘 동안은 영상 빈 구간이다
    gaps = [line for line in segment_lines(h.run_dir) if line.get("gap") == "paused"]
    assert len(gaps) == 1


@pytest.mark.process
def test_boundary_cancel_still_no_step_start(tmp_path: Path, spawned: Spawned) -> None:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_x")
    g.node("n_x", "core.flow.delay", inputs={"ms": 1}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = _harness(tmp_path, g, breakpoints=(Breakpoint(TEST_GRAPH, "n_x"),)).start(spawned)
    wait_until(lambda: h.has_event("debug.pause"), timeout=60, message=lambda: h.stderr())
    h.cancel()
    done = h.finish()
    assert [e["node"] for e in done.of("step.start")] == ["n_entry", "n_launch"]
    assert done.run_end is not None
    assert (done.run_end["code"], done.run_end["failure_step"]) == ("cancelled", None)
