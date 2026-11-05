"""인코더 준비가 늦어도 실패 구간 영상이 남는다 (M3 사람 확인 R1 F1, 2026-11-04).

R1 실행 #2uxf는 데몬을 띄운 뒤 첫 실행에서 인코더 열기 시험이 10초 넘게 걸려 그동안이 모두
`starting` 빈 구간이었다. 녹화 스레드는 이제 시험을 기다리는 동안에도 프레임을 메모리에 모았다가
시험이 끝나면 그 시각 그대로 쓴다 (`VideoRecorder._preroll`). 실행이 시험보다 먼저 끝나면 run.end 뒤
영상 마무리 단계(`runner.video_finishing`)가 시험을 더 기다려 쓰고, 상한·취소·감독자 사망·하드
종료면 `status: omitted`/`encoder_not_ready`로 남긴다 (3라운드). 느린 준비는 가짜 인코더의
`probe_delay_s`, 마무리 단계 상한은 숨은 검사 설정 `finish_wait_s`로 주입한다.
"""

from __future__ import annotations

import errno
import itertools
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from helpers.run import tk
from helpers.runner import RunnerHarness, step_of
from helpers.video import fake_lines, go, launch, segment_lines, write_scenario

from kb_testing.proc import Spawned, wait_until
from kookabug_core.engine.scenario import FakeScenario, ScenarioPlatform
from kookabug_core.record import video as video_mod
from kookabug_core.record.finalize import finalize_video, preview_video, read_video, video_summary
from kookabug_core.record.video import (
    ENCODER_WAIT_FILE,
    FRAME_MS,
    INDEX_FILE,
    SEGMENTS_FILE,
    TEST_ENV,
    VIDEO_DIR,
    Encoder,
    EncoderProbe,
    FakeEncoderFactory,
    VideoGate,
    VideoRecorder,
    stamp,
)
from kookabug_core.schema import check_shape

FINISHING = "run.end 뒤 최대"
"""runner가 영상 마무리 단계를 허락받았을 때 stderr에 남기는 말의 일부."""


