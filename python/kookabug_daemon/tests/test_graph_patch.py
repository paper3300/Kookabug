"""`graph.patch`와 동시 편집 (M5 계획 3.4·3.7, B1).

- 연산 묶음은 모두 적용하거나 하나도 안 한다. 틀린 연산·형식 오류 뒤 파일 바이트·mtime은 그대로
- 노드 ID는 바꿀 수 없다. 노드 지우기는 그 노드를 가리키는 next·$link도 지운다
- UI 저장 ↔ 에이전트 고치기: 늦은 쪽이 `revision_conflict`, 파일은 앞선 쪽 바이트
- agent 연결의 `graph.save force`는 판정 전에 `force_not_allowed` (덮어쓰기는 사람만)
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = pytest.mark.process

GRAPH = "tests/inventory_open.graph.json"
OLD_NS = 1_600_000_000 * 10**9
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": True}
NODE_ID = re.compile(r"^n_[a-z2-7]{8}$")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_sample_workspace(tmp_path / "ws")
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    local.write_text(
        json.dumps({"format": "kookabug.local/0", "permissions": {"preset": "full"}}),
        encoding="utf-8",
    )
    os.utime(root / GRAPH, ns=(OLD_NS, OLD_NS))
    return root


@pytest.fixture
def daemon(ws: Path, tmp_path: Path) -> Iterator[ThreadDaemon]:
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core", "graph_edit")) as d:
        yield d


def disk(root: Path) -> dict[str, Any]:
    return json.loads((root / GRAPH).read_text(encoding="utf-8"))


def revision(client: DaemonClient) -> str:
    opened = client.call("graph.open", {"path": GRAPH})
    client.call("graph.close", {"doc_id": opened["doc_id"]})
    return opened["revision"]


def patch(client: DaemonClient, base: str, *ops: dict[str, Any]) -> dict[str, Any]:
    return client.call("graph.patch", {"path": GRAPH, "base_revision": base, "ops": list(ops)})


def test_ops_apply_atomically(daemon: ThreadDaemon, ws: Path) -> None:
    with daemon.client(AGENT) as agent:
        base = revision(agent)
        result = patch(
            agent,
            base,
            {"op": "add_node", "ref": "log", "type": "core.log.message", "title": "기록",
             "in": {"message": "인벤토리 확인 전"}},
            {"op": "disconnect", "from": "n_press_i", "exit": "done"},
            {"op": "connect", "from": "n_press_i", "exit": "done", "to": "log"},
            {"op": "connect", "from": "log", "exit": "done", "to": "n_check_inventory"},
            {"op": "set_node", "id": "n_press_i", "title": "인벤토리 키",
             "in": {"keys": "Tab", "hold_ms": 50}},
            {"op": "move", "id": "log", "position": {"x": 700.4, "y": 160}},
            {"op": "set_meta", "title": "인벤토리 열기 (에이전트)"},
        )  # fmt: skip
    assert result["wrote"] is True and result["removed_refs"] == []
    log_id = result["created"]["log"]
    assert NODE_ID.match(log_id)
    value = disk(ws)
    assert value["nodes"][log_id] == {
        "in": {"message": "인벤토리 확인 전"},
        "next": {"done": "n_check_inventory"},
        "title": "기록",
        "type": "core.log.message",
        "version": 1,
    }
    assert value["nodes"]["n_press_i"]["next"] == {"done": log_id}
    assert value["nodes"]["n_press_i"]["in"] == {"keys": "Tab", "hold_ms": 50}
    assert value["layout"]["nodes"][log_id] == {"x": 700, "y": 160}
    assert value["meta"]["title"] == "인벤토리 열기 (에이전트)"
    assert value["meta"]["tags"] == ["inventory", "smoke"]  # 병합: 다른 키는 그대로
    assert result["revision"] != base

    # 묶음 중간이 틀리면 앞의 연산도 적용하지 않는다
    before = (ws / GRAPH).read_bytes()
    with daemon.client(AGENT) as agent, pytest.raises(DaemonError) as caught:
        patch(
            agent,
            result["revision"],
            {"op": "set_meta", "title": "적용되면 안 됨"},
            {"op": "connect", "from": "n_entry", "exit": "start", "to": "n_missing"},
        )
    assert caught.value.kind == "patch_invalid"
    assert caught.value.data["index"] == 1
    assert (ws / GRAPH).read_bytes() == before


def raw_agent(d: ThreadDaemon) -> DaemonClient:
    """보내기 전 params 검사를 하지 않는 agent 연결 (daemon이 거부하는지 본다)."""
    client = DaemonClient.open(d.port, check=False)
    hello = {"token": d.session.token, "protocol": 1, "client": AGENT}
    client.hello_result = client.call("session.hello", hello)
    return client


def test_node_id_change_rejected(daemon: ThreadDaemon, ws: Path) -> None:
    before = (ws / GRAPH).read_bytes()
    with raw_agent(daemon) as agent:
        base = revision(agent)
        attempts: list[dict[str, Any]] = [
            # set_node에는 id·type을 바꿀 칸이 없다 (형식 오류 -32602)
            {"op": "set_node", "id": "n_press_i", "new_id": "n_renamed"},
            {"op": "set_node", "id": "n_press_i", "type": "core.input.click"},
            # 새 노드의 ID는 daemon이 정한다
            {"op": "add_node", "ref": "a", "type": "core.log.message", "id": "n_mine"},
        ]
        for op in attempts:
            with pytest.raises(DaemonError) as caught:
                patch(agent, base, op)
            assert caught.value.code == -32602, op
        # ref가 기존 노드 ID와 같으면 거부 (기존 노드를 가리키는지 새 노드인지 모호하다)
        with pytest.raises(DaemonError) as caught:
            patch(agent, base, {"op": "add_node", "ref": "n_press_i", "type": "core.log.message"})
        assert caught.value.kind == "patch_invalid"
    assert (ws / GRAPH).read_bytes() == before
    assert (ws / GRAPH).stat().st_mtime_ns == OLD_NS


def test_remove_node_drops_links(daemon: ThreadDaemon, ws: Path) -> None:
    with daemon.client(AGENT) as agent:
        result = patch(agent, revision(agent), {"op": "remove_node", "id": "n_enter_world"})
    assert sorted(result["removed_refs"], key=lambda r: r["from"]) == [
        {"from": "n_entry", "kind": "next", "key": "start"},
        {"from": "n_use_window", "kind": "link", "key": "window"},
    ]
    value = disk(ws)
    assert "n_enter_world" not in value["nodes"]
    assert "n_enter_world" not in value["layout"]["nodes"]
    assert "next" not in value["nodes"]["n_entry"]  # 비게 된 next·in도 지운다
    assert "in" not in value["nodes"]["n_use_window"]
    # 다른 노드 ID는 그대로다
    assert set(value["nodes"]) == {
        "n_check_inventory", "n_entry", "n_press_i", "n_skip_maintenance", "n_use_window",
    }  # fmt: skip
    # 지운 결과의 의미 진단(시작 노드 연결 없음 등)은 결과로만 알린다
    assert isinstance(result["diagnostics"], list)


def test_bad_op_leaves_file_bytes(daemon: ThreadDaemon, ws: Path) -> None:
    before = (ws / GRAPH).read_bytes()
    with daemon.client(AGENT) as agent:
        base = revision(agent)
        cases: list[tuple[list[dict[str, Any]], str]] = [
            ([{"op": "set_node", "id": "n_missing", "title": "x"}], "patch_invalid"),
            ([{"op": "disconnect", "from": "n_entry", "exit": "nope"}], "patch_invalid"),
            ([{"op": "unlink", "to": "n_press_i", "pin": "keys"}], "patch_invalid"),
            ([{"op": "add_node", "ref": "x", "type": "core.no.such"}], "patch_invalid"),
            (
                [
                    {"op": "add_node", "ref": "x", "type": "core.log.message"},
                    {"op": "add_node", "ref": "x", "type": "core.log.message"},
                ],
                "patch_invalid",
            ),
            # 적용한 값이 그래프 형식에 맞지 않음 (핀 이름 규칙)
            ([{"op": "set_node", "id": "n_press_i", "in": {"Bad-Pin": 1}}], "validation_failed"),
        ]
        for ops, kind in cases:
            with pytest.raises(DaemonError) as caught:
                patch(agent, base, *ops)
            assert caught.value.kind == kind, (ops, caught.value)
        # 기준이 틀리면 연산을 보지도 않는다
        with pytest.raises(DaemonError) as caught:
            patch(agent, "0" * 64, {"op": "set_meta", "title": "x"})
        assert caught.value.kind == "revision_conflict"
        assert caught.value.data["revision"] == base
        # runs/ 아래 스냅샷은 고칠 수 없다, .kookabug/는 경로부터 거부
        for path, kind in (
            ("runs/r1/graph.graph.json", "read_only"),
            (".kookabug/x.graph.json", "private_path"),
        ):
            target = ws / path
            if kind == "read_only":
                target.parent.mkdir(parents=True)
                target.write_bytes(before)
            ops = [{"op": "set_meta", "title": "x"}]
            with pytest.raises(DaemonError) as caught:
                agent.call("graph.patch", {"path": path, "base_revision": base, "ops": ops})
            assert caught.value.kind == kind
    assert (ws / GRAPH).read_bytes() == before
    assert (ws / GRAPH).stat().st_mtime_ns == OLD_NS
    assert (ws / "runs/r1/graph.graph.json").read_bytes() == before


def test_create_with_ops_is_one_decision_and_atomic(daemon: ThreadDaemon, ws: Path) -> None:
    new = "tests/agent_ops.graph.json"
    with daemon.client(AGENT) as agent:
        # 틀린 연산이면 파일을 만들지 않는다
        with pytest.raises(DaemonError) as caught:
            agent.call(
                "graph.create",
                {"path": new, "kind": "test",
                 "ops": [{"op": "connect", "from": "n_entry", "exit": "start", "to": "nope"}]},
            )  # fmt: skip
        assert caught.value.kind == "patch_invalid"
        assert not (ws / new).exists()
        opened = agent.call(
            "graph.create",
            {"path": new, "kind": "test",
             "ops": [{"op": "add_node", "ref": "ok", "type": "core.test.pass"},
                     {"op": "connect", "from": "n_entry", "exit": "start", "to": "ok"}]},
        )  # fmt: skip
        agent.call("graph.close", {"doc_id": opened["doc_id"]})
    ok = opened["created"]["ok"]
    value = json.loads((ws / new).read_text(encoding="utf-8"))
    assert value["nodes"]["n_entry"]["next"] == {"start": ok}
    assert opened["value"] == value


def test_list_and_check_by_path(daemon: ThreadDaemon, ws: Path) -> None:
    with daemon.client(AGENT) as agent:
        graphs = {g["path"]: g for g in agent.call("graph.list", {"under": "tests"})["graphs"]}
        assert graphs[GRAPH] == {"path": GRAPH, "kind": "test", "title": "인벤토리 열기"}
        assert all(path.startswith("tests/") for path in graphs)
        everything = agent.call("graph.list")["graphs"]
        assert any(g["path"].startswith("subgraphs/") for g in everything)
        before = (ws / GRAPH).read_bytes()
        # 디스크 값 검증 = graph.open의 진단 (비밀값 환경에 따른 오류도 같게 나온다)
        disk_check = agent.call("graph.check", {"path": GRAPH})["diagnostics"]
        opened = agent.call("graph.open", {"path": GRAPH})
        agent.call("graph.close", {"doc_id": opened["doc_id"]})
        assert disk_check == opened["diagnostics"]
        broken = disk(ws)
        broken["nodes"]["n_entry"]["next"] = {"start": "n_gone"}
        value_check = agent.call("graph.check", {"path": GRAPH, "value": broken})["diagnostics"]
        assert any(d["node"] == "n_entry" and d["severity"] == "error" for d in value_check)
        assert not any(d["node"] == "n_entry" and d["severity"] == "error" for d in disk_check)
        assert (ws / GRAPH).read_bytes() == before


@pytest.mark.parametrize("first", ["ui", "agent"])
def test_late_writer_rejected_both_orders(daemon: ThreadDaemon, ws: Path, first: str) -> None:
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        opened = ui.call("graph.open", {"path": GRAPH})
        base = opened["revision"]
        assert revision(agent) == base

        def ui_save() -> dict[str, Any]:
            value = dict(opened["value"])
            value["meta"] = {**value["meta"], "title": "사람 편집"}
            return ui.call(
                "graph.save", {"doc_id": opened["doc_id"], "value": value, "base_revision": base}
            )

        def agent_patch() -> dict[str, Any]:
            return patch(agent, base, {"op": "set_meta", "title": "에이전트 편집"})

        early, late = (ui_save, agent_patch) if first == "ui" else (agent_patch, ui_save)
        early()
        winner = (ws / GRAPH).read_bytes()
        with pytest.raises(DaemonError) as caught:
            late()
        assert caught.value.kind == "revision_conflict"
        assert (ws / GRAPH).read_bytes() == winner
        expected = "사람 편집" if first == "ui" else "에이전트 편집"
        assert disk(ws)["meta"]["title"] == expected
        if first == "agent":
            # 에이전트가 쓴 것을 UI가 연 문서에 알린다 (감시 → graph.changed)
            note = ui.notifications.get(timeout=10)
            while note["method"] != "graph.changed":
                note = ui.notifications.get(timeout=10)
            assert note["params"]["doc_id"] == opened["doc_id"]


def test_agent_force_save_rejected(daemon: ThreadDaemon, ws: Path) -> None:
    before = (ws / GRAPH).read_bytes()
    with daemon.client(AGENT) as agent:
        opened = agent.call("graph.open", {"path": GRAPH})
        value = dict(opened["value"])
        value["meta"] = {"title": "덮어쓰기"}
        for base in ("0" * 64, opened["revision"]):
            with pytest.raises(DaemonError) as caught:
                agent.call(
                    "graph.save",
                    {
                        "doc_id": opened["doc_id"],
                        "value": value,
                        "base_revision": base,
                        "force": True,
                    },
                )
            assert caught.value.kind == "force_not_allowed"
        assert (ws / GRAPH).read_bytes() == before
        # force 없는 저장은 정책(full)대로 된다
        saved = agent.call(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
        )
        assert saved["wrote"] is True
    # 사람(UI)은 덮어쓰기를 고를 수 있다 (M2 흐름 그대로)
    with daemon.client() as ui:
        opened = ui.call("graph.open", {"path": GRAPH})
        value = dict(opened["value"])
        value["meta"] = {"title": "사람 덮어쓰기"}
        ui.call(
            "graph.save",
            {"doc_id": opened["doc_id"], "value": value, "base_revision": "0" * 64, "force": True},
        )
    assert disk(ws)["meta"]["title"] == "사람 덮어쓰기"
