"""M3 계약 (M3 계획 2.11): 디버거·영상·증거·기록 읽기 필드와 새 메타스키마.

새 필드는 모두 선택이라 M0b·M1·M2 코드가 만든 실행 기록(`fixtures/run-history`)이 그대로
통과해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb_testing.packaging import REPO_ROOT
from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.record import read_run
from kookabug_core.schema import check_shape, kind_of, metaschema
from kookabug_core.schema.models.breakpoints import Breakpoints
from kookabug_core.schema.models.events import Event
from kookabug_core.schema.models.run import Run
from kookabug_core.schema.models.video_index import FramesLine, SegmentsLine, VideoIndex

HISTORY = REPO_ROOT / "fixtures" / "run-history"
RUN = "r8k2x7qm"
T = "2026-10-29T06:02:11.104Z"
T2 = "2026-10-29T06:03:11.104Z"


def ev(event: str, seq: int = 1, **fields: Any) -> dict[str, Any]:
    return {"event": event, "run": RUN, "seq": seq, "t": T, **fields}


def codes(diags: list[Any]) -> list[tuple[str, str]]:
    return [(d.code, d.pointer) for d in diags]


def roundtrip_event(sample: dict[str, Any]) -> None:
    assert check_shape(sample, "events") == [], sample
    assert Event.model_validate(sample).model_dump(mode="json", exclude_unset=True) == sample


# ------------------------------------------------------------------ 예전 실행 기록


def history_folders() -> list[Path]:
    return sorted(p for p in HISTORY.iterdir() if p.is_dir())


def test_history_fixture_covers_m0b_and_m2() -> None:
    names = [p.name for p in history_folders()]
    assert any(n.startswith("m0b-") for n in names) and any(n.startswith("m2-") for n in names)
    kinds = {
        json.loads(line)["event"]
        for folder in history_folders()
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    }
    # 경계 멈춤(M0b debug.pause/resume)·감독자 마무리·입력 복구·워커·스텝 기록이 다 들어 있다
    assert {
        "debug.pause",
        "debug.resume",
        "input.recovered",
        "worker.exit",
        "cancel.requested",
        "step.end",
    } <= kinds


@pytest.mark.parametrize("folder", history_folders(), ids=lambda p: p.name)
def test_debug_events_new_fields_optional_old_runs_valid(folder: Path) -> None:
    # M3 전 코드가 쓴 events.jsonl·run.json이 새 스키마로 그대로 통과한다 (새 필드는 선택)
    lines = (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    for line in lines:
        event = loads_strict(line)
        assert check_shape(event, "events") == [], line
        Event.model_validate(event)
    run_json = loads_strict((folder / "run.json").read_text(encoding="utf-8"))
    assert kind_of(run_json) == "run"
    assert check_shape(run_json) == []
    Run.model_validate(run_json)
    # 기록 읽기도 경고 없이 같은 줄을 읽는다
    view = read_run(folder)
    assert view.warnings == [] and not view.truncated
    assert len(view.events) == len(lines)


def test_m0b_debug_pause_resume_without_new_fields() -> None:
    roundtrip_event(ev("debug.pause", step="s3"))
    roundtrip_event(ev("debug.resume", step="s3"))
    roundtrip_event(ev("debug.pause"))


def test_debug_pause_resume_new_fields() -> None:
    pause = ev(
        "debug.pause",
        graph="subgraphs/enter_world.graph.json",
        node="n_wait_title",
        path=["n_enter_world", "n_wait_title"],
        reason="breakpoint",
        step="s4",
        where="boundary",
    )
    roundtrip_event(pause)
    roundtrip_event({**pause, "reason": "request", "where": "poll"})
    resume = ev("debug.resume", epoch=1, mode="step_over", paused_ms=3000, step="s4")
    roundtrip_event(resume)
    for mode in ("continue", "step_into", "step_out", "step_over"):
        roundtrip_event({**resume, "mode": mode})
    assert codes(check_shape({**pause, "reason": "hit"}, "events")) == [
        ("invalid_value", "/reason")
    ]
    assert codes(check_shape({**pause, "where": "worker"}, "events")) == [
        ("invalid_value", "/where")
    ]
    assert codes(check_shape({**resume, "mode": "run"}, "events")) == [("invalid_value", "/mode")]
    assert codes(check_shape({**resume, "epoch": 0}, "events")) == [("out_of_range", "/epoch")]
    assert codes(check_shape({**resume, "paused_ms": -1}, "events")) == [
        ("out_of_range", "/paused_ms")
    ]


# ------------------------------------------------------------------ step.end·run.end


STEP_END = ev(
    "step.end",
    attempt=1,
    duration_ms=5200,
    exit="timeout",
    outputs={},
    status="success",
    step="s4",
)

EVIDENCE = {
    "candidates": [
        {"rect": [812, 701, 296, 88], "scale": 1.0, "score": 0.61},
        {"rect": [10, 20, 296, 88], "scale": 1.25, "score": 0.42},
    ],
    "first": "steps/s4_first.png",
    "first_at_ms": 0,
    "last": "steps/s4_fail.png",
    "last_at_ms": 5180,
    "mid": "steps/s4_mid.png",
    "mid_at_ms": 2400,
    "mid_offset_ms": 190,
    "target": "targets/title/start_button.target.json",
    "threshold": 0.85,
}


def test_step_end_active_duration_and_evidence_shape() -> None:
    roundtrip_event({**STEP_END, "active_duration_ms": 2200})
    roundtrip_event({**STEP_END, "active_duration_ms": 2200, "evidence": EVIDENCE})
    # 일부만 (예외 스텝: 후보 없음)
    roundtrip_event({**STEP_END, "evidence": {"first": "steps/s4_first.png", "first_at_ms": 0}})
    bad = {**STEP_END, "active_duration_ms": -1}
    assert codes(check_shape(bad, "events")) == [("out_of_range", "/active_duration_ms")]
    four = {**EVIDENCE, "candidates": EVIDENCE["candidates"] * 2}
    assert codes(check_shape({**STEP_END, "evidence": four}, "events")) == [
        ("out_of_range", "/evidence/candidates")
    ]
    wrong_rect = {**EVIDENCE, "candidates": [{"rect": [1, 2, 3], "scale": 1.0, "score": 0.5}]}
    assert check_shape({**STEP_END, "evidence": wrong_rect}, "events")
    assert codes(check_shape({**STEP_END, "evidence": {**EVIDENCE, "extra": 1}}, "events")) == [
        ("unknown_field", "/evidence/extra")
    ]


def test_evidence_mid_nullable_with_reason_and_offset() -> None:
    # 2차 N3: 중간은 최선 노력. 없으면 null + 이유, 있으면 실제 캡처 시각과 편차
    no_mid = {k: v for k, v in EVIDENCE.items() if not k.startswith("mid")}
    roundtrip_event(
        {**STEP_END, "evidence": {**no_mid, "mid": None, "mid_missing": "no_sample_near_mid"}}
    )
    # null인데 이유가 없음, null인데 시각이 있음, 있는데 시각이 없음, 있는데 이유를 붙임
    for evidence in (
        {**no_mid, "mid": None},
        {**no_mid, "mid": None, "mid_missing": "no_sample_near_mid", "mid_at_ms": 10},
        {**no_mid, "mid": None, "mid_missing": "no_sample_near_mid", "mid_offset_ms": 10},
        {**no_mid, "mid": "steps/s4_mid.png"},
        {**no_mid, "mid": "steps/s4_mid.png", "mid_at_ms": 2400},
        {**EVIDENCE, "mid_missing": "no_sample_near_mid"},
        {**no_mid, "mid_missing": "no_sample_near_mid"},
    ):
        assert check_shape({**STEP_END, "evidence": evidence}, "events"), evidence
    assert check_shape(
        {**STEP_END, "evidence": {**no_mid, "mid": None, "mid_missing": "far"}}, "events"
    )


RUN_END = ev(
    "run.end",
    code="assertion_passed",
    duration_ms=9000,
    failure_path=None,
    failure_step=None,
    finalized_by="runner",
    reason="검증 1개 성공",
    verdict="pass",
)


def test_run_end_debug_fields() -> None:
    roundtrip_event(
        {**RUN_END, "active_duration_ms": 6000, "debug_intervened": True, "paused_ms": 3000}
    )
    assert check_shape({**RUN_END, "debug_intervened": "yes"}, "events")


def test_run_end_omitted_video_encoder_stuck_shape() -> None:
    # 2차 N2: 녹화 스레드가 멈춰 영상을 포기한 실행
    roundtrip_event({**RUN_END, "omitted": [{"kind": "video", "reason": "encoder_stuck"}]})
    for bad in (
        [],
        [{"kind": "video"}],
        [{"kind": "screenshot", "reason": "encoder_stuck"}],
        [{"kind": "video", "reason": "policy_off"}],
        [{"kind": "video", "reason": "encoder_stuck", "name": "x"}],
    ):
        assert check_shape({**RUN_END, "omitted": bad}, "events"), bad


def test_omitted_kind_includes_thumbnail() -> None:
    entry = {"kind": "thumbnail", "reason": "secret_input", "source": "x#/nodes/n/in/p"}
    roundtrip_event({**STEP_END, "omitted": [entry]})
    assert codes(check_shape({**STEP_END, "omitted": [{**entry, "kind": "video"}]}, "events")) == [
        ("invalid_value", "/omitted/0/kind")
    ]


# ------------------------------------------------------------------ run.json


def finished_run(**extra: Any) -> dict[str, Any]:
    data = loads_strict((HISTORY / "m2-login-fail" / "run.json").read_text(encoding="utf-8"))
    return {**data, **extra}


def test_run_json_video_and_observed_shape() -> None:
    video = {"bytes": 152000, "deleted": 0, "kept": 2, "status": "recorded"}
    observed = {"backend": "wgc", "client_size": [1280, 720], "dpi": 144}
    run = finished_run(
        active_duration_ms=4000,
        debug_intervened=True,
        observed=observed,
        pause_count=1,
        paused_ms=3000,
        retried_steps=1,
        video=video,
    )
    assert check_shape(run) == []
    assert Run.model_validate(run).model_dump(mode="json", exclude_unset=True) == run
    for status, reason in (
        ("unavailable", "mf_missing"),
        ("unavailable", "backend_missing"),
        ("unavailable", "encoder_open_failed"),
        ("omitted", "encoder_stuck"),
        ("failed", "write_failed"),
    ):
        summary = {"bytes": 0, "deleted": 0, "kept": 0, "reason": reason, "status": status}
        assert check_shape(finished_run(video=summary)) == [], status
    none = {"bytes": 0, "deleted": 3, "kept": 0, "status": "none"}
    assert check_shape(finished_run(video=none)) == []
    # 사용 불가·포기·실패에는 이유가 있어야 하고, 남긴 영상에는 이유가 없다
    assert check_shape(finished_run(video={**none, "status": "unavailable"}))
    assert check_shape(finished_run(video={**video, "reason": "mf_missing"}))
    assert check_shape(finished_run(video={**video, "status": "lost"}))
    assert check_shape(finished_run(observed={**observed, "dpi": 0}))
    assert check_shape(finished_run(observed={"backend": "wgc", "client_size": [1280]}))
    assert check_shape(finished_run(retried_steps=-1))


# ------------------------------------------------------------------ 브레이크포인트 파일


BREAKPOINTS = {
    "breakpoints": [
        {"graph": "subgraphs/enter_world.graph.json", "node": "n_wait_title"},
        {"graph": "tests/inventory_open.graph.json", "node": "n_press_i"},
    ],
    "format": "kookabug.breakpoints/0",
}


def test_breakpoints_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "breakpoints.json"
    path.write_text(canonical_dumps(BREAKPOINTS), encoding="utf-8")
    data = loads_strict(path.read_text(encoding="utf-8"))
    assert data == BREAKPOINTS
    assert kind_of(data) == "breakpoints"
    assert check_shape(data) == []
    model = Breakpoints.model_validate(data)
    assert model.model_dump(mode="json", exclude_unset=True) == BREAKPOINTS
    assert check_shape({"breakpoints": [], "format": "kookabug.breakpoints/0"}) == []


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ({"graph": "tests/a.graph.json"}, "missing_field"),
        ({"graph": "tests/a.graph.json", "node": "n.x"}, "pattern_mismatch"),
        ({"graph": "tests\\a.graph.json", "node": "n_x"}, "pattern_mismatch"),
        ({"graph": "tests/a.target.json", "node": "n_x"}, "pattern_mismatch"),
        ({"graph": "tests/a.graph.json", "node": "n_x", "hits": 2}, "unknown_field"),
    ],
)
def test_breakpoints_file_rejects_bad_entries(entry: dict[str, Any], code: str) -> None:
    data = {"breakpoints": [entry], "format": "kookabug.breakpoints/0"}
    assert code in [d.code for d in check_shape(data)]


# ------------------------------------------------------------------ 영상 색인


SEGMENT = {
    "bytes": 153000,
    "file": "seg-0001.mp4",
    "frame_ms": 200,
    "frames": 300,
    "mode": "failed_only",
    "size": [1280, 720],
    "t0": T,
    "t_end": T2,
    "window": "w1",
}
GAP = {"gap": "secret_input", "step": "s7", "t_end": T2, "t_start": T}


def line_problems(value: Any, ref: str) -> list[Any]:
    return check_shape(value, "video-index", ref=f"#/$defs/{ref}")


def test_video_index_and_segments_line_shape() -> None:
    index = {
        "bytes": 153000,
        "deleted": [{"file": "seg-0002.part.mp4", "mode": "on", "reason": "interrupted"}],
        "format": "kookabug.video-index/0",
        "gaps": [GAP, {"gap": "interrupted", "t_end": T2, "t_start": T}],
        "segments": [SEGMENT],
        "status": "recorded",
    }
    assert kind_of(index) == "video-index"
    assert check_shape(index) == []
    assert VideoIndex.model_validate(index).model_dump(mode="json", exclude_unset=True) == index
    for line in (SEGMENT, GAP):
        assert line_problems(line, "SegmentsLine") == []
        assert SegmentsLine.model_validate(line).model_dump(mode="json", exclude_unset=True) == line
    # 판정 pass라 failed_only 조각을 지움
    passed = {
        **index,
        "bytes": 0,
        "deleted": [{"file": "seg-0001.mp4", "mode": "failed_only", "reason": "run_pass"}],
        "segments": [],
    }
    assert check_shape(passed) == []
    assert line_problems({**SEGMENT, "file": "video.mp4"}, "SegmentsLine")
    assert line_problems({**SEGMENT, "mode": "off"}, "SegmentsLine")
    assert line_problems({**SEGMENT, "frames": 0}, "SegmentsLine")
    assert check_shape({**index, "status": "recorded", "reason": "mf_missing"})


def test_part_mp4_only_in_deleted_not_in_segments() -> None:
    # 검수 T1-1: 쓰는 중 파일(.part.mp4)은 재생 보장이 없다. 완성 조각 목록(segments.jsonl 줄,
    # index.json segments, run.index video.segments)에는 올 수 없고 지운 조각 기록에만 온다
    part = {**SEGMENT, "file": "seg-0001.part.mp4"}
    assert codes(line_problems(part, "Segment")) == [("pattern_mismatch", "/file")]
    assert line_problems(part, "SegmentsLine")
    index = {
        "bytes": 1,
        "deleted": [],
        "format": "kookabug.video-index/0",
        "gaps": [],
        "segments": [part],
        "status": "recorded",
    }
    assert codes(check_shape(index)) == [("pattern_mismatch", "/segments/0/file")]
    run_index = {
        "failure_chain": [],
        "last_seq": 0,
        "pauses": [],
        "run": None,
        "run_dir": "runs/x",
        "run_id": RUN,
        "state": "ended",
        "stats": [],
        "steps": [],
        "video": {"finalized": True, "gaps": [], "segments": [part], "status": "recorded"},
    }
    assert check_shape(run_index, "run-index")
    assert (
        check_shape(
            {**run_index, "video": {**run_index["video"], "segments": [SEGMENT]}}, "run-index"
        )
        == []
    )
    deleted = {"file": "seg-0001.part.mp4", "mode": "on", "reason": "interrupted"}
    assert check_shape({**index, "deleted": [deleted], "segments": []}) == []
    for name in ("seg-1.mp4", "seg-0001.part.part.mp4", "seg-0001.mp4.part"):
        assert check_shape({**index, "deleted": [{**deleted, "file": name}], "segments": []}), name


def test_video_segment_line_has_grid_fields_and_gap_reasons() -> None:
    # 검수 M3: 5 fps 격자 (t0·frame_ms·frames)로 재생 위치 ↔ 실행 시각을 복원한다
    segment = metaschema("video-index")["$defs"]["Segment"]
    assert {"t0", "frame_ms", "frames", "t_end"} <= set(segment["required"])
    for field in ("t0", "frame_ms", "frames"):
        missing = {k: v for k, v in SEGMENT.items() if k != field}
        assert line_problems(missing, "Segment"), field
    reasons = set(metaschema("video-index")["$defs"]["GapReason"]["enum"])
    assert reasons == {
        "policy_off",
        "secret_input",
        "paused",
        "no_window",
        "capture_missed",
        "unavailable",
        "failed",  # T5: 녹화 중 쓰기 실패 (감독자 마무리도 status·reason을 알도록)
        "starting",  # T5 2라운드: 인코더 열기 시험을 기다린 실행 앞부분
        "interrupted",
    }
    for reason in reasons:
        assert line_problems({**GAP, "gap": reason}, "SegmentsLine") == [], reason
    # T5: unavailable·failed 빈 구간은 영상 이유를 싣는다
    gap = {**GAP, "gap": "unavailable", "reason": "mf_missing"}
    assert line_problems(gap, "SegmentsLine") == []
    assert line_problems({**gap, "reason": "nope"}, "SegmentsLine")
    assert line_problems({**GAP, "gap": "pending"}, "SegmentsLine")
    # 조각과 빈 구간 필드를 섞은 줄은 어느 쪽도 아니다
    assert line_problems({**SEGMENT, "gap": "paused"}, "SegmentsLine")


def test_frames_jsonl_line_shape() -> None:
    lines = [
        {"pixels_at": T, "repeat": False, "slot": 0},
        {"pixels_at": T, "repeat": True, "slot": 1},
    ]
    for line in lines:
        assert line_problems(line, "FramesLine") == []
        assert FramesLine.model_validate(line).model_dump(mode="json") == line
    assert line_problems({"pixels_at": T, "repeat": False, "slot": -1}, "FramesLine")
    assert line_problems({"pixels_at": T, "slot": 0}, "FramesLine")
    assert line_problems({"pixels_at": "06:02:11", "repeat": False, "slot": 0}, "FramesLine")


def test_video_index_omitted_status_and_cleanup_failed() -> None:
    # 2차 N2: 포기한 실행의 색인은 조각 없이 omitted/encoder_stuck.
    # 지우지 못한 파일은 cleanup_failed (다음 마무리가 다시 시도)
    omitted = {
        "bytes": 0,
        "deleted": [
            {"file": "seg-0001.mp4", "reason": "encoder_stuck"},
            {"file": "seg-0002.part.mp4", "reason": "encoder_stuck"},
        ],
        "format": "kookabug.video-index/0",
        "gaps": [],
        "reason": "encoder_stuck",
        "segments": [],
        "status": "omitted",
    }
    assert check_shape(omitted) == []
    assert check_shape({**omitted, "cleanup_failed": ["seg-0002.part.mp4"]}) == []
    assert check_shape({k: v for k, v in omitted.items() if k != "reason"})
    assert check_shape({**omitted, "cleanup_failed": [""]})
    assert check_shape({**omitted, "reason": "stuck"})
    unavailable = {**omitted, "deleted": [], "reason": "mf_missing", "status": "unavailable"}
    assert check_shape(unavailable) == []


# ------------------------------------------------------------------ runner 제어 RPC


def test_runner_resume_and_breakpoints_params() -> None:
    def problems(value: Any, ref: str) -> list[Any]:
        return check_shape(value, "rpc", ref=f"#/$defs/{ref}")

    assert problems({}, "RunResumeParams") == []  # M0b 호출 (mode 없음) = continue
    assert problems({"mode": "step_into"}, "RunResumeParams") == []
    assert problems({"mode": "jump"}, "RunResumeParams")
    assert problems({"breakpoints": BREAKPOINTS["breakpoints"]}, "RunBreakpointsParams") == []
    assert problems({"breakpoints": [{"graph": "a.graph.json"}]}, "RunBreakpointsParams")
    spec_props = metaschema("rpc")["$defs"]["RunSpec"]["properties"]
    assert "breakpoints" in spec_props
    assert "breakpoints" not in metaschema("rpc")["$defs"]["RunSpec"]["required"]


# ------------------------------------------------------------------ daemon 메서드 표

DEBUG_METHODS = {
    "debug.breakpoints.get",
    "debug.breakpoints.set",
    "run.pause",
    "run.resume",
    "run.restart",
}
READ_METHODS = {"run.index", "run.children", "run.step", "run.file", "run.compare"}


def drpc(value: Any, ref: str) -> list[Any]:
    return check_shape(value, "daemon-rpc", ref=ref)


def test_daemon_rpc_method_table_m3() -> None:
    defs = metaschema("daemon-rpc")["$defs"]
    table = defs["Methods"]["properties"]
    for name in DEBUG_METHODS | READ_METHODS | {"run.export"}:
        row = table[name]["properties"]
        assert set(table[name]["required"]) == {"params", "renderer", "result", "tool"}
        for part in ("params", "result"):
            assert row[part]["$ref"].removeprefix("#/$defs/") in defs, (name, part)
        tool = row["tool"]["const"]
        assert tool == ("kb_run_events" if name in READ_METHODS else "ui_only"), name
        # 디버그·읽기는 렌더러가 부르고, 내보내기는 주 프로세스만 (dest는 저장 대화 상자)
        assert row["renderer"]["const"] is (name != "run.export"), name
    assert "debug.breakpoints.changed" in defs["Notifications"]["properties"]

    def params(method: str, value: Any) -> list[Any]:
        return drpc(value, f"#/$defs/Methods/properties/{method}/properties/params")

    def result(method: str, value: Any) -> list[Any]:
        return drpc(value, f"#/$defs/Methods/properties/{method}/properties/result")

    bps = {"breakpoints": BREAKPOINTS["breakpoints"]}
    assert params("debug.breakpoints.get", {}) == []
    assert params("debug.breakpoints.set", bps) == []
    assert params("debug.breakpoints.set", {"breakpoints": [{"node": "n"}]})
    assert result("debug.breakpoints.get", bps) == []
    assert params("run.pause", {"run_id": RUN}) == []
    assert params("run.resume", {"run_id": RUN}) == []
    assert params("run.resume", {"mode": "step_out", "run_id": RUN}) == []
    assert params("run.resume", {"mode": "back", "run_id": RUN})
    assert result("run.resume", {"state": "paused"}) == []
    assert result("run.pause", {"state": "stopped"})
    started = {"graph": "tests/a.graph.json", "run_dir": "runs/x", "run_id": "a1b2c3d4"}
    assert result("run.restart", started) == []
    assert params("run.children", {"limit": 500, "offset": 0, "parent": "s3", "run_id": RUN}) == []
    assert params("run.children", {"limit": 501, "offset": 0, "parent": "s3", "run_id": RUN})
    assert (
        params(
            "run.children",
            {"iteration": 9999, "limit": 1, "offset": 0, "parent": "s3", "run_id": RUN},
        )
        == []
    )
    assert result("run.children", {"offset": 0, "steps": [STEP_NODE], "total": 1}) == []
    assert params("run.step", {"run_id": RUN, "step": "s4"}) == []
    step = {
        "events": [STEP_END, ev("log", seq=2, level="info", message="m", node="n", step="s4")],
        "ocr_text": None,
        "run_dir": "runs/x",
        "step": STEP_NODE,
        "thumbnail": "thumbs/s4.jpg",
    }
    assert result("run.step", step) == []
    # 이벤트 본문은 events 스키마로 본다
    assert result("run.step", {**step, "events": [{**STEP_END, "status": "bad"}]})
    assert params("run.file", {"name": "run.json", "run_id": RUN}) == []
    assert params("run.file", {"name": "events.jsonl", "run_id": RUN})
    assert result("run.file", {"bytes": 10, "text": "{}", "truncated": False}) == []
    assert params("run.compare", {"run_id": RUN}) == []
    assert params("run.compare", {"baseline": "a1b2c3d4", "run_id": RUN, "step": "s4"}) == []
    assert result("run.compare", {"baseline": None, "run_id": RUN}) == []
    assert params("run.export", {"dest": "C:/out/a.zip", "run_id": RUN}) == []
    assert params("run.export", {"run_id": RUN})
    assert (
        params("run.list", {"before": "x", "graph": "tests/a.graph.json", "verdict": "fail"}) == []
    )
    assert params("run.list", {"verdict": "unknown"})
    summary = {
        "code": "unhandled_fail",
        "debug_intervened": False,
        "duration_ms": 900,
        "failure_path": ["n_enter_world", "n_wait_title"],
        "failure_title": "월드 접속 > 타이틀 대기",
        "flaky": False,
        "game_build": None,
        "graph": "tests/a.graph.json",
        "last_seq": 20,
        "outcome": {"exit_code": 1, "finalized_by": "runner", "verdict": "fail"},
        "profile": None,
        "reason": "r",
        "run_dir": "runs/x",
        "run_id": RUN,
        "started_at": T,
        "state": "ended",
    }
    assert result("run.list", {"next": None, "runs": [summary], "runs_bytes": 1024}) == []
    assert result("run.list", {"runs": []}) == []  # M2 모양 그대로도 된다
    opened = drpc({"read_only": True}, "#/$defs/GraphOpenResult")
    assert [d.pointer for d in opened if d.code == "unknown_field"] == []
    codes_ = set(defs["RequestFailedCode"]["enum"])
    assert {"read_only", "not_paused", "run_not_debuggable"} <= codes_


# ------------------------------------------------------------------ 기록 읽기 결과


STEP_NODE = {
    "attempt": 1,
    "children": 0,
    "duration_ms": 3008,
    "evidence": True,
    "exit": "timeout",
    "graph": "subgraphs/enter_world.graph.json",
    "node": "n_wait_title",
    "omitted": [{"kind": "thumbnail", "reason": "policy_off"}],
    "parent": "s2",
    "path": ["n_enter_world", "n_wait_title"],
    "status": "fail",
    "step": "s4",
    "t_end": T2,
    "t_start": T,
    "thumbnail": False,
}


def test_run_index_and_compare_shapes() -> None:
    loop = {
        **STEP_NODE,
        "children": 4,
        "iterations": [
            {"duration_ms": 10, "iteration": 0, "status": "success", "steps": 2, "t_start": T},
            {"duration_ms": None, "iteration": 1, "status": "aborted", "steps": 2, "t_start": T2},
        ],
        "step": "s3",
    }
    index = {
        "failure_chain": ["s2", "s4"],
        "last_seq": 40,
        "pauses": [{"reason": "breakpoint", "step": "s4", "t_end": None, "t_start": T}],
        "run": finished_run(),
        "run_dir": "runs/2026-10-29T06-02-11_inventory_open_r8k2x7qm",
        "run_id": RUN,
        "state": "ended",
        "stats": [
            {
                "count": 2,
                "error": 0,
                "fail": 1,
                "graph": "subgraphs/enter_world.graph.json",
                "last_failure_step": "s4",
                "max_ms": 3008,
                "mean_ms": 1520.5,
                "node": "n_wait_title",
                "p95_ms": 3008,
                "success": 1,
            }
        ],
        "steps": [STEP_NODE, loop],
        "video": {"finalized": False, "gaps": [GAP], "segments": [SEGMENT], "status": "recorded"},
    }
    assert check_shape(index, "run-index") == []
    assert check_shape({**index, "video": None, "run": None}, "run-index") == []
    assert check_shape({**index, "steps": [{**STEP_NODE, "status": "interrupted"}]}, "run-index")
    compare = {
        "baseline": "a1b2c3d4",
        "baseline_picked": "auto",
        "env": [{"baseline": 96, "key": "observed.dpi", "run": 144}],
        "graph": {"baseline_hash": "a" * 64, "changed": [], "hash": "a" * 64, "same": True},
        "run_id": RUN,
        "screen": {
            "baseline_file": "thumbs/s4.jpg",
            "baseline_step": "s4",
            "diff_ratio": 0.12,
            "file": "steps/s4_fail.png",
            "regions": [[300, 200, 400, 240]],
            "step": "s4",
        },
        "time": {"inflections": [], "nodes": []},
    }
    ref = "#/$defs/CompareResult"
    assert check_shape(compare, "run-index", ref=ref) == []
    none = {"baseline": None, "message": "비교할 성공 실행 없음", "run_id": RUN}
    assert check_shape(none, "run-index", ref=ref) == []
    missing = {
        **compare["screen"],
        "baseline_file": None,
        "diff_ratio": None,
        "reason": "no_thumbnail",
    }
    del missing["diff_ratio"]
    assert check_shape({**compare, "screen": missing}, "run-index", ref=ref) == []
    six = {**compare["screen"], "regions": [[0, 0, 1, 1]] * 6}
    assert check_shape({**compare, "screen": six}, "run-index", ref=ref)