def ts(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class SlowOpenFactory(FakeEncoderFactory):
    """조각 인코더 열기가 오래 걸린다 (동기 Media Foundation 열기 흉내, vreview_2 Mid)."""

    def open(self, path: Path, size: tuple[int, int]) -> Encoder:
        time.sleep(0.4)
        return super().open(path, size)


def recorder_on(
    tmp_path: Path, probe_delay_s: float, *, slow_open: bool = False
) -> tuple[VideoRecorder, VideoGate, Any, Path]:
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    platform = ScenarioPlatform(scenario)
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("on")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = EncoderProbe(FakeEncoderFactory(probe_delay_s=probe_delay_s))
    factory = SlowOpenFactory() if slow_open else FakeEncoderFactory()
    recorder = VideoRecorder(run_dir, gate, platform, factory, probe=probe)
    return recorder, gate, game, run_dir


def assert_no_overlap(index: dict[str, Any]) -> None:
    spans = sorted(
        [(ts(g["t_start"]), ts(g["t_end"])) for g in index["gaps"]]
        + [(ts(s["t0"]), ts(s["t_end"])) for s in index["segments"]]
    )
    for (_, end), (start, _) in itertools.pairwise(spans):
        assert end <= start + 1e-6, (spans, index)  # 조각·빈 구간이 겹치지 않는다


def test_slow_probe_keeps_frames_from_before_encoder_ready(tmp_path: Path) -> None:
    """시험이 2초 걸려도 창이 생긴 때부터 영상이 있다 (빈 구간은 창이 생기기 전뿐)."""
    recorder, gate, game, run_dir = recorder_on(tmp_path, probe_delay_s=2.0)
    started = time.time()
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(3.0)
    gate.release("s1")
    assert recorder.stop()
    lines = segment_lines(run_dir)
    segments = [line for line in lines if "file" in line]
    gaps = [line for line in lines if "gap" in line]
    assert segments, lines
    first = segments[0]
    # 첫 조각은 시험이 끝난 때(2초)가 아니라 창이 생긴 직후부터
    assert ts(first["t0"]) - started < 0.5, (first, started)
    starting = [g for g in gaps if g["gap"] == "starting"]
    assert all(ts(g["t_end"]) - ts(g["t_start"]) < 0.5 for g in starting), starting
    # 모은 칸도 실제 프레임(반복이 아님)이다 — 칸마다 새로 가져온 화면
    frames = (run_dir / VIDEO_DIR / first["file"].replace(".mp4", ".frames.jsonl")).read_text(
        "utf-8"
    )
    slots = [json.loads(line) for line in frames.splitlines() if line]
    early = [s for s in slots if s["slot"] < int(1.5 * 1000 / FRAME_MS)]
    assert early and sum(not s["repeat"] for s in early) >= len(early) * 0.6, early


def test_preroll_drops_frames_before_a_block(tmp_path: Path) -> None:
    """모으는 동안 비밀값 차단이 끼면 그 앞 프레임은 버린다 — 조각이 차단을 건너 잇지 않고, 차단 중
    화면은 들어가지 않는다."""
    recorder, gate, game, run_dir = recorder_on(tmp_path, probe_delay_s=2.0)
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(0.6)
    gate.hold("s2")
    gate.classify("s2", "on", secret=True, window=game.window)
    time.sleep(0.5)
    block_end = time.time()
    gate.release("s2")
    time.sleep(2.0)
    gate.release("s1")
    assert recorder.stop()
    segments = [line for line in segment_lines(run_dir) if "file" in line]
    assert segments
    assert ts(segments[0]["t0"]) >= block_end - 0.05  # 차단 뒤 프레임부터
    for frames in fake_lines(run_dir).values():
        for slot in frames:
            assert ts(slot["pixels_at"]) >= block_end - 0.05, slot


def test_preroll_bounded_by_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """메모리 상한을 넘으면 가장 오래된 프레임부터 버린다 (빈 구간은 남은 첫 프레임까지)."""
    recorder, gate, game, run_dir = recorder_on(tmp_path, probe_delay_s=2.0)
    monkeypatch.setattr(video_mod, "PREROLL_BYTES", 1)  # 한 장만 남는다
    started = time.time()
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(2.6)
    gate.release("s1")
    assert recorder.stop()
    lines = segment_lines(run_dir)
    segments = [line for line in lines if "file" in line]
    starting = [g for g in lines if g.get("gap") == "starting"]
    assert segments and starting
    # 남은 것은 시험이 끝나기 직전 프레임 하나: 빈 구간이 거의 시험 시간만큼
    assert ts(starting[0]["t_end"]) - started > 1.5, starting
    assert ts(segments[0]["t0"]) >= ts(starting[0]["t_end"]) - 0.01


@pytest.mark.parametrize("slow_open", [False, True])
@pytest.mark.parametrize("reason", ["secret_input", "policy_off"])
def test_preroll_stops_at_final_block_before_close(
    tmp_path: Path, reason: str, slow_open: bool
) -> None:
    """vreview_1·2 Mid: 준비 중 마지막 스텝이 차단으로 분류되고 곧바로 실행이 끝나도, 모은 프레임
    쓰기와 반복 칸 채우기가 차단 시작을 넘지 않는다 — 최종 색인에서 조각과 빈 구간이 겹치지
    않는다. `slow_open`은 시험(0.8초) 뒤 조각 인코더 열기가 0.4초 걸려, 처음 받은 차단 이력 뒤에
    차단이 확정되는 순서다 (프레임마다·채우기마다 최신 이력을 본다)."""
    recorder, gate, game, run_dir = recorder_on(
        tmp_path, probe_delay_s=0.8 if slow_open else 1.5, slow_open=slow_open
    )
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(0.35)
    gate.hold("s2")  # 입력 계산·비밀값 분류 대기 (보류)
    time.sleep(0.5)
    mode = "off" if reason == "policy_off" else "on"
    gate.classify("s2", mode, secret=reason == "secret_input", window=game.window)
    gate.release("s2")  # 실행기 스텝 정리 순서 그대로
    gate.release("s1")
    gate.close()  # 분류 뒤 곧바로 실패·종료
    ended = stamp(time.time())
    assert recorder.stop()
    index = finalize_video(run_dir, {"event": "run.end", "t": ended, "verdict": "fail"})
    assert index is not None
    assert index["segments"], index  # 차단 앞 영상은 남는다
    blocks = [g for g in index["gaps"] if g["gap"] == reason]
    assert blocks, index
    assert_no_overlap(index)
    block_start = min(ts(g["t_start"]) for g in blocks)
    assert all(ts(s["t_end"]) <= block_start + 1e-6 for s in index["segments"]), index


def test_fill_limit_follows_latest_block_history(tmp_path: Path) -> None:
    """채우기 상한: 보류 중이면 보류 시작, 비우지 않았거나 열린 off 구간이면 그 시작
    (vreview_2 Mid)."""
    window = FakeScenario.load(write_scenario(tmp_path)).launch_game("game.exe").window
    now = [100.0]
    gate = VideoGate(mono=lambda: now[0], wall=lambda: now[0] + 1_000_000)
    gate.set_base("on")
    gate.hold("s1")
    now[0] = 101.0
    gate.classify("s1", "on", secret=False, window=window)
    gate.drain()  # 창 없음 구간을 비운다 (녹화 스레드가 반영함)
    assert gate.fill_limit(105.0) == 105.0
    now[0] = 102.0
    gate.hold("s2")  # 보류: 분류 결과 off면 빈 구간이 여기서 시작한다
    assert gate.fill_limit(105.0) == 102.0
    now[0] = 103.0
    gate.classify("s2", "on", secret=True, window=window)
    assert gate.fill_limit(105.0) == 102.0  # 열린 비밀값 구간 (보류 시작부터)
    now[0] = 104.0
    gate.release("s2")
    assert gate.fill_limit(105.0) == 102.0  # 끝났지만 아직 비우지 않은 구간
    gate.drain()
    assert gate.fill_limit(105.0) == 105.0


def test_finalize_turns_leftover_encoder_wait_marker_into_not_ready(tmp_path: Path) -> None:
    """늦은 인코더 대기 표식이 남았으면(대기 중 하드 종료) 마무리가 `starting`/`encoder_not_ready`
    빈 구간과 `status: omitted`로 바꾸고 표식을 지운다. 다시 마무리해도 같다."""
    video = tmp_path / VIDEO_DIR
    video.mkdir()
    marker = {
        "frames": 4,
        "t_end": "2026-11-05T01:00:02.000Z",
        "t_start": "2026-11-05T01:00:00.000Z",
    }
    (video / ENCODER_WAIT_FILE).write_text(json.dumps(marker), encoding="utf-8")
    view, finalized = read_video(tmp_path)
    assert not finalized and view is not None
    assert (view["status"], view.get("reason")) == ("omitted", "encoder_not_ready")
    end = {"event": "run.end", "t": "2026-11-05T01:00:02.100Z", "verdict": "fail"}
    first = finalize_video(tmp_path, end)
    assert first is not None
    assert (first["status"], first["reason"]) == ("omitted", "encoder_not_ready")
    assert first["gaps"] == [
        {
            "gap": "starting",
            "reason": "encoder_not_ready",
            "t_end": marker["t_end"],
            "t_start": marker["t_start"],
        }
    ]
    assert not (video / ENCODER_WAIT_FILE).exists()
    assert finalize_video(tmp_path, end) == first


@pytest.mark.parametrize(
    ("phase", "reason"), [("waiting", "encoder_not_ready"), ("writing", "encoder_stuck")]
)
def test_marker_phase_decides_abandon_reason_despite_partial_segment(
    tmp_path: Path, phase: str, reason: str
) -> None:
    """vreview_3 Mid: 표식 단계가 포기 이유를 정한다 — 준비 대기(`waiting`)면 `encoder_not_ready`,
    쓰기 중(`writing`)이면 `encoder_stuck`. 쓰다 만 `.part.mp4`를 지운 기록이 있어도 `recorded`가
    되지 않는다. 작성자가 살아 있을 때의 미리 계산(`preview_video`, runner)과 복구 마무리
    (`finalize_video`, 감독자)가 같은 상태를 내고, 다시 마무리해도 같다."""
    video = tmp_path / VIDEO_DIR
    video.mkdir()
    marker = {
        "frames": 4,
        "phase": phase,
        "t_end": "2026-11-05T01:00:02.000Z",
        "t_start": "2026-11-05T01:00:00.000Z",
    }
    (video / ENCODER_WAIT_FILE).write_text(json.dumps(marker), encoding="utf-8")
    (video / "seg-0001.part.mp4").write_text("{}\n", encoding="utf-8")
    frame = {"pixels_at": "2026-11-05T01:00:01.000Z", "repeat": False, "slot": 0}
    (video / "seg-0001.frames.jsonl").write_text(json.dumps(frame) + "\n", encoding="utf-8")
    end = {"event": "run.end", "t": "2026-11-05T01:00:09.000Z", "verdict": "fail"}
    preview = preview_video(tmp_path, end)
    assert preview is not None
    assert (video / ENCODER_WAIT_FILE).exists() and (video / "seg-0001.part.mp4").exists()
    first = finalize_video(tmp_path, end)
    assert first is not None
    assert (first["status"], first["reason"], first["segments"]) == ("omitted", reason, [])
    assert [d["file"] for d in first["deleted"]] == ["seg-0001.part.mp4"]
    assert video_summary(preview) == video_summary(first)
    assert sorted(p.name for p in video.iterdir()) == [INDEX_FILE]
    assert finalize_video(tmp_path, end) == first


def test_marker_stays_until_late_frames_are_written(tmp_path: Path) -> None:
    """준비가 끝나도 모은 프레임을 쓰고 닫을 때까지 표식이 `writing`으로 남고, 결과를 기록한 뒤에야
    지운다 (vreview_3 Mid — 그 사이 쓰기가 멈추면 마무리가 실제 이유를 안다)."""
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("failed_only")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    signal = tmp_path / "write"
    stuck = {"op": "write", "nth": 1, "resume_after_s": 1.5, "signal": str(signal)}
    recorder = VideoRecorder(
        run_dir, gate, ScenarioPlatform(scenario), FakeEncoderFactory(stuck=stuck),
        probe=EncoderProbe(FakeEncoderFactory(probe_delay_s=1.0)), late_wait_s=None,
    )  # fmt: skip
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "failed_only", secret=False, window=game.window)
    time.sleep(0.6)
    gate.release("s1")
    gate.close()
    recorder.request_stop()
    wait_until(lambda: recorder.awaiting_encoder, timeout=5)
    assert json.loads(marker.read_text(encoding="utf-8"))["phase"] == "waiting"
    wait_until(lambda: Path(f"{signal}.ready").exists(), timeout=10)  # 준비 뒤 첫 쓰기에서 멈춤
    assert json.loads(marker.read_text(encoding="utf-8"))["phase"] == "writing"
    assert recorder.awaiting_encoder
    assert recorder.join(10.0)
    assert not marker.exists()
    assert [line for line in segment_lines(run_dir) if "file" in line]
    assert len(settled_lines(run_dir)) == 1  # 결과를 모두 기록한 뒤 완료 줄


