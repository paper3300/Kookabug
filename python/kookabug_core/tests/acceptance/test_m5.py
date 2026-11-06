"""M5 완료 기준 (구현 계획 v0 1장 M5 행, M5 계획 5장) 인수 테스트, Python 쪽.

B3에서 3번(같은 행위가 CLI·daemon(MCP)에서 같은 권한 판정)의 권한 표 검사를 넣는다. 나머지 기준의
인수 시나리오는 B6이 더한다.

- CLI 경로: 실제 `kookabug run` 하위 프로세스(`KOOKABUG_AGENT` — 늘 사람 없음)와, CLI가 쓰는 주체
  함수(`cli_principal`)로 본 서비스 판정. CLI에 편집·입력 명령이 없으므로 실행 밖의 도구는 서비스
  판정이 CLI 쪽 기준이다
- MCP 경로: 실제 `kookabug mcp --unattended --agent-id <같은 ID>` → daemon. daemon이 집행한 판정은
  서비스 `require`가 돌려준(또는 예외에 실은) 값을 관찰한다(허용 판정은 결과에 실리지 않는다)
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned
from kookabug_core.documents import ENTRY_NODE, template
from kookabug_core.permissions import PRESETS, TOOLSETS, Principal
from kookabug_core.service import (
    RUN_START_TOOL,
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
    cli_principal,
)

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

AGENT_ID: Final = "m5-agent"
GRAPH: Final = "tests/inventory_open.graph.json"
PASS_GRAPH: Final = "tests/m5_pass.graph.json"
WINDOW: Final = "SampleRPG"


def _patch_args(ws: Path) -> dict[str, Any]:
    base = hashlib.sha256((ws / GRAPH).read_bytes()).hexdigest()
    return {"path": GRAPH, "base_revision": base, "ops": [{"op": "set_meta", "title": "m5"}]}


# 대표 도구: (권한 도구, 권한 인자, MCP 인자)
CASES: Final[list[tuple[str, str, Callable[[Path, str], dict[str, Any]]]]] = [
    ("kb_graph_get", GRAPH, lambda ws, p: {"path": GRAPH}),
    ("kb_graph_patch", GRAPH, lambda ws, p: _patch_args(ws)),
    (
        RUN_START_TOOL,
        PASS_GRAPH,
        lambda ws, p: {"path": PASS_GRAPH, "idempotency_key": f"m5-{p}"},
    ),
    ("kb_input_click", WINDOW, lambda ws, p: {"window": WINDOW, "point": [1, 1]}),
    ("kb_screen_list", "screens", lambda ws, p: {}),
]


def _workspace(tmp_path: Path, preset: str) -> Path:
    ws = copy_sample_workspace(tmp_path / "ws")
    graph = template("test")
    graph.pop("layout")
    graph["nodes"] = {
        ENTRY_NODE: {"type": "core.graph.entry", "version": 1, "next": {"start": "n_pass"}},
        "n_pass": {"type": "core.test.pass", "version": 1},
    }
    (ws / PASS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
    local = ws / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": {"preset": preset}}
    local.write_text(json.dumps(body), encoding="utf-8")
    return ws


@pytest.mark.parametrize("preset", PRESETS)
def test_same_decision_cli_and_mcp_all_presets(
    tmp_path: Path, spawned: Spawned, preset: str
) -> None:
    ws = _workspace(tmp_path, preset)
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    principal = cli_principal({"KOOKABUG_AGENT": AGENT_ID})
    assert principal == Principal("agent", AGENT_ID, attended=False)
    service = WorkspaceService(ws, environ=environ)
    expected = {tool: service.authorize(principal, tool, arg).to_dict() for tool, arg, _ in CASES}

    # ① 실제 CLI 하위 프로세스 (실행만 CLI 명령이 있다)
    done = run_cli(
        ["run", PASS_GRAPH, "--json"],
        cwd=ws,
        env={**cli_env(tmp_path), **environ, "KOOKABUG_AGENT": AGENT_ID},
    )
    cli = json.loads(done.stdout)
    assert cli["principal"] == {"kind": "agent", "id": AGENT_ID, "attended": False}
    assert cli["decision"] == expected[RUN_START_TOOL], done.stderr

    # ② 실제 kookabug mcp --unattended → daemon
    observed: dict[str, list[dict[str, Any]]] = {}
    with ThreadDaemon(
        ws, environ=environ, agent_toolsets=("core",), platform_fake=ws / "fake-platform.json"
    ) as d:
        original = d.daemon.service.require

        def observe(who: Principal, tool: str, arg: str = "", **kwargs: Any) -> Any:
            if who.kind != "agent" or tool == "kb_toolset_enable":
                return original(who, tool, arg, **kwargs)
            assert who == principal, who  # 주체·attended가 그대로 넘어왔다
            try:
                result = original(who, tool, arg, **kwargs)
            except (PermissionDenied, ApprovalRequired) as exc:
                observed.setdefault(tool, []).append(exc.decision.to_dict())
                raise
            observed.setdefault(tool, []).append(result.to_dict())
            return result

        d.daemon.service.require = observe  # type: ignore[method-assign]
        with McpClient.start(
            spawned,
            ws,
            tmp_path / "mcp",
            "--unattended",
            "--agent-id",
            AGENT_ID,
            env=daemon_env(tmp_path),
        ) as mcp:
            mcp.initialize()
            mcp.data("kb_toolset_enable", {"toolsets": list(TOOLSETS)})
            for tool, _arg, make in CASES:
                result = mcp.call_tool(tool, make(ws, preset), timeout=120)
                code = (result.get("structuredContent") or {}).get("error", {}).get("code")
                if expected[tool]["final"] == "deny":
                    assert code == "permission_denied", (tool, result)
                    assert result["structuredContent"]["error"]["decision"] == expected[tool]
                else:
                    assert code not in ("permission_denied", "approval_required"), (tool, result)
            assert mcp.close() == 0
    for tool, _arg, _make in CASES:
        assert observed.get(tool), tool
        assert all(seen == expected[tool] for seen in observed[tool]), (tool, observed[tool])
