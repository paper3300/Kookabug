"""실행 색인 (M3 계획 2.7): `events.jsonl`을 한 번 훑어 기록 뷰어가 읽는 모양을 만든다.

- **스텝 트리**: 스텝마다 `step.start`·`attempt.end`·`step.end`를 합친 줄 하나. 부모는 호출
  스텝이고, 반복은 실행기에서 깊이를 더하지 않으므로(같은 프레임의 형제 스텝) 색인이 묶는다:
  반복 노드에 처음 도착한 스텝(반복 스텝)이 부모가 되고, 본문 스텝과 본문이 끝나 반복 노드로
  돌아온 스텝(되돌아옴)이 그 아래 회차(`iteration`)로 들어간다. 되돌아옴은 방금 끝난 회차의
  마지막 자식이다
- 반복 노드는 스냅샷 그래프의 노드 종류로 안다. 스냅샷이 없는 폴더(예전 실행)는 출구 `body`로 나간
  스텝을 반복 스텝으로 본다
- 반복 스텝의 필드는 그 스텝(첫 도착) 것 그대로다. 반복 전체는 `iterations`(회차·시작·경과·가장 나쁜
  결과·안쪽 호출을 포함한 스텝 수)로 본다
- **실패 사슬**: `run.end.failure_step`에서 색인 부모를 따라 루트까지. 입력 계산 실패도 그 스텝의
  `step.start`·`step.end`가 있으므로 사슬 끝이 된다. 경계 취소는 실패 스텝이 없다(빈 사슬)
- 노드별 통계(끝난 스텝만), 멈춤 구간, 영상(`video/index.json`, 없으면 `segments.jsonl`), 썸네일은
  파일 유무가 기준이다(이벤트에 없다)
- **늘리기**: `RunIndex.update`는 지난 위치부터 완전한 줄만 더 읽는다(진행 중 실행). 파일이 줄었으면
  처음부터 다시 만든다
- **캐시**: 끝난 실행의 색인은 `.kookabug/cache/runs/<run_id>.index.json`에 둔다. `events.jsonl`의
  크기·수정 시각이 같으면 다시 만들지 않는다 (`cached_index`)
- 줄마다 파일 위치를 기억해 `step_events`가 그 스텝 이벤트만 다시 읽는다

읽기는 실행 폴더를 고치지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, cast

from kookabug_core.canonical import loads_strict
from kookabug_core.record.artifacts import THUMBS_DIR
from kookabug_core.record.finalize import read_video
from kookabug_core.record.runfolder import EVENTS_FILE, SNAPSHOT_DIR
from kookabug_core.record.snapshot import GRAPH_PREFIX

__all__ = [
    "CACHE_DIR",
    "CACHE_FORMAT",
    "LOOP_TYPES",
    "MAX_PAGE",
    "RunIndex",
    "RunState",
    "StepRow",
    "cached_index",
    "index_cache_file",
    "node_titles",
    "thumbnails",
    "video_view",
    "write_cache",
]

CACHE_DIR: Final = (".kookabug", "cache", "runs")
"""워크스페이스 기준 색인 캐시 폴더 (`<run_id>.index.json`)."""
CACHE_FORMAT: Final = "kookabug.run-index-cache/1"
MAX_PAGE: Final = 500
LOOP_TYPES: Final = frozenset({"core.flow.repeat", "core.flow.while"})
LOOP_EXIT: Final = "body"
STEP_EVENTS: Final = frozenset({"step.start", "attempt.end", "step.end", "log"})
"""스텝 하나의 자세한 기록 (`run.step`)에 넣는 이벤트."""

type RunState = Literal["running", "ended"]

_RANK: Final = {"success": 0, "running": 1, "aborted": 2, "cancelled": 3, "fail": 4, "error": 5}
"""회차 결과: 가장 나쁜 것 (error > fail > cancelled > aborted > running > success)."""
_STATUS_OF: Final = {rank: status for status, rank in _RANK.items()}


def _ms(t: str) -> int:
    """`2026-10-29T06:02:11.104Z` → 유닉스 ms."""
    return int(datetime.fromisoformat(t).timestamp() * 1000 + 0.5)


def _step_number(step: str) -> int:
    try:
        return int(step[1:])
    except ValueError:
        return 0


def index_cache_file(root: Path, run_id: str) -> Path:
    return root.joinpath(*CACHE_DIR, f"{run_id}.index.json")


# ---------------------------------------------------------------- 스냅샷 그래프


class _Snapshot:
    """실행 폴더 `snapshot/`의 그래프 노드 (종류·제목·호출 대상). 읽지 못한 파일은 모름(None)."""

    def __init__(self, folder: Path) -> None:
        self.root = folder / SNAPSHOT_DIR
        self.present = self.root.is_dir()
        self._graphs: dict[str, dict[str, Any] | None] = {}

    def node(self, graph: str | None, node: str) -> Mapping[str, Any] | None:
        if graph is None or not self.present:
            return None
        if graph not in self._graphs:
            self._graphs[graph] = _read_nodes(self.root / graph)
        nodes = self._graphs[graph]
        found = None if nodes is None else nodes.get(node)
        return cast(Mapping[str, Any], found) if isinstance(found, dict) else None

    def callee(self, graph: str | None, node: str) -> str | None:
        found = self.node(graph, node)
        config = None if found is None else found.get("config")
        target = config.get("graph") if isinstance(config, dict) else None
        return target if isinstance(target, str) and target else None

    def is_loop(self, graph: str | None, node: str) -> bool | None:
        """반복 노드인가 (스냅샷에 그 노드가 없으면 None)."""
        found = self.node(graph, node)
        return None if found is None else found.get("type") in LOOP_TYPES


def _read_nodes(path: Path) -> dict[str, Any] | None:
    try:
        data = loads_strict(path.read_bytes().decode("utf-8"))
    except OSError, UnicodeDecodeError, ValueError:
        return None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    return cast(dict[str, Any], nodes) if isinstance(nodes, dict) else None


def node_titles(folder: Path, graph: str, path: Iterable[str]) -> list[str]:
    """호출 경로의 노드 제목 (스냅샷에서. 제목·스냅샷이 없으면 노드 ID)."""
    snapshot = _Snapshot(folder)
    titles: list[str] = []
    current: str | None = graph
    for node_id in path:
        found = snapshot.node(current, node_id)
        title = None if found is None else found.get("title")
        titles.append(title if isinstance(title, str) and title else node_id)
        current = snapshot.callee(current, node_id)
    return titles


# ---------------------------------------------------------------- 스텝 줄


@dataclass(slots=True)
class StepRow:
    step: str
    parent: str | None
    """색인 부모: 호출 스텝, 또는 반복 스텝."""
    frame: str | None
    """이벤트의 `parent` (그 스텝을 부른 호출 스텝, 테스트 프레임은 None)."""
    node: str
    path: list[str]
    t_start: str
    iteration: int | None = None
    """색인 부모가 반복 스텝일 때 그 회차."""
    attempt: int = 1
    status: str | None = None
    """`step.end`의 status (끝나지 않았으면 None)."""
    exit: str | None = None
    t_end: str | None = None
    duration_ms: int | None = None
    active_duration_ms: int | None = None
    artifacts: list[str] | None = None
    omitted: list[Any] | None = None
    evidence: bool = False
    retried: bool = False
    message: str | None = None
    calls: str | None = None
    """서브그래프 호출이면 부른 그래프 (`step.end.graph`에서 스냅샷 접두를 뗀 것)."""
    loop: bool = False
    """반복 스텝 (반복 노드에 처음 도착한 스텝, 회차를 가진다)."""
    reentry: bool = False
    """반복 노드로 되돌아온 스텝."""
    children: int = 0
    offsets: list[int] = field(default_factory=list[int])
    """이 스텝의 `step.start`·`attempt.end`·`step.end`·`log` 줄 시작 위치."""

    def to_list(self) -> list[Any]:
        """캐시용 (`children`은 복원할 때 다시 센다)."""
        return [getattr(self, name) for name in _ROW_FIELDS]

    @classmethod
    def from_list(cls, values: list[Any]) -> StepRow:
        return cls(**dict(zip(_ROW_FIELDS, values, strict=True)))


_ROW_FIELDS: Final = (
    "step",
    "parent",
    "frame",
    "node",
    "path",
    "t_start",
    "iteration",
    "attempt",
    "status",
    "exit",
    "t_end",
    "duration_ms",
    "active_duration_ms",
    "artifacts",
    "omitted",
    "evidence",
    "retried",
    "message",
    "calls",
    "loop",
    "reentry",
    "offsets",
)


@dataclass(slots=True)
class _Iter:
    """반복 스텝의 회차 하나 (안쪽 호출·반복 포함 스텝을 센다)."""

    iteration: int
    t_start: str
    start_ms: int
    steps: int = 0
    open: int = 0
    worst: int = 0
    end_ms: int | None = None


@dataclass(slots=True)
class _Loop:
    node: str
    step: str
    iteration: int = 0


# ---------------------------------------------------------------- 색인


class RunIndex:
    """실행 하나의 색인. `update`로 파일을 더 읽어 늘린다 (스레드 안전하지 않다: 부르는 쪽이
    잠근다)."""

    def __init__(self, folder: str | os.PathLike[str]) -> None:
        self.folder = Path(folder)
        self._snapshot: _Snapshot | None = None
        self._clear()

    def _clear(self) -> None:
        self.position = 0
        """완전한 줄까지 읽은 바이트 위치."""
        self.size = 0
        self.mtime_ns = 0
        self.last_seq = 0
        self.run_id: str | None = None
        self.graph: str | None = None
        self.run_end: dict[str, Any] | None = None
        self.rows: dict[str, StepRow] = {}
        self.pauses: list[dict[str, Any]] = []
        self._children: dict[str | None, list[str]] = {}
        self._iter_children: dict[tuple[str, int], list[str]] = {}
        self._iters: dict[str, dict[int, _Iter]] = {}
        self._loops: dict[str | None, list[_Loop]] = {}
        self._frame_graphs: dict[str | None, str] = {}

    # ------------------------------------------------------------ 읽기

    def update(self) -> RunIndex:
        """지난 위치부터 완전한 줄을 더 읽는다. 파일이 줄었으면 처음부터 다시 만든다."""
        path = self.folder / EVENTS_FILE
        try:
            with path.open("rb") as f:
                stat = os.fstat(f.fileno())
                if stat.st_size < self.position:
                    self._clear()
                f.seek(self.position)
                chunk = f.read()
        except FileNotFoundError:
            return self
        self.size, self.mtime_ns = stat.st_size, stat.st_mtime_ns
        end = chunk.rfind(b"\n") + 1
        offset = self.position
        for raw in chunk[:end].split(b"\n")[:-1]:
            line_at = offset
            offset += len(raw) + 1
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict):
                self.feed(cast(dict[str, Any], event), line_at)
        self.position += end
        return self

    @property
    def snapshot(self) -> _Snapshot:
        if self._snapshot is None:
            self._snapshot = _Snapshot(self.folder)
        return self._snapshot

    def feed(self, event: Mapping[str, Any], offset: int = -1) -> None:
        """이벤트 하나를 더한다 (`seq` 순서대로)."""
        seq = event.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            self.last_seq = max(self.last_seq, seq)
        kind = event.get("event")
        step = event.get("step")
        if kind == "step.start" and isinstance(step, str):
            self._start(event, step, offset)
        elif kind in ("step.end", "attempt.end", "log") and isinstance(step, str):
            row = self.rows.get(step)
            if row is None:
                return
            if offset >= 0:
                row.offsets.append(offset)
            if kind == "step.end":
                self._end(row, event)
            elif kind == "attempt.end":
                attempt = event.get("attempt")
                if isinstance(attempt, int):
                    row.attempt = max(row.attempt, attempt + 1)
        elif kind == "run.start":
            run = event.get("run")
            graph = event.get("graph")
            self.run_id = run if isinstance(run, str) else self.run_id
            if isinstance(graph, str):
                self.graph = graph
        elif kind == "run.end":
            self.run_end = dict(event)
            run = event.get("run")
            if self.run_id is None and isinstance(run, str):
                self.run_id = run
        elif kind == "debug.pause":
            span: dict[str, Any] = {
                "step": step if isinstance(step, str) else None,
                "t_start": event.get("t"),
                "t_end": None,
            }
            for key in ("reason", "where"):
                if isinstance(event.get(key), str):
                    span[key] = event[key]
            self.pauses.append(span)
        elif kind == "debug.resume":
            open_span = next((s for s in reversed(self.pauses) if s["t_end"] is None), None)
            if open_span is not None:
                open_span["t_end"] = event.get("t")
                if isinstance(event.get("mode"), str):
                    open_span["mode"] = event["mode"]

    def _start(self, event: Mapping[str, Any], step: str, offset: int) -> None:
        if step in self.rows:
            return
        frame = event.get("parent")
        frame = frame if isinstance(frame, str) else None
        node = str(event.get("node", ""))
        path = event.get("path")
        row = StepRow(
            step,
            frame,
            frame,
            node,
            [str(p) for p in path] if isinstance(path, list) else [node],
            str(event.get("t", "")),
        )
        if offset >= 0:
            row.offsets.append(offset)
        stack = self._loops.get(frame)
        if stack:
            hit = next((i for i in range(len(stack) - 1, -1, -1) if stack[i].node == node), None)
            if hit is not None:
                # 반복 노드로 되돌아옴: 방금 끝난 회차의 마지막 자식 (안쪽 반복은 이미 끝났다)
                del stack[hit + 1 :]
                loop = stack[hit]
                row.parent, row.iteration, row.reentry = loop.step, loop.iteration, True
            else:
                loop = stack[-1]
                own = event.get("iteration")
                row.parent = loop.step
                row.iteration = own if isinstance(own, int) else loop.iteration
        self.rows[step] = row
        self._link(row)

    def _link(self, row: StepRow) -> None:
        """부모의 자식 목록과 감싼 반복 회차들에 더한다 (`_start`·캐시 복원)."""
        parent = row.parent
        self._children.setdefault(parent, []).append(row.step)
        if parent is not None:
            parent_row = self.rows.get(parent)
            if parent_row is not None:
                parent_row.children += 1
            if row.iteration is not None and parent_row is not None and parent_row.loop:
                self._iter_children.setdefault((parent, row.iteration), []).append(row.step)
        start_ms = _safe_ms(row.t_start)
        for loop_step, iteration in self._enclosing(row):
            iters = self._iters.setdefault(loop_step, {})
            item = iters.get(iteration)
            if item is None:
                item = iters[iteration] = _Iter(iteration, row.t_start, start_ms)
            elif start_ms < item.start_ms:
                item.t_start, item.start_ms = row.t_start, start_ms
            item.steps += 1
            item.open += 1

    def _enclosing(self, row: StepRow) -> list[tuple[str, int]]:
        """그 스텝을 감싼 (반복 스텝, 회차)들 (호출을 넘어 바깥까지)."""
        found: list[tuple[str, int]] = []
        child = row
        while child.parent is not None:
            parent = self.rows.get(child.parent)
            if parent is None:
                break
            if parent.loop and child.iteration is not None:
                found.append((parent.step, child.iteration))
            child = parent
        return found

    def _end(self, row: StepRow, event: Mapping[str, Any]) -> None:
        if row.status is not None:
            return
        row.status = str(event.get("status", "error"))
        exit_ = event.get("exit")
        row.exit = exit_ if isinstance(exit_, str) else None
        row.t_end = str(event.get("t", ""))
        for name in ("duration_ms", "active_duration_ms"):
            value = event.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(row, name, value)
        attempt = event.get("attempt")
        if isinstance(attempt, int):
            row.attempt = attempt
        artifacts = event.get("artifacts")
        if isinstance(artifacts, list):
            row.artifacts = [str(a) for a in cast(list[Any], artifacts)]
        omitted = event.get("omitted")
        if isinstance(omitted, list):
            row.omitted = list(cast(list[Any], omitted))
        row.evidence = isinstance(event.get("evidence"), dict)
        row.retried = event.get("retried") is True
        message = event.get("message")
        row.message = message if isinstance(message, str) else None
        graph = event.get("graph")
        if isinstance(graph, str) and graph:
            row.calls = graph.removeprefix(GRAPH_PREFIX)
        self._close(row)
        self._track_loop(row)
        if row.calls is not None or row.step in self._loops:
            # 호출 스텝이 끝났다: 그 프레임의 반복 상태는 더 쓰지 않는다
            self._loops.pop(row.step, None)

    def _close(self, row: StepRow) -> None:
        """감싼 회차들의 끝 시각·결과를 고친다 (`_end`·캐시 복원)."""
        end_ms = _safe_ms(row.t_end or "")
        rank = _RANK.get(row.status or "error", _RANK["error"])
        for loop_step, iteration in self._enclosing(row):
            item = self._iters[loop_step][iteration]
            item.open -= 1
            item.worst = max(item.worst, rank)
            item.end_ms = end_ms if item.end_ms is None else max(item.end_ms, end_ms)

    def _track_loop(self, row: StepRow) -> None:
        stack = self._loops.setdefault(row.frame, [])
        if row.reentry:
            loop = next((x for x in stack if x.step == row.parent), None)
            if loop is None:
                return
            if row.exit == LOOP_EXIT and row.status == "success":
                loop.iteration += 1
            else:
                del stack[stack.index(loop) :]
            return
        if row.exit != LOOP_EXIT or row.status != "success":
            return
        known = self.snapshot.is_loop(self.graph_of(row), row.node)
        if known is False:
            return
        row.loop = True
        stack.append(_Loop(row.node, row.step))

    # ------------------------------------------------------------ 그래프

    def graph_of(self, row: StepRow) -> str:
        """스텝 노드가 든 그래프 (워크스페이스 기준. 모르면 빈 문자열)."""
        return self._frame_graph(row.frame)

    def _frame_graph(self, frame: str | None) -> str:
        found = self._frame_graphs.get(frame)
        if found is not None:
            return found
        if frame is None:
            graph = self.graph or ""
        else:
            call = self.rows.get(frame)
            if call is None:
                return ""
            graph = call.calls or self.snapshot.callee(self._frame_graph(call.frame), call.node)
            graph = graph or ""
        if graph:
            self._frame_graphs[frame] = graph
        return graph

    def callee_of(self, row: StepRow) -> str | None:
        """호출 스텝이면 부른 그래프 (`step.end.graph`, 끝나지 않았으면 스냅샷에서), 아니면 None."""
        if row.calls is not None:
            return row.calls
        return self.snapshot.callee(self.graph_of(row), row.node)

    # ------------------------------------------------------------ 결과

    def node_json(self, row: StepRow, state: RunState, thumbs: frozenset[str]) -> dict[str, Any]:
        """색인의 스텝 하나 (`run-index.schema.json` `StepNode`)."""
        status = row.status or ("running" if state == "running" else "aborted")
        out: dict[str, Any] = {
            "step": row.step,
            "parent": row.parent,
            "node": row.node,
            "graph": self.graph_of(row),
            "path": row.path,
            "attempt": row.attempt,
            "status": status,
            "exit": row.exit,
            "t_start": row.t_start,
            "t_end": row.t_end,
            "duration_ms": row.duration_ms,
            "children": row.children,
            "evidence": row.evidence,
            "thumbnail": row.step in thumbs,
        }
        if row.iteration is not None:
            out["iteration"] = row.iteration
        if row.active_duration_ms is not None:
            out["active_duration_ms"] = row.active_duration_ms
        if row.artifacts is not None:
            out["artifacts"] = row.artifacts
        if row.omitted is not None:
            out["omitted"] = row.omitted
        if row.retried:
            out["retried"] = True
        if row.message is not None:
            out["message"] = row.message
        calls = self.callee_of(row)
        if calls is not None:
            out["calls"] = calls
        if row.loop:
            out["iterations"] = self.iterations(row.step, state)
        return out

    def iterations(self, loop_step: str, state: RunState = "ended") -> list[dict[str, Any]]:
        """반복 스텝의 회차 요약 (`IterationSummary`, 회차 순). 끝나지 않은 회차는 경과가 None."""
        found: list[dict[str, Any]] = []
        for iteration in sorted(self._iters.get(loop_step, {})):
            item = self._iters[loop_step][iteration]
            worst = item.worst
            if item.open > 0:
                worst = max(worst, _RANK["running" if state == "running" else "aborted"])
            duration = None
            if item.open == 0 and item.end_ms is not None:
                duration = max(0, item.end_ms - item.start_ms)
            found.append(
                {
                    "iteration": item.iteration,
                    "t_start": item.t_start,
                    "duration_ms": duration,
                    "status": _STATUS_OF[worst],
                    "steps": item.steps,
                }
            )
        return found

    def iteration_steps(self, loop_step: str, iteration: int) -> list[StepRow]:
        """반복 스텝의 한 회차 바로 아래 스텝 (본문 스텝과 되돌아옴, step 순)."""
        return [self.rows[s] for s in self._iter_children.get((loop_step, iteration), ())]

    def failure_chain(self) -> list[str]:
        """루트부터 `run.end.failure_step`까지 (실패 스텝이 색인에 없으면 빈 목록)."""
        failure = (self.run_end or {}).get("failure_step")
        if not isinstance(failure, str) or failure not in self.rows:
            return []
        chain: list[str] = []
        current: str | None = failure
        while current is not None and current in self.rows:
            chain.append(current)
            current = self.rows[current].parent
        return chain[::-1]

    def stats(self) -> list[dict[str, Any]]:
        """노드별 통계 (그래프·노드마다, 끝난 스텝만)."""
        groups: dict[tuple[str, str], list[StepRow]] = {}
        for row in self.rows.values():
            if row.status is not None:
                groups.setdefault((self.graph_of(row), row.node), []).append(row)
        found: list[dict[str, Any]] = []
        for (graph, node), rows in sorted(groups.items()):
            durations = sorted(r.duration_ms or 0 for r in rows)
            failures = [r.step for r in rows if r.status in ("fail", "error")]
            rank = max(1, math.ceil(0.95 * len(durations)))
            found.append(
                {
                    "graph": graph,
                    "node": node,
                    "count": len(rows),
                    "success": sum(r.status == "success" for r in rows),
                    "fail": sum(r.status == "fail" for r in rows),
                    "error": sum(r.status == "error" for r in rows),
                    "mean_ms": sum(durations) / len(durations),
                    "p95_ms": float(durations[rank - 1]),
                    "max_ms": durations[-1],
                    "last_failure_step": failures[-1] if failures else None,
                }
            )
        return found

    def result(
        self,
        *,
        run_dir: str,
        state: RunState,
        run_json: Mapping[str, Any] | None,
        video: Mapping[str, Any] | None,
        thumbs: frozenset[str],
    ) -> dict[str, Any]:
        """`run.index` 결과 (`run-index.schema.json`)."""
        chain = self.failure_chain()
        shown = set(self._children.get(None, ())) | set(chain)
        steps = [
            self.node_json(self.rows[s], state, thumbs)
            for s in sorted(shown, key=_step_number)
            if s in self.rows
        ]
        run_id = self.run_id or _run_id_from(self.folder)
        return {
            "run_id": run_id,
            "run_dir": run_dir,
            "state": state,
            "last_seq": self.last_seq,
            "run": None if run_json is None else dict(run_json),
            "steps": steps,
            "failure_chain": chain,
            "stats": self.stats(),
            "pauses": [dict(p) for p in self.pauses],
            "video": None if video is None else dict(video),
        }

    def children(
        self,
        parent: str,
        iteration: int | None,
        offset: int,
        limit: int,
        *,
        state: RunState,
        thumbs: frozenset[str],
    ) -> tuple[int, list[dict[str, Any]]]:
        """(그 부모·회차 아래 스텝 수, `offset`부터 `limit`개). 부모가 색인에 없으면 KeyError."""
        if parent not in self.rows:
            raise KeyError(parent)
        if iteration is not None and self.rows[parent].loop:
            items = self._iter_children.get((parent, iteration), [])
        else:
            items = self._children.get(parent, [])
        page = items[offset : offset + min(limit, MAX_PAGE)]
        return len(items), [self.node_json(self.rows[s], state, thumbs) for s in page]

    def step_events(self, step: str) -> list[dict[str, Any]]:
        """그 스텝의 `step.start`·`attempt.end`·`step.end`·`log` 이벤트 (seq 순). 색인에 없는
        스텝이면 KeyError."""
        row = self.rows[step]
        found: list[dict[str, Any]] = []
        try:
            with (self.folder / EVENTS_FILE).open("rb") as f:
                for offset in row.offsets:
                    f.seek(offset)
                    try:
                        event = json.loads(f.readline())
                    except ValueError:
                        continue
                    if (
                        isinstance(event, dict)
                        and event.get("step") == step
                        and event.get("event") in STEP_EVENTS
                    ):
                        found.append(cast(dict[str, Any], event))
        except FileNotFoundError:
            return []
        return sorted(found, key=lambda e: e.get("seq", 0))

    # ------------------------------------------------------------ 캐시

    def to_cache(self) -> dict[str, Any]:
        return {
            "format": CACHE_FORMAT,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "position": self.position,
            "last_seq": self.last_seq,
            "run_id": self.run_id,
            "graph": self.graph,
            "run_end": self.run_end,
            "pauses": self.pauses,
            "rows": [row.to_list() for row in self.rows.values()],
        }

    @classmethod
    def from_cache(cls, folder: Path, data: Mapping[str, Any]) -> RunIndex:
        """캐시에서 되살린다 (형식이 다르면 ValueError)."""
        if data.get("format") != CACHE_FORMAT:
            raise ValueError("색인 캐시 형식이 다르다")
        index = cls(folder)
        index.size = int(data["size"])
        index.mtime_ns = int(data["mtime_ns"])
        index.position = int(data["position"])
        index.last_seq = int(data["last_seq"])
        index.run_id = data.get("run_id")
        index.graph = data.get("graph")
        run_end = data.get("run_end")
        index.run_end = dict(run_end) if isinstance(run_end, dict) else None
        index.pauses = [dict(p) for p in data.get("pauses", [])]
        for values in data["rows"]:
            row = StepRow.from_list(list(values))
            index.rows[row.step] = row
            index._link(row)
            if row.status is not None:
                index._close(row)
        return index


def _safe_ms(t: str) -> int:
    try:
        return _ms(t)
    except ValueError:
        return 0


def _run_id_from(folder: Path) -> str:
    return folder.name.rsplit("_", 1)[-1]


# ---------------------------------------------------------------- 폴더 정보


def thumbnails(folder: Path) -> frozenset[str]:
    """썸네일이 있는 스텝 (`thumbs/<스텝>.jpg`, 파일 유무가 기준)."""
    try:
        with os.scandir(folder / THUMBS_DIR) as entries:
            return frozenset(
                e.name[:-4] for e in entries if e.name.endswith(".jpg") and e.is_file()
            )
    except OSError:
        return frozenset()


def video_view(folder: Path) -> dict[str, Any] | None:
    """뷰어가 쓰는 영상 정보 (`VideoView`): `video/index.json`, 없으면 `segments.jsonl`. 영상 폴더가
    없으면 None."""
    index, finalized = read_video(folder)
    if index is None:
        return None
    view: dict[str, Any] = {
        "finalized": finalized,
        "status": index["status"],
        "segments": list(index.get("segments", [])),
        "gaps": list(index.get("gaps", [])),
    }
    if "reason" in index:
        view["reason"] = index["reason"]
    return view


def cached_index(folder: Path, cache: Path | None) -> RunIndex:
    """끝난 실행의 색인: `cache`가 `events.jsonl`의 크기·수정 시각과 맞으면 그것, 아니면 새로 만들고
    `cache`에 쓴다 (쓰기 실패는 무시한다 — 다음에 다시 만든다)."""
    try:
        stat = (folder / EVENTS_FILE).stat()
    except OSError:
        return RunIndex(folder).update()
    if cache is not None:
        try:
            data = json.loads(cache.read_bytes())
            if (
                isinstance(data, dict)
                and data.get("size") == stat.st_size
                and data.get("mtime_ns") == stat.st_mtime_ns
            ):
                return RunIndex.from_cache(folder, cast(dict[str, Any], data))
        except OSError, ValueError, KeyError, TypeError:
            pass
    index = RunIndex(folder).update()
    if cache is not None:
        write_cache(index, cache)
    return index


def write_cache(index: RunIndex, cache: Path) -> bool:
    """색인을 캐시 파일에 원자적으로 쓴다 (같은 폴더 임시 파일 + replace)."""
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=cache.parent, prefix=f".{cache.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(index.to_cache(), f, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp, cache)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True
