"""에이전트 게임 조작 = 한 스텝짜리 제어 실행 (M5 계획 3.9, B3).

`control.*`은 daemon이 만든 그래프 값을 기존 runner·감독자·입력 임대권·액터 경로로 돌린다. 가짜
플랫폼(장면 표 `running: true` — 이미 떠 있는 SampleRPG 창)과 가짜 입력 기록으로 본다. 실제 입력
(SendInput)은 `kookabug_mcp/tests/test_control_live.py`(desktop_input, 조율자 실행).
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import shutil
import signal
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env
from helpers.runner import RUNNER_CMD

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kb_testing.packaging import REPO_ROOT
from kb_testing.proc import read_fake_input_log, wait_until
from kookabug_core.documents import ENTRY_NODE, template
from kookabug_core.record import read_run_json
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.runs import CONTROL_GRAPH, RunManager

pytestmark = [pytest.mark.process, pytest.mark.timeout(240)]

WINDOW = "SampleRPG"
SECRET = "s3cr3t-Pw-0417"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-c", "attended": False}


@dataclass
class Rig:
    root: Path
    env: dict[str, str]
    platform: Path
    input_log: Path

    def daemon(self) -> ThreadDaemon:
        supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=self.env)
        service = WorkspaceService(self.root, environ=self.env, supervisor=supervisor)
        return ThreadDaemon(self.root, service=service, platform_fake=self.platform)

    def inputs(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.input_log)

    def run_folders(self) -> list[Path]:
        runs = self.root / "runs"
        return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []


def make_rig(
    tmp_path: Path,
    permissions: Mapping[str, Any] | None = None,
    hooks: Mapping[str, Mapping[str, str]] | None = None,
) -> Rig:
    root = copy_sample_workspace(tmp_path / "ws")
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    scenario = json.loads((frames / "scenario.json").read_text(encoding="utf-8"))
    scenario["running"] = True
    (frames / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    log = tmp_path / "input.jsonl"
    spec = tmp_path / "platform.json"
    spec.write_text(
        json.dumps(
            {
                "scenario": str(frames / "scenario.json"),
                "input_log": str(log),
                "hooks": {k: dict(v) for k, v in (hooks or {}).items()},
            }
        ),
        encoding="utf-8",
    )
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    body = {"format": "kookabug.local/0", "permissions": dict(permissions or {"preset": "full"})}
    local.write_text(json.dumps(body), encoding="utf-8")
    env = cli_env(tmp_path, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    return Rig(root, env, spec, log)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return make_rig(tmp_path)


@pytest.fixture
def daemon(rig: Rig) -> Iterator[ThreadDaemon]:
    with rig.daemon() as d:
        yield d


def graph_with(middle: dict[str, Any] | None) -> dict[str, Any]:
    """시작 → (`middle`) → 통과 테스트 그래프."""
    value = template("test")
    first = "n_mid" if middle is not None else "n_pass"
    nodes: dict[str, Any] = {
        ENTRY_NODE: {"type": "core.graph.entry", "version": 1, "next": {"start": first}},
        "n_pass": {"type": "core.test.pass", "version": 1},
    }
    if middle is not None:
        nodes["n_mid"] = {**middle, "next": {"done": "n_pass"}}
    value["nodes"] = nodes
    value.pop("layout")
    return value


def refused(client: DaemonClient, method: str, params: Mapping[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def balanced(inputs: list[dict[str, Any]]) -> bool:
    """누른 키·버튼이 모두 떼어졌다."""
    held: dict[tuple[str, str], int] = {}
    for line in inputs:
        name = str(line.get("key") or line.get("button"))
        key = (str(line.get("device")), name)
        if line["op"] == "down":
            held[key] = held.get(key, 0) + 1
        elif line["op"] == "up":
            held[key] = held.get(key, 0) - 1
    return all(v <= 0 for v in held.values())


def test_click_runs_as_single_step_run_with_lease(rig: Rig, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        result = agent.call("control.click", {"window": WINDOW, "point": [512, 412]}, timeout=120)
        assert result["verdict"] == "pass", result
        downs = [x for x in rig.inputs() if x["op"] == "down"]
        ups = [x for x in rig.inputs() if x["op"] == "up"]
        assert len(downs) == len(ups) == 1 and downs[0]["button"] == "left"
        # 입력은 runner(임대권 소유자)가 그 실행으로 했다
        assert all(x["by"] == "runner" and x["run"] == result["run_id"] for x in downs + ups)
        assert balanced(rig.inputs())
        # 키 입력·target 클릭도 같은 경로
        key = agent.call("control.key", {"window": WINDOW, "keys": "ctrl+a"}, timeout=120)
        assert key["verdict"] == "pass", key
        assert balanced(rig.inputs())
        status = agent.call("run.status", {"run_id": result["run_id"]})
        assert status["state"] == "ended" and status["graph"] == CONTROL_GRAPH
        # 창이 없으면 입력하지 않고 실패 결과
        before = len(rig.inputs())
        missing = agent.call("control.click", {"window": "Other", "point": [1, 1]}, timeout=120)
        assert missing["verdict"] == "fail" and missing["error"]["code"]
        assert len(rig.inputs()) == before
    folders = rig.run_folders()
    assert len(folders) == 3
    data = read_run_json(folders[0] / "run.json")
    assert data is not None
    assert data["source"] == "agent_control" and data["agent"] == {"id": "agent-c"}
    assert data["agent_mask"] == 1
    # 그래프는 스냅샷에만 있다 (워크스페이스·.kookabug/에 쓰지 않음)
    assert (folders[0] / "snapshot" / CONTROL_GRAPH).is_file()
    assert not (rig.root / CONTROL_GRAPH).exists()
    assert not list((rig.root / ".kookabug").rglob("*.graph.json"))
    # 기록 뷰어 목록의 배지
    with daemon.client() as ui:
        listed = ui.call("run.list", {})["runs"]
        assert {r.get("source") for r in listed} == {"agent_control"}


def test_control_rejected_while_recording(rig: Rig, daemon: ThreadDaemon) -> None:
    manager: RunManager = daemon.daemon.run_manager
    reservation = manager.reserve_recording()
    try:
        with daemon.client(AGENT) as agent:
            for state in ("starting", "recording", "paused"):
                if state != "starting":
                    reservation.set_state(state)
                error = refused(agent, "control.click", {"window": WINDOW, "point": [1, 1]})
                assert (error.kind, error.data["state"]) == ("recording_active", state)
                error = refused(agent, "app.launch", {})
                assert error.kind == "recording_active"
    finally:
        reservation.release()
    assert rig.run_folders() == []
    assert rig.inputs() == []


def test_control_rejected_while_run_active(rig: Rig, daemon: ThreadDaemon) -> None:
    wait = {"type": "core.flow.delay", "version": 1, "in": {"ms": 60_000}}
    (rig.root / "tests" / "wait.graph.json").write_text(json.dumps(graph_with(wait)), "utf-8")
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        started = ui.call("run.start", {"path": "tests/wait.graph.json"})
        try:
            error = refused(agent, "control.key", {"window": WINDOW, "keys": "a"})
            assert (error.kind, error.data["run_id"]) == ("run_busy", started["run_id"])
            assert refused(agent, "app.launch", {}).kind == "run_busy"
        finally:
            ui.call("run.cancel", {"run_id": started["run_id"]})
            wait_until(
                lambda: ui.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
                timeout=60,
            )
    assert len(rig.run_folders()) == 1
    assert rig.inputs() == []


def test_type_secret_value_not_returned(
    rig: Rig, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # daemon 사전 검증은 이 프로세스 환경에서, runner는 rig 환경에서 비밀값을 찾는다
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    with daemon.client(AGENT) as agent:
        result = agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)
        assert result["verdict"] == "pass", result
        assert SECRET not in json.dumps(result)
        # 게임에는 갔다 (가짜 입력 기록 = 게임 쪽)
        assert any(x["op"] == "text" for x in rig.inputs())
        run_id = result["run_id"]
        # 에이전트가 읽는 기록 (3.8 분류로 가림)
        events = agent.call("run.events", {"run_id": run_id, "limit": 500})
        assert events["classified"] and SECRET not in json.dumps(events, ensure_ascii=False)
        status = agent.call("run.status", {"run_id": run_id})
        assert SECRET not in json.dumps(status, ensure_ascii=False)
        # 없는 키: 검증 오류에도 값이 없다 (키 이름만)
        error = refused(agent, "control.type", {"window": WINDOW, "secret": "acc.none"})
        assert error.kind == "validation_failed"
        assert SECRET not in json.dumps([error.message, error.data], ensure_ascii=False)
        # 실패 사유에 비밀이 섞이면 ***
        failed = agent.call("control.type", {"window": "Other", "secret": "acc.pw"}, timeout=120)
        assert failed["verdict"] == "fail" and SECRET not in json.dumps(failed)
    folder = rig.run_folders()[0]
    assert SECRET not in (folder / "run.json").read_text(encoding="utf-8")
    assert SECRET not in (folder / "snapshot" / CONTROL_GRAPH).read_text(encoding="utf-8")


def test_runner_killed_mid_control_keys_released(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, hooks={"after_down": {"ctrl": "hang"}})
    with rig.daemon() as d, d.client(AGENT) as agent:
        manager: RunManager = d.daemon.run_manager
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["result"] = agent.call(
                    "control.key", {"window": WINDOW, "keys": "ctrl+a"}, timeout=120
                )
            except BaseException as exc:
                box["error"] = exc

        worker = threading.Thread(target=call)
        worker.start()
        wait_until(lambda: any(x["op"] == "down" and x["key"] == "ctrl" for x in rig.inputs()))
        run_id = manager.active_run()
        assert run_id is not None
        handle = manager._runs[run_id].handle  # pyright: ignore[reportPrivateUsage]
        assert handle is not None and handle.runner_ident is not None
        os.kill(handle.runner_ident.pid, signal.SIGTERM)  # Windows: TerminateProcess
        worker.join(120)
        assert "error" not in box, box
        result = box["result"]
        assert result["verdict"] == "error" and result["error"]["code"] == "runner_died"
    inputs = rig.inputs()
    last = inputs[-1]
    assert (last["op"], last["key"], last["by"]) == ("up", "ctrl", "supervisor")
    assert balanced(inputs)


def test_control_allowed_when_run_denied(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, {"preset": "read_only", "toolsets": {"control": "allow"}})
    with rig.daemon() as d, d.client(AGENT) as agent:
        done = agent.call("control.click", {"window": WINDOW, "point": [5, 5]}, timeout=120)
        assert done["verdict"] == "pass"
        error = refused(agent, "run.start", {"path": "tests/smoke_headless.graph.json"})
        assert error.kind == "permission_denied"
        assert error.data["decision"]["source"] == "preset:read_only"
    assert len(rig.run_folders()) == 1


def test_public_run_start_private_path_still_rejected(rig: Rig, daemon: ThreadDaemon) -> None:
    private = rig.root / ".kookabug" / "x.graph.json"
    private.write_text(json.dumps(graph_with(None)), encoding="utf-8")
    with daemon.client() as ui, daemon.client(AGENT) as agent:
        for client in (ui, agent):
            error = refused(client, "run.start", {"path": ".kookabug/x.graph.json"})
            assert error.kind == "private_path"
        # 공개 run.start에는 그래프 값·권한 생략 인자가 없다 (계약이 받지 않음)
        with daemon.client(AGENT) as raw:
            raw.check = False  # 계약 밖 params를 그대로 보낸다
            for extra in (
                {"graph_value": {"nodes": {}}},
                {"approved": True},
                {"source": "agent_control"},
            ):
                with pytest.raises(DaemonError) as caught:
                    raw.call("run.start", {"path": "tests/smoke_headless.graph.json", **extra})
                assert caught.value.code == -32602, extra
    assert rig.run_folders() == []


def test_app_launch_outside_run(rig: Rig, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        # 예제 kookabug.json의 game.executable은 null
        error = refused(agent, "app.launch", {})
        assert error.kind == "launch_failed" and "game.executable" in error.message
        local = rig.root / ".kookabug" / "local.json"
        data = json.loads(local.read_text(encoding="utf-8"))
        data["settings"] = {
            "game.executable": sys.executable,
            "game.args": ["-c", "import time; time.sleep(30)"],
        }
        local.write_text(json.dumps(data), encoding="utf-8")
        pid = agent.call("app.launch", {"profile": None})["pid"]
    try:
        assert pid > 0
        assert rig.run_folders() == []  # 실행이 아니다 (Job 밖, 기록 없음)
    finally:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)


ATTENDED = {**AGENT, "attended": True}


def approval_request(client: DaemonClient, timeout: float = 15) -> dict[str, Any]:
    """ui 연결의 다음 `approval.requested` params."""
    deadline = time.monotonic() + timeout
    while (left := deadline - time.monotonic()) > 0:
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            break
        if message.get("method") == "approval.requested":
            return message["params"]
    raise AssertionError("approval.requested가 오지 않았다")


def test_run_start_ask_allows_execution(tmp_path: Path) -> None:
    """B3 검수 H1: run ask에 사람이 '한 번 허용'하면 실행이 실제로 시작된다 (승인 사실이 감독자
    시작까지 내부 값으로 간다). 승인 전에는 실행 폴더가 없다."""
    rig = make_rig(tmp_path, {"preset": "full", "toolsets": {"run": "ask"}})
    wait = {"type": "core.flow.delay", "version": 1, "in": {"ms": 60_000}}
    (rig.root / "tests" / "wait.graph.json").write_text(json.dumps(graph_with(wait)), "utf-8")
    with rig.daemon() as d, d.client() as ui, d.client(ATTENDED) as agent:
        pending = agent.request(
            "run.start", {"path": "tests/wait.graph.json", "idempotency_key": "h1"}
        )
        ask = approval_request(ui)
        assert ask["tool"] == "kb_run_start"
        assert rig.run_folders() == []
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        run_id = pending.result(30)["run_id"]
        try:
            assert ui.call("run.status", {"run_id": run_id})["state"] == "running"
        finally:
            ui.call("run.cancel", {"run_id": run_id})
            wait_until(
                lambda: ui.call("run.status", {"run_id": run_id})["state"] == "ended",
                timeout=60,
            )
        # 승인 없는 ask는 여전히 시작하지 않는다 (사람 없음 → no_approver)
    with rig.daemon() as d, d.client(ATTENDED) as agent:
        error = refused(agent, "run.start", {"path": "tests/wait.graph.json"})
        assert (error.kind, error.data["reason"]) == ("approval_required", "no_approver")
    assert len(rig.run_folders()) == 1
    assert rig.inputs() == []


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("control.click", {"window": WINDOW, "point": [1, 1]}),
        ("control.key", {"window": WINDOW, "keys": "a"}),
        ("control.type", {"window": WINDOW, "text": "review-text"}),
    ],
)
def test_control_allow_once_reaches_runner(
    tmp_path: Path, method: str, params: dict[str, Any]
) -> None:
    """B3 검수 H1: 기본 runner 프리셋(control ask)에서 '한 번 허용'하면 제어 실행이 입력까지
    간다."""
    rig = make_rig(tmp_path, {"preset": "runner"})
    with rig.daemon() as d, d.client() as ui, d.client(ATTENDED) as agent:
        pending = agent.request(method, params)
        ask = approval_request(ui)
        assert rig.inputs() == [] and rig.run_folders() == []
        ui.call("approval.respond", {"id": ask["id"], "verdict": "allow_once"})
        result = pending.result(60)
        assert result["verdict"] == "pass", result
        assert rig.inputs() and balanced(rig.inputs())
        # 다음 호출은 다시 묻는다 (한 번 허용은 규칙을 남기지 않음) — 거부하면 입력 없음
        count = len(rig.inputs())
        pending = agent.request(method, params)
        ask = approval_request(ui)
        ui.call("approval.respond", {"id": ask["id"], "verdict": "deny"})
        with pytest.raises(DaemonError) as caught:
            pending.result(60)
        assert caught.value.kind == "approval_denied"
        assert len(rig.inputs()) == count
    assert len(rig.run_folders()) == 1
