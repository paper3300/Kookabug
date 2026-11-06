"""에이전트용 실행 기록 읽기 (M5 계획 3.3·3.5·3.8): `run.failure`·`run.events`·`run.search`·
`run.artifact`·`run.diff`.

기존 기록 읽기(`run.index/children/step/file/compare/subscribe`)는 사람 화면용 원문이라 에이전트
연결은 판정 전에 거부한다(`agent_use_safe_api`, `tools.AGENT_RAW`). 여기 메서드는 누가 불러도
`agent_view`로 가린 결과를 준다 — 사람(UI)은 기존 메서드로 원문을 본다.

- 대표 인자(권한 판정)는 실행 ID(`run.search`는 "")
- 이미지는 긴 변 `max_side`(≤1568)·1 MiB 이하 PNG로 줄여 `.kookabug/cache/agent/<연결>/`에 쓰고
  이름만 준다(MCP shim이 읽어 싣고 지운다). `as_frame`이면 정지 화면 캐시에 넣고 `frame_id`
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, Final

from kookabug_core.record.compare import pick_baseline
from kookabug_core.record.index import video_view
from kookabug_daemon.agent_cache import MAX_SIDE, AgentCache, shrink_png
from kookabug_daemon.agent_view import IMAGE_SUFFIXES, TEXT_SUFFIXES, VIDEO_INDEX, AgentRun
from kookabug_daemon.documents import RUNS_NAME
from kookabug_daemon.frames import EditorFrame, FrameCache
from kookabug_daemon.methods import Call, MethodSpec, no_arg
from kookabug_daemon.methods.graph import request_int
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.targets import require_platform

__all__ = ["METHODS", "load_view"]

DEFAULT_EVENTS: Final = 200
MAX_EVENTS: Final = 500
DEFAULT_SEARCH_RUNS: Final = 20
DEFAULT_MATCHES: Final = 50
MAX_MATCHES: Final = 500
TEXT_LIMIT: Final = 256 * 1024
MATCH_TEXT: Final = 500


def _run_id(call: Call) -> str:
    return str(call.params["run_id"])


def load_view(call: Call, run_id: str) -> tuple[AgentRun, str]:
    """(에이전트용 보기, 실행 상태)."""
    where = call.daemon.run_manager.locate(run_id)
    return AgentRun.load(where.run_id, where.folder), where.state


# ---------------------------------------------------------------- run.failure


def _failure(call: Call) -> dict[str, Any]:
    run_id = _run_id(call)
    view, state = load_view(call, run_id)
    info = view.run_info()
    run_end = next((e for e in view.events if e.get("event") == "run.end"), None)
    end = view.event(run_end) if run_end is not None else {}
    failure_step = info.get("failure_step") or end.get("failure_step")
    chain: list[str] = []
    current = failure_step if isinstance(failure_step, str) else None
    while current is not None and current in view.steps:
        chain.append(current)
        current = view.steps[current].parent
    chain.reverse()
    failure: dict[str, Any] | None = None
    if chain:
        facts = view.steps[chain[-1]]
        failure = {
            "step": facts.step,
            "node": facts.node,
            "path": facts.path,
            "status": facts.status,
            "exit": facts.exit,
        }
        if facts.end is not None:
            shown = view.event(facts.end)
            for key in ("error", "message"):
                if key in shown:
                    failure[key] = shown[key]
    runs = call.daemon.root / RUNS_NAME
    found = pick_baseline(runs, view.run_json) if view.run_json else None
    video = video_view(view.folder)
    result: dict[str, Any] = {
        "run_id": view.run_id,
        "state": state,
        "classified": view.classified,
        "verdict": info.get("verdict", end.get("verdict")),
        "code": info.get("code", end.get("code")),
        "failure_step": failure_step if isinstance(failure_step, str) else None,
        "failure_path": info.get("failure_path", end.get("failure_path")),
        "failure": failure,
        "chain": [
            {"step": s, "node": view.steps[s].node, "status": view.steps[s].status} for s in chain
        ],
        "evidence": view.evidence_files(reversed(chain)),
        "video": None
        if video is None
        else {
            "status": video.get("status"),
            "segments": len(video.get("segments") or ()),
            "gaps": len(video.get("gaps") or ()),
        },
        "last_success": None if found is None else found[0],
    }
    reason = info.get("reason", end.get("reason"))
    if isinstance(reason, str):
        result["reason"] = reason
    return result


# ---------------------------------------------------------------- run.events


def _events(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    view, _ = load_view(call, _run_id(call))
    after = request_int(params.get("after_seq", 0))
    limit = min(request_int(params.get("limit", DEFAULT_EVENTS)), MAX_EVENTS)
    step = params.get("step")
    kinds = params.get("kinds")
    wanted = None if kinds is None else {str(k) for k in kinds}
    picked: list[dict[str, Any]] = []
    truncated = False
    for raw in view.events:
        seq = raw.get("seq")
        if not isinstance(seq, int) or seq <= after:
            continue
        if step is not None and raw.get("step") != step:
            continue
        if wanted is not None and raw.get("event") not in wanted:
            continue
        if len(picked) >= limit:
            truncated = True
            break
        picked.append(view.event(raw))
    next_seq = picked[-1]["seq"] if picked else after
    return {
        "events": picked,
        "next_seq": next_seq,
        "truncated": truncated,
        "classified": view.classified,
    }


# ---------------------------------------------------------------- run.search


def _search(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    query = str(params["query"]).casefold()
    limit = min(request_int(params.get("limit", DEFAULT_MATCHES)), MAX_MATCHES)
    given = params.get("runs")
    if given is None:
        listed = call.daemon.run_manager.list_runs(DEFAULT_SEARCH_RUNS)["runs"]
        run_ids = [str(r["run_id"]) for r in listed]
    else:
        run_ids = [str(r) for r in given]
    matches: list[dict[str, Any]] = []
    skipped: list[str] = []
    for run_id in run_ids:
        if len(matches) >= limit:
            break
        try:
            view, _ = load_view(call, run_id)
        except RequestFailed:
            skipped.append(run_id)
            continue
        if not view.classified:
            # 분류 없는 기록은 글자를 주지 않는다 (찾기도 건너뛴다)
            skipped.append(run_id)
            continue
        for raw in view.events:
            for text in view.text_of(raw):
                if query in text.casefold():
                    matches.append(
                        {
                            "run": view.run_id,
                            "seq": raw.get("seq"),
                            "kind": raw.get("event"),
                            "step": raw.get("step"),
                            "text": text[:MATCH_TEXT],
                        }
                    )
                    break
            if len(matches) >= limit:
                break
    return {"matches": matches, "skipped": skipped, "truncated": len(matches) >= limit}


# ---------------------------------------------------------------- run.artifact


def _safe_rel(given: str) -> str:
    """실행 폴더 기준 상대 경로 ('/'). 루트·상위·드라이브·역슬래시는 거부."""
    if "\\" in given or ":" in given or given.startswith("/"):
        raise InvalidParams(f"실행 폴더 기준 상대 경로('/')여야 한다: {given!r}", path=given)
    parts = PurePosixPath(given).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise InvalidParams(f"실행 폴더 기준 상대 경로('/')여야 한다: {given!r}", path=given)
    return "/".join(parts)


def _artifact(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    run_id = _run_id(call)
    rel = _safe_rel(str(params["path"]))
    view, _ = load_view(call, run_id)
    refused = view.refusal(rel)
    if refused is not None:
        raise refused
    path = view.folder / PurePosixPath(rel)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise RequestFailed("not_found", f"'{rel}'이(가) 없다", path=rel) from None
    except OSError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    suffix = PurePosixPath(rel).suffix.casefold()
    if rel == VIDEO_INDEX or suffix in TEXT_SUFFIXES:
        text = data[:TEXT_LIMIT].decode("utf-8", errors="replace")
        return {"kind": "text", "path": rel, "text": text, "truncated": len(data) > TEXT_LIMIT}
    if suffix not in IMAGE_SUFFIXES:
        raise RequestFailed("not_evidence", f"'{rel}'은(는) 이미지·글자 증거가 아니다", path=rel)
    require_platform()
    if params.get("as_frame") is True:
        return _as_frame(call, run_id, rel, data)
    max_side = min(request_int(params.get("max_side", MAX_SIDE)), MAX_SIDE)
    try:
        png, width, height = shrink_png(data, max(1, max_side))
    except ValueError as exc:
        text = f"'{rel}'을(를) 이미지로 읽을 수 없다: {exc}"
        raise RequestFailed("target_image_invalid", text, message=text) from exc
    name = AgentCache(call.daemon.root).put(call.connection, png)
    return {
        "kind": "image",
        "path": rel,
        "cache": name,
        "width": width,
        "height": height,
        "bytes": len(png),
    }


def _as_frame(call: Call, run_id: str, rel: str, data: bytes) -> dict[str, Any]:
    """실행 증거 이미지를 정지 화면으로 (`kb_target_create`의 `{run, file}` 출처). 편집기 캐시에는
    PNG를 쓰지 않는다. 만든 연결·출처(실행, 파일)를 프레임에 둔다 — 에이전트가 쓸 때 다시 본다."""
    import numpy as np

    from kookabug_platform.frames import decode_image

    try:
        pixels = np.array(decode_image(data), copy=True)
    except ValueError as exc:
        text = f"'{rel}'을(를) 이미지로 읽을 수 없다: {exc}"
        raise RequestFailed("target_image_invalid", text, message=text) from exc
    pixels.setflags(write=False)
    size = (int(pixels.shape[1]), int(pixels.shape[0]))
    frame_id = FrameCache.new_id()
    frame = EditorFrame(
        frame_id,
        pixels,
        size,
        96,
        f"{frame_id}.png",
        origin="run",
        owner=call.connection,
        source=(run_id, rel),
    )
    call.daemon.frames.add(frame)
    return {"kind": "frame", "path": rel, "frame_id": frame_id, "width": size[0], "height": size[1]}


def artifact_frame(call: Call, run_id: str, rel: str) -> EditorFrame:
    """`target.save`의 실행 증거 출처: 에이전트용 분류를 지난 이미지만 정지 화면으로."""
    rel = _safe_rel(rel)
    view, _ = load_view(call, run_id)
    refused = view.refusal(rel)
    if refused is not None:
        raise refused
    if PurePosixPath(rel).suffix.casefold() not in IMAGE_SUFFIXES:
        raise RequestFailed("not_evidence", f"'{rel}'은(는) 이미지 증거가 아니다", path=rel)
    require_platform()
    try:
        data = (view.folder / PurePosixPath(rel)).read_bytes()
    except FileNotFoundError:
        raise RequestFailed("not_found", f"'{rel}'이(가) 없다", path=rel) from None
    shown = _as_frame(call, run_id, rel, data)
    return call.daemon.frames.get(shown["frame_id"])


def recheck_source(call: Call, frame: EditorFrame) -> None:
    """실행 증거에서 연 정지 화면을 에이전트가 쓸 때 분류를 다시 본다 (그 사이 기록이 늘어
    비밀 조상이 드러났으면 거부)."""
    if frame.source is None:
        return
    run_id, rel = frame.source
    view, _ = load_view(call, run_id)
    refused = view.refusal(rel)
    if refused is not None:
        raise refused


# ---------------------------------------------------------------- run.diff


def _withhold_side(screen: dict[str, Any], key: str, view: AgentRun | None) -> None:
    rel = screen.get(key)
    if not isinstance(rel, str):
        return
    refused = RequestFailed("unclassified_run", "") if view is None else view.refusal(rel)
    if refused is None:
        return
    screen[key] = None
    screen.pop("diff_ratio", None)
    screen.pop("regions", None)
    screen["reason"] = "secret_step" if refused.code == "secret_step" else "agent_withheld"


def _diff(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    run_id = _run_id(call)
    baseline = params.get("baseline")
    records = call.daemon.run_manager.records
    result = records.compare(
        run_id, None if baseline is None else str(baseline), None, cache_result=False
    )
    view, _ = load_view(call, run_id)
    base_id = result.get("baseline")
    base_view = None
    if isinstance(base_id, str):
        base_view, _ = load_view(call, base_id)
    classified = view.classified and (base_view is None or base_view.classified)
    if not classified:
        return _safe_diff(result)
    screen = result.get("screen")
    if isinstance(screen, dict):
        shown = dict(screen)
        _withhold_side(shown, "file", view)
        _withhold_side(shown, "baseline_file", base_view)
        result["screen"] = shown
    result["classified"] = True
    return result


def _safe_diff(result: Mapping[str, Any]) -> dict[str, Any]:
    """한쪽이라도 분류 없는 기록이면 안전 필드만 (B2 검수 H4): 실행 ID·기준·노드별 시간(노드 ID와
    기간), 그래프는 같은지만, 화면은 스텝 ID만. 환경 값·파일 경로·글자는 주지 않는다."""
    out: dict[str, Any] = {
        "run_id": result.get("run_id"),
        "baseline": result.get("baseline"),
        "baseline_picked": result.get("baseline_picked"),
        "classified": False,
    }
    time = result.get("time")
    if isinstance(time, dict):
        out["time"] = time
    graph = result.get("graph")
    if isinstance(graph, dict) and "same" in graph:
        out["graph"] = {"same": graph["same"]}
    screen = result.get("screen")
    if isinstance(screen, dict):
        out["screen"] = {
            "step": screen.get("step"),
            "baseline_step": screen.get("baseline_step"),
            "file": None,
            "baseline_file": None,
            "reason": "unclassified_run",
        }
    return out


async def _failure_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_failure, call)


async def _events_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_events, call)


async def _search_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_search, call)


async def _artifact_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_artifact, call)


async def _diff_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_diff, call)


METHODS: Final = {
    "run.failure": MethodSpec(_failure_handler, _run_id),
    "run.events": MethodSpec(_events_handler, _run_id),
    "run.search": MethodSpec(_search_handler, no_arg),
    "run.artifact": MethodSpec(_artifact_handler, _run_id),
    "run.diff": MethodSpec(_diff_handler, _run_id),
}