def journal_full(monkeypatch: pytest.MonkeyPatch, run_dir: Path) -> list[dict[str, Any] | None]:
    """`segments.jsonl` 덧붙이기가 계속 공간 부족(ENOSPC)으로 실패한다. 실패한 때마다 그 순간의
    대기 표식(없으면 None)을 모은다 (vreview_4 재현과 같은 주입: 파일 API 오류)."""
    original = Path.open
    attempts: list[dict[str, Any] | None] = []
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE

    def open_file(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if path.name == SEGMENTS_FILE and mode == "a":
            attempts.append(json.loads(marker.read_text("utf-8")) if marker.exists() else None)
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_file)
    return attempts


FAIL_END = {"event": "run.end", "t": "2026-11-05T01:00:09.000Z", "verdict": "fail"}


def assert_abandoned(run_dir: Path, reason: str) -> dict[str, Any]:
    """감독자 복구와 같은 마무리(`finalize_video`)가 포기 이유를 내고, runner의 미리 계산과 같다."""
    preview = preview_video(run_dir, FAIL_END)
    index = finalize_video(run_dir, FAIL_END)
    assert preview is not None and index is not None
    assert (index["status"], index.get("reason"), index["segments"]) == ("omitted", reason, [])
    assert video_summary(preview) == video_summary(index)
    assert finalize_video(run_dir, FAIL_END) == index  # 다시 마무리해도 같다
    return index


