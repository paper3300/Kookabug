"""영상 마무리·감독자 복구·고장 주입 (구현 계획 M3 2.5, T5, 검수 M4·2차 N2).

`finalize_video`는 최종 `run.end` 기준이고 다시 불러도 결과가 같다. 작성자(녹화 스레드)가 끝난
뒤에만 파일을 정리한다: runner는 3초 안에 녹화 스레드가 끝나지 않으면 영상을 포기하고
(`run.end.omitted` `video`/`encoder_stuck`) `video/`를 건드리지 않으며, runner 종료를 확인한
감독자가 지운다.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import make_workspace
from helpers.run import tk
from helpers.runner import RunnerHarness
from helpers.video import go, launch, run_video, segment_lines, write_scenario

from kb_testing.proc import Spawned, wait_until
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
