"""M5 완료 기준 (구현 계획 v0 1장 M5 행, M5 계획 5장) 인수 테스트, Python 쪽.

1. 외부 에이전트가 MCP로 그래프를 만들고 실행하고 실패를 분석한다 — 실제 `kookabug mcp` stdio +
   같은 프로세스 daemon + 실제 runner + 가짜 플랫폼(예제 게임 장면 표). 계획 9절대로 둘로 나눈다:
   비밀값을 다루지 않는 실패(이미지·비교 성공)와 비밀번호를 호출 인자로 받는 예제 로그인 실패(노드·
   출구·가린 메시지·증거 거부)
2. 권한 거부가 집행된다 — 실행 deny·사람 없는 ask·control deny·`AGENT_DENIED`·승인 거부·시간 초과·
   screens deny(직접 RPC)·glob 문자 경로의 "항상 허용"이 다른 파일로 번지지 않음. 모두 아무것도
   바꾸지 않는다(파일 바이트·실행 폴더·입력 기록)
3. 같은 행위가 CLI·daemon(MCP)에서 같은 권한 판정, `kookabug mcp`가 주체·attended를 그대로 넘김
4. UI와 에이전트가 동시에 고치면 늦은 쪽이 거부된다 (양쪽 순서·승인 대기 중 UI 저장·agent force)
5. 판단 노드의 에이전트에는 제어 도구가 없다 — 예제 워크스페이스 그래프를 실제 runner로 돌려 선택지
   출구로 이어지는 것까지
(엄격) 녹화·실행·임대권 중 에이전트 입력 금지·키 남지 않음·control만 허용해도 제어 가능, 에이전트로
비밀값 원문이 나가지 않음

실제 SendInput 게임 조작은 `kookabug_mcp/tests/test_control_live.py`(desktop_input, 조율자 실행),
실제 에이전트 CLI·실제 모델 API는 `Docs/verification/m5-manual.md`다. 다른 테스트 모듈을 import하지
않는다. 자세한 경우는 근거 테스트(`kookabug_mcp/tests/*`, `kookabug_daemon/tests/test_{approvals,
agent_view,control_methods,graph_patch,screens_methods}.py`, `kookabug_core/tests/record/
test_agent_mask.py`, `kookabug_nodes/tests/test_agent_judge.py`)에 있다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import shutil
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env, run_cli
from helpers.daemon_runs import TEST, RunRig
from helpers.graphs import (
    GraphBuilder,
    link,
    secret,
    setting,
    subgraph_interface,
    write_json,
)
from helpers.run import tk
from helpers.runner import RUNNER_CMD

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace, daemon_env
from kb_testing.fake_model_api import FakeModelApi
from kb_testing.mcp_client import McpClient
from kb_testing.packaging import REPO_ROOT
from kb_testing.proc import Spawned, read_fake_input_log, wait_until
from kb_testing.sample_game import EXAMPLE_SECRET_ENV, EXAMPLE_SECRETS, copy_example_workspace
from kookabug_core.documents import ENTRY_NODE, template
from kookabug_core.inputs import InputLease, LeaseOwner, create_backend
from kookabug_core.inputs.lease import LEASE_NAME_ENV, STATE_DIR_ENV
from kookabug_core.permissions import PRESETS, TOOLSETS, Principal
from kookabug_core.service import (
    RUN_START_TOOL,
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
    cli_principal,
)
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.runs import RunManager

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

AGENT_ID: Final = "m5-agent"
GRAPH: Final = "tests/inventory_open.graph.json"
PASS_GRAPH: Final = "tests/m5_pass.graph.json"
WINDOW: Final = "SampleRPG"
WAIT_MS: Final = 30_000
FAKE_AGENT: Final = REPO_ROOT / "tools" / "kb_testing" / "fake_acp_agent.py"
EXAMPLE_PW: Final = EXAMPLE_SECRETS["accounts.qa_tester_01"]
PW: Final = "hunter2-m5"


def agent_hello(agent_id: str = AGENT_ID, *, attended: bool = True) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": agent_id, "attended": attended}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_local(root: Path, permissions: Mapping[str, Any] | None) -> None:
    """`.kookabug/local.json`의 `permissions`만 바꾼다 (다른 키 그대로)."""
    path = root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body: dict[str, Any] = (
        json.loads(path.read_text("utf-8")) if path.exists() else {"format": "kookabug.local/0"}
    )
    if permissions is None:
        body.pop("permissions", None)
    else:
        body["permissions"] = dict(permissions)
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def refused(
    client: DaemonClient, method: str, params: Mapping[str, Any] | None = None
) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, dict(params or {}), timeout=120)
    return caught.value


def notification(client: DaemonClient, method: str, timeout: float = 15) -> dict[str, Any]:
    """그 이름의 다음 알림 params (다른 알림은 버린다)."""
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == method:
            return message["params"]
    raise AssertionError(f"{timeout}초 안에 {method} 알림이 오지 않았다")


def error_of(future: Future[Any], timeout: float = 60) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        future.result(timeout)
    return caught.value


def patch_params(root: Path, rel: str = GRAPH, title: str = "에이전트") -> dict[str, Any]:
    return {
        "path": rel,
        "base_revision": sha(root / rel),
        "ops": [{"op": "set_meta", "title": title}],
    }


def balanced(inputs: list[dict[str, Any]]) -> bool:
    """누른 키·버튼이 모두 떼어졌다."""
    held: dict[tuple[str, str], int] = {}
    for line in inputs:
        key = (str(line.get("device")), str(line.get("key") or line.get("button")))
        if line["op"] == "down":
            held[key] = held.get(key, 0) + 1
        elif line["op"] == "up":
            held[key] = held.get(key, 0) - 1
    return all(v <= 0 for v in held.values())


def run_folder(root: Path, run_id: str) -> Path:
    (folder,) = [p for p in (root / "runs").iterdir() if p.name.endswith(f"_{run_id}")]
    return folder


def events_of(root: Path, run_id: str) -> list[dict[str, Any]]:
    text = (run_folder(root, run_id) / "events.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def wait_ended(client: DaemonClient, run_id: str) -> None:
    wait_until(
        lambda: client.call("run.status", {"run_id": run_id})["state"] == "ended",
        timeout=90,
        interval=0.1,
    )


# ---------------------------------------------------------------- 실행 환경


@dataclass
class ControlRig:
    """예제 워크스페이스 사본 + 이미 떠 있는 SampleRPG(가짜 장면 표 `running`) + 가짜 입력 기록."""

    root: Path
    env: dict[str, str]
    platform: Path
    input_log: Path

    def daemon(self, **kwargs: Any) -> ThreadDaemon:
        supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=self.env)
        service = WorkspaceService(self.root, environ=self.env, supervisor=supervisor)
        return ThreadDaemon(self.root, service=service, platform_fake=self.platform, **kwargs)

    def inputs(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.input_log)

    def run_folders(self) -> list[Path]:
        runs = self.root / "runs"
        return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


def control_rig(
    tmp_path: Path,
    permissions: Mapping[str, Any] | None,
    hooks: Mapping[str, Mapping[str, str]] | None = None,
) -> ControlRig:
    root = copy_sample_workspace(tmp_path / "ws")
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    scenario = json.loads((frames / "scenario.json").read_text(encoding="utf-8"))
    scenario["running"] = True
    (frames / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    log = tmp_path / "input.jsonl"
    spec = tmp_path / "platform.json"
    body = {
        "scenario": str(frames / "scenario.json"),
        "input_log": str(log),
        "hooks": {k: dict(v) for k, v in (hooks or {}).items()},
    }
    spec.write_text(json.dumps(body), encoding="utf-8")
    write_local(root, permissions)
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return ControlRig(root, env, spec, log)


@pytest.fixture
def example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(key, value)  # daemon 사전 검증 (이 프로세스)
    return copy_example_workspace(tmp_path)


def example_daemon(root: Path, tmp_path: Path, **env: str) -> ThreadDaemon:
    environ = {
        **cli_env(tmp_path),
        **EXAMPLE_SECRET_ENV,
        "KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user"),
        **env,
    }
    service = WorkspaceService(
        root, environ=environ, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=environ)
    )
    return ThreadDaemon(
        root, service=service, platform_fake=root / "fake-platform.json", agent_toolsets=("core",)
    )


@pytest.fixture
def start_mcp(spawned: Spawned, tmp_path: Path) -> Iterator[Callable[..., McpClient]]:
    clients: list[McpClient] = []

    def start(root: Path, *args: str) -> McpClient:
        out = tmp_path / f"mcp{len(clients)}"
        client = McpClient.start(spawned, root, out, *args, env=daemon_env(tmp_path))
        clients.append(client)
        client.initialize()
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)


def run_and_wait(mcp: McpClient, path: str, key: str) -> dict[str, Any]:
    started = mcp.data("kb_run_start", {"path": path, "idempotency_key": key})
    status = mcp.data("kb_run_status", {"run": started["run"], "wait_ms": WAIT_MS})
    assert status["state"] == "ended", status
    return status


# ---------------------------------------------------------------- 1 MCP로 만들고 실행하고 분석


def title_ops(target: str) -> list[dict[str, Any]]:
    """게임을 띄우고 타이틀의 `target`을 기다린다 (없으면 timeout fail — 증거 스크린샷)."""
    return [
        {
            "op": "add_node",
            "ref": "launch",
            "type": "core.app.launch",
            "title": "게임 띄우기",
            "in": {
                "args": setting("game.args"),
                "cwd": setting("game.cwd"),
                "path": setting("game.executable"),
                "timeout_ms": 30000,
                "window_title": setting("game.title"),
            },
        },
        {
            "op": "add_node",
            "ref": "wait",
            "type": "core.image.wait",
            "title": "시작 단추 기다리기",
            "in": {"target": {"$target": target}, "timeout_ms": 3000},
        },
        {"op": "add_node", "ref": "ok", "type": "core.test.pass"},
        {"op": "connect", "from": "n_entry", "exit": "start", "to": "launch"},
        {"op": "connect", "from": "launch", "exit": "attached", "to": "wait"},
        {"op": "connect", "from": "wait", "exit": "found", "to": "ok"},
    ]


def test_agent_builds_runs_and_analyzes_via_mcp(
    example: Path, tmp_path: Path, start_mcp: Callable[..., McpClient]
) -> None:
    """완료 기준 1 (비밀값을 다루지 않는 실패): 툴셋 켜기 → 만들기 → 실행 통과 → 고쳐서 깨뜨리기 →
    실행 실패 → 실패 요약·이벤트·증거 이미지·지난 성공과 비교."""
    new = "tests/agent_title.graph.json"
    write_local(example, {"preset": "full"})
    with example_daemon(example, tmp_path):
        mcp = start_mcp(example)
        core = set(mcp.tool_names())
        assert "kb_graph_create" not in core and "kb_project_info" in core
        enabled = mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit", "run"]})
        assert {"kb_graph_create", "kb_graph_patch", "kb_run_start"} <= set(enabled["tools"])
        assert {"kb_graph_patch", "kb_run_compare"} <= set(mcp.tool_names())

        created = mcp.data(
            "kb_graph_create",
            {
                "path": new,
                "kind": "test",
                "title": "에이전트가 만든 타이틀 확인",
                "ops": title_ops("targets/title/start_button.target.json"),
            },
        )
        wait_id = created["created"]["wait"]
        checked = mcp.data("kb_graph_validate", {"path": new})
        assert all(d["severity"] != "error" for d in checked["diagnostics"]), checked
        passed = run_and_wait(mcp, new, "m5-pass")
        assert passed["outcome"]["verdict"] == "pass", passed

        # 에이전트가 target을 바꿔 깨뜨린다 (기준 revision 필수)
        got = mcp.data("kb_graph_get", {"path": new})
        broken_target = {"$target": "targets/broken/start_button_swapped.target.json"}
        mcp.data(
            "kb_graph_patch",
            {
                "path": new,
                "base_revision": got["revision"],
                "ops": [{"op": "set_node", "id": wait_id, "in": {"target": broken_target}}],
            },
        )
        failed = run_and_wait(mcp, new, "m5-fail")
        assert failed["outcome"]["verdict"] == "fail"
        failure = failed["failure"]
        assert failure["classified"] is True
        assert failure["failure"]["node"] == wait_id and failure["failure"]["exit"] == "timeout"
        assert failure["failure_path"] == [wait_id]
        assert failure["last_success"] == passed["run_id"]
        shot = next(p for p in failure["evidence"] if p.endswith(".png"))

        events = mcp.data("kb_run_events", {"run": failed["run_id"], "kinds": ["step.end"]})
        wait_end = next(e for e in events["events"] if e["step"] == failure["failure"]["step"])
        assert (wait_end["status"], wait_end["exit"]) == ("fail", "timeout")

        result = mcp.call_tool("kb_run_artifact_get", {"run": failed["run_id"], "path": shot})
        assert result["isError"] is False, result
        (image,) = [c for c in result["content"] if c["type"] == "image"]
        data = base64.b64decode(image["data"])
        pixels = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        assert pixels is not None and max(pixels.shape[:2]) <= 1568
        assert len(data) <= 1024 * 1024

        diff = mcp.data("kb_run_compare", {"run": failed["run_id"]})
        assert diff["baseline"] == passed["run_id"]
        assert diff["screen"]["step"] == failure["failure"]["step"]
        found = mcp.data("kb_log_search", {"query": "timeout"})
        assert isinstance(found["matches"], list)
        assert mcp.close() == 0
        mcp.assert_protocol_only()


def test_agent_analyzes_secret_login_failure_via_mcp(
    example: Path, tmp_path: Path, start_mcp: Callable[..., McpClient]
) -> None:
    """완료 기준 1 (계획 9절 B6 메모): 비밀번호를 호출 인자로 받는 예제 로그인 실패 — 실패
    노드·출구는 주고, 메시지는 가리고, 비밀 호출 안쪽 증거는 주지 않는다(`[]`·`secret_step`)."""
    broken = "tests/broken/swapped_target.graph.json"
    write_local(example, {"preset": "runner"})
    with example_daemon(example, tmp_path):
        mcp = start_mcp(example)
        mcp.data("kb_toolset_enable", {"toolsets": ["run"]})
        status = run_and_wait(mcp, broken, "m5-login")
        assert status["outcome"]["verdict"] == "fail"
        summary = status["failure"]
        assert summary["failure_path"][0] == "n_enter_world"
        # 실패 위치 "월드 접속 > 타이틀 대기" (예제 깨진 각본 설명)
        assert summary["failure_path"] == ["n_enter_world", "n_wait_title"]
        assert summary["failure"]["node"] == "n_wait_title"
        assert summary["failure"]["exit"] == "timeout"
        assert summary["evidence"] == []  # 비밀값을 받은 호출 스텝 안쪽 이미지는 주지 않는다
        run_id = status["run_id"]
        # 안쪽 스텝의 증거 파일은 디스크에 있지만 에이전트에게는 secret_step
        inner = [
            path
            for e in events_of(example, run_id)
            if e["event"] == "step.end"
            for path in e.get("artifacts", ())
        ]
        assert inner, "안쪽 스텝 증거가 기록에 없다"
        for path in inner:
            error = mcp.error("kb_run_artifact_get", {"run": run_id, "path": path})
            assert error["code"] == "secret_step", (path, error)
        seen = json.dumps(
            [
                status,
                mcp.data("kb_run_events", {"run": run_id, "limit": 500}),
                mcp.data("kb_log_search", {"query": "sample"}),
                mcp.data("kb_run_status"),
            ],
            ensure_ascii=False,
        )
        assert EXAMPLE_PW not in seen
        # 사람이 보는 기록에는 원문 그대로 있다 (D3 — 가림은 에이전트로 나가는 길에만)
        assert EXAMPLE_PW in (run_folder(example, run_id) / "events.jsonl").read_text("utf-8")
        assert mcp.close() == 0


# ---------------------------------------------------------------- 2 권한 거부


def test_denials_change_nothing(tmp_path: Path) -> None:
    rig = control_rig(tmp_path, None)  # 기본 프리셋 graph_author
    graph = rig.root / GRAPH
    old_ns = 1_600_000_000 * 10**9
    os.utime(graph, ns=(old_ns, old_ns))
    before, mtime = graph.read_bytes(), graph.stat().st_mtime_ns
    night = agent_hello("night", attended=False)
    with rig.daemon(approval_timeout_s=1.5) as d:
        with d.client(night) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": list(TOOLSETS)})
            # 실행 deny: 실행 폴더가 생기지 않는다
            error = refused(agent, "run.start", {"path": "tests/smoke_headless.graph.json"})
            assert error.kind == "permission_denied"
            assert error.data["decision"]["source"] == "preset:graph_author"
            # 사람 없는 ask = deny
            error = refused(agent, "graph.patch", patch_params(rig.root))
            assert (error.kind, error.data["decision"]["reason"]) == (
                "permission_denied",
                "unattended_ask",
            )
            error = refused(agent, "graph.create", {"path": "tests/new.graph.json", "kind": "test"})
            assert error.kind == "permission_denied"
            # control deny: 입력 없음
            for method, params in (
                ("control.click", {"window": WINDOW, "point": [5, 5]}),
                ("control.key", {"window": WINDOW, "keys": "a"}),
                ("control.type", {"window": WINDOW, "text": "x"}),
                ("app.launch", {}),
            ):
                assert refused(agent, method, params).kind == "permission_denied", method
            # 사람만 쓰는 메서드 (판정 전 거부)
            for method, params in (
                ("approval.list", {}),
                ("approval.respond", {"id": "ap_0000000000000000", "verdict": "allow_once"}),
                (
                    "permissions.set",
                    {"layer": "project", "permissions": {"preset": "full"}, "base_revision": None},
                ),
                ("agent.connections", {}),
                ("agents.get", {}),
                ("agents.detect", {}),
                ("daemon.shutdown", {}),
            ):
                assert refused(agent, method, params).kind == "permission_denied", method
            assert refused(agent, "run.index", {"run_id": "abcd1234"}).kind == (
                "agent_use_safe_api"
            )
            assert d.is_running()

        # screens deny: 직접 RPC로도 집행 (workspace.* 길로 돌아가지 못함)
        write_local(rig.root, {"preset": "graph_author", "toolsets": {"screens": "deny"}})
        with d.client(agent_hello("screens")) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": ["screens"]})
            screen = "screens/login.screen.json"
            assert refused(agent, "screens.list", {}).kind == "permission_denied"
            assert refused(agent, "screens.get", {"path": screen}).kind == "permission_denied"
            assert refused(agent, "workspace.read", {"path": screen}).kind == "permission_denied"
            entries = agent.call("workspace.tree")["entries"]
            assert not [e for e in entries if e["path"].casefold().startswith("screens")]
        write_local(rig.root, None)

        # 사람 확인: 거부·시간 초과는 아무것도 바꾸지 않는다
        with d.client() as ui, d.client(agent_hello()) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": list(TOOLSETS)})
            pending = agent.request("graph.patch", patch_params(rig.root))
            asked = notification(ui, "approval.requested")
            ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
            assert error_of(pending).kind == "approval_denied"
            pending = agent.request(
                "graph.create", {"path": "tests/new.graph.json", "kind": "test"}
            )
            notification(ui, "approval.requested")
            assert error_of(pending).kind == "approval_timeout"
            assert notification(ui, "approval.resolved")["verdict"] == "timeout"

            # "항상 허용"은 glob 문자 경로 그 파일 하나에만
            glob_rel, a_rel, b_rel = (
                "tests/[ab].graph.json",
                "tests/a.graph.json",
                "tests/b.graph.json",
            )
            for rel in (glob_rel, a_rel, b_rel):
                opened = ui.call("graph.create", {"path": rel, "kind": "test"})
                ui.call("graph.close", {"doc_id": opened["doc_id"]})
            pending = agent.request("graph.patch", patch_params(rig.root, glob_rel))
            asked = notification(ui, "approval.requested")
            assert asked["always_rule"] == "kb_graph_patch(tests/[[]ab].graph.json)"
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_always"})
            pending.result(30)
            agent.call("graph.patch", patch_params(rig.root, glob_rel, "다시"))  # 묻지 않음
            for rel in (a_rel, b_rel):
                kept = (rig.root / rel).read_bytes()
                pending = agent.request("graph.patch", patch_params(rig.root, rel))
                asked = notification(ui, "approval.requested")
                assert asked["arg"] == rel
                ui.call("approval.respond", {"id": asked["id"], "verdict": "deny"})
                assert error_of(pending).kind == "approval_denied"
                assert (rig.root / rel).read_bytes() == kept
    assert graph.read_bytes() == before and graph.stat().st_mtime_ns == mtime
    assert not (rig.root / "tests" / "new.graph.json").exists()
    assert rig.run_folders() == []
    assert rig.inputs() == []
    rules = json.loads((rig.root / ".kookabug" / "local.json").read_text("utf-8"))
    assert rules["permissions"]["rules"] == [
        {"rule": "kb_graph_patch(tests/[[]ab].graph.json)", "verdict": "allow"}
    ]


# ---------------------------------------------------------------- 3 CLI·MCP 같은 판정, 주체 전달


def _patch_args(ws: Path) -> dict[str, Any]:
    return {
        "path": GRAPH,
        "base_revision": sha(ws / GRAPH),
        "ops": [{"op": "set_meta", "title": "m5"}],
    }


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
    write_local(ws, {"preset": preset})
    return ws


@pytest.mark.parametrize("preset", PRESETS)
def test_same_decision_cli_and_mcp_all_presets(
    tmp_path: Path, spawned: Spawned, preset: str
) -> None:
    """CLI 경로: 실제 `kookabug run` 하위 프로세스(`KOOKABUG_AGENT` — 늘 사람 없음)와 CLI가 쓰는
    주체 함수(`cli_principal`)로 본 서비스 판정. MCP 경로: 실제 `kookabug mcp --unattended
    --agent-id <같은 ID>` → daemon이 집행한 판정(서비스 `require`가 돌려준 값·예외에 실은 값)."""
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


def test_mcp_principal_passthrough(tmp_path: Path, start_mcp: Callable[..., McpClient]) -> None:
    """daemon이 본 주체 = `--agent-id`·`--unattended` 그대로. attended면 ask가 사람 확인으로(사람
    연결이 없으면 `no_approver`), `--unattended`면 같은 ask가 deny(`unattended_ask`)."""
    ws = copy_sample_workspace(tmp_path / "ws")
    before = (ws / GRAPH).read_bytes()
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core",)) as d:
        panel = start_mcp(ws, "--agent-id", "panel:s1", "--client", "panel")
        night = start_mcp(ws, "--agent-id", "ci-1", "--unattended")
        default = start_mcp(ws)
        infos = {name: m.data("kb_project_info")["principal"] for name, m in
                 (("panel", panel), ("night", night), ("default", default))}  # fmt: skip
        assert infos["panel"] == {"kind": "agent", "id": "panel:s1", "attended": True}
        assert infos["night"] == {"kind": "agent", "id": "ci-1", "attended": False}
        assert infos["default"] == {"kind": "agent", "id": f"mcp:{default.proc.pid}",
                                    "attended": True}  # fmt: skip
        seen = {
            c.principal.id: (c.principal, c.client_name)
            for c in d.daemon.transport.connections
            if c.principal is not None and c.principal.kind == "agent"
        }
        assert seen["panel:s1"] == (Principal("agent", "panel:s1", attended=True), "panel")
        assert seen["ci-1"] == (Principal("agent", "ci-1", attended=False), "mcp")
        for mcp, code, reason in (
            (panel, "approval_required", "preset"),
            (night, "permission_denied", "unattended_ask"),
        ):
            mcp.data("kb_toolset_enable", {"toolsets": ["graph_edit"]})
            base = mcp.data("kb_graph_get", {"path": GRAPH})["revision"]
            error = mcp.error(
                "kb_graph_patch",
                {"path": GRAPH, "base_revision": base, "ops": [{"op": "set_meta", "title": "x"}]},
            )
            assert (error["code"], error["decision"]["reason"]) == (code, reason)
        # 툴셋은 연결마다: 기본 연결은 graph_edit를 켜지 않았다
        error = default.error("kb_graph_patch", _patch_args(ws))
        assert error["code"] in ("toolset_disabled", "not_available"), error
        for mcp in (panel, night, default):
            assert mcp.close() == 0
    assert (ws / GRAPH).read_bytes() == before


# ---------------------------------------------------------------- 4 동시 편집


def test_concurrent_ui_and_agent_edit_late_rejected(tmp_path: Path) -> None:
    ws = copy_sample_workspace(tmp_path / "ws")
    environ = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    graph = ws / GRAPH
    write_local(ws, {"preset": "full"})
    with ThreadDaemon(ws, environ=environ, agent_toolsets=("core", "graph_edit")) as d:
        with d.client() as ui, d.client(agent_hello()) as agent:
            for first in ("ui", "agent"):
                opened = ui.call("graph.open", {"path": GRAPH})
                base = opened["revision"]

                def ui_save(
                    opened: dict[str, Any] = opened, base: str = base, first: str = first
                ) -> None:
                    value = dict(opened["value"])
                    value["meta"] = {**value["meta"], "title": f"사람 {first}"}
                    ui.call(
                        "graph.save",
                        {"doc_id": opened["doc_id"], "value": value, "base_revision": base},
                    )

                def agent_patch(base: str = base, first: str = first) -> None:
                    ops = [{"op": "set_meta", "title": f"에이전트 {first}"}]
                    agent.call("graph.patch", {"path": GRAPH, "base_revision": base, "ops": ops})

                early, late = (ui_save, agent_patch) if first == "ui" else (agent_patch, ui_save)
                early()
                winner = graph.read_bytes()
                with pytest.raises(DaemonError) as caught:
                    late()
                assert caught.value.kind == "revision_conflict", first
                assert graph.read_bytes() == winner
                ui.call("graph.close", {"doc_id": opened["doc_id"]})

            # 에이전트는 덮어쓰기(force)를 못 한다 — 사람만 고른다
            opened = agent.call("graph.open", {"path": GRAPH})
            value = {**opened["value"], "meta": {"title": "덮어쓰기"}}
            kept = graph.read_bytes()
            for base in ("0" * 64, opened["revision"]):
                error = refused(
                    agent,
                    "graph.save",
                    {"doc_id": opened["doc_id"], "value": value, "base_revision": base,
                     "force": True},
                )  # fmt: skip
                assert error.kind == "force_not_allowed"
            assert graph.read_bytes() == kept
            agent.call("graph.close", {"doc_id": opened["doc_id"]})

        # 승인 대기 중 UI가 저장하면 승인 뒤 쓰기가 늦은 쪽으로 거부
        write_local(ws, {"preset": "graph_author"})
        with d.client() as ui, d.client(agent_hello()) as agent:
            agent.call("agent.toolsets.enable", {"toolsets": ["graph_edit"]})
            pending = agent.request("graph.patch", patch_params(ws))
            asked = notification(ui, "approval.requested")
            opened = ui.call("graph.open", {"path": GRAPH})
            value = {
                **opened["value"],
                "meta": {**opened["value"]["meta"], "title": "사람 대기 중"},
            }
            ui.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
            human = graph.read_bytes()
            ui.call("approval.respond", {"id": asked["id"], "verdict": "allow_once"})
            assert error_of(pending).kind == "revision_conflict"
            assert graph.read_bytes() == human


# ---------------------------------------------------------------- 5 판단 노드


def judge_graph(node: dict[str, Any]) -> dict[str, Any]:
    """예제 게임을 띄우고 화면을 캡처해 판단 (`title` → 통과, `loading`·`unsure` → 실패)."""
    nodes: dict[str, Any] = {
        ENTRY_NODE: {"type": "core.graph.entry", "version": 1, "next": {"start": "n_launch"}},
        "n_launch": {
            "type": "core.app.launch",
            "version": 1,
            "in": {
                "args": setting("game.args"),
                "cwd": setting("game.cwd"),
                "path": setting("game.executable"),
                "timeout_ms": 30000,
                "window_title": setting("game.title"),
            },
            "next": {"attached": "n_shot"},
        },
        "n_shot": {"type": "core.screen.capture", "version": 1, "next": {"done": "n_judge"}},
        "n_judge": {
            "version": 1,
            **node,
            "next": {"title": "n_pass", "loading": "n_fail", "unsure": "n_fail"},
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
        "n_fail": {"type": "core.test.fail", "version": 1, "in": {"reason": "다른 답"}},
    }
    value = template("test")
    value.pop("layout")
    value["nodes"] = nodes
    return value


def test_judge_nodes_get_no_control_tools(
    example: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "sk-m5-SECRET-0123456789"
    monkeypatch.setenv("KOOKABUG_SECRET_MODEL_KEY", key)
    user = tmp_path / "user"
    user.mkdir()
    log, script = tmp_path / "agent.jsonl", tmp_path / "script.json"
    agent_env = {"KB_FAKE_ACP_SCRIPT": str(script), "KB_FAKE_ACP_LOG": str(log)}
    settings = {
        "format": "kookabug.user-settings/0",
        "agents": [
            {
                "id": "fake",
                "name": "가짜",
                "command": sys.executable,
                "args": [str(FAKE_AGENT)],
                "env": agent_env,
            }
        ],
    }
    (user / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), "utf-8")
    script.write_text(
        json.dumps(
            {
                "steps": [
                    {"do": "permission"},
                    {"do": "answer", "answer": "title", "reason": "시작 화면"},
                ]
            }
        ),
        encoding="utf-8",
    )
    choices = {"choices": ["title", "loading"]}
    cli = {"type": "core.agent.cli_judge", "in": {"prompt": "지금 화면은?",
           "image": link("n_shot.image")}, "config": {**choices, "agent": "fake"}}  # fmt: skip
    (example / "tests" / "judge_cli.graph.json").write_text(json.dumps(judge_graph(cli)), "utf-8")
    secret_env = {"KOOKABUG_SECRET_MODEL_KEY": key, "KOOKABUG_RPC_KEY": "rpc-token-m5"}
    with FakeModelApi('{"answer": "title", "reason": "제목"}') as api:
        api_node = {
            "type": "core.agent.api_judge",
            "in": {"prompt": "지금 화면은?", "image": link("n_shot.image"),
                   "model": "m-1", "api_key": secret("model.key")},
            "config": {**choices, "provider": "anthropic", "endpoint": api.base},
        }  # fmt: skip
        (example / "tests" / "judge_api.graph.json").write_text(
            json.dumps(judge_graph(api_node)), "utf-8"
        )
        with example_daemon(example, tmp_path, **secret_env) as d, d.client() as ui:
            ran = {}
            for name in ("judge_cli", "judge_api"):
                run_id = ui.call("run.start", {"path": f"tests/{name}.graph.json"})["run_id"]
                wait_ended(ui, run_id)
                ran[name] = run_id
                events = events_of(example, run_id)
                (end,) = [e for e in events if e["event"] == "run.end"]
                assert end["verdict"] == "pass", end
                step = next(
                    e["step"]
                    for e in events
                    if e["event"] == "step.start" and e["node"] == "n_judge"
                )
                (judged,) = [e for e in events if e["event"] == "step.end" and e["step"] == step]
                assert judged["exit"] == "title"  # 예제 그래프의 판단 노드가 선택지 출구로
                assert (run_folder(example, run_id) / "steps" / f"{step}_judge.json").is_file()
        (request,) = api.requests
    # api: 요청 본문에 도구 정의가 없다
    body = request["body"]
    assert not {"tools", "tool_choice", "functions"} & set(body)
    assert body["model"] == "m-1"
    # cli: MCP 서버 없음, fs·terminal 능력 없음, 권한 요청 거절, 빈 임시 폴더, KOOKABUG_* 없음
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    (init,) = [e for e in lines if e.get("method") == "initialize"]
    assert init["params"]["clientCapabilities"] == {
        "fs": {"readTextFile": False, "writeTextFile": False},
        "terminal": False,
    }
    (new,) = [e for e in lines if e.get("method") == "session/new"]
    assert new["params"]["mcpServers"] == []
    (start,) = [e for e in lines if e["event"] == "start"]
    assert start["cwd_entries"] == [] and not Path(start["cwd"]).exists()
    assert not Path(start["cwd"]).resolve().is_relative_to(example.resolve())
    assert list(start["env"]) == ["KOOKABUG_AGENT"]
    assert start["env"]["KOOKABUG_AGENT"].startswith(f"judge:{ran['judge_cli']}:")
    perms = [
        e["result"]["outcome"]
        for e in lines
        if e["event"] == "response" and e["method"] == "session/request_permission"
    ]
    assert perms == [{"outcome": "selected", "optionId": "reject"}]  # 거절 선택지
    # 에이전트(판단 결과 포함)로 키가 새지 않는다
    for name in ("judge_cli", "judge_api"):
        assert key not in (run_folder(example, ran[name]) / "events.jsonl").read_text("utf-8")
    assert key not in log.read_text(encoding="utf-8")


# ---------------------------------------------------------------- (엄격) 게임 조작


def test_agent_input_blocked_by_lease_and_recording(tmp_path: Path) -> None:
    rig = control_rig(tmp_path, {"preset": "full"})
    click = {"window": WINDOW, "point": [512, 412]}
    agent = agent_hello("ctl", attended=False)
    with rig.daemon() as d, d.client() as ui, d.client(agent) as bot:
        bot.call("agent.toolsets.enable", {"toolsets": ["control"]})
        # 녹화 중 (starting·recording·paused)
        manager: RunManager = d.daemon.run_manager
        reservation = manager.reserve_recording()
        try:
            for state in ("starting", "recording", "paused"):
                if state != "starting":
                    reservation.set_state(state)
                error = refused(bot, "control.click", click)
                assert (error.kind, error.data["state"]) == ("recording_active", state)
                assert refused(bot, "app.launch", {}).kind == "recording_active"
        finally:
            reservation.release()
        # 실행 중
        wait = template("test")
        wait.pop("layout")
        wait["nodes"] = {
            ENTRY_NODE: {"type": "core.graph.entry", "version": 1, "next": {"start": "n_d"}},
            "n_d": {"type": "core.flow.delay", "version": 1, "in": {"ms": 60_000},
                    "next": {"done": "n_p"}},
            "n_p": {"type": "core.test.pass", "version": 1},
        }  # fmt: skip
        (rig.root / "tests" / "wait.graph.json").write_text(json.dumps(wait), "utf-8")
        started = ui.call("run.start", {"path": "tests/wait.graph.json"})
        try:
            error = refused(bot, "control.key", {"window": WINDOW, "keys": "a"})
            assert (error.kind, error.data["run_id"]) == ("run_busy", started["run_id"])
        finally:
            ui.call("run.cancel", {"run_id": started["run_id"]})
            wait_ended(ui, started["run_id"])
        # 다른 주체가 입력 임대권을 쥐고 있음 (같은 임대권 이름·상태 폴더)
        other_dir = tmp_path / "other-run"
        other_dir.mkdir()
        backend = create_backend(
            "fake", input_log=tmp_path / "other.jsonl", run="othr0001", by="other",
            hooks=None, gate=threading.Event(),
        )  # fmt: skip
        owner = LeaseOwner.current("runner", run_id="othr0001", run_dir=other_dir)
        lease = InputLease(
            owner,
            backend,
            name=rig.env[LEASE_NAME_ENV],
            directory=Path(rig.env[STATE_DIR_ENV]),
        )
        lease.acquire()
        try:
            assert refused(bot, "control.click", click).kind == "input_lease_busy"
        finally:
            lease.release(None)
        assert rig.inputs() == []
        # 비면 된다: 누른 것은 모두 뗀다
        done = bot.call("control.click", click, timeout=120)
        assert done["verdict"] == "pass", done
        assert rig.inputs() and balanced(rig.inputs())

    # runner가 입력 도중 죽어도 키가 남지 않는다 (감독자가 뗀다)
    hung = control_rig(tmp_path / "hang", {"preset": "full"}, {"after_down": {"ctrl": "hang"}})
    with hung.daemon() as d, d.client(agent) as bot:
        bot.call("agent.toolsets.enable", {"toolsets": ["control"]})
        manager = d.daemon.run_manager
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["result"] = bot.call(
                    "control.key", {"window": WINDOW, "keys": "ctrl+a"}, timeout=120
                )
            except BaseException as exc:
                box["error"] = exc

        worker = threading.Thread(target=call)
        worker.start()
        wait_until(lambda: any(x["op"] == "down" and x["key"] == "ctrl" for x in hung.inputs()))
        run_id = manager.active_run()
        assert run_id is not None
        handle = manager._runs[run_id].handle  # pyright: ignore[reportPrivateUsage]
        assert handle is not None and handle.runner_ident is not None
        os.kill(handle.runner_ident.pid, signal.SIGTERM)  # Windows: TerminateProcess
        worker.join(120)
        assert "error" not in box, box
        assert box["result"]["verdict"] == "error"
    inputs = hung.inputs()
    assert (inputs[-1]["op"], inputs[-1]["key"], inputs[-1]["by"]) == ("up", "ctrl", "supervisor")
    assert balanced(inputs)


def test_control_allowed_when_run_denied(
    tmp_path: Path, start_mcp: Callable[..., McpClient]
) -> None:
    """`control=allow, run=deny`: 실제 `kookabug mcp`로 게임 조작은 되고 실행은 거부 (제어 실행은
    `kb_run_start`로 다시 판정하지 않는다)."""
    rig = control_rig(tmp_path, {"preset": "read_only", "toolsets": {"control": "allow"}})
    with rig.daemon(agent_toolsets=("core",)):
        mcp = start_mcp(rig.root, "--unattended")
        mcp.data("kb_toolset_enable", {"toolsets": ["control", "run"]})
        done = mcp.data("kb_input_click", {"window": WINDOW, "point": [5, 5]})
        assert done["verdict"] == "pass", done
        error = mcp.error(
            "kb_run_start", {"path": "tests/smoke_headless.graph.json", "idempotency_key": "k"}
        )
        assert error["code"] == "permission_denied"
        assert error["decision"]["source"] == "preset:read_only"
        assert mcp.close() == 0
    (folder,) = rig.run_folders()
    data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert data["source"] == "agent_control"
    assert rig.inputs() and balanced(rig.inputs())


# ---------------------------------------------------------------- (엄격) 비밀값


def plant(root: Path, run_id: str, events: Iterable[Mapping[str, Any]], **run_json: Any) -> Path:
    """실행기 이벤트로 끝난 실행 폴더를 만든다 (`seq`·`t`·`run`을 붙인다)."""
    folder = root / "runs" / f"2026-11-06T01-00-00_t_{run_id}"
    folder.mkdir(parents=True)
    lines = [
        json.dumps({"t": "2026-11-06T01:00:00.001Z", **e, "seq": i, "run": run_id},
                   ensure_ascii=False)
        for i, e in enumerate(events, 1)
    ]  # fmt: skip
    (folder / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    data = {
        "format": "kookabug.run/0",
        "graph": TEST,
        "run_id": run_id,
        "started_at": "2026-11-06T01:00:00.001Z",
        "ended_at": "2026-11-06T01:00:00.500Z",
        "status": "finished",
        "conditions": {"deadline_ms": 1000, "platform": "fake", "profile": None, "settings": {}},
        **run_json,
    }
    (folder / "run.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return folder


SERVER_BOX: Final = (262, 200, 500, 64)
"""예제 게임 서버 선택 화면의 "Server 1" 줄 (민감 target으로 둔다)."""


def evidence_rig(tmp_path: Path, ocr_models: Path) -> RunRig:
    """비밀값이 `$link`(변수)·호출 인자로 들어간 스크린샷 스텝과 민감 target OCR 스텝이 있는
    그래프. 실제 daemon → runner → 워커로 돌고, 대역은 가짜 플랫폼(예제 게임 서버 선택 화면 프레임)
    뿐이다 — 찾기·OCR은 실제 엔진."""
    frame = REPO_ROOT / "fixtures" / "sample-game" / "frames" / "lobby.png"
    sub = "subgraphs/s.graph.json"
    server = "targets/server.target.json"
    graph = (
        tk()
        .entry("n_plain")
        .node("n_plain", "testkit.shot", inputs={"save": True, "name": "plain.png"},
              next={"done": "n_set"})
        .node("n_set", "core.var.set", inputs={"name": "pw", "value": secret("acc.pw")},
              next={"done": "n_use"})
        .node("n_get", "core.var.get", inputs={"name": "pw"})
        .node("n_use", "testkit.shot",
              inputs={"save": True, "name": "use.png", "value": link("n_get.value")},
              next={"done": "n_call"})
        .call("n_call", sub, inputs={"pw": secret("acc.pw")}, next={"done": "n_read"})
        .node("n_read", "core.ocr.read", inputs={"region": {"$target": server}},
              next={"done": "n_x"})
        .node("n_x", "core.test.fail", inputs={"reason": "끝"})
    )  # fmt: skip
    rig = RunRig.make(
        tmp_path,
        graph,
        KOOKABUG_SECRET_ACC_PW=PW,
        KOOKABUG_OCR_MODELS=str(ocr_models),
    )
    (
        tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"}))
        .entry("n_in")
        .node("n_in", "testkit.shot",
              inputs={"save": True, "name": "in.png", "value": link("n_entry.pw")},
              next={"done": "n_exit"})
        .exit("n_exit", "done")
    ).write(rig.root, sub)  # fmt: skip
    x, y, w, h = SERVER_BOX
    pixels = cv2.imdecode(np.frombuffer(frame.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert pixels is not None
    ok, crop = cv2.imencode(".png", pixels[y : y + h, x : x + w])
    assert ok
    path = write_json(rig.root, server, {"format": "kookabug.target/0", "image": "server.png",
                                         "sensitive": True})  # fmt: skip
    (path.parent / "server.png").write_bytes(crop.tobytes())
    spec = json.loads(rig.platform.read_text(encoding="utf-8"))
    spec["frames"] = [str(frame)]
    rig.platform.write_text(json.dumps(spec), encoding="utf-8")
    write_json(rig.root, ".kookabug/local.json",
               {"format": "kookabug.local/0", "permissions": {"preset": "full"}})  # fmt: skip
    return rig


def secret_run_graph() -> GraphBuilder:
    """비밀값이 입력·로그·실패 메시지·판정 사유로 들어가는 그래프 (끝은 fail)."""
    return (
        tk()
        .entry("n_take")
        .node("n_take", "testkit.sleep", inputs={"ms": 1, "value": secret("acc.pw")},
              next={"done": "n_log"})
        .node("n_log", "core.log.message", inputs={"text": secret("acc.pw")},
              next={"done": "n_cmp"})
        .node("n_cmp", "core.assert.compare", inputs={"a": secret("acc.pw"), "op": "==", "b": "x"})
    )  # fmt: skip


def test_agent_never_sees_secret_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", PW)
    rig = RunRig.make(tmp_path / "rig", secret_run_graph(), KOOKABUG_SECRET_ACC_PW=PW)
    write_json(rig.root, ".kookabug/local.json",
               {"format": "kookabug.local/0", "permissions": {"preset": "full"}})  # fmt: skip

    # ① 실제 runner 실행: 입력·로그·실패 메시지·판정 사유에 비밀값 (D3 — 기록에는 원문)
    agent = agent_hello()
    with rig.daemon() as d, d.client() as ui, d.client(agent) as bot:
        run_id = ui.call("run.start", {"path": TEST})["run_id"]
        wait_ended(ui, run_id)
        assert PW in ui.call("run.file", {"run_id": run_id, "name": "events_tail"})["text"]
        seen = [
            bot.call("run.events", {"run_id": run_id, "limit": 500}),
            bot.call("run.failure", {"run_id": run_id}),
            bot.call("run.status", {"run_id": run_id}),
            bot.call("run.list", {}),
            bot.call("run.search", {"query": PW}),
        ]
        assert PW not in json.dumps(seen, ensure_ascii=False)
        assert seen[1]["failure"]["node"] == "n_cmp" and seen[1]["reason"] == "***"
        assert seen[4]["matches"] == []
    # 실행 뒤 비밀값을 바꾸거나 지워도 가림은 그대로 (분류가 기록에 있다)
    for value in ("changed-value", None):
        if value is None:
            rig.env.pop("KOOKABUG_SECRET_ACC_PW", None)
            monkeypatch.delenv("KOOKABUG_SECRET_ACC_PW")
        else:
            rig.env["KOOKABUG_SECRET_ACC_PW"] = value
            monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", value)
        with rig.daemon() as d, d.client(agent) as bot:
            got = bot.call("run.events", {"run_id": run_id, "limit": 500})
            assert PW not in json.dumps(got, ensure_ascii=False)
            assert bot.call("run.failure", {"run_id": run_id})["reason"] == "***"

    # ② 증거 파일: $link(변수)·호출 인자로 받은 비밀 스텝, 민감 target OCR 글자 — 실제 runner가 쓴
    # 실행 폴더·증거 그대로
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", PW)
    ev = evidence_rig(tmp_path / "evidence", ocr_models)
    with ev.daemon() as d, d.client() as ui, d.client(agent) as bot:
        eng = ui.call("run.start", {"path": TEST})["run_id"]
        wait_ended(ui, eng)
        folder = run_folder(ev.root, eng)
        assert json.loads((folder / "run.json").read_text(encoding="utf-8"))["agent_mask"] == 1
        events = events_of(ev.root, eng)
        ends = {e["step"]: e for e in events if e["event"] == "step.end"}
        nodes = {e["step"]: e["node"] for e in events if e["event"] == "step.start"}
        by_node = {nodes[s]: ends[s] for s in ends if s in nodes}
        assert {"n_use", "n_in", "n_read", "n_x"} <= set(by_node), by_node
        ocr = by_node["n_read"]["outputs"]["text"]
        assert isinstance(ocr, str) and "Server" in ocr, ocr  # 실제 OCR, 사람 기록에는 원문 (D3)
        assert ocr in ui.call("run.file", {"run_id": eng, "name": "events_tail"})["text"]
        secret_shots = [*by_node["n_use"]["artifacts"], *by_node["n_in"]["artifacts"]]
        assert len(secret_shots) == 2, by_node
        withheld = [*secret_shots, *by_node["n_read"].get("artifacts", [])]
        for rel in withheld:
            assert (folder / rel).is_file(), rel
            error = refused(bot, "run.artifact", {"run_id": eng, "path": rel})
            assert error.kind == "secret_step", rel
        (plain,) = by_node["n_plain"]["artifacts"]
        assert bot.call("run.artifact", {"run_id": eng, "path": plain})["kind"] == "image"
        got = bot.call("run.events", {"run_id": eng, "limit": 500})
        failure = bot.call("run.failure", {"run_id": eng})
        assert not set(withheld) & set(failure["evidence"])
        text = json.dumps([got, failure], ensure_ascii=False)
        assert PW not in text and ocr not in text
        rel = f"runs/{folder.name}/{secret_shots[0]}"
        assert refused(bot, "target.load_image", {"path": rel}).kind == "agent_use_safe_api"

    # ③ 분류 없는 옛 기록 (M5 이전): 안전 필드만
    plant(
        rig.root,
        "olds0001",
        [
            {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}},
            {"event": "step.start", "attempt": 1, "node": "n_login", "parent": None,
             "path": ["n_login"], "step": "s1"},
            {"event": "log", "level": "info", "message": f"암호 {PW}", "node": "n_login",
             "step": "s1"},
            {"event": "step.end", "attempt": 1, "duration_ms": 5, "exit": None, "status": "error",
             "step": "s1", "outputs": {"text": PW},
             "error": {"code": "boom", "message": f"실패 {PW}"}},
            {"event": "run.end", "verdict": "error", "code": "boom", "reason": f"실패 {PW}",
             "failure_step": "s1", "failure_path": ["n_login"], "finalized_by": "runner",
             "duration_ms": 50},
        ],
        verdict="error",
        code="boom",
        reason=f"실패 {PW}",
    )  # fmt: skip
    with rig.daemon() as d, d.client(agent) as bot:
        old = bot.call("run.events", {"run_id": "olds0001"})
        assert old["classified"] is False
        assert PW not in json.dumps([old, bot.call("run.failure", {"run_id": "olds0001"})],
                                    ensure_ascii=False)  # fmt: skip
        assert "olds0001" in bot.call("run.search", {"query": "암호"})["skipped"]

        # 원문을 주는 기존 길은 agent에게 막혀 있다
        for method, params in (
            ("run.index", {"run_id": run_id}),
            ("run.children", {"run_id": run_id, "parent": "s1", "offset": 0, "limit": 10}),
            ("run.step", {"run_id": run_id, "step": "s1"}),
            ("run.file", {"run_id": run_id, "name": "events_tail"}),
            ("run.compare", {"run_id": run_id}),
            ("run.subscribe", {"run_id": run_id, "after_seq": 0}),
        ):
            assert refused(bot, method, params).kind == "agent_use_safe_api", method
