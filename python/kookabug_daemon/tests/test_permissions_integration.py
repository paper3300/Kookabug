"""M0b 완료 기준 6의 daemon 쪽 통합 검증 (M2 계획 2.5, T5).

- 실행 `kb_run_start(tests/t)`: 같은 정책 파일 계층에서 ① 실제 CLI 하위 프로세스
  `kookabug run`(`KOOKABUG_AGENT`), ② daemon agent 연결(attended false)의 `run.start`,
  ③ `WorkspaceService.authorize`의 판정이 같고 집행도 같다 (거부면 CLI 종료 코드 5·daemon
  `permission_denied`, 둘 다 실행 폴더 없음)
- 편집 `kb_graph_patch`·`kb_graph_create`·`kb_target_create`: ② daemon과 ③ 서비스의 판정이
  같고, 거부·승인 필요면 파일 바이트·mtime이 그대로다 (CLI에는 편집 명령이 없다)
- UI 연결은 같은 정책에서도 판정받지 않는다
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import run_cli
from helpers.daemon_runs import TEST, RunRig
from helpers.graphs import GraphBuilder

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import wait_until
from kookabug_core.permissions import Principal
from kookabug_core.service import (
    RUN_START_TOOL,
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
)
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.methods import Call, MethodSpec, registry

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

AGENT_ID = "agent-7"
OLD_NS = 1_600_000_000 * 10**9
NEW_GRAPH = "tests/agent_new.graph.json"
NEW_TARGET = "targets/agent_new.target.json"


def agent(*, attended: bool = False) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": AGENT_ID, "attended": attended}


def write_local(rig: RunRig, permissions: Mapping[str, Any] | None) -> None:
    path = rig.root / ".kookabug" / "local.json"
    path.parent.mkdir(exist_ok=True)
    body: dict[str, Any] = {"format": "kookabug.local/0"}
    if permissions is not None:
        body["permissions"] = dict(permissions)
    path.write_text(json.dumps(body), encoding="utf-8")


def write_team(rig: RunRig, permissions: Mapping[str, Any]) -> None:
    path = rig.root / "kookabug.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["permissions"] = dict(permissions)
    path.write_text(json.dumps(data), encoding="utf-8")


def run_folders(root: Path) -> list[Path]:
    runs = root / "runs"
    return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


# ---------------------------------------------------------------- 실행: 세 경로


def layers(
    user: Mapping[str, Any] | None = None,
    team: Mapping[str, Any] | None = None,
    local: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """정책 파일 세 계층(사용자 설정·팀 `kookabug.json`·프로젝트 `local.json`)의 `permissions`."""
    return {"user": user, "team": team, "local": local}


RUN_POLICIES: list[Any] = [
    pytest.param(
        layers(local={"toolsets": {"run": "allow"}}), ("allow", "allow", "toolset"), id="allow"
    ),
    # 기본 프리셋 graph_author
    pytest.param(layers(), ("deny", "deny", "preset"), id="deny"),
    pytest.param(
        layers(local={"toolsets": {"run": "ask"}}),
        ("ask", "deny", "unattended_ask"),
        id="unattended_ask",
    ),
    pytest.param(layers(user={"preset": "full"}), ("allow", "allow", "preset"), id="user_allow"),
    pytest.param(
        layers(
            user={"preset": "full"},
            local={"rules": [{"verdict": "deny", "rule": "kb_run_start(tests/*)"}]},
        ),
        ("deny", "deny", "rule"),
        id="project_rule_deny",
    ),
    pytest.param(
        layers(user={"preset": "full"}, team={"preset": "read_only"}),
        ("deny", "deny", "team_ceiling"),
        id="team_ceiling",
    ),
]


def write_layers(rig: RunRig, policy: Mapping[str, Any]) -> None:
    user = Path(rig.env["KOOKABUG_USER_CONFIG_DIR"])
    user.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {"format": "kookabug.user-settings/0"}
    if policy["user"] is not None:
        body["permissions"] = dict(policy["user"])
    (user / "settings.json").write_text(json.dumps(body), encoding="utf-8")
    if policy["team"] is not None:
        write_team(rig, policy["team"])
    write_local(rig, policy["local"])


@pytest.mark.parametrize(("policy", "expected"), RUN_POLICIES)
def test_run_start_same_decision_real_cli_daemon_service(
    tmp_path: Path, policy: Mapping[str, Any], expected: tuple[str, str, str]
) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_layers(rig, policy)

    # ③ 서비스
    principal = Principal("agent", AGENT_ID, attended=False)
    service = WorkspaceService(rig.root, environ=rig.env)
    decision = service.authorize(principal, RUN_START_TOOL, TEST).to_dict()
    assert (decision["verdict"], decision["final"], decision["reason"]) == expected

    # ① 실제 CLI 하위 프로세스 (사람 없는 에이전트)
    done = run_cli(
        ["run", TEST, "--json"], cwd=rig.root, env={**rig.env, "KOOKABUG_AGENT": AGENT_ID}
    )
    cli = json.loads(done.stdout)
    assert cli["principal"] == {"kind": "agent", "id": AGENT_ID, "attended": False}
    assert cli["decision"] == decision
    cli_folders = run_folders(rig.root)

    # ② daemon agent 연결. daemon이 집행한 판정은 서비스 `require`가 실제로 돌려준(또는 예외에
    # 실은) 값을 관찰한다 (허용은 결과에 판정을 싣지 않는다)
    with rig.daemon() as d, d.client(agent(attended=False)) as client:
        observed: list[dict[str, Any]] = []
        original = d.daemon.service.require

        def observe(who: Principal, tool: str, arg: str = "", **kwargs: Any) -> Any:
            if tool != RUN_START_TOOL:  # 결과를 기다리는 run.status 판정
                return original(who, tool, arg, **kwargs)
            assert (who, arg) == (principal, TEST)
            try:
                result = original(who, tool, arg, **kwargs)
            except (PermissionDenied, ApprovalRequired) as exc:
                observed.append(exc.decision.to_dict())
                raise
            observed.append(result.to_dict())
            return result

        d.daemon.service.require = observe  # type: ignore[method-assign]
        if decision["final"] == "allow":
            started = client.call("run.start", {"path": TEST})
            wait_until(
                lambda: (
                    client.call("run.status", {"run_id": started["run_id"]})["state"] == "ended"
                ),
                interval=0.1,
            )
        else:
            with pytest.raises(DaemonError) as caught:
                client.call("run.start", {"path": TEST})
            assert caught.value.kind == "permission_denied"
            assert caught.value.data["decision"] == decision
    assert observed == [decision]

    # 집행도 같다
    if decision["final"] == "allow":
        assert done.returncode == 0 and cli["verdict"] == "pass", done.stderr
        assert len(cli_folders) == 1 and len(run_folders(rig.root)) == 2
    else:
        assert done.returncode == 5 and cli["run_dir"] is None, done.stderr
        assert cli_folders == [] and run_folders(rig.root) == []


def test_denied_enforced_no_run_folder_via_daemon(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_team(rig, {"preset": "read_only"})
    with rig.daemon() as d, d.client(agent()) as client:
        for params in ({"path": TEST}, {"path": TEST, "idempotency_key": "k"}):
            with pytest.raises(DaemonError) as caught:
                client.call("run.start", params)
            assert caught.value.kind == "permission_denied"
            assert caught.value.data["decision"]["final"] == "deny"
        assert d.daemon.runs.active_run() is None
    assert run_folders(rig.root) == []


def test_attended_agent_ask_is_approval_required_not_started(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_local(rig, {"toolsets": {"run": "ask"}})
    with rig.daemon() as d, d.client(agent(attended=True)) as client:
        with pytest.raises(DaemonError) as caught:
            client.call("run.start", {"path": TEST})
        assert caught.value.kind == "approval_required"
        assert caught.value.data["decision"]["final"] == "ask"
        assert d.daemon.runs.active_run() is None
    assert run_folders(rig.root) == []


def test_ui_principal_not_judged_under_deny_policy(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_team(rig, {"preset": "read_only"})
    with rig.daemon() as d, d.client() as ui:
        started = ui.call("run.start", {"path": TEST})
        wait_until(
            lambda: ui.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
            interval=0.1,
        )
        assert ui.call("run.list", {})["runs"][0]["outcome"]["verdict"] == "pass"
    assert len(run_folders(rig.root)) == 1


# ---------------------------------------------------------------- 편집: 두 경로


def stub_target_save() -> MethodSpec:
    """`target.save`가 아직 없는 daemon(T6 전)에서 판정 경로를 검사하는 대역: 판정을 지나면 파일을
    쓴다. 그래서 거부·승인 필요면 파일이 생기지 않음으로 집행까지 본다."""

    async def save(call: Call) -> dict[str, Any]:
        path = call.daemon.root / str(call.params["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        raise AssertionError("판정을 지나면 안 된다")

    return MethodSpec(save, lambda call: str(call.params["path"]))


def edit_methods() -> dict[str, MethodSpec]:
    methods = registry()
    methods.setdefault("target.save", stub_target_save())
    return methods


def attempt(client: DaemonClient, tool: str) -> DaemonError:
    """그 도구에 대응하는 메서드를 부른다 (읽기 도구로 연 뒤). 거부·승인 필요 오류를 돌려준다."""
    with pytest.raises(DaemonError) as caught:
        if tool == "kb_graph_patch":
            opened = client.call("graph.open", {"path": TEST})
            value = opened["value"]
            value["meta"] = {"title": "에이전트 편집"}
            client.call(
                "graph.save",
                {"doc_id": opened["doc_id"], "value": value, "base_revision": opened["revision"]},
            )
        elif tool == "kb_graph_create":
            client.call("graph.create", {"path": NEW_GRAPH, "kind": "test"})
        else:
            crop = {"frame_id": "f1", "rect": [0, 0, 4, 4]}
            params = {"path": NEW_TARGET, "spec": {}, "crop": crop, "base_revision": None}
            client.call("target.save", params)
    return caught.value


TOOL_ARGS: dict[str, str] = {
    "kb_graph_patch": TEST,
    "kb_graph_create": NEW_GRAPH,
    "kb_target_create": NEW_TARGET,
}
EDIT_POLICIES: dict[str, tuple[Callable[[RunRig], None], bool, str]] = {
    # 이름 → (정책 쓰기, 사람 있는 에이전트, daemon 오류 종류)
    "deny": (lambda rig: write_team(rig, {"preset": "read_only"}), False, "permission_denied"),
    "ask": (
        lambda rig: write_local(rig, {"toolsets": {"graph_edit": "ask"}}),
        True,
        "approval_required",
    ),
    "unattended_ask": (
        lambda rig: write_local(rig, {"toolsets": {"graph_edit": "ask"}}),
        False,
        "permission_denied",
    ),
}


@pytest.mark.parametrize("policy", list(EDIT_POLICIES))
@pytest.mark.parametrize("tool", list(TOOL_ARGS))
def test_graph_edit_same_decision_daemon_service(tmp_path: Path, tool: str, policy: str) -> None:
    rig = RunRig.make(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    write_policy, attended, kind = EDIT_POLICIES[policy]
    write_policy(rig)
    graph = rig.root / TEST
    os.utime(graph, ns=(OLD_NS, OLD_NS))
    before = graph.read_bytes()

    principal = Principal("agent", AGENT_ID, attended=attended)
    service = WorkspaceService(rig.root, environ=rig.env)
    expected = service.authorize(principal, tool, TOOL_ARGS[tool]).to_dict()

    daemon = ThreadDaemon(rig.root, service=rig.service(), methods=edit_methods())
    with daemon as d, d.client(agent(attended=attended)) as client:
        error = attempt(client, tool)
    assert error.kind == kind, error
    assert error.data["decision"] == expected
    assert tool in error.message
    # 거부·승인 필요: 아무것도 쓰지 않았다
    assert graph.read_bytes() == before and graph.stat().st_mtime_ns == OLD_NS
    assert not (rig.root / NEW_GRAPH).exists()
    assert not (rig.root / NEW_TARGET).exists()
