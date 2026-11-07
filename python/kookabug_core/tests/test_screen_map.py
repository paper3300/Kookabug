"""화면 지도 이동 그래프 (`screens.map`, M7 계획 3.3, B4): 확정 화면·후보·실행 기록에서 간선, `of`
후보 배지, `to` 해석."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from helpers.explored import SESSION, SESSION_REL, make_explored_workspace
from helpers.graphs import write_json
from helpers.run_chain import chain_workspace, record_run

from kookabug_core.screen_map import build_map

X = f"x:{SESSION}"


def edge(data: dict[str, Any], source: str, target: str | None, label: str) -> dict[str, Any]:
    found = [
        e for e in data["edges"] if (e["from"], e["to"], e["label"]) == (source, target, label)
    ]
    assert len(found) == 1, (source, target, label, data["edges"])
    return found[0]


def confirm(root: Path, sid: str) -> None:
    write_json(
        root,
        f"screens/{sid}.screen.json",
        {
            "format": "kookabug.screen/1",
            "title": sid,
            "detect": {"all": [{"$target": "targets/lobby/title.target.json"}]},
        },
    )


def test_edges_from_confirmed_candidates_runs(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    chain_workspace(root)
    make_explored_workspace(root)
    for sid in ("world_field", "inventory", "loading"):
        confirm(root, sid)
    from kookabug_core.workspace import Workspace

    record_run(Workspace.open(root), ["enter_world", "open_inventory"])
    data = build_map(root, sessions=[{"id": SESSION, "title": "예제 탐색"}])
    nodes = {s["node"]: s for s in data["screens"]}
    assert {"lobby", "old", "world_field", f"{X}/upgrade", f"{X}/result", f"{X}/loading"} <= set(
        nodes
    )
    assert nodes[f"{X}/loading"]["incomplete"] is True and not nodes[f"{X}/loading"]["promotable"]
    assert nodes[f"{X}/upgrade"]["promotable"] is True
    assert nodes["lobby"]["detect_text"] == 'image("title")'
    # 후보 이동: 같은 세션 후보 키 → 후보 노드, 확정 ID → 확정 노드
    up = edge(data, f"{X}/upgrade", f"{X}/result", "강화 버튼")
    assert up["status"] == "tried" and up["sources"] == [{"kind": "explored", "session": SESSION}]
    assert edge(data, f"{X}/upgrade", "lobby", "키 esc")["status"] == "tried"
    untried = edge(data, f"{X}/upgrade", None, "점 (0.50, 0.90)")
    assert (
        untried["status"] == "untried" and untried["note"] == "구매" and "unresolved" not in untried
    )
    # 확정 화면 이동 (세션에서 승격된 화면의 to는 그 세션 후보 키로 푼다)
    assert edge(data, "lobby", f"{X}/result", "키 f1")["sources"] == [
        {"kind": "explored", "session": SESSION}
    ]
    # 실행 기록 사슬
    run = edge(data, "world_field", "inventory", "open_inventory · ok")
    assert run["via"] == {"call": "subgraphs/open_inventory.graph.json", "exit": "ok"}
    assert run["sources"][0]["kind"] == "run" and run["sources"][0]["count"] == 1
    assert edge(data, "lobby", "loading", "pick_server · ok")["status"] == "tried"
    assert data["sessions"] == [{"id": SESSION, "title": "예제 탐색"}]
    assert data["start"] == "inventory" or data["start"] in nodes
    # 같은 입력이면 같은 revision
    assert (
        build_map(root, sessions=[{"id": SESSION, "title": "예제 탐색"}])["revision"]
        == data["revision"]
    )


def test_of_candidate_badges_confirmed(tmp_path: Path) -> None:
    root = make_explored_workspace(tmp_path / "ws")
    data = build_map(root)
    nodes = {s["node"]: s for s in data["screens"]}
    # of 후보는 카드로 그리지 않는다
    assert f"{X}/bag" not in nodes
    assert nodes["old"]["explored_adds"] == 1
    assert nodes["lobby"]["explored_adds"] == 0
    # 그 이동은 확정 카드에서 나가는 "확인 전" 간선
    pending = edge(data, "old", "lobby", "닫기")
    assert pending["pending"] is True
    assert pending["sources"] == [{"kind": "explored", "session": SESSION}]
    assert edge(data, "old", f"{X}/upgrade", "키 i")["pending"] is True


def test_unresolved_to(tmp_path: Path) -> None:
    root = make_explored_workspace(tmp_path / "ws")
    card = root / SESSION_REL / "result.screen.json"
    doc = json.loads(card.read_text(encoding="utf-8"))
    doc["moves"].append({"via": {"key": "f2"}, "to": "nowhere", "status": "tried"})
    card.write_text(json.dumps(doc), encoding="utf-8")
    data = build_map(root)
    lost = edge(data, f"{X}/result", None, "키 f2")
    assert lost["unresolved"] == "nowhere"
    # 승격된 키는 승격 ID로 푼다 (explore.json promoted)
    explore = root / SESSION_REL / "explore.json"
    body = json.loads(explore.read_text(encoding="utf-8"))
    body["promoted"] = {"nowhere": "old"}
    explore.write_text(json.dumps(body), encoding="utf-8")
    data = build_map(root)
    assert edge(data, f"{X}/result", "old", "키 f2")["status"] == "tried"
