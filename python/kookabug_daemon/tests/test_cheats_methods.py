"""치트 채택 daemon 메서드 (M8 계획 3.2·3.5·3.13, B2) — 엄격: Agent는 채택·분류를 못 한다.

`cheats.list/adopt/unadopt/categories.set`은 `ui_only` + `AGENT_DENIED`: 에이전트 연결은 사람 있는
연결(attended)이어도 판정 전에 `permission_denied`이고 파일이 바뀌지 않는다. 사람 연결의 채택은 지식
연산 한 경로로 쓰여 감사 이력에 남는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.methods.tools import AGENT_DENIED, HUMAN_CHEAT_METHODS, METHOD_TOOLS, UI_ONLY

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-c", "attended": True}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_example_workspace(tmp_path)


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_adopt_human_only_agent_denied(ws: Path, daemon: ThreadDaemon) -> None:
    assert HUMAN_CHEAT_METHODS <= AGENT_DENIED
    assert all(METHOD_TOOLS[m] == UI_ONLY for m in HUMAN_CHEAT_METHODS)
    cheats_file = ws / "knowledge" / "cheats.json"
    config = ws / "kookabug.json"
    before = (sha(cheats_file), sha(config))
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        base = sha(config)
        for method, params in (
            ("cheats.list", {}),
            ("cheats.adopt", {"id": "give_gold", "rev": 1, "category": "dev_safe"}),
            ("cheats.unadopt", {"id": "give_gold", "rev": 1}),
            (
                "cheats.categories.set",
                {
                    "base_sha256": base,
                    "categories": [{"id": "x", "title": "x", "unattended": True}],
                    "enabled": True,
                },
            ),
        ):
            assert refused(agent, method, params).kind == "permission_denied", method
        assert (sha(cheats_file), sha(config)) == before
        listed = ui.call("cheats.list", {})
        assert [c["id"] for c in listed["cheats"]] == ["give_gold"]
        assert listed["cheats"][0]["adopted"] is False
        # 없는 분류·rev 다름은 쓰지 않고 거부
        assert (
            refused(ui, "cheats.adopt", {"id": "give_gold", "rev": 1, "category": "nope"}).kind
            == "not_found"
        )
        assert (
            refused(ui, "cheats.adopt", {"id": "give_gold", "rev": 2, "category": "dev_safe"}).kind
            == "revision_conflict"
        )
        adopted = ui.call("cheats.adopt", {"id": "give_gold", "rev": 1, "category": "dev_safe"})
        assert adopted["adoption"]["by"] == "human" and len(adopted["adoption"]["digest"]) == 64
        assert ui.call("cheats.list", {})["cheats"][0]["adopted"] is True
        log = (ws / "knowledge" / "log.jsonl").read_text(encoding="utf-8").splitlines()
        last = json.loads(log[-1])
        assert (last["op"], last["result"], last["agent"]["kind"]) == ("adopt", "applied", "human")
        # 분류를 지우면 채택은 남아도 무효로 보인다 (실행 거부와 같은 판단)
        ui.call(
            "cheats.categories.set",
            {"base_sha256": sha(config), "categories": [], "enabled": True},
        )
        listed = ui.call("cheats.list", {})["cheats"][0]
        assert listed["adopted"] is False and "분류" in listed["problem"]
        # 다른 sha로는 쓰지 않는다
        assert (
            refused(
                ui,
                "cheats.categories.set",
                {"base_sha256": "0" * 64, "categories": [], "enabled": False},
            ).kind
            == "revision_conflict"
        )
        assert ui.call("cheats.unadopt", {"id": "give_gold", "rev": 1})["adoption"] is None


def test_knowledge_ops_adopt_refused_for_agent_actor(ws: Path) -> None:
    """지식 연산 경로 자체도 Agent 주체의 채택 연산을 거부한다 (MCP `kb_knowledge_apply`가 B4에서
    쓰는 길)."""
    from kookabug_core.knowledge import ops
    from kookabug_core.knowledge.formats import Actor, KnowledgeError

    before = sha(ws / "knowledge" / "cheats.json")
    request = {
        "request_id": "r-adopt",
        "ops": [
            {
                "op": "adopt",
                "file": "cheats",
                "id": "give_gold",
                "base_rev": 1,
                "category": "dev_safe",
            }
        ],
    }
    with pytest.raises(KnowledgeError) as caught:
        ops.apply(ws, request, actor=Actor("agent", id="a"), check_secrets=lambda texts: None)
    assert caught.value.code == "adoption_reserved"
    assert sha(ws / "knowledge" / "cheats.json") == before
