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
from kookabug_daemon.methods.tools import AGENT_RAW, METHOD_TOOLS, UI_ONLY_AGENT_ALLOWED
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
         "rect": [0, 0, 2, 2]},
        {"path": "targets/deny_new.target.json",
         "source": {"run": "abcd1234", "file": "steps/s1_fail.png"}, "rect": [0, 0, 2, 2]},
    ],
    # M5 B2: run·observe·screens 툴셋, kb_log_search
    "kb_log_search": [{"query": "x"}, {"query": "x", "runs": ["abcd1234"], "limit": 5}],
    "kb_run_start": [{"path": GRAPH, "idempotency_key": "k"}],
    "kb_run_cancel": [{"run": "abcd1234"}],
    "kb_run_events": [{"run": "abcd1234"}, {"run": "abcd1234", "after_seq": 3, "limit": 5}],
    "kb_run_artifact_get": [{"run": "abcd1234", "path": "steps/s1_fail.png"}],
    "kb_run_compare": [{"run": "abcd1234"}, {"run": "abcd1234", "base": "efgh5678"}],
    "kb_screen_capture": [{}, {"window": "Sample"}],
    "kb_image_find": [
        {"frame_id": "f_x", "target": "targets/login/login_button.target.json"}
    ],
    "kb_ocr_read": [{"frame_id": "f_x"}, {"frame_id": "f_x", "rect": [0, 0, 2, 2]}],
    "kb_screen_list": [{}, {"under": "lobby"}],
    "kb_screen_get": [{"path": "screens/login.screen.json"}],
    # M5 B3: control 툴셋 (B2가 넘김)
    "kb_input_click": [
        {"window": "SampleRPG", "point": [10, 10]},
        {"window": "SampleRPG", "target": "targets/login/login_button.target.json",
         "button": "right", "count": 2},
    ],
    "kb_input_key": [{"window": "SampleRPG", "keys": "ctrl+a"}],
    "kb_input_type": [{"window": "SampleRPG", "text": "abc"},
                      {"window": "SampleRPG", "secret": "accounts.qa_tester_01"}],
    "kb_app_launch": [{}, {"profile": "login_fail"}],
    # M7: 탐색 세션·화면 지도 저장·식별 (screens 툴셋)
    "kb_screen_identify": [{"frame_id": "f_x"}],
    "kb_explore_start": [{"title": "탐색"}, {"title": "탐색", "goal": "g", "max_steps": 5}],
    "kb_explore_end": [{}],
    "kb_screen_save": [{"key": "title", "frame_id": "f_x"},
                       {"key": "title", "frame_id": "f_x", "title": "타이틀",
                        "detect": {"all": [{"image": [0, 0, 2, 2]}]},
                        "moves": [{"via": {"key": "esc"}, "to": None, "status": "untried"}]}],
}  # fmt: skip
PROCESS_SKIP = {"kb_run_cancel"}
"""daemon이 판정 전에 대표 인자(실행의 그래프 경로)를 구하다 `run_not_found`가 되는 도구 — 정적
검사(처리기 → 메서드 → 판정 도구)만 본다."""


def test_cases_cover_every_handled_tool() -> None:
    handled = {d.name for d in TOOL_DEFS if d.handler is not None}
    assert set(CASES) == handled


class RecordingLink:
    """daemon 대신 부른 메서드를 기록하고 그럴듯한 결과를 준다."""

    def __init__(self) -> None:
        self.methods: list[str] = []
        self.toolsets = frozenset({"core", "graph_edit"})
        self.root = Path(".")
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
            "plugins.list": {"plugins": [], "stale_reason": None},
            "run.list": {"runs": []},
            "run.status": {"state": "ended", "outcome": {"verdict": "fail"}},
            "run.failure": {"failure": {"node": "n", "step": "s1", "error": None}},
            "run.search": {"matches": [], "skipped": [], "truncated": False},
            "run.start": {"run_id": "abcd1234", "graph": GRAPH, "run_dir": "d"},
            "run.cancel": {},
            "run.events": {"events": [], "next_seq": 0, "truncated": False, "classified": True},
            "run.artifact": {"kind": "text", "path": "p", "text": "", "truncated": False},
            "run.diff": {"run_id": "abcd1234", "baseline": None},
            "windows.list": {"windows": [{"handle": 1, "title": "Sample Game", "process": "p",
                                          "pid": 1, "client_size": [2, 2], "dpi": 96}]},
            "target.capture": {"frame_id": "f_x", "width": 2, "height": 2, "dpi": 96,
                               "client_size": [2, 2], "image": {"cache": "f_x.png"}},
            "target.open": {"spec": {"image": "a.png"}, "revision": "r", "image": None,
                            "diagnostics": []},
            "target.preview": {"found": False, "match": None, "best": None, "threshold": 0.8},
            "screen.read_text": {"text": "", "lines": []},
            "screens.list": {"screens": []},
            "screens.get": {"path": "screens/login.screen.json", "value": {}},
            "target.save": {"revision": "r", "image": "i.png", "preview": None, "warnings": []},
            "permissions.get": {"principal": self.principal, "tools": []},
            "control.click": {"run_id": "abcd1234", "verdict": "pass"},
            "control.key": {"run_id": "abcd1234", "verdict": "pass"},
            "control.type": {"run_id": "abcd1234", "verdict": "pass"},
            "app.launch": {"pid": 1234},
            "screens.identify": {"matches": [], "unknown": [], "checked": 0, "problems": []},
            "explore.start": {"session": "20261107-000000-abcd", "folder": "f", "max_steps": 5},
            "explore.end": {"session": "20261107-000000-abcd",
                            "counts": {"screens": 0, "moves": 0, "untried": 0}},
            "screens.save": {"path": "p", "key": "title", "revision": "r", "also_matches": [],
                             "shot": "saved"},
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
        # 기록 원문 메서드는 daemon이 agent를 거부한다 — 처리기도 부르지 않는다 (M5 3.5)
        assert method not in AGENT_RAW, (tool, method)


@pytest.mark.process
@pytest.mark.parametrize(
    ("tool", "args"),
    [(t, a) for t, forms in CASES.items() if t not in PROCESS_SKIP for a in forms],
)
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
    with ThreadDaemon(ws, environ=environ):  # 툴셋 전부 켬 (판정만 본다)
        mcp = start_mcp()
        mcp.initialize()
        error = mcp.error(tool, args)
        assert error["code"] == "permission_denied", error
        assert error["decision"]["source"] == f"rule:{tool}"
        assert mcp.close() == 0
    assert graph.read_bytes() == before
    assert not (ws / "tests/deny_new.graph.json").exists()
    assert not (ws / "targets/deny_new.target.json").exists()
    assert not (ws / "runs").exists()
