"""멱등 마무리 (구현 계획 M0b 2.7 `finalize_run`).

runner가 어떻게 끝났든 runner 종료를 확인한 쪽(감독자 복구 경로)이 부른다. 두 번 불러도 결과가
같다 (이벤트 중복 없음).

1. 저널 끝이 잘린 줄이면 마지막 완전한 줄까지 자른다 (`truncated_bytes`)
2. 키 복구: 기록상 눌렸을 수 있는 키가 있고 복구 표시 파일(`input-recovery.json`)이 없으면
   `recover_inputs`를 부른다 (임대권 안의 복구는 부르는 쪽 몫). 복구했으면 `input.recovered`
3. `run.end`가 없으면 `run.end`(`error`/`runner_died`, `finalized_by: supervisor`)를 덧붙인다.
   **있으면 덮어쓰지 않는다** (`run.end` 뒤에는 `input.recovered`만 더해질 수 있다). 저널에
   `debug.pause`가 있으면 멈춘 시간·디버거 개입도 저널에서 세어 넣는다 (M3)
4. 영상 마무리 `finalize_video` (M3 2.5): 저널에 있는 최종 `run.end` 기준
5. `run.json`이 `finished`가 아니거나 `run.end`와 다르면 `run.end`에서 다시 만든다
   (`run_json_repaired: true`). 영상 요약(`video`)은 `video/index.json`에서 읽어 넣는다

열린 스텝에는 `step.end`를 쓰지 않는다 (읽기가 "중단"으로 표시한다).

**영상 마무리** (`finalize_video`, runner와 감독자가 같은 함수를 쓰고 다시 불러도 결과가 같다).
선행 조건: 부르는 쪽이 작성자(녹화 스레드)가 없음을 확인했다 — runner는 녹화 스레드 종료를 확인한
경우만, 감독자는 runner 프로세스 종료를 확인한 뒤.

0. `run.end.omitted`에 `video`/`encoder_stuck`이 있으면 `video/` 안 파일을 모두 지우고
   `status: omitted`를 공개한다 (지우지 못한 파일은 `cleanup_failed`, 다음 마무리가 다시 시도)
1. `segments.jsonl`을 읽는다 (끝의 잘린 줄은 버림). 줄이 있는 `.mp4`는 완성 조각, `.part.mp4`와 줄
   없는 `.mp4`는 지우고 `{gap: interrupted}`
2. 보관 판정 (사용자 결정 U5): 판정 `fail`·`error`면 `failed_only` 조각을 남기고, `pass`·`skipped`·
   사용자 취소(`cancel_reason: cancelled`)면 지운다. `on` 조각은 늘 남긴다. 이미 없는 파일은 지운
   것으로 본다
3. `video/index.json`을 같은 폴더 임시 파일 + replace로 공개한다. 이미 있어도 디스크와 맞춰 다시
   쓴다 (앞 마무리의 지운 기록·중단 구간은 이어받는다)
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from kookabug_core.canonical import canonical_dumps
from kookabug_core.record.journal import Journal
from kookabug_core.record.reader import InputKey, RunView, held_inputs, read_run
from kookabug_core.record.runfolder import (
    EVENTS_FILE,
    INPUT_RECOVERY_FILE,
    RUN_FORMAT,
    RUN_JSON_FILE,
    finished_run_json,
    read_run_json,
    run_id_of_folder,
    run_json_matches,
    write_run_json,
)
from kookabug_core.record.video import (
    INDEX_FILE,
    INDEX_FORMAT,
    SEGMENTS_FILE,
    VIDEO_DIR,
    WRITER_FILE,
)

__all__ = [
    "FinalizeResult",
    "InputRecoveryOutcome",
    "RecoverInputs",
    "VideoWriterAlive",
    "finalize_run",
    "finalize_video",
    "read_video",
    "read_video_index",
    "video_summary",
]

_SEGMENT_FILE: Final = re.compile(r"seg-(\d{4,})(\.part)?\.mp4")
_FRAMES_FILE: Final = re.compile(r"seg-(\d{4,})\.frames\.jsonl")
_DELETE_TRIES: Final = 10
_DELETE_WAIT_S: Final = 0.05

type InputRecovery = Literal[
    "already_recovered", "lease_busy", "not_needed", "recovered", "unavailable"
]


@dataclass(frozen=True, slots=True)
class InputRecoveryOutcome:
    """키 복구 결과. `recovered`면 `inputs`를 뗐다."""

    status: InputRecovery
    inputs: Sequence[InputKey] = ()


# (실행 폴더, 눌렸을 수 있는 키) → 결과. 임대권 안의 복구는 T6 `recover_run`이 맡는다
type RecoverInputs = Callable[[Path, Sequence[InputKey]], InputRecoveryOutcome]


@dataclass(slots=True)
class FinalizeResult:
    run_end: dict[str, Any]
    truncated_bytes: int = 0
    input_recovery: InputRecovery = "not_needed"
    appended: list[str] = field(default_factory=list[str])
    """이번 호출이 저널에 더한 이벤트 종류 (두 번째 호출이면 빈 목록)."""
    run_json_repaired: bool = False


def finalize_run(
    run_dir: str | os.PathLike[str],
    *,
    runner_exit_code: int | None = None,
    recover_inputs: RecoverInputs | None = None,
    seed: Mapping[str, Any] | None = None,
    now: Callable[[], datetime] | None = None,
) -> FinalizeResult:
    """runner가 끝난 실행 폴더를 마무리한다. runner 종료 확인 뒤에만 부른다 (작성자는 하나).

    `seed`는 `run.json`도 `run.start`도 없을 때(runner가 기록을 시작하기 전에 죽음) 쓸 시작
    정보(`run_id`·`graph`·`started_at` 등)다.
    """
    folder = Path(run_dir)
    clock = now or (lambda: datetime.now(UTC))
    events_path = folder / EVENTS_FILE

    # 1. 잘린 끝 줄
    view = read_run(folder)
    truncated = view.truncated_bytes
    if truncated:
        os.truncate(events_path, view.valid_size)
        view = read_run(folder)

    start_json = read_run_json(folder / RUN_JSON_FILE)
    run_id = _run_id(folder, view, start_json, seed)
    # 시작 정보를 모르면 아무것도 쓰기 전에 실패한다
    base = _start_fields(start_json, view, run_id, seed)
    appended: list[str] = []

    with Journal(events_path, run_id, writer="supervisor", now=clock) as journal:
        # 2. 키 복구
        recovery = _recover_inputs(folder, view, run_id, recover_inputs, journal, appended)

        # 3. run.end
        run_end = view.run_end
        if run_end is None:
            run_end = journal.emit(
                _runner_died(view, runner_exit_code, recovery, truncated, clock())
            )
            appended.append("run.end")

    # 4. 영상 (최종 run.end 기준). 실패해도 run.json은 쓴다 (영상 요약만 빠진다)
    summary: dict[str, Any] | None = None
    try:
        index = finalize_video(folder, run_end)
    except Exception:
        index = read_video_index(folder / VIDEO_DIR)
    if index is not None:
        summary = video_summary(index)

    # 5. run.json
    repaired = False
    if not run_json_matches(start_json, run_end):
        data = finished_run_json(base, run_end)
        data["run_json_repaired"] = True
        pauses = _pause_count(view)
        if pauses:
            data["pause_count"] = pauses
        if summary is not None:
            data["video"] = summary
        write_run_json(folder / RUN_JSON_FILE, data)
        repaired = True
    elif summary is not None and start_json is not None and start_json.get("video") != summary:
        # runner가 마무리했지만 영상 요약이 다르다 (runner가 영상을 포기해 감독자가 지운 경우 등)
        write_run_json(folder / RUN_JSON_FILE, {**start_json, "video": summary})

    return FinalizeResult(
        run_end=run_end,
        truncated_bytes=truncated,
        input_recovery=recovery,
        appended=appended,
        run_json_repaired=repaired,
    )


def _recover_inputs(
    folder: Path,
    view: RunView,
    run_id: str,
    recover_inputs: RecoverInputs | None,
    journal: Journal,
    appended: list[str],
) -> InputRecovery:
    held = held_inputs(view)
    if not held:
        return "not_needed"
    if (folder / INPUT_RECOVERY_FILE).exists():
        # 다음 임대권 소유자가 이미 뗐다
        return "already_recovered"
    if recover_inputs is None:
        return "unavailable"
    outcome = recover_inputs(folder, held)
    if outcome.status == "recovered":
        journal.emit(
            {
                "by": {"kind": "supervisor"},
                "event": "input.recovered",
                "from_run": run_id,
                "inputs": [k.to_event() for k in (outcome.inputs or held)],
            }
        )
        appended.append("input.recovered")
    return outcome.status


def _runner_died(
    view: RunView,
    exit_code: int | None,
    recovery: InputRecovery,
    truncated: int,
    now: datetime,
) -> dict[str, Any]:
    code_text = f" (종료 코드 {exit_code})" if exit_code is not None else ""
    open_steps = view.interrupted_steps
    last = open_steps[-1] if open_steps else None
    event: dict[str, Any] = {
        "code": "runner_died",
        "duration_ms": _duration_ms(view, now),
        "event": "run.end",
        "failure_path": last.path if last is not None and last.path else None,
        "failure_step": last.step if last is not None else None,
        "finalized_by": "supervisor",
        "input_recovery": recovery,
        "reason": f"runner가 실행을 마무리하지 못하고 끝났다{code_text}",
        "verdict": "error",
    }
    if exit_code is not None:
        event["runner_exit_code"] = exit_code
    if view.cancel_reason is not None:
        event["cancel_reason"] = view.cancel_reason
    if truncated:
        event["truncated_bytes"] = truncated
    if _pause_count(view):
        # 디버거가 개입한 실행은 runner가 죽었어도 그렇게 남긴다 (기준 실행·배지, M3 T2 검수)
        paused_ms = _paused_ms(view, now)
        event["paused_ms"] = paused_ms
        event["debug_intervened"] = True
        if event["duration_ms"] is not None:
            event["active_duration_ms"] = max(0, event["duration_ms"] - paused_ms)
    return event


def _pause_count(view: RunView) -> int:
    return sum(1 for e in view.events if e.get("event") == "debug.pause")


def _paused_ms(view: RunView, now: datetime) -> int:
    """저널의 멈춘 시간 합: 재개한 멈춤은 `debug.resume.paused_ms`, 멈춘 채 끝났으면 그 멈춤부터
    지금까지."""
    total = 0
    open_at: str | None = None
    for event in view.events:
        kind = event.get("event")
        if kind == "debug.pause":
            open_at = event.get("t")
        elif kind == "debug.resume":
            open_at = None
            value = event.get("paused_ms")
            if isinstance(value, int):
                total += value
    if open_at is not None:
        with contextlib.suppress(TypeError, ValueError):
            began = datetime.fromisoformat(open_at)
            total += max(0, int((now - began).total_seconds() * 1000))
    return total


def _duration_ms(view: RunView, now: datetime) -> int | None:
    start = view.run_start
    if start is None:
        return None
    try:
        began = datetime.fromisoformat(start["t"])
    except KeyError, TypeError, ValueError:
        return None
    return max(0, int((now - began).total_seconds() * 1000))


def _run_id(
    folder: Path,
    view: RunView,
    start_json: Mapping[str, Any] | None,
    seed: Mapping[str, Any] | None,
) -> str:
    for candidate in (
        view.run_id,
        (start_json or {}).get("run_id"),
        (seed or {}).get("run_id"),
        run_id_of_folder(folder),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    raise ValueError(f"run_id를 알 수 없다: {folder}")


def _start_fields(
    start_json: Mapping[str, Any] | None,
    view: RunView,
    run_id: str,
    seed: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """완료 `run.json`의 바탕: 기존 `run.json` → `seed` → `run.start`에서 아는 것."""
    base: dict[str, Any] = {}
    run_start = view.run_start
    if run_start is not None:
        base["graph"] = run_start.get("graph")
        base["started_at"] = run_start.get("t")
    base.update(seed or {})
    base.update(start_json or {})
    base.update(format=RUN_FORMAT, run_id=run_id)
    if not isinstance(base.get("graph"), str) or not isinstance(base.get("started_at"), str):
        raise ValueError(
            "run.json도 run.start도 없어 시작 정보를 알 수 없다. seed에 graph·started_at을 준다"
        )
    return base


# ---------------------------------------------------------------- 영상 (M3 2.5)


def read_video_index(video: Path) -> dict[str, Any] | None:
    """공개된 `video/index.json` (없거나 읽을 수 없으면 None)."""
    try:
        value = json.loads((video / INDEX_FILE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(value, dict):
        return None
    index = cast(dict[str, Any], value)
    return index if index.get("format") == INDEX_FORMAT else None


def read_video(run_dir: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, bool]:
    """실행 폴더의 영상 색인과 마무리 여부. 공개된 `index.json`이 있으면 그것(True), 없으면
    `segments.jsonl`만 보고 만든 같은 모양(False — 이중 고장으로 아무도 마무리하지 못한 폴더).
    읽기는    파일을 고치거나 지우지 않는다. 영상 폴더가 없으면 (None, False)."""
    video = Path(run_dir) / VIDEO_DIR
    index = read_video_index(video)
    if index is not None:
        return index, True
    if not video.is_dir():
        return None, False
    lines = _segment_lines(video)
    segments = [
        dict(line) for line in lines if "file" in line and (video / str(line["file"])).exists()
    ]
    status, reason = _video_status(lines, None, [])
    view: dict[str, Any] = {
        "bytes": sum(int(s.get("bytes", 0)) for s in segments),
        "deleted": [],
        "format": INDEX_FORMAT,
        "gaps": sorted(
            (dict(line) for line in lines if "gap" in line),
            key=lambda g: (str(g["t_start"]), str(g["t_end"])),
        ),
        "segments": sorted(segments, key=lambda s: str(s["t0"])),
        "status": status,
    }
    if reason is not None:
        view["reason"] = reason
    return view, False


def video_summary(index: Mapping[str, Any]) -> dict[str, Any]:
    """`run.json`의 `video` (`index.json`에서): 상태·남은·지운 조각 수·바이트·이유."""
    summary: dict[str, Any] = {
        "bytes": int(index.get("bytes", 0)),
        "deleted": len(index.get("deleted", ())),
        "kept": len(index.get("segments", ())),
        "status": index["status"],
    }
    if "reason" in index:
        summary["reason"] = index["reason"]
    return summary


def video_omitted(run_end: Mapping[str, Any]) -> bool:
    """runner가 영상을 포기했다 (`run.end.omitted`의 `video`/`encoder_stuck`)."""
    omitted = run_end.get("omitted")
    if not isinstance(omitted, list):
        return False
    return any(
        isinstance(item, dict) and cast(Mapping[str, Any], item).get("kind") == "video"
        for item in cast(list[Any], omitted)
    )


def _keep_failed_only(run_end: Mapping[str, Any]) -> tuple[bool, str | None]:
    """`failed_only` 조각을 남기는가와, 지우면 그 이유 (사용자 결정 U5)."""
    if run_end.get("cancel_reason") == "cancelled":
        return False, "run_cancelled"
    verdict = run_end.get("verdict")
    if verdict in ("fail", "error"):
        return True, None
    return False, "run_skipped" if verdict == "skipped" else "run_pass"


def finalize_video(
    run_dir: str | os.PathLike[str], run_end: Mapping[str, Any]
) -> dict[str, Any] | None:
    """영상을 최종 `run.end` 기준으로 마무리하고 공개한 색인을 돌려준다. 영상 폴더가 없으면 None.

    선행 조건: 작성자(녹화 스레드)가 끝났다 — 부르는 쪽이 확인한다 (모듈 설명)."""
    video = Path(run_dir) / VIDEO_DIR
    if not video.is_dir():
        return None
    _check_writer_gone(video)
    previous = read_video_index(video)
    _remove_stale_temps(video)
    if video_omitted(run_end):
        index = _omitted_index(video, previous)
    else:
        index = _recorded_index(video, run_end, previous)
    _publish(video, index)
    return index


def _omitted_index(video: Path, previous: Mapping[str, Any] | None) -> dict[str, Any]:
    deleted = _carried(previous, "encoder_stuck")
    failed: list[str] = []
    for path in sorted(_names(video)):
        if path.name == INDEX_FILE:
            continue
        if _SEGMENT_FILE.fullmatch(path.name):
            _add_deleted(deleted, {"file": path.name, "reason": "encoder_stuck"})
        if not _delete(path):
            failed.append(path.name)
    index: dict[str, Any] = {
        "bytes": 0,
        "deleted": deleted,
        "format": INDEX_FORMAT,
        "gaps": [],
        "reason": "encoder_stuck",
        "segments": [],
        "status": "omitted",
    }
    if failed:
        index["cleanup_failed"] = failed
    return index


def _recorded_index(
    video: Path, run_end: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> dict[str, Any]:
    lines = _segment_lines(video)
    listed = {str(line["file"]): line for line in lines if "file" in line}
    gaps: list[dict[str, Any]] = [dict(line) for line in lines if "gap" in line]
    deleted = _carried(previous, "interrupted")
    # 앞 마무리가 남긴 중단 구간 (그 파일은 이미 지웠다)
    for gap in (previous or {}).get("gaps", ()):
        if isinstance(gap, dict):
            item = cast(dict[str, Any], gap)
            if item.get("gap") == "interrupted" and item not in gaps:
                gaps.append(item)
    failed: list[str] = []

    # 1. 쓰다 만 조각: .part.mp4와 segments.jsonl 줄 없는 .mp4
    for path in sorted(_names(video)):
        match = _SEGMENT_FILE.fullmatch(path.name)
        if match is None or (match.group(2) is None and path.name in listed):
            continue
        frames = video / f"seg-{match.group(1)}.frames.jsonl"
        span = _frames_span(frames)
        end_t = run_end.get("t")
        if span is None and isinstance(end_t, str):
            span = (end_t, end_t)
        if span is not None:
            gap = {"gap": "interrupted", "t_end": span[1], "t_start": span[0]}
            if gap not in gaps:
                gaps.append(gap)
        _add_deleted(deleted, {"file": path.name, "reason": "interrupted"})
        for target in (path, frames):
            if not _delete(target):
                failed.append(target.name)

    # 2. 보관 판정
    keep, why = _keep_failed_only(run_end)
    segments: list[dict[str, Any]] = []
    total = 0
    for name, line in listed.items():
        path = video / name
        if line.get("mode") == "on" or keep:
            if path.exists():
                segments.append(dict(line))
                total += path.stat().st_size
            continue
        _add_deleted(deleted, {"file": name, "mode": line.get("mode"), "reason": why})
        frames = video / name.replace(".mp4", ".frames.jsonl")
        for target in (path, frames):
            if not _delete(target):
                failed.append(target.name)

    status, reason = _video_status(lines, previous, deleted)
    index: dict[str, Any] = {
        "bytes": total,
        "deleted": deleted,
        "format": INDEX_FORMAT,
        "gaps": sorted(gaps, key=lambda g: (str(g["t_start"]), str(g["t_end"]))),
        "segments": sorted(segments, key=lambda s: str(s["t0"])),
        "status": status,
    }
    if reason is not None:
        index["reason"] = reason
    if failed:
        index["cleanup_failed"] = failed
    return index


def _video_status(
    lines: Sequence[Mapping[str, Any]],
    previous: Mapping[str, Any] | None,
    deleted: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None]:
    for gap in lines:
        if gap.get("gap") == "unavailable":
            return "unavailable", str(gap.get("reason", "encoder_open_failed"))
    for gap in lines:
        if gap.get("gap") == "failed":
            return "failed", str(gap.get("reason", "write_failed"))
    if any("file" in line for line in lines) or deleted:
        return "recorded", None
    if previous is not None and previous.get("status") == "recorded":
        return "recorded", None
    return "none", None


def _segment_lines(video: Path) -> list[dict[str, Any]]:
    """`segments.jsonl`의 온전한 줄 (끝의 잘린 줄·깨진 줄은 버린다)."""
    try:
        text = (video / SEGMENTS_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[dict[str, Any]] = []
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        line = cast(dict[str, Any], value)
        name = line.get("file")
        if name is not None and (
            not _SEGMENT_FILE.fullmatch(str(name)) or str(name).endswith(".part.mp4")
        ):
            continue
        if name is None and "gap" not in line:
            continue
        lines.append(line)
    return lines


def _frames_span(frames: Path) -> tuple[str, str] | None:
    """쓰다 만 조각의 첫·마지막 칸 픽셀 시각 (`frames.jsonl`)."""
    try:
        text = frames.read_text(encoding="utf-8")
    except OSError:
        return None
    stamps: list[str] = []
    for raw in text.split("\n"):
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            at = cast(dict[str, Any], value).get("pixels_at")
            if isinstance(at, str):
                stamps.append(at)
    if not stamps:
        return None
    return min(stamps), max(stamps)


def _carried(previous: Mapping[str, Any] | None, *reasons: str) -> list[dict[str, Any]]:
    """앞 마무리가 지운 기록 중 이어받을 것 (그 파일은 이제 디스크에 없다)."""
    out: list[dict[str, Any]] = []
    for item in (previous or {}).get("deleted", ()):
        if isinstance(item, dict):
            entry = cast(dict[str, Any], item)
            if entry.get("reason") in reasons:
                out.append(dict(entry))
    return out


def _add_deleted(deleted: list[dict[str, Any]], entry: Mapping[str, Any]) -> None:
    clean = {k: v for k, v in entry.items() if v is not None}
    if all(d.get("file") != clean["file"] for d in deleted):
        deleted.append(clean)


def _delete(path: Path) -> bool:
    """지운다 (이미 없으면 지운 것). Windows 공유 위반은 잠깐 다시 해 본다. 지웠으면 True."""
    for attempt in range(_DELETE_TRIES):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            if attempt + 1 < _DELETE_TRIES:
                time.sleep(_DELETE_WAIT_S)
        except OSError:
            return False
    return False


class VideoWriterAlive(Exception):
    """녹화 스레드(작성자)가 아직 `video/`를 쥐고 있다. 마무리는 아무것도 하지 않았다."""


def _check_writer_gone(video: Path) -> None:
    """작성자 표시 파일(`.writer`)을 지워 본다. 녹화 스레드는 살아 있는 동안 이 파일을 삭제 공유
    없이 열어 두므로, 지울 수 없으면 작성자가 살아 있다 (선행 조건 위반 — 아무것도 하지 않는다).
    runner 프로세스가 끝나면 핸들도 닫힌다."""
    try:
        (video / WRITER_FILE).unlink()
    except FileNotFoundError:
        return
    except PermissionError as exc:
        raise VideoWriterAlive(f"녹화 스레드가 아직 {video}를 쓰고 있다") from exc


def _remove_stale_temps(video: Path) -> None:
    """앞 마무리·인코더 열기 시험이 남긴 임시 파일 (`.`으로 시작)."""
    for path in _names(video):
        if path.name.startswith("."):
            _delete(path)


def _names(video: Path) -> list[Path]:
    try:
        return list(video.iterdir())
    except OSError:
        return []


def _publish(video: Path, index: Mapping[str, Any]) -> None:
    """`index.json`을 같은 폴더 임시 파일 + replace로 공개한다."""
    text = canonical_dumps(dict(index)).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".index.", suffix=".tmp", dir=video)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(_DELETE_TRIES * 10):
            try:
                os.replace(tmp, video / INDEX_FILE)
                break
            except PermissionError:
                if attempt + 1 >= _DELETE_TRIES * 10:
                    raise
                time.sleep(0.005)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
