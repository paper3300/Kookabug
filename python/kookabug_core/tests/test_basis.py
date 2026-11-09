"""두 기준·실행 기준 고정 (M8 계획 3.6·E4, B3) — 엄격: 사용자 파일 손상.

작업 기준 쓰기는 팀 파일을 건드리지 않고, 실행은 시작 때 고정한 덧씌움 바이트로만 돈다(실행 도중
작업 변경이 바뀌어도 영향 없음). 팀 파일이 바뀐 변경은 `stale`로 덧씌움에서 빠지고 기록에 남는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from helpers.run import tk
from helpers.runner import RunnerHarness

from kb_testing.proc import Spawned
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import basis
from kookabug_core.knowledge.formats import Actor, KnowledgeError
from kookabug_core.record.snapshot import take_snapshot
from kookabug_core.supervisor import StartOptions
from kookabug_core.workspace import Workspace

TARGET = "targets/shop/buy.target.json"
TEST = "tests/shop/buy_potion.graph.json"
AGENT = Actor("agent", "agent-c")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def moved(ws: Path, x: float = 0.6445) -> bytes:
    value = json.loads((ws / TARGET).read_text("utf-8"))
    value["search"]["region"] = [x, 0.8125, 0.2539, 0.1875]
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def test_overlay_resolves_and_snapshot_freezes(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    team = (ws / TARGET).read_bytes()
    first = moved(ws)
    doc = basis.write(ws, {TARGET: first}, actor=AGENT, kind="locator_repair")
    assert (ws / TARGET).read_bytes() == team  # 팀 파일은 그대로
    assert doc["files"] == [
        {
            "after_sha256": sha(first),
            "base_sha256": sha(team),
            "copy": f"knowledge/working/{doc['id']}/files/{TARGET}",
            "path": TARGET,
        }
    ]
    # 이 Agent는 작업 사본을, 다른 Agent·팀은 팀 파일을 본다
    assert basis.view(ws, TARGET, job=None, agent="agent-c")[0] == first
    assert basis.view(ws, TARGET, job=None, agent="agent-x")[0] == team
    frozen = basis.freeze(ws, "working", agent="agent-c")
    assert frozen.overlay == {TARGET: first}
    assert frozen.record["working"] == [{"id": doc["id"], "files": {TARGET: sha(first)}}]
    assert frozen.record["knowledge"]["features/shop"] == 1
    snap = take_snapshot(Workspace.open(ws), TEST, tmp_path / "snap", overlay=frozen.overlay)
    assert TARGET in snap.overlaid
    assert (tmp_path / "snap" / TARGET).read_bytes() == first
    # 실행 도중 작업 변경이 바뀌어도 고정한 바이트·스냅샷은 그대로 (같은 변경을 갱신)
    second = moved(ws, 0.6)
    again = basis.write(ws, {TARGET: second}, actor=AGENT)
    assert again["id"] == doc["id"]
    assert frozen.overlay[TARGET] == first
    assert (tmp_path / "snap" / TARGET).read_bytes() == first
    assert basis.freeze(ws, "working", agent="agent-c").overlay == {TARGET: second}
    # 팀 기준은 덧씌움 없음
    team_basis = basis.freeze(ws, "team")
    assert team_basis.overlay == {} and team_basis.record["kind"] == "team"
    assert (ws / TARGET).read_bytes() == team


def test_stale_when_team_changes(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    doc = basis.write(ws, {TARGET: moved(ws)}, actor=AGENT)
    change = basis.load_change(ws, doc["id"])
    assert change is not None and basis.effective_state(ws, change) == "active"
    # 사람이 팀 파일을 고쳤다 → 그 변경은 stale (덧씌움에서 빠지고 기록에 남는다)
    (ws / TARGET).write_bytes((ws / TARGET).read_bytes() + b"\n")
    assert basis.effective_state(ws, change) == "stale"
    frozen = basis.freeze(ws, "working", agent="agent-c")
    assert frozen.overlay == {} and frozen.record["stale"] == [doc["id"]]
    assert basis.view(ws, TARGET, job=None, agent="agent-c")[1] is None
    # 사본을 밖에서 고쳐도 stale (기록과 다른 바이트로 실행하지 않는다)
    other = copy_example_workspace(tmp_path / "b")
    doc = basis.write(other, {TARGET: moved(other)}, actor=AGENT)
    (other / doc["files"][0]["copy"]).write_bytes(b"{}")
    change = basis.load_change(other, doc["id"])
    assert change is not None and basis.effective_state(other, change) == "stale"


def test_working_write_paths_only_tests_subgraphs_targets(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    for rel in ("kookabug.json", "knowledge/cheats.json", "AGENTS.md", "screens/x.screen.json"):
        with pytest.raises(KnowledgeError) as caught:
            basis.write(ws, {rel: b"{}"}, actor=AGENT)
        assert caught.value.code == "policy_path"
    with pytest.raises(KnowledgeError) as caught:
        basis.write(ws, {"tests/../kookabug.json": b"{}"}, actor=AGENT)
    assert caught.value.code == "policy_path"
    assert basis.load_changes(ws) == []


def test_concurrent_working_write_does_not_overwrite(tmp_path: Path) -> None:
    """쓰는 쪽이 읽은 바이트(expect)와 지금 보기가 다르면 덮지 않는다."""
    ws = copy_example_workspace(tmp_path)
    team = (ws / TARGET).read_bytes()
    basis.write(ws, {TARGET: moved(ws)}, actor=AGENT, expect={TARGET: sha(team)})
    with pytest.raises(KnowledgeError) as caught:
        basis.write(ws, {TARGET: moved(ws, 0.5)}, actor=AGENT, expect={TARGET: sha(team)})
    assert caught.value.code == "revision_conflict"


@dataclass
class OverlayHarness(RunnerHarness):
    overlay: Mapping[str, bytes] = field(default_factory=dict[str, bytes])
    record: Mapping[str, Any] | None = None

    def options(self) -> StartOptions:
        return replace(
            super().options(),
            overlay=dict(self.overlay) or None,
            basis=self.record,
            job="j-20261109-000000-0000",
        )


@pytest.mark.process
def test_run_json_records_basis(tmp_path: Path, spawned: Spawned) -> None:
    """실행은 감독자가 실행 폴더에 고정한 덧씌움 바이트로 스냅샷을 만들고 run.json에 기준을
    남긴다."""
    passing = tk().entry("n_pass").node("n_pass", "core.test.pass")
    failing = tk().entry("n_fail").node("n_fail", "core.test.fail")
    data = (json.dumps(failing.build(), sort_keys=True) + "\n").encode()
    record = {
        "kind": "working",
        "working": [{"id": "w-20261109-000000-0000", "files": {"tests/t.graph.json": sha(data)}}],
        "stale": [],
        "knowledge": {},
    }
    h = OverlayHarness.make(tmp_path, passing, overlay={"tests/t.graph.json": data}, record=record)
    team = (h.ws.root / "tests" / "t.graph.json").read_bytes()
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_json is not None and done.run_json["verdict"] == "fail"
    assert done.run_json["basis"] == record
    assert done.run_json["job"] == "j-20261109-000000-0000"
    assert (h.run_dir / "snapshot" / "tests" / "t.graph.json").read_bytes() == data
    assert (h.ws.root / "tests" / "t.graph.json").read_bytes() == team
    assert [p.read_bytes() for p in (h.run_dir / "overlay").iterdir()] == [data]
