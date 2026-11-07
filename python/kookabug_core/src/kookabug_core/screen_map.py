"""화면 지도 이동 그래프 (`screens.map`, M7 계획 3.3·3.3a).

카드(노드) = 확정 화면(`screens/`) + 탐색 후보(`screens/_explored/<세션>/<키>`). `of` 후보는 카드로
그리지 않고 그 확정 카드에 "탐색 추가 N" 배지와 확인 전 간선으로 보인다. 간선 = 화면 파일의 이동
(`moves`) + 실행 기록 사슬(3.3a).

`to` 해석: 같은 세션 후보 키 → (그 세션에서 승격된 키면 승격 ID) → 확정 ID. 못 찾으면 `to: null` +
`unresolved`.

**실행 기록 사슬**(3.3a)은 읽는 필드를 허용 목록 하나(`ALLOWED`)로 제한한다 — `run.json`의
판정·출처·시각, `events.jsonl`의 `step.start`·`step.end` 스텝 ID·부모·노드·호출 경로·출구·
서브그래프 스냅샷 경로, 스냅샷 서브그래프의 `interface.exits.*.screen`. 이미지·OCR 글자·입력
값·`secret_paths`는 읽지 않는다. 같은 부모 안 이웃한 두 호출이 모두 화면을 선언한 출구로 끝나면
간선 하나(실행당 같은 간선 한 번). 사이에 화면 없는 출구로 끝난 호출이 있으면 사슬이 끊기고,
안쪽 호출은 바깥 다음 호출과 잇지 않는다. 대상은 끝난 실행 최근 100개(에이전트 제어 실행
제외). 실행마다 결과를 `.kookabug/cache/screen-map-runs.json`에 둔다(열쇠 = 폴더 이름 +
`run.json` 크기·수정 시각 + `events.jsonl` 크기). 없는 실행 폴더의 항목은 버린다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.record.runfolder import run_id_of_folder
from kookabug_core.screens import (
    EXPLORE_FILE,
    EXPLORED_DIR,
    SCREENS_DIR,
    ScreenDef,
    ScreenFileError,
    ScreenMove,
    explored_candidates,
    read_screen_file,
    screen_index,
)
from kookabug_core.workspace import Workspace

__all__ = [
    "ALLOWED",
    "CACHE_FILE",
    "MAX_RUNS",
    "build_map",
    "detect_text",
    "run_edges",
]

log = logging.getLogger(__name__)

MAX_RUNS: Final = 100
CACHE_FILE: Final = (".kookabug", "cache", "screen-map-runs.json")
CACHE_FORMAT: Final = "kookabug.screen-map-runs/0"
RUNS_DIR: Final = "runs"
SNAPSHOT_PREFIX: Final = "snapshot/"
CONTROL_SOURCE: Final = "agent_control"

ALLOWED: Final[Mapping[str, frozenset[str]]] = {
    "run.json": frozenset({"status", "verdict", "source", "started_at", "ended_at"}),
    "event": frozenset(
        {"event", "step", "parent", "node", "path", "exit", "graph", "seq", "iteration"}
    ),
    "graph": frozenset({"interface"}),
    "interface": frozenset({"exits"}),
    "exit": frozenset({"screen"}),
}
"""실행 기록에서 읽는 필드 전부 (3.3a). 이 밖의 필드는 읽지 않는다 — 검사가 그 밖 필드를 읽으면
실패하는 기록으로 확인한다."""


def _loads(text: str) -> Any:
    """기록 JSON 읽기 (검사가 바꿔 끼워 허용 밖 필드 읽기를 잡는다)."""
    return json.loads(text)


def _pick(value: Any, kind: str) -> dict[str, Any]:
    """`value`에서 허용 필드만 꺼낸다 (`.get`만 쓴다 — 다른 키를 건드리지 않는다)."""
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for name in ALLOWED[kind]:
        found = value.get(name)  # pyright: ignore[reportUnknownMemberType]
        if found is not None:
            out[name] = found
    return out


# ---------------------------------------------------------------- 실행 기록 사슬


@dataclass(frozen=True, slots=True)
class RunEdge:
    source: str
    target: str
    call: str
    exit: str


def _exit_screens(folder: Path, graph: str, memo: dict[str, dict[str, str]]) -> dict[str, str]:
    """스냅샷 서브그래프의 출구 → 화면 ID (선언한 것만)."""
    if graph in memo:
        return memo[graph]
    found: dict[str, str] = {}
    rel = graph if graph.startswith(SNAPSHOT_PREFIX) else SNAPSHOT_PREFIX + graph
    parts = rel.split("/")
    # 실행 폴더 밖을 읽지 않는다 (`..`·절대 경로·드라이브·역슬래시, B4 검수 Low 3)
    if any(p in ("", ".", "..") or ":" in p or "\\" in p for p in parts):
        memo[graph] = found
        return found
    path = folder.joinpath(*parts)
    try:
        data = _pick(_loads(path.read_text(encoding="utf-8")), "graph")
    except OSError, ValueError, UnicodeDecodeError:
        data = {}
    interface = _pick(data.get("interface"), "interface")
    exits = interface.get("exits")
    if isinstance(exits, Mapping):
        for name in list(exits):  # pyright: ignore[reportUnknownArgumentType]
            screen = _pick(exits.get(name), "exit").get("screen")  # pyright: ignore[reportUnknownMemberType]
            if isinstance(screen, str) and screen:
                found[str(name)] = screen
    memo[graph] = found
    return found


def _chain(folder: Path) -> list[RunEdge]:
    """실행 하나의 간선 (같은 간선은 한 번)."""
    try:
        lines = (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeDecodeError:
        return []
    parent_of: dict[tuple[str, int], str | None] = {}
    ends: dict[tuple[str, int], tuple[int, str | None, str]] = {}
    order = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = _pick(_loads(line), "event")
        except ValueError:
            continue  # 끝에 덜 쓴 줄
        kind = event.get("event")
        step = event.get("step")
        if not isinstance(step, str):
            continue
        key = (step, int(event.get("iteration", 0) or 0))
        if kind == "step.start":
            parent = event.get("parent")
            parent_of[key] = parent if isinstance(parent, str) else None
        elif kind == "step.end":
            graph = event.get("graph")
            if isinstance(graph, str):
                order += 1
                exit_name = event.get("exit")
                ends[key] = (order, exit_name if isinstance(exit_name, str) else None, graph)
    memo: dict[str, dict[str, str]] = {}
    by_parent: dict[str | None, list[tuple[int, str | None, str]]] = {}
    for key, end in ends.items():
        by_parent.setdefault(parent_of.get(key), []).append(end)
    edges: dict[tuple[str, str, str, str], RunEdge] = {}
    for calls in by_parent.values():
        previous: str | None = None
        for _, exit_name, graph in sorted(calls):
            screen = (
                _exit_screens(folder, graph, memo).get(exit_name) if exit_name is not None else None
            )
            if screen is None:
                previous = None  # 화면 선언 없는 출구: 사슬이 끊긴다
                continue
            if previous is not None and previous != screen:
                call = graph.removeprefix(SNAPSHOT_PREFIX)
                assert exit_name is not None
                edge = RunEdge(previous, screen, call, exit_name)
                edges.setdefault((edge.source, edge.target, edge.call, edge.exit), edge)
            previous = screen
    return list(edges.values())


def _cache_key(folder: Path) -> list[Any] | None:
    try:
        run_json = (folder / "run.json").stat()
    except OSError:
        return None
    try:
        events = (folder / "events.jsonl").stat().st_size
    except OSError:
        events = -1
    return [folder.name, run_json.st_size, run_json.st_mtime_ns, events]


def run_edges(root: Path, *, use_cache: bool = True) -> list[dict[str, Any]]:
    """끝난 실행 최근 `MAX_RUNS`개의 사슬 간선 (같은 간선은 합쳐 `count`·`last_run`)."""
    runs_dir = root / RUNS_DIR
    cache_path = root.joinpath(*CACHE_FILE)
    cache: dict[str, Any] = {}
    if use_cache:
        with contextlib.suppress(OSError, ValueError, UnicodeDecodeError):
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("format") == CACHE_FORMAT:
                cache = dict(loaded.get("runs") or {})
    fresh: dict[str, Any] = {}
    finished: list[tuple[str, str, str, list[RunEdge]]] = []
    folders = (
        sorted(
            p
            for p in runs_dir.iterdir()
            if p.is_dir() and not p.is_symlink() and not p.is_junction()
        )
        if runs_dir.is_dir() and not runs_dir.is_symlink() and not runs_dir.is_junction()
        else []
    )
    for folder in folders:
        key = _cache_key(folder)
        if key is None:
            continue
        hit = cache.get(folder.name)
        if isinstance(hit, dict) and hit.get("key") == key:
            entry = hit
        else:
            try:
                info = _pick(_loads((folder / "run.json").read_text(encoding="utf-8")), "run.json")
            except OSError, ValueError, UnicodeDecodeError:
                continue
            usable = info.get("status") == "finished" and info.get("source") != CONTROL_SOURCE
            edges = _chain(folder) if usable else []
            entry = {
                "key": key,
                "usable": usable,
                "started_at": str(info.get("started_at", "")),
                "edges": [[e.source, e.target, e.call, e.exit] for e in edges],
            }
        fresh[folder.name] = entry  # 없는 실행 폴더의 항목은 여기서 빠진다
        run_id = run_id_of_folder(folder)
        if entry.get("usable") and run_id is not None:
            finished.append(
                (
                    str(entry.get("started_at", "")),
                    folder.name,
                    run_id,
                    [RunEdge(*map(str, e)) for e in entry.get("edges", [])],
                )
            )
    if use_cache and fresh != cache:
        body = json.dumps({"format": CACHE_FORMAT, "runs": fresh}, ensure_ascii=False)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(cache_path, body.encode("utf-8"))
        except (OSError, DocumentError) as exc:
            log.debug("화면 지도 실행 캐시를 쓰지 못했다: %s", exc)
    finished.sort()
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for _, _, run_id, edges in finished[-MAX_RUNS:]:
        for e in edges:
            item = merged.setdefault(
                (e.source, e.target, e.call, e.exit),
                {"from": e.source, "to": e.target, "call": e.call, "exit": e.exit, "count": 0},
            )
            item["count"] += 1
            item["last_run"] = run_id
    return list(merged.values())


# ---------------------------------------------------------------- 지도


def detect_text(screen: ScreenDef) -> str:
    """판정 조건 한 줄 (`image("title") && !image("loading") && text("강화 확률")`)."""
    parts: list[str] = []
    for c in screen.detect():
        if c.target is not None:
            name = c.target.rsplit("/", 1)[-1].removesuffix(".target.json")
            term = f'image("{name}")'
        elif c.ocr is not None:
            term = f'text("{c.ocr.text}")'
        else:
            continue
        parts.append(term if c.group == "all" else f"!{term}")
    return " && ".join(parts)


def _via(move: ScreenMove) -> tuple[dict[str, Any], str]:
    if move.element is not None:
        return {"click": {"element": move.element}}, move.element
    if move.point is not None:
        x, y = move.point
        return {"click": {"point": [x, y]}}, f"점 ({x:.2f}, {y:.2f})"
    return {"key": move.key}, f"키 {move.key}"


def _origin(screen: ScreenDef | None) -> dict[str, Any] | None:
    if screen is None or screen.origin is None:
        return None
    o = screen.origin
    out: dict[str, Any] = {"kind": o.kind, "session": o.session}
    if o.agent is not None:
        out["agent"] = o.agent
    if o.at is not None:
        out["at"] = o.at
    return out


@dataclass(slots=True)
class _Edges:
    items: dict[tuple[str, str | None, str, str], dict[str, Any]] = field(
        default_factory=dict[tuple[str, str | None, str, str], dict[str, Any]]
    )

    def add(
        self,
        source: str,
        target: str | None,
        via: Mapping[str, Any],
        label: str,
        status: str,
        origin: dict[str, Any],
        *,
        unresolved: str | None = None,
        pending: bool = False,
        note: str | None = None,
    ) -> None:
        key = (source, target, json.dumps(via, sort_keys=True), unresolved or "")
        edge = self.items.get(key)
        if edge is None:
            edge = {
                "from": source,
                "to": target,
                "via": dict(via),
                "label": label,
                "status": status,
                "sources": [],
            }
            if unresolved is not None:
                edge["unresolved"] = unresolved
            if pending:
                edge["pending"] = True
            if note is not None:
                edge["note"] = note
            self.items[key] = edge
        elif status == "tried":
            edge["status"] = "tried"
        if not pending:
            edge.pop("pending", None)
        if origin not in edge["sources"]:
            edge["sources"].append(origin)


def build_map(
    root: Path,
    *,
    sessions: Iterable[Mapping[str, Any]] = (),
    thumb: Callable[[str], str | None] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """`screens.map` 결과. `sessions`는 daemon의 세션 목록(`explore.list`), `thumb`는 대표 스크린샷
    경로 → 썸네일 캐시 이름(사람 연결만, 에이전트는 None)."""
    workspace = Workspace.open(root)
    index = screen_index(workspace)
    screens: list[dict[str, Any]] = []
    confirmed: dict[str, dict[str, Any]] = {}
    defs: list[tuple[str, ScreenDef, dict[str, Any] | None]] = []
    for sid, paths in sorted(index.items()):
        rel = paths[0]
        card: dict[str, Any] = {
            "node": sid,
            "id": sid,
            "path": rel,
            "state": "confirmed",
            "title": None,
            "kind": "screen",
            "origin": None,
            "thumb": None,
            "detect_text": "",
            "elements": [],
            "counts": {"moves": 0, "elements": 0},
            "explored_adds": 0,
            "problem": None,
        }
        if len(paths) > 1:
            card["problem"] = f"같은 ID의 파일이 여럿이다: {', '.join(paths)}"
        try:
            screen = read_screen_file(workspace.root.joinpath(*rel.split("/")), rel)
        except ScreenFileError as exc:
            card["problem"] = str(exc)
        else:
            _fill(card, screen, thumb)
            defs.append((sid, screen, None))
        screens.append(card)
        confirmed[sid] = card
    promoted: dict[str, dict[str, str]] = {}
    candidates = explored_candidates(workspace)
    for session in {c.session for c in candidates if c.session}:
        assert session is not None
        path = root / SCREENS_DIR / EXPLORED_DIR / session / EXPLORE_FILE
        with contextlib.suppress(OSError, ValueError, UnicodeDecodeError):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("promoted"), dict):
                promoted[session] = {str(k): str(v) for k, v in data["promoted"].items()}
    keys: dict[str, set[str]] = {}
    for c in candidates:
        if (
            c.placement == "session"
            and c.session is not None
            and c.screen is not None
            and c.screen.of is None
        ):
            keys.setdefault(c.session, set()).add(c.key)
    for c in candidates:
        if c.placement != "session" or c.session is None:
            continue
        screen = c.screen
        if screen is not None and screen.of is not None and screen.of in confirmed:
            confirmed[screen.of]["explored_adds"] += 1
            defs.append((screen.of, screen, {"session": c.session, "key": c.key, "of": True}))
            continue
        node = f"x:{c.session}/{c.key}"
        card = {
            "node": node,
            "key": c.key,
            "session": c.session,
            "path": c.path,
            "state": "explored",
            "title": None,
            "kind": "screen",
            "origin": None,
            "thumb": None,
            "detect_text": "",
            "elements": [],
            "counts": {"moves": 0, "elements": 0},
            "of": None if screen is None else screen.of,
            "incomplete": screen is not None and screen.incomplete,
            "promotable": c.promotable,
            "problem": c.problem,
        }
        if screen is not None:
            _fill(card, screen, thumb)
            defs.append((node, screen, {"session": c.session, "key": c.key, "of": False}))
        screens.append(card)

    edges = _Edges()
    for node, screen, cand in defs:
        # 확정 화면도 탐색에서 승격된 것이면 그 세션 후보 키로 `to`를 푼다
        if cand is not None:
            session = cand["session"]
        else:
            session = screen.origin.session if screen.origin is not None else None
        if cand is None:
            origin = (
                {"kind": "explored", "session": screen.origin.session}
                if screen.origin is not None
                else {"kind": "manual"}
            )
        else:
            origin = {"kind": "explored", "session": session}
        for move in screen.moves:
            via, label = _via(move)
            target, unresolved = _resolve(move.to, session, keys, promoted, confirmed)
            edges.add(
                node,
                target,
                via,
                label,
                move.status,
                origin,
                unresolved=unresolved,
                pending=cand is not None and bool(cand["of"]),
                note=move.note,
            )
    for e in run_edges(root, use_cache=use_cache):
        if e["from"] not in confirmed:
            continue
        target = e["to"] if e["to"] in confirmed else None
        stem = e["call"].rsplit("/", 1)[-1].removesuffix(".graph.json")
        edges.add(
            e["from"],
            target,
            {"call": e["call"], "exit": e["exit"]},
            f"{stem} · {e['exit']}",
            "tried",
            {"kind": "run", "count": e["count"], "last_run": e["last_run"]},
            unresolved=None if target is not None else e["to"],
        )
    edge_list = sorted(edges.items.values(), key=lambda x: (x["from"], str(x["to"]), x["label"]))
    incoming = {e["to"] for e in edge_list if e["status"] == "tried" and e["to"] is not None}
    starts = [s["node"] for s in screens if s["state"] == "confirmed" and s["node"] not in incoming]
    start = starts[0] if starts else (screens[0]["node"] if screens else None)
    body: dict[str, Any] = {
        "screens": screens,
        "edges": edge_list,
        "sessions": [dict(s) for s in sessions],
        "start": start,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return {"revision": digest[:16], **body}


def _fill(
    card: dict[str, Any], screen: ScreenDef, thumb: Callable[[str], str | None] | None
) -> None:
    card["title"] = screen.title
    card["kind"] = screen.kind
    card["origin"] = _origin(screen)
    card["detect_text"] = detect_text(screen)
    card["elements"] = [
        {"name": e.name, "kind": e.kind, "rect": list(e.rect)} for e in screen.elements
    ]
    card["counts"] = {"moves": len(screen.moves), "elements": len(screen.elements)}
    if screen.shot is not None and thumb is not None:
        card["thumb"] = thumb(screen.shot.image)


def _resolve(
    to: str | None,
    session: str | None,
    keys: Mapping[str, set[str]],
    promoted: Mapping[str, Mapping[str, str]],
    confirmed: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """(노드, 못 찾은 이름)."""
    if to is None:
        return None, None
    if session is not None:
        if to in keys.get(session, set()):
            return f"x:{session}/{to}", None
        moved = promoted.get(session, {}).get(to)
        if moved is not None and moved in confirmed:
            return moved, None
    if to in confirmed:
        return to, None
    return None, to
