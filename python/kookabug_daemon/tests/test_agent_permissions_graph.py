"""그래프 메서드의 에이전트 권한 (M2 계획 2.5, T4): 거부·승인 필요면 파일을 쓰지 않는다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kookabug_daemon.client import DaemonError

pytestmark = pytest.mark.process

GRAPH = "tests/inventory_open.graph.json"
NEW = "tests/agent_new.graph.json"
OLD_NS = 1_600_000_000 * 10**9


def agent(*, attended: bool = False) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-7", "attended": attended}


def set_policy(root: Path, layer: str, permissions: dict[str, Any]) -> None:
    if layer == "team":
        path = root / "kookabug.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["permissions"] = permissions
    else:
        path = root / ".kookabug" / "local.json"
        path.parent.mkdir(exist_ok=True)
        data = {"format": "kookabug.local/0", "permissions": permissions}
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_sample_workspace(tmp_path / "ws")
    os.utime(root / GRAPH, ns=(OLD_NS, OLD_NS))
    return root


@pytest.fixture
def environ(tmp_path: Path) -> dict[str, str]:
    return {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}


def attempt_writes(d: ThreadDaemon, client_info: dict[str, Any]) -> dict[str, DaemonError]:
    """열기(읽기 도구)는 되고, 저장·만들기는 거부되어야 한다. 메서드 → 오류."""
    errors: dict[str, DaemonError] = {}
    with d.client(client_info) as client:
        opened = client.call("graph.open", {"path": GRAPH})
        value = opened["value"]
        value["meta"] = {"title": "에이전트 편집"}
        attempts: dict[str, dict[str, Any]] = {
            "graph.save": {
                "doc_id": opened["doc_id"],
                "value": value,
                "base_revision": opened["revision"],
            },
            "graph.create": {"path": NEW, "kind": "test"},
        }
        for method, params in attempts.items():
            with pytest.raises(DaemonError) as exc:
                client.call(method, params)
            errors[method] = exc.value
    return errors


def test_agent_graph_save_denied_by_preset_no_write(ws: Path, environ: dict[str, str]) -> None:
    set_policy(ws, "team", {"preset": "read_only"})
    before = (ws / GRAPH).read_bytes()
    with ThreadDaemon(ws, environ=environ) as d:
        errors = attempt_writes(d, agent(attended=True))
        for error in errors.values():
            assert error.kind == "permission_denied"
            assert error.data["decision"]["final"] == "deny"
        assert "kb_graph_patch" in errors["graph.save"].message
        assert "kb_graph_create" in errors["graph.create"].message
        assert (ws / GRAPH).read_bytes() == before
        assert (ws / GRAPH).stat().st_mtime_ns == OLD_NS
        assert not (ws / NEW).exists()

        # 같은 정책에서도 UI 연결은 판정받지 않는다
        with d.client() as ui:
            opened = ui.call("graph.open", {"path": GRAPH})
            value = opened["value"]
            value["meta"] = {"title": "사람 편집"}
            saved = ui.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
            assert saved["wrote"] is True


def test_agent_ask_approval_required_no_write(ws: Path, environ: dict[str, str]) -> None:
    set_policy(ws, "project", {"toolsets": {"graph_edit": "ask"}})
    before = (ws / GRAPH).read_bytes()
    with ThreadDaemon(ws, environ=environ) as d:
        attended = attempt_writes(d, agent(attended=True))
        for error in attended.values():
            assert error.kind == "approval_required"
            assert error.data["decision"]["final"] == "ask"
        unattended = attempt_writes(d, agent(attended=False))
        for error in unattended.values():
            assert error.kind == "permission_denied"
            assert error.data["decision"]["reason"] == "unattended_ask"
    assert (ws / GRAPH).read_bytes() == before
    assert (ws / GRAPH).stat().st_mtime_ns == OLD_NS
    assert not (ws / NEW).exists()
