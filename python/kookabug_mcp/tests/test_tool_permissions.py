"""MCP 도구 → daemon 판정 도구 일치 (M5 B1 검수 H1·H2 회귀).

- 처리기가 부르는 daemon 메서드는 모두 그 MCP 도구 이름으로 판정된다(자기 연결 문서 닫기
  `graph.close`만 판정 없는 허용 메서드). 다른 도구로 판정되는 메서드를 부르면 그 도구의 명시 deny를
  우회한다
- 실제 `kookabug mcp`로, 각 도구를 명시 deny하면 입력 형태와 관계없이 `permission_denied`
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.mcp_client import McpClient
from kookabug_daemon.methods.tools import METHOD_TOOLS, UI_ONLY_AGENT_ALLOWED
from kookabug_mcp.tools import TOOL_DEFS, by_name

type Start = Callable[..., McpClient]

GRAPH = "tests/inventory_open.graph.json"
REV = "a" * 64

# 도구 → 입력 형태들 (처리기가 있는 core·graph_edit 도구 전부)
CASES: dict[str, list[dict[str, Any]]] = {
    "kb_project_info": [{}],
    "kb_toolset_enable": [{"toolsets": ["run"]}],
    "kb_graph_list": [{}, {"under": "tests"}],
    "kb_graph_get": [{"path": GRAPH}],
    "kb_graph_validate": [{"path": GRAPH}, {"path": GRAPH, "value": {"nodes": {}}}],
    "kb_node_search": [{}, {"query": "key"}],
    "kb_run_status": [{}, {"run": "abcd1234"}],
    "kb_graph_create": [
        {"path": "tests/deny_new.graph.json", "kind": "test"},
        {
            "path": "tests/deny_new.graph.json",
            "kind": "test",
            "ops": [{"op": "add_node", "ref": "a", "type": "core.test.pass"}],
        },
    ],
    "kb_graph_patch": [
        {"path": GRAPH, "base_revision": REV, "ops": [{"op": "set_meta", "title": "x"}]}
    ],
    "kb_target_create": [
        {"path": "targets/deny_new.target.json", "source": {"frame_id": "f_x"},
         "rect": [0, 0, 2, 2]}
    ],
}  # fmt: skip


def test_cases_cover_every_handled_tool() -> None:
    handled = {d.name for d in TOOL_DEFS if d.handler is not None}
    assert set(CASES) == handled


class RecordingLink:
    """daemon 대신 부른 메서드를 기록하고 그럴듯한 결과를 준다."""

    def __init__(self) -> None:
        self.methods: list[str] = []
        self.toolsets = frozenset({"core", "graph_edit"})
        self.principal = {"kind": "agent", "id": "t", "attended": True}

    def call(self, method: str, params: Mapping[str, Any] | None = None, **_: Any) -> Any:
        self.methods.append(method)
        opened = {"doc_id": "d_1", "revision": REV, "value": {}, "diagnostics": []}
        return {
            "workspace.info": {"root": "r", "profiles": [], "plugins": [], "diagnostics": []},
            "agent.toolsets.enable": {"enabled": ["core", "run"], "tools": []},
            "graph.list": {"graphs": []},
            "graph.check": {"diagnostics": []},
            "graph.open": opened,
            "graph.create": {**opened, "created": {}},
            "graph.close": {},
            "graph.patch": {
                "revision": REV, "wrote": True, "created": {}, "removed_refs": [],
                "diagnostics": [],
            },
            "nodes.list": {"schemas": []},
            "run.list": {"runs": []},
            "run.status": {"state": "ended", "outcome": None},
            "target.save": {"revision": "r", "image": "i.png", "preview": None, "warnings": []},
        }[method]  # fmt: skip

    def enable(self, toolsets: list[str]) -> dict[str, Any]:
        return self.call("agent.toolsets.enable", {"toolsets": toolsets})


@pytest.mark.parametrize(("tool", "args"), [(t, a) for t, forms in CASES.items() for a in forms])
def test_handler_methods_judged_as_same_tool(tool: str, args: dict[str, Any]) -> None:
    link = RecordingLink()
    handler = by_name()[tool].handler
    assert handler is not None
    handler(link, args)  # pyright: ignore[reportArgumentType]
    assert link.methods
    for method in link.methods:
        judged = METHOD_TOOLS[method]
        assert judged == tool or method in UI_ONLY_AGENT_ALLOWED, (tool, method, judged)


@pytest.mark.process
@pytest.mark.parametrize(("tool", "args"), [(t, a) for t, forms in CASES.items() for a in forms])
def test_explicit_tool_deny_enforced(
    tmp_path: Path, ws: Path, environ: dict[str, str], start_mcp: Start, tool: str,
    args: dict[str, Any],
) -> None:  # fmt: skip
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    rules = [{"rule": tool, "verdict": "deny"}]
    body = {"format": "kookabug.local/0", "permissions": {"preset": "full", "rules": rules}}
    local.write_text(json.dumps(body), encoding="utf-8")
    graph = ws / GRAPH
    before = graph.read_bytes()
    args = dict(args)
    if tool == "kb_graph_patch":
        args["base_revision"] = hashlib.sha256(before).hexdigest()
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core", "graph_edit")):
        mcp = start_mcp()
        mcp.initialize()
        error = mcp.error(tool, args)
        assert error["code"] == "permission_denied", error
        assert error["decision"]["source"] == f"rule:{tool}"
        assert mcp.close() == 0
    assert graph.read_bytes() == before
    assert not (ws / "tests/deny_new.graph.json").exists()
    assert not (ws / "targets/deny_new.target.json").exists()