def test_late_result_journal_failure_keeps_writing_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vreview_4 Mid: 준비 뒤 모은 프레임을 쓰고 닫았는데 조각 줄도, 이어서 `failed` 줄도 공간
    부족으로 기록하지 못하면 표식을 지우지 않는다(`writing`) — 마무리가 `omitted`/`encoder_stuck`을
    낸다. 저널에 없는 완성 조각을 `interrupted`로 지운 기록 때문에 `recorded`가 되지 않는다."""
    recorder, gate, game, run_dir = recorder_on(tmp_path, probe_delay_s=1.5)
    attempts = journal_full(monkeypatch, run_dir)
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(0.4)
    gate.close()
    assert recorder.stop()
    assert (recorder.status, recorder.reason) == ("failed", "write_failed")  # 메모리에만 있다
    assert len(attempts) == 2, attempts  # 조각 줄, 실패 줄
    assert all(a is not None and a["phase"] == "writing" for a in attempts), attempts
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    assert json.loads(marker.read_text("utf-8"))["phase"] == "writing"
    monkeypatch.undo()
    index = assert_abandoned(run_dir, "encoder_stuck")
    assert {d["reason"] for d in index["deleted"]} == {"encoder_stuck"}
    assert sorted(p.name for p in (run_dir / VIDEO_DIR).iterdir()) == [INDEX_FILE]


@pytest.mark.parametrize("full", [False, True])
def test_unavailable_result_settles_marker_only_when_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    """늦은 대기 뒤 시험이 인코더를 쓸 수 없다고 끝나면: `unavailable` 줄을 기록했을 때만 표식을
    지운다(상태 `unavailable`). 기록하지 못하면 표식이 준비 대기(`waiting`)로 남아 마무리가
    `omitted`/`encoder_not_ready`를 낸다."""
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("on")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = EncoderProbe(FakeEncoderFactory(probe_delay_s=1.0, unavailable="mf_missing"))
    recorder = VideoRecorder(
        run_dir, gate, ScenarioPlatform(scenario), FakeEncoderFactory(), probe=probe
    )
    attempts = journal_full(monkeypatch, run_dir) if full else []
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(0.4)
    gate.close()
    assert recorder.stop()
    monkeypatch.undo()
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    if full:
        assert len(attempts) == 1 and attempts[0] is not None
        assert json.loads(marker.read_text("utf-8"))["phase"] == "waiting"
        assert_abandoned(run_dir, "encoder_not_ready")
    else:
        assert not marker.exists()
        index = finalize_video(run_dir, FAIL_END)
        assert index is not None
        assert (index["status"], index["reason"]) == ("unavailable", "mf_missing")


@pytest.mark.parametrize("full", [False, True])
def test_give_up_settles_marker_only_when_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, full: bool
) -> None:
    """늦은 대기를 포기할 때도 `starting`/`encoder_not_ready` 줄을 기록했을 때만 표식을 지운다.
    어느 쪽이든 마무리는 `omitted`/`encoder_not_ready`다."""
    recorder, gate, game, run_dir = recorder_on(tmp_path, probe_delay_s=30.0)
    attempts = journal_full(monkeypatch, run_dir) if full else []
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "on", secret=False, window=game.window)
    time.sleep(0.4)
    gate.close()
    assert recorder.stop()  # 스스로 포기한다 (`PREROLL_STOP_WAIT_S`)
    monkeypatch.undo()
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    assert marker.exists() == full
    assert len(attempts) == (1 if full else 0)
    assert_abandoned(run_dir, "encoder_not_ready")


def settled_lines(run_dir: Path) -> list[dict[str, Any]]:
    return [line for line in segment_lines(run_dir) if line.get("encoder_wait") == "settled"]


@pytest.mark.parametrize("hold_reader", [False, True])
def test_recorded_late_frames_survive_marker_reader_handle(
    tmp_path: Path, hold_reader: bool
) -> None:
    """vreview_5 Mid: 표식을 평범한 읽기 핸들로 연 채(Windows는 삭제·교체가 공유 위반·접근
    거부로 실패한다 — 오류 주입 없음) 늦은 쓰기를 정상 기록하면, 저널의 완료 줄이 근거라 표식이
    `writing`으로 남아도 `preview_video`·`finalize_video` 모두 조각을 보관한다. 핸들을 쥔 채
    마무리해도 같고(표식 지우기 실패는 `cleanup_failed`일 뿐), 닫은 뒤 다시 마무리해도 같다.
    `hold_reader=False`는 대조군."""
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("failed_only")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    signal = tmp_path / "write"
    stuck = {"op": "write", "nth": 1, "resume_after_s": 1.5, "signal": str(signal)}
    recorder = VideoRecorder(
        run_dir, gate, ScenarioPlatform(scenario), FakeEncoderFactory(stuck=stuck),
        probe=EncoderProbe(FakeEncoderFactory(probe_delay_s=1.5)),
    )  # fmt: skip
    marker = run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "failed_only", secret=False, window=game.window)
    time.sleep(0.4)
    gate.close()
    recorder.request_stop()
    wait_until(lambda: Path(f"{signal}.ready").exists(), timeout=10)  # 준비 뒤 첫 쓰기
    reader = marker.open("rb")
    try:
        assert json.loads(reader.read())["phase"] == "writing"
        if not hold_reader:
            reader.close()
        assert recorder.join(10.0)
        assert recorder.status == "recorded"
        assert len(settled_lines(run_dir)) == 1  # 결과를 모두 기록했다는 근거
        assert marker.exists() == hold_reader  # 지우기는 최선 시도 (핸들이 막음)
        preview = preview_video(run_dir, FAIL_END)
        index = finalize_video(run_dir, FAIL_END)
        assert preview is not None and index is not None
        assert index["status"] == "recorded" and index["segments"], index
        assert index["deleted"] == []
        assert video_summary(preview) == video_summary(index)
        assert ("cleanup_failed" in index) == hold_reader
    finally:
        reader.close()
    again = finalize_video(run_dir, FAIL_END)
    assert again is not None and again["segments"] == index["segments"]
    assert video_summary(again) == video_summary(index) and "cleanup_failed" not in again
    assert not marker.exists()


def test_settled_line_is_a_segments_line() -> None:
    """완료 줄은 `segments.jsonl` 형식(`SegmentsLine`)의 한 갈래다."""
    line = {"encoder_wait": "settled", "t": "2026-11-05T01:00:02.000Z"}
    assert check_shape(line, "video-index", ref="#/$defs/SegmentsLine") == []
    assert check_shape({**line, "encoder_wait": "done"}, "video-index", ref="#/$defs/SegmentsLine")


def test_recorder_gives_up_late_wait_with_reason(tmp_path: Path) -> None:
    """runner처럼 `late_wait_s=None`이면 포기를 받을 때까지 모은 프레임을 들고 기다리고(대기 표식),
    포기하면 실행 끝까지 `starting`/`encoder_not_ready` 빈 구간을 남기고 표식을 지운다."""
    scenario = FakeScenario.load(write_scenario(tmp_path / "scenario"))
    game = scenario.launch_game("game.exe")
    gate = VideoGate()
    gate.set_base("failed_only")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    probe = EncoderProbe(FakeEncoderFactory(probe_delay_s=30.0))
    recorder = VideoRecorder(
        run_dir, gate, ScenarioPlatform(scenario), FakeEncoderFactory(), probe=probe,
        late_wait_s=None,
    )  # fmt: skip
    recorder.start()
    gate.hold("s1")
    gate.classify("s1", "failed_only", secret=False, window=game.window)
    time.sleep(0.6)
    gate.release("s1")
    gate.close()
    closed = time.time()
    recorder.request_stop()
    wait_until(lambda: recorder.awaiting_encoder, timeout=5)
    assert recorder.late_modes == {"failed_only"}
    assert (run_dir / VIDEO_DIR / ENCODER_WAIT_FILE).exists()
    assert not recorder.join(3.0)  # 스스로 포기하지 않는다
    recorder.abandon_encoder_wait()
    assert recorder.join(3.0)
    gaps = [line for line in segment_lines(run_dir) if line.get("gap") == "starting"]
    assert len(gaps) == 1 and gaps[0]["reason"] == "encoder_not_ready", gaps
    assert abs(ts(gaps[0]["t_end"]) - closed) < 0.1  # 실행이 끝난(게이트를 닫은) 때까지
    assert not (run_dir / VIDEO_DIR / ENCODER_WAIT_FILE).exists()


# ---------------------------------------------------------------- 실제 runner


def fail_graph(record: dict[str, Any] | None = None) -> Any:
    g = tk(record=record).entry("n_launch")
    launch(g, "n_launch", "n_a")
    g.node("n_a", "core.input.key", inputs=go("a"), next={"done": "n_w"})
    g.node("n_w", "core.flow.delay", inputs={"ms": 600}, next={"done": "n_end"})
    return g.node("n_end", "core.test.fail")


def slow_env(probe_delay_s: float, finish_wait_s: float | None = None) -> dict[str, str]:
    config: dict[str, Any] = {"encoder": "fake", "fake": {"probe_delay_s": probe_delay_s}}
    if finish_wait_s is not None:
        config["finish_wait_s"] = finish_wait_s
    return {TEST_ENV: json.dumps(config)}


def read_index(h: RunnerHarness) -> dict[str, Any]:
    return json.loads((h.run_dir / VIDEO_DIR / INDEX_FILE).read_text(encoding="utf-8"))


def granted(h: RunnerHarness) -> list[dict[str, Any]]:
    """감독자가 보낸 `runner.video_finishing` 답 (허락 여부)."""
    asked = {
        body.get("id")
        for direction, body in h.messages
        if direction == "recv" and body.get("method") == "runner.video_finishing"
    }
    return [
        body["result"]
        for direction, body in h.messages
        if direction == "send" and body.get("id") in asked and "result" in body
    ]


@pytest.mark.process
@pytest.mark.timeout(90)
@pytest.mark.parametrize("deadline_ms", [60_000, 10_000])
def test_failure_video_kept_with_ten_second_encoder_preparation(
    tmp_path: Path, spawned: Spawned, deadline_ms: int
) -> None:
    """vreview_1·2 High: 실제 runner, 인코더 준비 10초 + 1초 남짓에 끝나는 실패 실행. 기본 기한이면
    첫 스텝 전 사전 대기가 준비를 끝내고, 10초 기한이면(사전 대기는 남은 기한의 절반뿐) 실행이 먼저
    끝나 run.end 뒤 영상 마무리 단계가 모은 프레임을 쓴다 — 어느 쪽이든 실패 직전 대기 스텝이
    `failed_only` 조각으로 남고, 판정·종료 코드·마무리 기한은 그대로다. 고치기 전에는 1라운드
    `segments=[]`(기본 기한), 2라운드 `segments=[]`(10초 기한)였다."""
    scenario = write_scenario(tmp_path / "scenario")
    h = RunnerHarness.make(
        tmp_path, fail_graph(), scenario=str(scenario), env_extra=slow_env(10.0),
        deadline_ms=deadline_ms,
    )  # fmt: skip
    done = h.start(spawned).finish(timeout=60)
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert "cancel_reason" not in done.run_end and "omitted" not in done.run_end
    index = read_index(h)
    assert index["segments"], index
    launch_start, _ = step_of(done.view.events, "n_launch")
    delay_start, delay_end = step_of(done.view.events, "n_w")
    assert delay_end is not None
    run_start = ts(done.of("run.start")[0]["t"])
    assert "영상 인코더 준비를" in h.stderr()
    if deadline_ms == 60_000:
        # 첫 스텝은 인코더 준비(약 10초) 뒤에 시작했고, 그 뒤 실행 자체는 짧았다
        assert ts(launch_start["t"]) - run_start >= 8.0, (launch_start, run_start)
        assert not [g for g in index["gaps"] if g["gap"] == "starting"], index
        assert FINISHING not in h.stderr()
    else:
        # 사전 대기는 남은 기한의 절반에서 끊기고, 실행은 준비보다 먼저 끝났다
        assert ts(launch_start["t"]) - run_start < 6.0, (launch_start, run_start)
        assert ts(done.run_end["t"]) - run_start < 9.5, done.run_end
        assert FINISHING in h.stderr()
        assert granted(h) and granted(h)[0]["granted"] is True
    assert ts(done.run_end["t"]) - ts(launch_start["t"]) < 5.0
    # 실패 직전 대기 스텝 구간 전체가 영상에 들어 있다. 앞 스텝(키 입력)이 10 ms 남짓이라 그
    # 사이 프레임을 못 잡으면 첫 칸이 대기 스텝 분류 뒤 캡처 지연만큼 늦다 — 격자 한 칸까지 본다
    covered = [
        s
        for s in index["segments"]
        if ts(s["t0"]) <= ts(delay_start["t"]) + FRAME_MS / 1000
        and ts(s["t_end"]) >= ts(delay_end["t"]) - 0.25
    ]
    assert covered, (index, delay_start, delay_end)
    assert_no_overlap(index)
    assert done.run_json is not None
    assert done.run_json["video"]["kept"] >= 1 and done.run_json["video"]["status"] == "recorded"
    assert not (h.run_dir / VIDEO_DIR / ENCODER_WAIT_FILE).exists()


@pytest.mark.process
@pytest.mark.timeout(90)
def test_video_off_run_does_not_wait_for_encoder(tmp_path: Path, spawned: Spawned) -> None:
    """영상이 꺼진 실행(테스트 `record.video: off`)은 인코더 준비를 기다리지 않는다."""
    scenario = write_scenario(tmp_path / "scenario")
    graph = fail_graph(record={"video": "off"})
    h = RunnerHarness.make(tmp_path, graph, scenario=str(scenario), env_extra=slow_env(10.0))
    done = h.start(spawned).finish(timeout=60)
    assert done.exit_code == 0, h.stderr()
    launch_start, _ = step_of(done.view.events, "n_launch")
    assert ts(launch_start["t"]) - ts(done.of("run.start")[0]["t"]) < 3.0
    assert "영상 인코더 준비를" not in h.stderr()
    assert FINISHING not in h.stderr()


def assert_not_ready(h: RunnerHarness, video: dict[str, Any] | None) -> None:
    """그 실행의 영상은 조용히 사라지지 않고 `omitted`/`encoder_not_ready`로 드러난다."""
    assert video is not None
    assert (video["status"], video.get("reason"), video["kept"]) == (
        "omitted",
        "encoder_not_ready",
        0,
    ), video
    index = read_index(h)
    assert (index["status"], index.get("reason")) == ("omitted", "encoder_not_ready"), index
    assert [g["reason"] for g in index["gaps"] if g["gap"] == "starting"] == [
        "encoder_not_ready"
    ], index
    assert not list((h.run_dir / VIDEO_DIR).glob("*.mp4"))
    assert not (h.run_dir / VIDEO_DIR / ENCODER_WAIT_FILE).exists()


def short_fail_harness(tmp_path: Path, **kw: Any) -> RunnerHarness:
    scenario = write_scenario(tmp_path / "scenario")
    env = slow_env(60.0, kw.pop("finish_wait_s", None))
    return RunnerHarness.make(
        tmp_path, fail_graph(), scenario=str(scenario), env_extra=env, deadline_ms=6_000, **kw
    )


@pytest.mark.process
@pytest.mark.timeout(90)
def test_video_finishing_cap_marks_encoder_not_ready(tmp_path: Path, spawned: Spawned) -> None:
    """마무리 단계 상한(여기서는 2초)을 넘기면 모은 프레임을 버리고 상태를 명시적으로 남긴다.
    판정·종료 코드는 그대로다."""
    h = short_fail_harness(tmp_path, finish_wait_s=2.0)
    done = h.start(spawned).finish(timeout=60)
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert "omitted" not in done.run_end
    assert FINISHING in h.stderr() and "모은 프레임을 버렸다" in h.stderr()
    assert granted(h) and granted(h)[0]["granted"] is True
    assert done.run_json is not None
    assert_not_ready(h, done.run_json.get("video"))


def wait_finishing(h: RunnerHarness) -> None:
    wait_until(lambda: FINISHING in h.stderr(), timeout=30, message=h.stderr)


@pytest.mark.process
@pytest.mark.timeout(90)
def test_cancel_during_video_finishing(tmp_path: Path, spawned: Spawned) -> None:
    """마무리 단계 중 외부 취소: 감독자가 타이머를 지금 + 유예로 당기고, runner는 모은 프레임을
    버린 뒤 유예 안에 정상 마무리한다 (판정은 이미 쓴 run.end 그대로, exit 0)."""
    h = short_fail_harness(tmp_path).start(spawned)
    wait_finishing(h)
    began = time.monotonic()
    h.cancel()
    done = h.finish(timeout=30)
    assert time.monotonic() - began < 3.0
    assert done.exit_code == 0 and not h.hard_stopped, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert "cancel_reason" not in done.run_end
    assert done.run_json is not None
    assert_not_ready(h, done.run_json.get("video"))


@pytest.mark.process
@pytest.mark.timeout(90)
def test_supervisor_lost_during_video_finishing(tmp_path: Path, spawned: Spawned) -> None:
    """마무리 단계 중 감독자 사망: 감시자가 알아챈 사망 + 유예가 새 종료 기한이라 runner는 모은
    프레임을 버리고 그 안에 스스로 마무리한다 (자기 종료 없이 exit 0)."""
    h = short_fail_harness(tmp_path, dummy_supervisor=True, shutdown_grace_ms=3_000)
    h.start(spawned)
    wait_finishing(h)
    began = time.monotonic()
    h.kill_supervisor()
    done = h.finish(timeout=30, recover_record=False)
    assert time.monotonic() - began < 3.0
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert done.run_json is not None
    assert_not_ready(h, done.run_json.get("video"))


@pytest.mark.process
@pytest.mark.timeout(90)
def test_hard_stop_during_video_finishing(tmp_path: Path, spawned: Spawned) -> None:
    """마무리 단계 중 하드 종료(강제 정지): runner가 끝나도 남은 대기 표식으로 감독자 복구가
    `omitted`/`encoder_not_ready`를 남긴다. run.end(판정)는 runner가 쓴 그대로다."""
    h = short_fail_harness(tmp_path).start(spawned)
    wait_finishing(h)
    assert (h.run_dir / VIDEO_DIR / ENCODER_WAIT_FILE).exists()
    h.hard_stop_now()
    done = h.finish(timeout=30)
    assert done.exit_code == 4
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert done.run_end["finalized_by"] == "runner"
    assert done.run_json is not None
    assert_not_ready(h, done.run_json.get("video"))


@pytest.mark.process
@pytest.mark.timeout(90)
def test_pass_run_skips_video_finishing(tmp_path: Path, spawned: Spawned) -> None:
    """`failed_only` 프레임만 들고 있는 통과 실행은 남길 영상이 없으므로 마무리 단계를 청하지 않고
    곧바로 끝난다 (통과 실행이 인코더 준비에 붙잡히지 않는다)."""
    scenario = write_scenario(tmp_path / "scenario")
    graph = fail_graph().node("n_end", "core.test.pass")
    h = RunnerHarness.make(
        tmp_path, graph, scenario=str(scenario), env_extra=slow_env(60.0), deadline_ms=6_000
    )
    began = time.monotonic()
    done = h.start(spawned).finish(timeout=60)
    assert time.monotonic() - began < 15.0
    assert done.exit_code == 0 and done.run_end is not None
    assert done.run_end["verdict"] == "pass"
    assert FINISHING not in h.stderr() and not granted(h)
    assert done.run_json is not None
    assert_not_ready(h, done.run_json.get("video"))


def stuck_write_harness(tmp_path: Path, finish_wait_s: float) -> tuple[RunnerHarness, Path]:
    """10초 기한·준비 8초: 실행이 먼저 실패해 마무리 단계로 들어가고, 준비가 끝난 뒤 모은 프레임의
    첫 쓰기에서 인코더가 멈춘다 (vreview_3 재현과 같은 조건)."""
    scenario = write_scenario(tmp_path / "scenario")
    signal = tmp_path / "write"
    config = {
        "encoder": "fake",
        "finish_wait_s": finish_wait_s,
        "fake": {"probe_delay_s": 8.0, "stuck": {"op": "write", "signal": str(signal)}},
    }
    h = RunnerHarness.make(
        tmp_path, fail_graph(), scenario=str(scenario),
        env_extra={TEST_ENV: json.dumps(config)}, deadline_ms=10_000,
    )  # fmt: skip
    return h, signal


def assert_stuck(h: RunnerHarness, video: dict[str, Any] | None) -> dict[str, Any]:
    """포기 이유가 `encoder_stuck`으로 남고 `video/`에는 색인만 남는다."""
    assert video is not None
    assert (video["status"], video.get("reason"), video["kept"]) == (
        "omitted",
        "encoder_stuck",
        0,
    ), video
    index = read_index(h)
    assert (index["status"], index.get("reason"), index["segments"]) == (
        "omitted",
        "encoder_stuck",
        [],
    ), index
    assert video == video_summary(index)
    assert sorted(p.name for p in (h.run_dir / VIDEO_DIR).iterdir()) == [INDEX_FILE]
    return index


@pytest.mark.process
@pytest.mark.timeout(90)
@pytest.mark.parametrize("ending", ["cap", "hard_stop"])
def test_stuck_write_after_late_preparation_keeps_omission(
    tmp_path: Path, spawned: Spawned, ending: str
) -> None:
    """vreview_3 Mid: 마무리 단계에서 준비가 끝난 뒤 쓰기가 멈추면, 상한을 넘겨 runner가 정상
    마무리하든(`cap`) 사용자가 하드 종료하든(`hard_stop`) 감독자 복구 뒤에도 `omitted`/
    `encoder_stuck`이 남는다. 쓰다 만 조각 삭제 때문에 `recorded`가 되지 않고, runner가 쓴 요약과
    복구 뒤 요약이 같다. `run.end`(판정, `omitted` 없음)는 고치지 않는다."""
    h, signal = stuck_write_harness(tmp_path, finish_wait_s=3.0 if ending == "cap" else 30.0)
    h.start(spawned)
    h.wait_event("run.end")
    wait_until(lambda: Path(f"{signal}.ready").exists(), timeout=20, message=h.stderr)
    marker = h.run_dir / VIDEO_DIR / ENCODER_WAIT_FILE
    assert json.loads(marker.read_text(encoding="utf-8"))["phase"] == "writing"
    assert FINISHING in h.stderr()
    if ending == "hard_stop":
        h.hard_stop_now()
    code = h.wait(timeout=30)
    before = h.run_json()
    done = h.finish(timeout=10)
    assert code == (4 if ending == "hard_stop" else 0), h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "fail"
    assert "omitted" not in done.run_end and done.run_end["finalized_by"] == "runner"
    assert done.run_json is not None
    index = assert_stuck(h, done.run_json.get("video"))
    assert [d["reason"] for d in index["deleted"]] == ["encoder_stuck"]
    if ending == "cap":
        assert before is not None and before.get("video") == done.run_json["video"]
