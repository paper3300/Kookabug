import json
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import GraphBuilder
from helpers.runner import RUNNER_CMD

from kb_testing.proc import Spawned, direct_env, isolated_env
from kookabug_core.permissions import Principal
from kookabug_core.service import (
    ApprovalRequired,
    PermissionDenied,
    WorkspaceService,
    cli_principal,
)
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.workspace import WorkspaceError

AGENT = Principal("agent", "conn-1", attended=False)
PANEL = Principal("agent", "panel", attended=True)
HUMAN = Principal("user", "cli", attended=True)


def write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "ws"
    write(root / "kookabug.json", {"format": "kookabug.workspace/0"})
    env = {"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")}
    return root, env


def test_authorize_uses_workspace_and_user_layers(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    service = WorkspaceService(root, environ=env)
    assert service.authorize(AGENT, "kb_run_start").final == "deny"  # 기본 graph_author

    user_file = Path(env["KOOKABUG_USER_CONFIG_DIR"]) / "settings.json"
    write(user_file, {"format": "kookabug.user-settings/0", "permissions": {"preset": "runner"}})
    d = service.authorize(AGENT, "kb_run_start", "tests/a.graph.json")
    assert (d.final, d.layer, d.source) == ("allow", "user", "preset:runner")

    # 정책 파일은 판정마다 다시 읽는다
    write(
        root / ".kookabug" / "local.json",
        {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": "ask"}}},
    )
    d = service.authorize(AGENT, "kb_run_start")
    assert (d.verdict, d.final, d.layer) == ("ask", "deny", "project")
    assert service.authorize(PANEL, "kb_run_start").final == "ask"

    write(
        root / "kookabug.json",
        {"format": "kookabug.workspace/0", "permissions": {"preset": "read_only"}},
    )
    d = service.authorize(PANEL, "kb_run_start")
    assert (d.final, d.layer, d.reason) == ("deny", "team", "team_ceiling")
    assert service.authorize(HUMAN, "kb_run_start").final == "allow"


def test_authorize_invalid_policy_denies_agent(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    (root / ".kookabug").mkdir()
    (root / ".kookabug" / "local.json").write_text("{", encoding="utf-8")
    service = WorkspaceService(root, environ=env)
    d = service.authorize(PANEL, "kb_graph_get")
    assert (d.final, d.reason, d.layer) == ("deny", "policy_invalid", "project")
    assert [x.code for x in d.diagnostics] == ["json_invalid"]
    assert service.authorize(HUMAN, "kb_graph_get").final == "allow"


@pytest.mark.parametrize("which", ["user", "project", "team"])
def test_unreadable_policy_path_denies_agent(
    ws: tuple[Path, dict[str, str]], which: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 프로젝트 full 정책 + 어느 계층이든 정책 경로가 폴더·I/O 오류면 에이전트는 거부 (검수 반례)
    root, env = ws
    user_dir = Path(env["KOOKABUG_USER_CONFIG_DIR"])
    write(
        root / ".kookabug" / "local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "full"}},
    )
    service = WorkspaceService(root, environ=env)
    assert service.authorize(AGENT, "kb_input_click").final == "allow"

    path = {
        "user": user_dir / "settings.json",
        "project": root / ".kookabug" / "local.json",
        "team": root / "kookabug.json",
    }[which]
    backup = path.with_name(path.name + ".backup")
    if path.exists():
        path.rename(backup)
    path.mkdir(parents=True)
    d = service.authorize(AGENT, "kb_input_click")
    assert (d.final, d.reason, d.layer) == ("deny", "policy_invalid", which)
    assert [x.code for x in d.diagnostics] == ["json_invalid"]
    assert service.authorize(HUMAN, "kb_input_click").final == "allow"

    # 폴더를 치우고 원래 파일로 돌린 뒤 같은 경로의 읽기 오류
    path.rmdir()
    if backup.exists():
        backup.rename(path)
    real = Path.read_text

    def read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == path:
            raise PermissionError(13, "접근 거부", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    d = service.authorize(AGENT, "kb_input_click")
    assert (d.final, d.reason, d.layer) == ("deny", "policy_invalid", which)


def test_team_file_removed_after_open_denies_agent(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    write(
        root / "kookabug.json",
        {"format": "kookabug.workspace/0", "permissions": {"preset": "read_only"}},
    )
    write(
        root / ".kookabug" / "local.json",
        {"format": "kookabug.local/0", "permissions": {"preset": "full"}},
    )
    service = WorkspaceService(root, environ=env)
    assert service.authorize(AGENT, "kb_input_click").final == "deny"
    (root / "kookabug.json").unlink()
    d = service.authorize(AGENT, "kb_input_click")
    assert (d.final, d.reason, d.layer) == ("deny", "policy_invalid", "team")


def test_require_raises_for_deny_and_unapproved_ask(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    service = WorkspaceService(root, environ=env)
    with pytest.raises(PermissionDenied) as denied:
        service.require(PANEL, "kb_run_start")
    assert denied.value.decision.final == "deny"
    assert "kb_run_start" in str(denied.value)

    with pytest.raises(ApprovalRequired) as ask:
        service.require(PANEL, "kb_graph_patch")
    assert ask.value.decision.final == "ask"
    assert service.require(PANEL, "kb_graph_patch", approved=True).final == "ask"
    # 사람 없는 실행의 ask는 승인으로도 풀리지 않는다
    with pytest.raises(PermissionDenied):
        service.require(AGENT, "kb_graph_patch", approved=True)
    assert service.require(HUMAN, "kb_run_start").allowed


def test_service_needs_workspace_root(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        WorkspaceService(tmp_path)


class RecordingSupervisor(Supervisor):
    """`start`가 불렸는지만 남긴다 (프로세스를 띄우지 않는다)."""

    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[Path, str]] = []

    def start(self, workspace_root: Any, graph: str, options: Any = None) -> RunHandle:
        self.started.append((Path(workspace_root), graph))
        raise AssertionError("실행을 시작하면 안 된다")


def test_start_run_denied_does_not_spawn(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    supervisor = RecordingSupervisor()
    service = WorkspaceService(root, environ=env, supervisor=supervisor)
    # 기본 프리셋 graph_author: 에이전트의 kb_run_start는 deny
    with pytest.raises(PermissionDenied) as denied:
        service.start_run(AGENT, "tests/a.graph.json", approved=True)
    assert denied.value.tool == "kb_run_start" and denied.value.decision.final == "deny"
    assert supervisor.started == []
    assert not (root / "runs").exists()


def test_start_run_ask_without_approval_does_not_spawn(ws: tuple[Path, dict[str, str]]) -> None:
    root, env = ws
    write(
        root / ".kookabug" / "local.json",
        {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": "ask"}}},
    )
    supervisor = RecordingSupervisor()
    service = WorkspaceService(root, environ=env, supervisor=supervisor)
    with pytest.raises(ApprovalRequired) as ask:
        service.start_run(PANEL, "tests/a.graph.json")
    assert ask.value.decision.final == "ask"
    # 사람 없는 에이전트의 ask는 deny다 (승인으로도 풀리지 않는다)
    with pytest.raises(PermissionDenied):
        service.start_run(AGENT, "tests/a.graph.json", approved=True)
    assert supervisor.started == []
    assert not (root / "runs").exists()
    # 승인이 있으면 감독자까지 간다
    with pytest.raises(AssertionError):
        service.start_run(PANEL, "tests/a.graph.json", approved=True)
    assert supervisor.started == [(root.resolve(), "tests/a.graph.json")]


@pytest.mark.process
def test_start_run_allowed_returns_handle(
    ws: tuple[Path, dict[str, str]], tmp_path: Path, spawned: Spawned
) -> None:
    root, env = ws
    write(
        Path(env["KOOKABUG_USER_CONFIG_DIR"]) / "settings.json",
        {"format": "kookabug.user-settings/0", "permissions": {"preset": "runner"}},
    )
    GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").write(
        root, "tests/a.graph.json"
    )
    supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=direct_env(isolated_env(tmp_path)))
    service = WorkspaceService(root, environ=env, supervisor=supervisor)
    handle = service.start_run(
        AGENT, "tests/a.graph.json", StartOptions(deadline_ms=30_000, runs_dir=tmp_path / "runs")
    )
    if handle.launcher is not None:
        spawned.track(handle.launcher)
    assert handle.start_error is None
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and outcome.verdict == "pass"
    assert outcome.run_end is not None and outcome.run_end["finalized_by"] == "runner"
    assert outcome.run_dir.parent == tmp_path / "runs"


def test_cli_principal_from_env() -> None:
    assert cli_principal({}) == Principal("user", "cli", attended=True)
    assert cli_principal({"KOOKABUG_AGENT": "conn-7"}) == Principal("agent", "conn-7", False)
    assert cli_principal({"KOOKABUG_AGENT": ""}) == Principal("agent", "agent", False)


def test_cli_principal_reads_process_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOOKABUG_AGENT", raising=False)
    assert cli_principal().kind == "user"
    monkeypatch.setenv("KOOKABUG_AGENT", "x")
    assert cli_principal() == Principal("agent", "x", False)
