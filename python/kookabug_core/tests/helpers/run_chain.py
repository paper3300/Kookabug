"""실행 기록 사슬 검사용 (M7 B4, 계획 3.3a): 실제 실행기(가짜 플랫폼)로 그래프를 돌려 `runs/<폴더>/`
(`run.json`·`events.jsonl`·`snapshot/`)를 만든다. runner와 같은 `snapshot/` 접두를 쓴다."""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from testkit import registry_with_testkit

from helpers.graphs import GraphBuilder, make_workspace
from kookabug_core.engine import ExecOptions, Executor, FakeClock, FakePlatform, MemoryArtifacts
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets, Workspace

TEST = "tests/chain.graph.json"
SCREENS = {
    "login": "lobby",
    "pick_server": "loading",
    "enter_world": "world_field",
    "open_inventory": "inventory",
}


def sub(name: str, *, screen: str | None, inner: tuple[str, ...] = ()) -> GraphBuilder:
    """서브그래프: (안쪽 호출들) → 출구 ok (`screen`을 선언하거나 안 함)."""
    exit_decl: dict[str, Any] = {"kind": "ok"}
    if screen is not None:
        exit_decl["screen"] = screen
    g = GraphBuilder("subgraph", interface={"exits": {"ok": exit_decl}})
    nodes = [f"n_{i}" for i in range(len(inner))]
    g.entry(nodes[0] if nodes else "n_exit")
    for i, callee in enumerate(inner):
        nxt = nodes[i + 1] if i + 1 < len(nodes) else "n_exit"
        g.call(nodes[i], f"subgraphs/{callee}.graph.json", next={"ok": nxt})
    g.exit("n_exit", "ok")
    return g


def chain_workspace(root: Path, record: Mapping[str, Any] | None = None) -> Workspace:
    ws = make_workspace(root, record=dict(record) if record is not None else None)
    sub("login", screen="lobby").write(ws, "subgraphs/login.graph.json")
    sub("pick_server", screen="loading").write(ws, "subgraphs/pick_server.graph.json")
    sub("enter_world", screen="world_field", inner=("login", "pick_server")).write(
        ws, "subgraphs/enter_world.graph.json"
    )
    sub("open_inventory", screen="inventory").write(ws, "subgraphs/open_inventory.graph.json")
    sub("no_screen", screen=None).write(ws, "subgraphs/no_screen.graph.json")
    return ws


def chain_graph(calls: list[str], record: Mapping[str, Any] | None = None) -> GraphBuilder:
    g = GraphBuilder("test", record=dict(record) if record is not None else None)
    nodes = [f"n_{i}" for i in range(len(calls))]
    g.entry(nodes[0])
    for i, callee in enumerate(calls):
        nxt = nodes[i + 1] if i + 1 < len(nodes) else "n_pass"
        g.call(nodes[i], f"subgraphs/{callee}.graph.json", next={"ok": nxt})
    g.node("n_pass", "core.test.pass")
    return g


_counter = [0]


def record_run(
    ws: Workspace,
    calls: list[str],
    *,
    run_id: str | None = None,
    record: Mapping[str, Any] | None = None,
    source: str | None = None,
    extra_run: Mapping[str, Any] | None = None,
) -> Path:
    """그래프를 실제로 돌려 실행 폴더를 만든다 (`runs/<시각>_chain_<id>/`)."""
    chain_graph(calls, record).write(ws, TEST)
    program = load_program(ws, TEST, secrets=MemorySecrets({}))
    executor = Executor(
        registry_with_testkit(),
        platform=FakePlatform(()),
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
    )
    _counter[0] += 1
    rid = run_id or f"r{_counter[0]:07d}"
    result = executor.run(program, ExecOptions(run_id=rid, graph_prefix="snapshot/"))
    started = datetime(2026, 11, 7, tzinfo=UTC) + timedelta(minutes=_counter[0])
    folder = ws.root / "runs" / f"{started.strftime('%Y-%m-%dT%H-%M-%S')}_chain_{rid}"
    (folder / "snapshot").mkdir(parents=True)
    for part in ("tests", "subgraphs"):
        shutil.copytree(ws.root / part, folder / "snapshot" / part)
    with open(folder / "events.jsonl", "w", encoding="utf-8") as f:
        for event in result.events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    run_json: dict[str, Any] = {
        "format": "kookabug.run/0",
        "run_id": rid,
        "graph": TEST,
        "status": "finished",
        "verdict": result.verdict,
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": "비밀 사유 secret-reason",
        "secret_paths": ["/reason"],
    }
    if source is not None:
        run_json["source"] = source
    run_json.update(extra_run or {})
    (folder / "run.json").write_text(json.dumps(run_json, ensure_ascii=False), encoding="utf-8")
    return folder
