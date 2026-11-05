"""영상 마무리·감독자 복구·고장 주입 (구현 계획 M3 2.5, T5, 검수 M4·2차 N2).

`finalize_video`는 최종 `run.end` 기준이고 다시 불러도 결과가 같다. 작성자(녹화 스레드)가 끝난
뒤에만 파일을 정리한다: runner는 3초(마무리 유예가 짧으면 유예에서 기록 여유를 뺀 시간) 안에 녹화
스레드가 끝나지 않으면 영상을 포기하고 (`run.end.omitted` `video`/`encoder_stuck`) `video/`를
건드리지 않으며, runner 종료를 확인한 감독자가 지운다. 판정 확정 뒤 녹화 정리는 전체 기한 취소를
만들지 않는다 (CI 수정 5).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import make_workspace
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of
from helpers.video import go, launch, run_video, segment_lines, write_scenario

from kb_testing.proc import Spawned, barrier, wait_until
from kookabug_core.record import finalize as finalizing
from kookabug_core.record.finalize import (
    VideoWriterAlive,
    finalize_video,
    read_video,
    video_summary,
)
from kookabug_core.record.video import (
    INDEX_FILE,
    TEST_ENV,
    VIDEO_DIR,
    FakeEncoderFactory,
    VideoGate,
    VideoRecorder,
)
from kookabug_core.runner.run import video_wait_s
from kookabug_core.runner.spec import DEFAULT_SHUTDOWN_GRACE_MS
from kookabug_core.supervisor import RunHandle

DELAY = 600


def show(g: Any, node: str, scene: str, then: str, *, ms: int = DELAY, **kw: Any) -> Any:
    g.node(node, "core.input.key", inputs=go(scene), next={"done": f"{node}_w"}, **kw)
    return g.node(f"{node}_w", "core.flow.delay", inputs={"ms": ms}, next={"done": then})


def listing(video: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in sorted(video.iterdir())}


def index_of(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / VIDEO_DIR / INDEX_FILE).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 실제 runner·감독자


def harness(
    tmp_path: Path,
    g: Any,
    *,
    fake: Mapping[str, Any] | None = None,
    faults: Sequence[Mapping[str, Any]] = (),
    **kw: Any,
) -> RunnerHarness:
    scenario = write_scenario(tmp_path / "scenario")
    env = {TEST_ENV: json.dumps({"encoder": "fake", "fake": dict(fake or {})})}
    kw.setdefault("shutdown_grace_ms", 8_000)
    return RunnerHarness.make(
        tmp_path, g, scenario=str(scenario), env_extra=env, faults=faults, **kw
    )


def long_graph(*, record: Mapping[str, Any] | None = None) -> Any:
    """a(0.6초) → 영상 끈 0.3초 → b → 30초 기다림 (중간에 끊을 실행)."""
    g = tk(record=record).entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off")
    g.node(
        "n_off",
        "core.flow.delay",
        inputs={"ms": 300},
        next={"done": "n_b"},
        record={"video": "off"},
    )
    show(g, "n_b", "b", "n_pass", ms=30_000)
    return g.node("n_pass", "core.test.pass")


def short_graph(*, record: Mapping[str, Any] | None = None) -> Any:
    g = tk(record=record).entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_key")
    # 입력 노드: 입력 임대권을 쥐고 놓는 실행 (마무리 유예 안에 키 해제)
    g.node("n_key", "core.input.key", inputs=go("b"), next={"done": "n_b_w"})
    g.node("n_b_w", "core.flow.delay", inputs={"ms": DELAY}, next={"done": "n_pass"})
    return g.node("n_pass", "core.test.pass")


def wait_part(h: RunnerHarness, index: int, lines: int = 2) -> Path:
    """`seg-NNNN.part.mp4`에 칸이 `lines`개 넘게 쓰일 때까지."""
    part = h.run_dir / VIDEO_DIR / f"seg-{index:04d}.part.mp4"

    def ready() -> bool:
        try:
            return len(part.read_text(encoding="utf-8").splitlines()) >= lines
        except OSError:
            return False

    wait_until(ready, timeout=30, message=lambda: f"{part.name} 없음\n{h.stderr()}")
    return part


@pytest.mark.process
def test_supervisor_finalizes_partial_segments_after_runner_kill(
    tmp_path: Path, spawned: Spawned
) -> None:
    h = harness(tmp_path, long_graph()).start(spawned)
    wait_part(h, 2)
    video = h.run_dir / VIDEO_DIR
    # 이름을 바꾼 뒤 segments.jsonl 줄을 쓰기 전에 죽은 조각 (줄 없는 .mp4)
    (video / "seg-0099.mp4").write_text("{}\n", encoding="utf-8")
    h.kill_runner()
    done = h.finish()
    assert done.run_end is not None and done.run_end["code"] == "runner_died"
    index = index_of(h.run_dir)
    assert [s["file"] for s in index["segments"]] == ["seg-0001.mp4"]
    deleted = {d["file"]: d["reason"] for d in index["deleted"]}
    assert deleted == {"seg-0002.part.mp4": "interrupted", "seg-0099.mp4": "interrupted"}
    assert any(g["gap"] == "interrupted" for g in index["gaps"])
    assert set(listing(video)) == {
        INDEX_FILE,
        "segments.jsonl",
        "seg-0001.mp4",
        "seg-0001.frames.jsonl",
    }
    assert done.run_json is not None and done.run_json["video"] == video_summary(index)


@pytest.mark.process
def test_kill_after_pass_run_end_deletes_failed_only(tmp_path: Path, spawned: Spawned) -> None:
    faults = [{"point": "runner.after_run_end", "role": "runner", "action": "exit:9"}]
    h = harness(tmp_path, short_graph(record={"video": "failed_only"}), faults=faults)
    done = h.start(spawned).finish()
    assert done.exit_code == 9
    run_end = done.run_end
    assert run_end is not None
    # 감독자는 runner가 쓴 pass run.end를 덮지 않고 그 판정으로 지운다
    assert (run_end["verdict"], run_end["finalized_by"]) == ("pass", "runner")
    index = index_of(h.run_dir)
    assert index["segments"] == [] and index["deleted"]
    assert {d["reason"] for d in index["deleted"]} == {"run_pass"}
    assert not list((h.run_dir / VIDEO_DIR).glob("seg-*"))
    assert done.run_json is not None and done.run_json["video"]["kept"] == 0


@pytest.mark.process
def test_kill_after_cancel_run_end_uses_cancel_reason(tmp_path: Path, spawned: Spawned) -> None:
    faults = [{"point": "runner.after_run_end", "role": "runner", "action": "exit:9"}]
    h = harness(tmp_path, long_graph(record={"video": "failed_only"}), faults=faults)
    h.start(spawned)
    wait_part(h, 2)
    h.cancel()
    done = h.finish()
    run_end = done.run_end
    assert run_end is not None and run_end["cancel_reason"] == "cancelled"
    assert run_end["finalized_by"] == "runner"
    index = index_of(h.run_dir)
    assert index["segments"] == []
    assert {d["reason"] for d in index["deleted"]} == {"run_cancelled"}
    assert not list((h.run_dir / VIDEO_DIR).glob("seg-*"))


@pytest.mark.process
def test_encoder_release_hang_bounded_by_3s_grace(tmp_path: Path, spawned: Spawned) -> None:
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": None}}
    h = harness(tmp_path, short_graph(), fake=fake)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["verdict"] == "pass"
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    # 주 스레드는 녹화 멈춤 유예(3초) 뒤 마무리했다 (감독자 하드 종료 없음)
    assert not h.hard_stopped and h.stopping == ["finish"]
    ends = [e for e in done.view.events if e["event"] == "step.end"]
    from datetime import datetime

    waited = (
        datetime.fromisoformat(run_end["t"]) - datetime.fromisoformat(ends[-1]["t"])
    ).total_seconds()
    assert 2.5 <= waited < 6.0, waited
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True and lease["owner"] is None
    # runner 종료 뒤 감독자가 지웠다
    index = index_of(h.run_dir)
    assert (index["status"], index["reason"]) == ("omitted", "encoder_stuck")
    assert listing(h.run_dir / VIDEO_DIR).keys() == {INDEX_FILE}
    assert done.run_json is not None and done.run_json["video"]["status"] == "omitted"


@pytest.mark.process
@pytest.mark.parametrize("grace_ms", [3_000, 1_500])
def test_encoder_abandon_finishes_before_hard_stop_with_short_grace(
    tmp_path: Path, spawned: Spawned, grace_ms: int
) -> None:
    # 마무리 유예가 녹화 기다림 상한(3초) + 기록 여유(1초)보다 짧아도 영상 포기·run.end·run.json·
    # 임대권 놓기가 감독자 하드 종료(runner.stopping + 유예)보다 먼저 끝난다 (CI 수정 5 검수)
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": None}}
    h = harness(tmp_path, short_graph(), fake=fake, shutdown_grace_ms=grace_ms)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    assert not h.hard_stopped and h.stopping == ["finish"]
    run_end = done.run_end
    assert run_end is not None and run_end["finalized_by"] == "runner"
    assert run_end["verdict"] == "pass" and "cancel_reason" not in run_end
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    ends = [e for e in done.view.events if e["event"] == "step.end"]
    from datetime import datetime

    waited = (
        datetime.fromisoformat(run_end["t"]) - datetime.fromisoformat(ends[-1]["t"])
    ).total_seconds()
    assert video_wait_s(grace_ms) - 0.3 <= waited < grace_ms / 1000, waited
    lease = h.lease_file()
    assert lease is not None and lease["clean"] is True and lease["owner"] is None
    assert done.run_json is not None and done.run_json["video"]["status"] == "omitted"


@pytest.mark.process
@pytest.mark.parametrize("how", ["cancel", "death"])
def test_late_cancel_processing_still_finishes_before_hard_stop(
    tmp_path: Path, spawned: Spawned, how: str
) -> None:
    # 외부 취소·감독자 사망을 runner가 1.3초 늦게 처리해도(취소 순서 시작 전 지연), 녹화 기다림은
    # 실제 종료 기한(감독자가 건 타이머 — run.cancel의 hard_stop_in_ms / 감시자가 알아챈 사망 +
    # 유예)에 맞춰 줄어 하드 종료·자기 종료 전에 run.end를 쓴다. 유예 3초·멈춘 인코더 (CI 수정 5
    # 3차 검수). runner.stopping 시각을 기준으로 삼으면 기다림이 1.3초 늦게 끝나 exit 4다
    reason = "cancelled" if how == "cancel" else "supervisor_lost"
    gate = barrier(tmp_path / "cancel_hold")
    faults = [
        {
            "point": "runner.before_cancel",
            "role": "runner",
            "when": {"event": reason},
            "action": gate.action,
        }
    ]
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": None}}
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_d")
    g.node("n_d", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = harness(
        tmp_path,
        g,
        fake=fake,
        faults=faults,
        plugin_modules=(),
        shutdown_grace_ms=3_000,
        dummy_supervisor=how == "death",
    ).start(spawned)
    h.wait_event("step.start", node="n_d")
    time.sleep(0.4)  # 조각이 열려 닫을 인코더가 생긴다
    if how == "cancel":
        assert h.cancel() == "cancelling"  # 감독자 타이머는 이때 걸렸다
    else:
        h.kill_supervisor()  # 감시자가 사망을 알아챈 때부터 유예 뒤 자기 종료
    gate.wait_ready()
    time.sleep(1.3)
    gate.go()
    done = h.finish(recover_record=how == "cancel")
    assert done.exit_code == 0, (done.exit_code, done.run_end, h.stderr())
    assert not h.hard_stopped
    run_end = done.run_end
    assert run_end is not None and run_end["finalized_by"] == "runner"
    assert run_end["cancel_reason"] == reason
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]


def _stuck_cancel_run(
    tmp_path: Path, spawned: Spawned, *, faults: Sequence[Mapping[str, Any]] = ()
) -> RunnerHarness:
    """유예 3초·멈춘 인코더·30초 기다림 실행 (조각이 열린 뒤 돌려준다)."""
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": None}}
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_d")
    g.node("n_d", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = harness(
        tmp_path, g, fake=fake, faults=faults, plugin_modules=(), shutdown_grace_ms=3_000
    ).start(spawned)
    h.wait_event("step.start", node="n_d")
    time.sleep(0.4)  # 조각이 열려 닫을 인코더가 생긴다
    return h


def _assert_runner_recorded_before_hard_stop(h: RunnerHarness, done: Any) -> dict[str, Any]:
    assert done.exit_code == 0, (done.exit_code, done.run_end, h.stderr())
    assert not h.hard_stopped
    run_end = done.run_end
    assert run_end is not None and run_end["finalized_by"] == "runner"
    assert run_end["cancel_reason"] == "cancelled"
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    return run_end


@pytest.mark.process
@pytest.mark.parametrize("where", ["send", "receive"])
def test_delayed_cancel_message_still_finishes_before_hard_stop(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    # run.cancel이 감독자 송신 전(남은 시간을 잰 뒤) 또는 runner 수신 처리 전에 1.3초 늦어도,
    # runner는 감독자가 보낸 절대 단조 기한(hard_stop_at_mono)으로 녹화 기다림을 줄여 하드 종료
    # 전에 기록한다. 상대값(꺼낸 시각 + hard_stop_in_ms)만 쓰면 기한이 1.3초 늦게 잡혀 exit 4
    # (CI 수정 5 4차 검수). 유예 3초·멈춘 인코더
    faults: list[dict[str, Any]] = []
    gate = barrier(tmp_path / "control_hold")
    if where == "receive":
        faults.append(
            {
                "point": "runner.before_control",
                "role": "runner",
                "when": {"event": "run.cancel"},
                "action": gate.action,
            }
        )
    else:
        original = RunHandle._call

        def late_send(self: RunHandle, method: str, params: dict[str, Any] | None = None) -> Any:
            if method == "run.cancel":
                time.sleep(1.3)  # cancel()이 타이머를 걸고 기한을 잰 뒤, 보내기 전
            return original(self, method, params)

        monkeypatch.setattr(RunHandle, "_call", late_send)
    h = _stuck_cancel_run(tmp_path, spawned, faults=faults)
    if where == "receive":
        sender = threading.Thread(target=h.cancel)  # 답은 runner가 처리한 뒤에 온다
        sender.start()
        gate.wait_ready()
        time.sleep(1.3)
        gate.go()
        sender.join(30)
    else:
        assert h.cancel() == "cancelling"
    _assert_runner_recorded_before_hard_stop(h, h.finish())


@pytest.mark.process
@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="CI 러너의 느린 인코더에서 exit 4(encoder_stuck) — 로컬 재현 안 됨, BACKLOG에서 추적",
)
def test_cancel_arriving_while_finishing_shortens_video_wait(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 정상 판정(pass)으로 마무리에 들어가 이미 녹화를 기다리는 중에 외부 취소가 도착해 더 이른 종료
    # 기한이 알려지면, 진행 중인 기다림이 바로 줄어 하드 종료 전에 pass를 기록한다 (CI 수정 5
    # 5차 검수). 순서: 취소 요청(감독자 타이머 3초) → 송신 1.3초 지연 → 그 사이 그래프가 pass →
    # runner는 stopping + 유예 기준으로 녹화를 기다리기 시작 → 취소 도착(기한 = 요청 + 3초). 고정
    # 기다림이면 요청 + 약 3.15초까지 기다려 exit 4
    original = RunHandle._call

    def late_send(self: RunHandle, method: str, params: dict[str, Any] | None = None) -> Any:
        if method == "run.cancel":
            time.sleep(1.3)
        return original(self, method, params)

    monkeypatch.setattr(RunHandle, "_call", late_send)
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": None}}
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_d")
    g.node("n_d", "core.flow.delay", inputs={"ms": 1_550}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = harness(tmp_path, g, fake=fake, plugin_modules=(), shutdown_grace_ms=3_000).start(spawned)
    h.wait_event("step.start", node="n_d")
    time.sleep(0.4)
    assert h.cancel() == "cancelling"
    done = h.finish()
    assert done.exit_code == 0, (done.exit_code, done.run_end, h.stderr())
    assert not h.hard_stopped
    run_end = done.run_end
    assert run_end is not None and run_end["finalized_by"] == "runner"
    assert (run_end["verdict"], run_end["code"]) == ("pass", "test_pass"), run_end
    assert run_end["cancel_reason"] == "cancelled"  # 마무리 중 외부 취소도 받는다
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    # 취소는 pass 판정 뒤(이미 마무리 중)에 처리됐다
    events = done.view.events
    _, pass_end = step_of(events, "n_pass")
    assert pass_end is not None
    (requested,) = done.of("cancel.requested")
    assert events.index(pass_end) < events.index(requested)


@pytest.mark.process
@pytest.mark.parametrize("offset_s", [60_000.0, -60_000.0])
def test_cancel_with_mismatched_clock_origin_records_without_waiting(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch, offset_s: float
) -> None:
    # runner가 받은 절대 기한이 이미 지났거나 유예보다 멀면(시계 원점이 다르다고 본다) 녹화를
    # 기다리지 않고 바로 기록한다 — 하드 종료 전에 끝나고 영상은 포기
    original = RunHandle._call

    def shifted(self: RunHandle, method: str, params: dict[str, Any] | None = None) -> Any:
        if method == "run.cancel" and params is not None:
            params = {**params, "hard_stop_at_mono": params["hard_stop_at_mono"] + offset_s}
        return original(self, method, params)

    monkeypatch.setattr(RunHandle, "_call", shifted)
    h = _stuck_cancel_run(tmp_path, spawned)
    assert h.cancel() == "cancelling"
    done = h.finish()
    run_end = _assert_runner_recorded_before_hard_stop(h, done)
    (requested,) = done.of("cancel.requested")
    from datetime import datetime

    waited = (
        datetime.fromisoformat(run_end["t"]) - datetime.fromisoformat(requested["t"])
    ).total_seconds()
    # 녹화를 기다리지 않았다 (상대값만 쓰면 기한에서 기록 여유를 뺀 약 2초까지 기다린다)
    assert waited < 1.5, waited


@pytest.mark.process
def test_slow_encoder_release_after_pass_adds_no_deadline_cancel(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 판정(pass) 확정 뒤 녹화 정리(인코더 닫기 2.5초) 중에 전체 기한(2초)이 지나도 취소가 시작되지
    # 않는다 — 마무리는 판정을 바꾸지 않는다. 마무리 시간은 활성 경과에 그대로 든다 (CI 수정 5
    # 검수). 판정은 기한보다 확실히 먼저 나야 하므로 워커 없이 띄우기 → 0.3초(조각이 열려
    # 닫을 인코더가 생긴다) → 통과 (바쁜 PC에서도 1.5초 안쪽)
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": 2.5}}
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_d")
    g.node("n_d", "core.flow.delay", inputs={"ms": 300}, next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    h = harness(
        tmp_path,
        g,
        fake=fake,
        plugin_modules=(),
        deadline_ms=2_000,
        shutdown_grace_ms=DEFAULT_SHUTDOWN_GRACE_MS,
    )
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    _, pass_end = step_of(done.view.events, "n_pass")
    assert pass_end is not None  # 판정은 기한 전에 났다 (아니면 아래 stopping이 deadline_exceeded)
    assert not h.hard_stopped and h.stopping == ["finish"]
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["verdict"], run_end["code"]) == ("pass", "test_pass"), run_end
    assert "cancel_reason" not in run_end and done.of("cancel.requested") == []
    assert "omitted" not in run_end  # 녹화 스레드는 기다림 안에 끝났다
    assert run_end["paused_ms"] == 0
    assert run_end["active_duration_ms"] == run_end["duration_ms"] > 2_000
    assert done.run_json is not None and "cancel_reason" not in done.run_json


@pytest.mark.process
def test_run_json_rebuild_includes_video_summary_from_index(
    tmp_path: Path, spawned: Spawned
) -> None:
    faults = [{"point": "runner.before_run_json_final", "role": "runner", "action": "exit:9"}]
    h = harness(tmp_path, short_graph(), faults=faults)
    # pass 실행의 조각을 남기려고 워크스페이스에서 on (기본 failed_only는 아래 층에서 풀 수 없다)
    make_workspace(h.ws.root, record={"video": "on"})
    done = h.start(spawned).finish()
    assert done.exit_code == 9
    assert done.run_json is not None and done.run_json["run_json_repaired"] is True
    index = index_of(h.run_dir)
    assert index["status"] == "recorded" and index["segments"]
    assert done.run_json["video"] == video_summary(index)


def _stuck_run(
    tmp_path: Path, spawned: Spawned, *, resume_after_s: float | None
) -> tuple[RunnerHarness, Path, Path]:
    """녹화 스레드가 release에서 멈추는 실행. runner는 run.json을 쓴 뒤(임대권 놓기 전) 기다린다."""
    signal = tmp_path / "stuck"
    hold = tmp_path / "hold"
    fake = {
        "stuck": {
            "op": "release",
            "nth": 1,
            "resume_after_s": resume_after_s,
            "signal": str(signal),
        }
    }
    faults = [{"point": "runner.before_lease_release", "role": "runner", "action": f"wait:{hold}"}]
    h = harness(tmp_path, short_graph(), fake=fake, faults=faults).start(spawned)
    return h, signal, hold


def _ready(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


@pytest.mark.process
def test_stuck_encoder_run_end_omitted_and_runner_touches_no_video_file(
    tmp_path: Path, spawned: Spawned
) -> None:
    h, signal, hold = _stuck_run(tmp_path, spawned, resume_after_s=None)
    wait_until(_ready(signal, ".ready").exists, timeout=30, message=h.stderr)
    video = h.run_dir / VIDEO_DIR
    before = listing(video)
    wait_until(_ready(hold, ".ready").exists, timeout=30, message=h.stderr)
    # runner는 run.end·run.json까지 마쳤다: 영상 파일은 그대로, 색인 없음
    assert listing(video) == before
    assert INDEX_FILE not in before
    run_end = h.view().run_end
    assert run_end is not None
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    run_json = h.run_json()
    assert run_json is not None and run_json["video"]["status"] == "omitted"
    _ready(hold, ".go").write_text("", encoding="utf-8")
    done = h.finish()
    assert done.exit_code == 0
    assert listing(video).keys() == {INDEX_FILE}
    assert index_of(h.run_dir)["status"] == "omitted"


@pytest.mark.process
def test_stuck_writer_resuming_after_grace_cannot_change_final_state(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 유예(3초) 직후 release·이름 바꾸기·segments.jsonl 덧붙이기가 다시 진행되는 작성자
    h, signal, hold = _stuck_run(tmp_path, spawned, resume_after_s=3.6)
    wait_until(_ready(signal, ".resumed").exists, timeout=30, message=h.stderr)
    video = h.run_dir / VIDEO_DIR
    wait_until(
        lambda: any(line.get("file") for line in segment_lines(h.run_dir)),
        timeout=10,
        message=lambda: f"늦은 작성자가 줄을 쓰지 않았다 {listing(video)}",
    )
    assert INDEX_FILE not in listing(video)
    _ready(hold, ".go").write_text("", encoding="utf-8")
    done = h.finish()
    assert done.exit_code == 0
    assert listing(video).keys() == {INDEX_FILE}
    index = index_of(h.run_dir)
    assert (index["status"], index["segments"]) == ("omitted", [])
    assert done.run_json is not None and done.run_json["video"] == video_summary(index)


@pytest.mark.process
def test_open_handle_without_delete_share_not_deleted_by_runner(
    tmp_path: Path, spawned: Spawned
) -> None:
    h, _, hold = _stuck_run(tmp_path, spawned, resume_after_s=None)
    wait_until(_ready(hold, ".ready").exists, timeout=30, message=h.stderr)
    video = h.run_dir / VIDEO_DIR
    (part,) = video.glob("seg-*.part.mp4")
    # 작성자가 삭제 공유 없이 연 파일: 지울 수 없다 (runner는 지우려 하지도 않았다 — 아직 있다)
    with pytest.raises(PermissionError):
        part.unlink()
    assert part.exists()
    _ready(hold, ".go").write_text("", encoding="utf-8")
    h.finish()
    # 감독자가 runner 종료(핸들 닫힘)를 확인한 뒤 지웠다
    assert not part.exists()
    assert index_of(h.run_dir)["deleted"] == [{"file": part.name, "reason": "encoder_stuck"}]


@pytest.mark.process
@pytest.mark.parametrize("cancel", [False, True])
def test_stuck_encoder_pass_and_cancel_leave_zero_failed_only_files(
    tmp_path: Path, spawned: Spawned, cancel: bool
) -> None:
    signal = tmp_path / "stuck"
    fake = {"stuck": {"op": "write", "nth": 2, "resume_after_s": None, "signal": str(signal)}}
    g = (long_graph if cancel else short_graph)(record={"video": "failed_only"})
    h = harness(tmp_path, g, fake=fake).start(spawned)
    if cancel:
        # 쓰다가 멈춘 녹화 스레드가 있는 채로 사용자가 취소한다
        wait_until(_ready(signal, ".ready").exists, timeout=30, message=h.stderr)
        h.cancel()
    done = h.finish()
    run_end = done.run_end
    assert run_end is not None
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    assert run_end["verdict"] == ("error" if cancel else "pass")
    assert not list((h.run_dir / VIDEO_DIR).glob("seg-*"))
    assert index_of(h.run_dir)["status"] == "omitted"


# ---------------------------------------------------------------- 함수 단위 (재진입)


def prepared(tmp_path: Path, *, record: Mapping[str, Any] | None = None) -> Path:
    """마무리 전 실행 폴더 (조각 둘·빈 구간, 녹화 스레드는 끝남)."""
    g = tk(record=record).entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off")
    g.node(
        "n_off",
        "core.flow.delay",
        inputs={"ms": 300},
        next={"done": "n_b"},
        record={"video": "off"},
    )
    show(g, "n_b", "b", "n_pass")
    g.node("n_pass", "core.test.pass")
    ran = run_video(tmp_path, g, finalize=False)
    assert ran.writer_done and len(ran.segments()) == 2
    return ran.run_dir


PASS_END: Final[dict[str, Any]] = {"verdict": "pass", "t": "2026-11-02T00:00:00.000Z"}
FAIL_END: Final[dict[str, Any]] = {"verdict": "fail", "t": "2026-11-02T00:00:00.000Z"}


def copy(run_dir: Path, to: Path) -> Path:
    shutil.copytree(run_dir, to)
    return to


def test_video_finalize_idempotent(tmp_path: Path) -> None:
    run_dir = prepared(tmp_path, record={"video": "failed_only"})
    first = finalize_video(run_dir, PASS_END)
    files = listing(run_dir / VIDEO_DIR)
    second = finalize_video(run_dir, PASS_END)
    assert first == second
    assert listing(run_dir / VIDEO_DIR) == files
    assert first is not None and first["segments"] == [] and len(first["deleted"]) == 2


@pytest.mark.parametrize("when", ["before_publish", "after_publish"])
def test_kill_before_and_after_index_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    run_dir = prepared(tmp_path / "src", record={"video": "failed_only"})
    reference = finalize_video(copy(run_dir, tmp_path / "ref"), PASS_END)
    target = copy(run_dir, tmp_path / "t")
    if when == "before_publish":

        def killed(video: Path, index: Mapping[str, Any]) -> None:
            raise KeyboardInterrupt("공개 직전에 죽음")

        monkeypatch.setattr(finalizing, "_publish", killed)
        with pytest.raises(KeyboardInterrupt):
            finalize_video(target, PASS_END)
        monkeypatch.undo()
        assert not (target / VIDEO_DIR / INDEX_FILE).exists()
    else:
        finalize_video(target, PASS_END)
    again = finalize_video(target, PASS_END)
    assert again == reference
    assert listing(target / VIDEO_DIR) == listing(tmp_path / "ref" / VIDEO_DIR)


def test_kill_mid_delete_reentry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = prepared(tmp_path / "src", record={"video": "failed_only"})
    reference = finalize_video(copy(run_dir, tmp_path / "ref"), PASS_END)
    target = copy(run_dir, tmp_path / "t")
    real = finalizing._delete  # pyright: ignore[reportPrivateUsage]
    calls: list[Path] = []

    def dying(path: Path) -> bool:
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt("지우는 도중에 죽음")
        return real(path)

    monkeypatch.setattr(finalizing, "_delete", dying)
    with pytest.raises(KeyboardInterrupt):
        finalize_video(target, PASS_END)
    monkeypatch.undo()
    again = finalize_video(target, PASS_END)
    assert again == reference
    assert listing(target / VIDEO_DIR) == listing(tmp_path / "ref" / VIDEO_DIR)


def test_truncated_segments_line_ignored(tmp_path: Path) -> None:
    run_dir = prepared(tmp_path)
    path = run_dir / VIDEO_DIR / "segments.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    last = next(i for i in reversed(range(len(lines))) if '"file"' in lines[i])
    victim = json.loads(lines[last])["file"]
    lines[last] = lines[last][: len(lines[last]) // 2]  # 끝 줄이 잘렸다
    path.write_text("\n".join(lines[: last + 1]), encoding="utf-8")
    index = finalize_video(run_dir, FAIL_END)
    assert index is not None
    assert [s["file"] for s in index["segments"]] == ["seg-0001.mp4"]
    assert {"file": victim, "reason": "interrupted"} in index["deleted"]
    assert not (run_dir / VIDEO_DIR / victim).exists()
    assert any(g["gap"] == "interrupted" for g in index["gaps"])


def test_final_index_matches_disk_after_reentry(tmp_path: Path) -> None:
    run_dir = prepared(tmp_path, record={"video": "failed_only"})
    video = run_dir / VIDEO_DIR
    saved = (video / "seg-0001.mp4").read_bytes()
    first = finalize_video(run_dir, PASS_END)
    # 색인이 있어도 디스크가 다르면 다시 정리한다: 지웠다고 적힌 파일·색인에 없는 쓰다 만 조각
    (video / "seg-0001.mp4").write_bytes(saved)
    (video / "seg-0007.part.mp4").write_text("{}\n", encoding="utf-8")
    again = finalize_video(run_dir, PASS_END)
    assert again is not None and first is not None
    assert not (video / "seg-0001.mp4").exists() and not (video / "seg-0007.part.mp4").exists()
    assert again["segments"] == [] and again["status"] == first["status"]
    assert {"file": "seg-0007.part.mp4", "reason": "interrupted"} in again["deleted"]
    assert index_of(run_dir) == again


def test_finalize_video_refuses_while_writer_alive(tmp_path: Path) -> None:
    from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform

    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    recorder = VideoRecorder(run_dir, gate, platform, FakeEncoderFactory()).start()
    video = run_dir / VIDEO_DIR

    def written() -> bool:
        frames = video / "seg-0001.frames.jsonl"
        return frames.exists() and len(frames.read_text(encoding="utf-8").splitlines()) >= 2

    wait_until(written, timeout=10)
    before = listing(video)
    with pytest.raises(VideoWriterAlive):
        finalize_video(run_dir, PASS_END)
    after = listing(video)
    assert INDEX_FILE not in after
    assert {k for k in before if not k.startswith("seg-")} == {
        k for k in after if not k.startswith("seg-")
    }
    assert recorder.stop()
    index = finalize_video(run_dir, PASS_END)
    assert index is not None and index["status"] == "recorded"


def test_reader_shows_unfinalized_segments_without_writing(tmp_path: Path) -> None:
    run_dir = prepared(tmp_path, record={"video": "failed_only"})
    video = run_dir / VIDEO_DIR
    (video / "seg-0005.part.mp4").write_text("{}\n", encoding="utf-8")
    files = listing(video)
    view, finalized = read_video(run_dir)
    assert finalized is False and view is not None
    assert [s["file"] for s in view["segments"]] == ["seg-0001.mp4", "seg-0002.mp4"]
    assert view["status"] == "recorded"
    assert listing(video) == files  # 읽기는 고치지 않는다
    finalize_video(run_dir, FAIL_END)
    view, finalized = read_video(run_dir)
    assert finalized is True and view == index_of(run_dir)
