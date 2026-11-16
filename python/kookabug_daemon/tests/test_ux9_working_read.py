"""UX9 C: 읽기 도구가 작업 사본을 본다 (`kb_graph_validate`·`kb_graph_get`·`kb_graph_list`).

`--basis working` 작업에서 Agent가 만든 그래프는 `knowledge/working/w-…/files/<경로>`에만 있다.
`kb_run_start`(작업 기준 덧씌움)처럼 그 주체의 작업 사본에 있으면 그것, 없으면 워크스페이스 파일을
본다. 서브그래프 호출 검증도 작업 사본의 서브그래프를 본다. 다른 주체·사람은 팀 파일만.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import basis
from kookabug_core.knowledge.formats import Actor
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SUB = "subgraphs/common/ux9_enter.graph.json"
TEST = "tests/ux9_enter.graph.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-w", "attended": True}
OTHER = {**AGENT, "id": "agent-other"}


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}  # 작업 밖에서도 작업 기준으로 쓰는 프리셋
    local.write_text(json.dumps(body), encoding="utf-8")
    sub = (root / "subgraphs" / "enter_world.graph.json").read_bytes()
    test = (root / "tests" / "inventory_open.graph.json").read_text("utf-8")
    test = test.replace("subgraphs/enter_world.graph.json", SUB)
    assert SUB in test
    # 작업 사본에만 있는 서브그래프와 그것을 부르는 테스트 (팀 파일 없음)
    basis.write(
        root,
        {SUB: sub, TEST: test.encode("utf-8")},
        actor=Actor("agent", "agent-w"),
        kind="graph",
        expect={SUB: None, TEST: None},
    )
    assert not (root / SUB).exists() and not (root / TEST).exists()
    return root


def errors(diagnostics: list[dict[str, object]]) -> list[dict[str, object]]:
    """오류 진단 (검사 환경에 없는 예제 비밀값은 뺀다 — 팀 그래프도 같다)."""
    return [
        d for d in diagnostics if d.get("severity") == "error" and d.get("code") != "secret_missing"
    ]


def test_validate_and_get_see_working_copy(ws: Path) -> None:
    with ThreadDaemon(ws) as d, d.client(AGENT) as agent:
        for path in (SUB, TEST):
            checked = agent.call("graph.check", {"path": path})
            assert errors(checked["diagnostics"]) == [], (path, checked)
        opened = agent.call("graph.open", {"path": TEST})
        agent.call("graph.close", {"doc_id": opened["doc_id"]})
        assert opened["basis"] == "working"
        # 서브그래프 호출 검증도 작업 사본의 서브그래프를 본다 (graph_missing 없음)
        assert errors(opened["diagnostics"]) == [], opened["diagnostics"]
        assert {d.get("file") for d in opened["diagnostics"]} <= {TEST, None}
        listed = {g["path"]: g for g in agent.call("graph.list", {})["graphs"]}
        assert listed[SUB]["basis"] == "working" and listed[SUB].get("kind") == "subgraph"
        assert listed[TEST]["basis"] == "working"
        assert "basis" not in listed["tests/inventory_open.graph.json"]
        under = agent.call("graph.list", {"under": "subgraphs"})["graphs"]
        assert SUB in {g["path"] for g in under} and TEST not in {g["path"] for g in under}


def missing(client: DaemonClient, path: str) -> str | None:
    with pytest.raises(DaemonError) as caught:
        client.call("graph.check", {"path": path})
    return caught.value.kind


def test_other_principals_see_team_files(ws: Path) -> None:
    with ThreadDaemon(ws) as d:
        with d.client(OTHER) as other:
            assert missing(other, SUB) == "not_found"
            assert SUB not in {g["path"] for g in other.call("graph.list", {})["graphs"]}
        with d.client() as human:
            assert missing(human, TEST) == "not_found"


def test_working_subgraph_case_insensitive_path(tmp_path: Path) -> None:
    """검수1 Mid 5: 작업 사본 서브그래프를 대소문자만 다른 경로로 불러도 같은 파일(사본)이다 —
    직접 검증과 그것을 부르는 그래프 검증이 같은 규칙."""
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}
    local.write_text(json.dumps(body), encoding="utf-8")
    sub = "subgraphs/common/ux9_case.graph.json"
    test = "tests/ux9_case.graph.json"
    original = "subgraphs/enter_world.graph.json"
    graph = (root / "tests" / "inventory_open.graph.json").read_text("utf-8")
    graph = graph.replace(original, sub.upper())
    basis.write(
        root,
        {sub: (root / original).read_bytes(), test: graph.encode("utf-8")},
        actor=Actor("agent", "agent-w"),
        kind="graph",
        expect={sub: None, test: None},
    )
    with ThreadDaemon(root) as d, d.client(AGENT) as agent:
        assert errors(agent.call("graph.check", {"path": sub.upper()})["diagnostics"]) == []
        checked = agent.call("graph.check", {"path": test})
        assert errors(checked["diagnostics"]) == [], checked
        opened = agent.call("graph.open", {"path": test})
        agent.call("graph.close", {"doc_id": opened["doc_id"]})
        assert errors(opened["diagnostics"]) == [], opened["diagnostics"]
