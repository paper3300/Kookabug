"""지난 성공과 비교 (M3 계획 2.8): `run.compare` 결과(`run-index.schema.json` `CompareResult`).

- **기준 실행** (사용자 결정 U10): 같은 테스트 그래프·같은 프로필, 판정 `pass`, 디버거 개입 아님,
  이 실행보다 먼저 시작한 끝난 실행 중 가장 최근(`pick_baseline`). 폴더 이름이 `<시작 초>_<그래프
  줄기>_<run_id>`이므로 줄기가 다른 폴더는 `run.json`을 읽지 않고 건너뛴다
- **그래프**: 스냅샷 폴더(`snapshot/`)의 파일마다 sha256을 내고, 상대 경로(`/` 구분)로 정렬한
  `경로\\0파일 sha256\\n` 줄들의 sha256이 스냅샷 해시다. 파일 해시는 크기·수정 시각과 함께
  `.kookabug/cache/runs/<run_id>.snapshot.json`에 두고 같으면 다시 읽지 않는다. 한쪽이라도 스냅샷
  폴더가 없으면(예전 실행) 그래프 비교를 뺀다
- **환경**: `run.json`의 `observed`·`conditions`(프로필·플랫폼·설정)·`packages`·`plugins`·
  `game_build`. 같은 값은 넣지 않는다. 비밀값 설정은 값 대신 `{"secret": true}`
- **시간**: 노드별 평균 경과(멈춤을 뺀 경과). 이 실행의 반복 스텝마다 회차 경과에서 변곡을 찾고
  (`inflection`) 그 반복 본문에서 가장 많이 늦어진 노드의 전·후 평균을 함께 준다. 이 실행이 디버거로
  멈췄던 실행이면 변곡을 내지 않는다(회차 경과가 벽시계라)
- **화면**: 실패 스텝(또는 고른 스텝)의 마지막 증거(`evidence.last` → `_fail`/`_error` →
  썸네일)와 기준 실행에서 같은 호출 경로·같은 노드 스텝의 썸네일(남아 있는 마지막 회차). 호출
  스텝이면 그 증거를 캡처한 안쪽 스텝의 경로로 찾는다. 픽셀 비교는 부르는 쪽이 넘긴
  `differ`(daemon은 플랫폼의 OpenCV 함수)가 한다 — 코어는 OpenCV에 기대지 않는다
- **두 단계**: `prepare_compare`는 색인이 필요한 부분(부르는 쪽이 색인을 잠근 채),
  `finish_compare`는 스냅샷 해시·이미지 읽기·화면 차이(잠금 밖)
- 결과는 `.kookabug/cache/runs/<run_id>.compare.json`에 하나 둔다(색인 캐시 옆). 두 실행의
  `events.jsonl` 크기·수정 시각과 기준·스텝이 같으면 다시 계산하지 않는다

읽기만 하고 실행 폴더를 고치지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal, cast

from kookabug_core.record.artifacts import STEPS_DIR, thumbnail_path
from kookabug_core.record.index import CACHE_DIR, RunIndex, StepRow, thumbnails
from kookabug_core.record.runfolder import (
    EVENTS_FILE,
    RUN_JSON_FILE,
    SNAPSHOT_DIR,
    graph_stem,
    read_run_json,
    run_id_of_folder,
)

__all__ = [
    "NO_BASELINE",
    "Picked",
    "PreparedCompare",
    "RunSide",
    "ScreenDiffer",
    "compare_cache_file",
    "compare_runs",
    "debug_intervened",
    "env_diff",
    "finish_compare",
    "inflection",
    "loop_inflections",
    "node_means",
    "pick_baseline",
    "prepare_compare",
    "read_compare_cache",
    "snapshot_cache_file",
    "snapshot_digest",
    "write_compare_cache",
]

NO_BASELINE: Final = "비교할 성공 실행 없음"
SNAPSHOT_CACHE_FORMAT: Final = "kookabug.snapshot-hash-cache/1"
COMPARE_CACHE_FORMAT: Final = "kookabug.compare-cache/1"
INFLECTION_FACTOR: Final = 2.0
"""앞 절반 중앙값의 몇 배를 넘으면 늦어진 회차인가."""
INFLECTION_RUN: Final = 3
"""늦어진 회차가 몇 번 이어져야 변곡으로 보나 (남은 회차가 적으면 남은 전부, 최소 2)."""
INFLECTION_MIN_ITERATIONS: Final = 4
MAX_INFLECTIONS: Final = 20
"""결과에 넣는 변곡 수 상한 (안쪽 반복이 바깥 회차마다 새 반복 스텝을 만든다)."""

type ScreenDiffer = Callable[[bytes, bytes], tuple[float, list[list[int]]]]
"""(이 실행 이미지, 기준 이미지) → (차이 비율, 차이 영역 상자). 읽을 수 없으면 ValueError."""
type Picked = Literal["auto", "user"]


@dataclass(frozen=True, slots=True)
class RunSide:
    """비교하는 실행 한쪽: 폴더·`run.json`·색인 (부르는 쪽이 색인을 잠근 채 넘긴다)."""

    run_id: str
    folder: Path
    run_json: Mapping[str, Any]
    index: RunIndex


# ---------------------------------------------------------------- 기준 실행


def _profile(data: Mapping[str, Any]) -> Any:
    conditions = data.get("conditions")
    return conditions.get("profile") if isinstance(conditions, dict) else None


def _is_baseline_for(candidate: Mapping[str, Any], run: Mapping[str, Any]) -> bool:
    started = run.get("started_at")
    other = candidate.get("started_at")
    return (
        candidate.get("status") == "finished"
        and candidate.get("verdict") == "pass"
        and candidate.get("debug_intervened") is not True
        and candidate.get("graph") == run.get("graph")
        and _profile(candidate) == _profile(run)
        and isinstance(other, str)
        and isinstance(started, str)
        and other < started
    )


def pick_baseline(runs_dir: Path, run_json: Mapping[str, Any]) -> tuple[str, Path] | None:
    """기준 실행 (run_id, 폴더). 없으면 None.

    폴더는 실행 시작(`run.start`) 전에 만들어지므로 폴더 이름의 초 ≤ `started_at`이다. 그래서 초가
    이 실행보다 늦은 폴더는 보지 않고, 찾은 뒤에는 그 시작보다 `_FOLDER_SLACK` 넘게 앞선 폴더에서
    멈춘다 (겹쳐 돈 CLI 실행처럼 폴더를 먼저 만들고 늦게 시작한 실행을 놓치지 않게)."""
    graph = run_json.get("graph")
    started = run_json.get("started_at")
    if not isinstance(graph, str) or not isinstance(started, str):
        return None
    stem = graph_stem(graph)
    limit = _folder_second(started)
    try:
        names = sorted((p.name for p in runs_dir.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return None
    best: tuple[str, str, Path] | None = None
    stop: str | None = None
    for name in names:
        second, _, rest = name.partition("_")
        if second > limit:
            continue
        if stop is not None and second < stop:
            break
        run_id = run_id_of_folder(name)
        if run_id is None or rest.rpartition("_")[0] != stem:
            continue
        folder = runs_dir / name
        candidate = read_run_json(folder / RUN_JSON_FILE)
        if candidate is None or not _is_baseline_for(candidate, run_json):
            continue
        at = str(candidate["started_at"])
        if best is None or at > best[0]:
            best = (at, run_id, folder)
            stop = _folder_second(at, slack=_FOLDER_SLACK)
    return None if best is None else (best[1], best[2])


_FOLDER_SLACK: Final = timedelta(minutes=1)


def _folder_second(t: str, *, slack: timedelta = timedelta(0)) -> str:
    """`started_at` → 폴더 이름의 초 모양 (`2026-11-02T01-00-00`), `slack`만큼 앞당겨서."""
    try:
        at = datetime.fromisoformat(t) - slack
    except ValueError:
        return t[:19].replace(":", "-")
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%S")


# ---------------------------------------------------------------- 스냅샷 해시


def _snapshot_files(root: Path) -> Iterator[tuple[str, os.stat_result]]:
    for current, dirs, files in os.walk(root):
        dirs.sort()
        for name in files:
            path = Path(current, name)
            try:
                yield path.relative_to(root).as_posix(), path.stat()
            except OSError:
                continue


def _file_sha(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def snapshot_digest(folder: Path, cache: Path | None = None) -> tuple[str, dict[str, str]] | None:
    """(스냅샷 해시, 경로 → 파일 sha256). 스냅샷 폴더가 없으면 None.

    `cache`가 있으면 파일마다 크기·수정 시각이 같을 때 그 해시를 다시 쓰고, 바뀐 것이 있으면
    고쳐 쓴다 (쓰기 실패는 무시)."""
    root = folder / SNAPSHOT_DIR
    if not root.is_dir():
        return None
    known: dict[str, Any] = {}
    if cache is not None:
        try:
            data = json.loads(cache.read_bytes())
            if isinstance(data, dict) and data.get("format") == SNAPSHOT_CACHE_FORMAT:
                known = cast(dict[str, Any], data.get("files") or {})
        except OSError, ValueError:
            known = {}
    files: dict[str, str] = {}
    entries: dict[str, list[Any]] = {}
    changed = False
    for rel, stat in sorted(_snapshot_files(root)):
        hit = known.get(rel)
        if (
            isinstance(hit, list)
            and len(cast(list[Any], hit)) == 3
            and hit[0] == stat.st_size
            and hit[1] == stat.st_mtime_ns
        ):
            sha = str(hit[2])
        else:
            found = _file_sha(root / rel)
            if found is None:
                continue
            sha, changed = found, True
        files[rel] = sha
        entries[rel] = [stat.st_size, stat.st_mtime_ns, sha]
    if set(known) != set(entries):
        changed = True
    digest = hashlib.sha256()
    for rel, sha in files.items():
        digest.update(f"{rel}\0{sha}\n".encode())
    if cache is not None and changed:
        _write_json(cache, {"format": SNAPSHOT_CACHE_FORMAT, "files": entries})
    return digest.hexdigest(), files


def _graph_diff(
    run: tuple[str, dict[str, str]], base: tuple[str, dict[str, str]]
) -> dict[str, Any]:
    here, there = run[1], base[1]
    changed: list[dict[str, str]] = []
    for path in sorted(set(here) | set(there)):
        if path not in there:
            changed.append({"path": path, "change": "added"})
        elif path not in here:
            changed.append({"path": path, "change": "removed"})
        elif here[path] != there[path]:
            changed.append({"path": path, "change": "modified"})
    return {
        "hash": run[0],
        "baseline_hash": base[0],
        "same": run[0] == base[0],
        "changed": changed,
    }


# ---------------------------------------------------------------- 환경


def _setting_value(use: Any) -> Any:
    if not isinstance(use, dict):
        return use
    use = cast(dict[str, Any], use)
    return {"secret": True} if use.get("secret") is True else use.get("value")


def _env_values(data: Mapping[str, Any]) -> dict[str, Any]:
    """비교할 환경 값 (점 경로 → 값)."""
    out: dict[str, Any] = {}
    observed = data.get("observed")
    if isinstance(observed, dict):
        for key in ("backend", "client_size", "dpi"):
            if key in observed:
                out[f"observed.{key}"] = observed[key]
    conditions = data.get("conditions")
    if isinstance(conditions, dict):
        for key in ("profile", "platform"):
            if key in conditions:
                out[f"conditions.{key}"] = conditions[key]
        settings = conditions.get("settings")
        if isinstance(settings, dict):
            for key, use in cast(dict[str, Any], settings).items():
                out[f"conditions.settings.{key}"] = _setting_value(use)
    packages = data.get("packages")
    if isinstance(packages, dict):
        for name, version in cast(dict[str, Any], packages).items():
            out[f"packages.{name}"] = version
    plugins = data.get("plugins")
    if isinstance(plugins, list):
        for plugin in cast(list[Any], plugins):
            if isinstance(plugin, dict) and isinstance(plugin.get("id"), str):
                out[f"plugins.{plugin['id']}"] = plugin.get("version")
    if "game_build" in data:
        out["game_build"] = data["game_build"]
    return out


def env_diff(run: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[dict[str, Any]]:
    """환경 차이 (`CompareEnvDiff` 목록, 점 경로 순). 한쪽에 없는 값은 null."""
    here, there = _env_values(run), _env_values(baseline)
    found: list[dict[str, Any]] = []
    for key in sorted(set(here) | set(there)):
        a, b = here.get(key), there.get(key)
        if a != b:
            found.append({"key": key, "run": a, "baseline": b})
    return found


# ---------------------------------------------------------------- 시간


def inflection(durations: Sequence[int]) -> tuple[int, float, float] | None:
    """회차 경과 흐름의 변곡: (첫 늦은 회차의 위치, 앞 절반 중앙값, 그 위치부터의 중앙값).

    앞 절반(회차 수 // 2) 중앙값 `m`의 `INFLECTION_FACTOR`배를 넘는 경과가 `INFLECTION_RUN`번
    (남은 회차가 그보다 적으면 남은 전부, 최소 2번) 이어지기 시작한 첫 위치. 회차가
    `INFLECTION_MIN_ITERATIONS`보다 적으면 None."""
    n = len(durations)
    if n < INFLECTION_MIN_ITERATIONS:
        return None
    before = float(statistics.median(durations[: n // 2]))
    limit = INFLECTION_FACTOR * max(before, 1.0)
    for i in range(1, n):
        need = min(INFLECTION_RUN, n - i)
        if need < 2:
            break
        if all(d > limit for d in durations[i : i + need]):
            return i, before, float(statistics.median(durations[i:]))
    return None


def _duration(row: StepRow) -> int:
    """스텝 경과: 멈춤이 있었으면 멈춤을 뺀 경과(`active_duration_ms`), 아니면 `duration_ms`."""
    if row.active_duration_ms is not None:
        return row.active_duration_ms
    return row.duration_ms or 0


def _body_slowdown(
    index: RunIndex, loop: StepRow, before: Sequence[int], after: Sequence[int]
) -> tuple[str, float, float] | None:
    """변곡 전·후 회차의 본문 노드별 평균 경과를 비교해 가장 많이 는 노드 (노드, 전 평균, 후 평균).
    본문 스텝은 그 반복 회차의 바로 아래 스텝이다 (되돌아옴 제외, 호출은 호출 스텝 하나로)."""

    def means(iterations: Sequence[int]) -> dict[str, float]:
        groups: dict[str, list[int]] = {}
        for iteration in iterations:
            for row in index.iteration_steps(loop.step, iteration):
                if row.status is not None and not row.reentry:
                    groups.setdefault(row.node, []).append(_duration(row))
        return {node: sum(v) / len(v) for node, v in groups.items()}

    early, late = means(before), means(after)
    best: tuple[str, float, float] | None = None
    for node in sorted(set(early) & set(late)):
        if late[node] > early[node] and (
            best is None or late[node] - early[node] > best[2] - best[1]
        ):
            best = (node, early[node], late[node])
    return best


def loop_inflections(index: RunIndex) -> list[dict[str, Any]]:
    """이 실행의 반복 스텝마다 회차 경과 변곡 (끝난 회차만, 회차 순). 변곡 회차를 찾으면 그 반복
    본문에서 가장 많이 늦어진 노드와 전·후 평균도 준다 ("N회차부터 대기 평균 a → b")."""
    found: list[dict[str, Any]] = []
    for row in index.rows.values():
        if not row.loop:
            continue
        items = [i for i in index.iterations(row.step) if i["duration_ms"] is not None]
        hit = inflection([int(i["duration_ms"]) for i in items])
        if hit is None:
            continue
        at, before, after = hit
        item: dict[str, Any] = {
            "step": row.step,
            "graph": index.graph_of(row),
            "node": row.node,
            "from_iteration": int(items[at]["iteration"]),
            "before_ms": before,
            "after_ms": after,
        }
        body = _body_slowdown(
            index,
            row,
            [int(i["iteration"]) for i in items[:at]],
            [int(i["iteration"]) for i in items[at:]],
        )
        if body is not None:
            item.update(body_node=body[0], body_before_ms=body[1], body_after_ms=body[2])
        found.append(item)
        if len(found) >= MAX_INFLECTIONS:
            break
    return found


def node_means(index: RunIndex) -> dict[tuple[str, str], tuple[int, float]]:
    """(그래프, 노드) → (끝난 스텝 수, 평균 경과). 경과는 멈춤을 뺀 값 (`_duration`)."""
    groups: dict[tuple[str, str], list[int]] = {}
    for row in index.rows.values():
        if row.status is not None:
            groups.setdefault((index.graph_of(row), row.node), []).append(_duration(row))
    return {key: (len(v), sum(v) / len(v)) for key, v in groups.items()}


def debug_intervened(side: RunSide) -> bool:
    """디버거가 개입한 실행 (`run.json`, 진행 중이면 색인의 멈춤 구간)."""
    return side.run_json.get("debug_intervened") is True or bool(side.index.pauses)


def _time(run: RunSide, base: RunSide) -> dict[str, Any]:
    """노드별 평균(멈춤을 뺀 경과)과 변곡. 이 실행이 디버거로 멈췄던 실행이면 회차 경과(벽시계)에
    멈춘 시간이 들어 거짓 변곡이 나오므로 변곡을 내지 않고 `debug_intervened`를 남긴다
    (스키마 6장 "디버거가 개입한 실행은 시간 비교에서 뺀다")."""
    here, there = node_means(run.index), node_means(base.index)
    nodes: list[dict[str, Any]] = []
    for key in sorted(set(here) | set(there)):
        a, b = here.get(key), there.get(key)
        nodes.append(
            {
                "graph": key[0],
                "node": key[1],
                "count": 0 if a is None else a[0],
                "mean_ms": None if a is None else a[1],
                "baseline_count": 0 if b is None else b[0],
                "baseline_mean_ms": None if b is None else b[1],
            }
        )
    out: dict[str, Any] = {"nodes": nodes, "inflections": []}
    if debug_intervened(run):
        out["debug_intervened"] = True
    else:
        out["inflections"] = loop_inflections(run.index)
    return out


# ---------------------------------------------------------------- 화면


def _omitted(row: StepRow, kinds: frozenset[str]) -> bool:
    return any(isinstance(o, dict) and o.get("kind") in kinds for o in row.omitted or ())


def _evidence_file(side: RunSide, row: StepRow, thumbs: frozenset[str]) -> str | None:
    """이 실행 쪽 이미지: `evidence.last` → `_fail`/`_error` 증거 → 썸네일 (있는 파일만)."""
    candidates: list[str] = []
    if row.evidence:
        for event in side.index.step_events(row.step):
            evidence = event.get("evidence") if event.get("event") == "step.end" else None
            last = evidence.get("last") if isinstance(evidence, dict) else None
            if isinstance(last, str):
                candidates.append(last)
    for name in row.artifacts or ():
        stem = name.rsplit(".", 1)[0]
        if name.startswith(f"{STEPS_DIR}/") and stem.endswith(("_fail", "_error")):
            candidates.append(name)
    if row.step in thumbs:
        candidates.append(thumbnail_path(row.step))
    return next((c for c in candidates if (side.folder / c).is_file()), None)


def _inside(index: RunIndex, row: StepRow, call: str) -> bool:
    """`row`가 호출 스텝 `call`의 프레임 아래(중첩 호출 포함)에서 실행됐는가."""
    frame = row.frame
    while frame is not None:
        if frame == call:
            return True
        above = index.rows.get(frame)
        frame = None if above is None else above.frame
    return False


def _capture_row(side: RunSide, row: StepRow, thumbs: frozenset[str]) -> StepRow:
    """화면을 직접 캡처한 스텝. 호출 스텝은 직접 캡처하지 않으므로(증거는 안쪽 캡처를 넘겨받은
    것) 그 호출 아래에서 증거·썸네일이 있는 마지막 호출 아닌 스텝, 없으면 `row` 그대로."""
    if side.index.callee_of(row) is None:
        return row
    inner = [
        r
        for r in side.index.rows.values()
        if side.index.callee_of(r) is None
        and _inside(side.index, r, row.step)
        and (r.evidence or r.step in thumbs or _evidence_file(side, r, thumbs) is not None)
    ]
    return max(inner, key=lambda r: _step_number(r.step), default=row)


def _latest(rows: Iterable[StepRow]) -> StepRow | None:
    return max(rows, key=lambda r: _step_number(r.step), default=None)


def _screen(run: RunSide, base: RunSide, step: str) -> dict[str, Any]:
    """화면 비교 대상 (파일 고르기와 이유까지, 픽셀 비교는 `finish_compare`).

    기준 쪽은 같은 호출 경로·같은 노드의 썸네일(남은 마지막 회차). 비교할 스텝이 호출 스텝이면
    그 증거는 안쪽 스텝의 캡처이므로, 이 실행에서 그 캡처를 얻은 안쪽 스텝의 경로로 찾는다(그
    스텝에 기준 썸네일이 없으면 다른 노드로 넘어가지 않고 이유). 안쪽 스텝을 모를 때만 기준 실행에서
    그 호출 경로 아래의 마지막 썸네일을 쓴다. `baseline_step`은 실제로 쓴 스텝이다."""
    row = run.index.rows[step]
    thumbs = thumbnails(run.folder)
    inner = _capture_row(run, row, thumbs)
    out: dict[str, Any] = {"step": step, "file": None, "baseline_step": None, "baseline_file": None}
    out["file"] = _evidence_file(run, row, thumbs) or (
        _evidence_file(run, inner, thumbs) if inner is not row else None
    )
    base_rows = list(base.index.rows.values())
    base_thumbs = thumbnails(base.folder)
    exact = [r for r in base_rows if r.path == inner.path]
    if inner is not row or run.index.callee_of(row) is None:
        # 안쪽 캡처 스텝을 알면(또는 호출 스텝이 아니면) 같은 경로·같은 노드만 본다. 그 스텝에
        # 썸네일이 없으면 다른 노드로 넘어가지 않고 이유(policy_omitted·no_thumbnail)를 준다
        under: list[StepRow] = []
    else:
        # 호출 스텝인데 이 실행에서 증거를 캡처한 안쪽 스텝을 모름: 그 호출 경로 아래 마지막 썸네일
        depth = len(row.path)
        under = [
            r
            for r in base_rows
            if len(r.path) > depth
            and r.path[:depth] == row.path
            and base.index.callee_of(r) is None
        ]
    with_thumb = [r for r in exact if r.step in base_thumbs] or [
        r for r in under if r.step in base_thumbs
    ]
    used = _latest(with_thumb) or _latest(exact) or _latest(under)
    if used is not None:
        out["baseline_step"] = used.step
        if with_thumb:
            out["baseline_file"] = thumbnail_path(used.step)
    if out["file"] is None:
        omitted = _omitted(row, _SHOT_KINDS) or _omitted(inner, _SHOT_KINDS)
        out["reason"] = "policy_omitted" if omitted else "no_evidence"
    elif used is None:
        out["reason"] = "no_matching_step"
    elif out["baseline_file"] is None:
        out["reason"] = (
            "policy_omitted" if _omitted(used, frozenset({"thumbnail"})) else "no_thumbnail"
        )
    return out


_SHOT_KINDS: Final = frozenset({"screenshot", "thumbnail"})


def _step_number(step: str) -> int:
    try:
        return int(step[1:])
    except ValueError:
        return 0


# ---------------------------------------------------------------- 비교


@dataclass(slots=True)
class PreparedCompare:
    """색인에서 꺼낸 비교 재료 (`prepare_compare`). 색인 잠금 없이 `finish_compare`로 마무리한다."""

    result: dict[str, Any]
    run: tuple[str, Path]
    baseline: tuple[str, Path] | None


def prepare_compare(
    run: RunSide, baseline: RunSide | None, *, picked: Picked, step: str | None = None
) -> PreparedCompare:
    """색인이 필요한 부분(환경·시간·화면 대상 고르기). 부르는 쪽이 색인을 잠근 채 부른다. `step`이
    없으면 실패 스텝(`run.end.failure_step`)의 화면을 비교하고, 그것도 없으면 화면 비교를 뺀다.
    `step`이 색인에 없으면 KeyError."""
    if step is not None and step not in run.index.rows:
        raise KeyError(step)
    out: dict[str, Any] = {"run_id": run.run_id, "baseline_picked": picked}
    if baseline is None:
        out.update(baseline=None, message=NO_BASELINE)
        return PreparedCompare(out, (run.run_id, run.folder), None)
    out["baseline"] = baseline.run_id
    out["env"] = env_diff(run.run_json, baseline.run_json)
    out["time"] = _time(run, baseline)
    chain = run.index.failure_chain()
    target = step if step is not None else (chain[-1] if chain else None)
    if target is not None:
        out["screen"] = _screen(run, baseline, target)
    return PreparedCompare(out, (run.run_id, run.folder), (baseline.run_id, baseline.folder))


def finish_compare(
    prepared: PreparedCompare,
    *,
    differ: ScreenDiffer | None = None,
    snapshot_cache: Callable[[str], Path | None] | None = None,
) -> dict[str, Any]:
    """무거운 부분(스냅샷 해시·이미지 읽기·화면 차이). 색인을 보지 않으므로 잠금 밖에서 부른다.
    `snapshot_cache`는 실행 ID → 스냅샷 해시 캐시 파일. `differ`가 없으면(플랫폼 없음) 화면은
    파일만 주고, 이미지를 읽지 못하면 `reason: image_unreadable`."""
    out = dict(prepared.result)
    if prepared.baseline is None:
        return out

    def digest(side: tuple[str, Path]) -> tuple[str, dict[str, str]] | None:
        cache = None if snapshot_cache is None else snapshot_cache(side[0])
        return snapshot_digest(side[1], cache)

    here, there = digest(prepared.run), digest(prepared.baseline)
    if here is not None and there is not None:
        out["graph"] = _graph_diff(here, there)
    screen = out.get("screen")
    if isinstance(screen, dict) and "reason" not in screen and differ is not None:
        screen = out["screen"] = dict(cast(dict[str, Any], screen))
        try:
            mine = (prepared.run[1] / str(screen["file"])).read_bytes()
            theirs = (prepared.baseline[1] / str(screen["baseline_file"])).read_bytes()
            ratio, regions = differ(mine, theirs)
        except OSError, ValueError:
            screen["reason"] = "image_unreadable"
            return out
        screen["diff_ratio"] = max(0.0, min(1.0, float(ratio)))
        screen["regions"] = [list(map(int, r)) for r in regions[:5]]
    return out


def compare_runs(
    run: RunSide,
    baseline: RunSide | None,
    *,
    picked: Picked,
    step: str | None = None,
    differ: ScreenDiffer | None = None,
    snapshot_cache: Callable[[str], Path | None] | None = None,
) -> dict[str, Any]:
    """`CompareResult` (`prepare_compare` + `finish_compare`를 한 번에, 잠금이 필요 없는 곳용)."""
    prepared = prepare_compare(run, baseline, picked=picked, step=step)
    return finish_compare(prepared, differ=differ, snapshot_cache=snapshot_cache)


# ---------------------------------------------------------------- 캐시


def compare_cache_file(root: Path, run_id: str) -> Path:
    return root.joinpath(*CACHE_DIR, f"{run_id}.compare.json")


def snapshot_cache_file(root: Path, run_id: str) -> Path:
    return root.joinpath(*CACHE_DIR, f"{run_id}.snapshot.json")


def _events_stamp(folder: Path) -> list[int] | None:
    try:
        stat = (folder / EVENTS_FILE).stat()
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]


def _cache_key(
    run: Path, baseline: Path | None, baseline_id: str | None, step: str | None, picked: Picked
) -> dict[str, Any] | None:
    here = _events_stamp(run)
    there = None if baseline is None else _events_stamp(baseline)
    if here is None or (baseline is not None and there is None):
        return None
    return {
        "baseline": baseline_id,
        "picked": picked,
        "step": step,
        "run_events": here,
        "baseline_events": there,
    }


def read_compare_cache(
    cache: Path,
    run: Path,
    baseline: Path | None,
    baseline_id: str | None,
    step: str | None,
    picked: Picked,
) -> dict[str, Any] | None:
    """캐시한 비교 결과 (열쇠가 다르거나 없으면 None)."""
    key = _cache_key(run, baseline, baseline_id, step, picked)
    if key is None:
        return None
    try:
        data = json.loads(cache.read_bytes())
    except OSError, ValueError:
        return None
    if (
        isinstance(data, dict)
        and data.get("format") == COMPARE_CACHE_FORMAT
        and data.get("key") == key
        and isinstance(data.get("result"), dict)
    ):
        return cast(dict[str, Any], data["result"])
    return None


def write_compare_cache(
    cache: Path,
    run: Path,
    baseline: Path | None,
    baseline_id: str | None,
    step: str | None,
    picked: Picked,
    result: Mapping[str, Any],
) -> bool:
    key = _cache_key(run, baseline, baseline_id, step, picked)
    if key is None:
        return False
    return _write_json(cache, {"format": COMPARE_CACHE_FORMAT, "key": key, "result": result})


def _write_json(path: Path, data: Mapping[str, Any]) -> bool:
    """같은 폴더 임시 파일 + replace (실패는 False)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(temp, path)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True
