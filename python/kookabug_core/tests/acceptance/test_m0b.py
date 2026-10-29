"""M0b 완료 기준 (구현 계획 v0 1장) 인수 테스트. 기준 하나에 테스트 하나.

1. 노드 실행 중 취소·멈춤 요청이 들어감
2. 워커를 죽여도 기록이 확정됨
3. runner를 강제 종료해도 감독자가 기록을 마무리
4. runner를 강제 종료해도 감독자가 눌린 키를 해제 (가짜 입력 백엔드로 제어 계약까지. 실제
   SendInput 해제는 M1)
5. 잘린 JSONL을 읽어 "중단"으로 표시
6. 같은 행위가 CLI와 공유 서비스(`WorkspaceService.authorize`)에서 같은 권한 판정 (daemon 어댑터
   통합 검증은 daemon이 생기는 단계로 넘겼다)

감독자는 제품 진입점이다: 감독자 프로세스를 죽여야 하는 경우와 CLI 판정은 `kookabug run` 하위
프로세스, 멈춤·취소처럼 API로 제어하는 경우는 이 프로세스 안의 `WorkspaceService.start_run`.
다른 테스트 모듈을 import하지 않는다. 자세한 경우는 각 작업의 테스트에 있다 (`tests/runner/*`,
`tests/supervisor/*`, `tests/inputs/*`, `tests/record/*`, `tests/permissions/*`, kookabug_cli).
"""

from __future__ import annotations

import io
import json
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import CliProcess, cli_env, platform_file, run_cli
from helpers.graphs import GraphBuilder, make_workspace, write_json
from helpers.run import tk
from helpers.runner import RUNNER_CMD
from helpers.worker import PLUGIN_MODULES

from kb_testing.proc import (
    Spawned,
    assert_no_live,
    barrier,
    read_fake_input_log,
    wait_until,
)
from kookabug_cli import main as cli_main
from kookabug_core.inputs.lease import STATE_DIR_ENV, read_lease_file
from kookabug_core.permissions import Decision, Principal
from kookabug_core.record import RunView, read_run, read_run_json
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import RUN_START_TOOL, WorkspaceService, cli_principal
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.win import Job, Process, ProcessId, identify, run_job_name
from kookabug_sdk import _faults

pytestmark = [pytest.mark.process, pytest.mark.timeout(120)]

TEST = "tests/t.graph.json"
GRACE = {"shutdown_grace_ms": 2_000, "worker_cancel_grace_ms": 1_000}
PLUGINS = [a for m in PLUGIN_MODULES for a in ("--plugin-module", m)]


# ---------------------------------------------------------------- 그래프·시작


def gate_then_block(signal: Path) -> GraphBuilder:
    return (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_block"})
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def block_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_block")
        .node("n_block", "testkit.block", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def key_graph(key: str = "ctrl") -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": key}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def tap_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_tap")
        .node("n_tap", "testkit.input.tap", inputs={"x": 3, "y": 4}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def workspace(
    tmp_path: Path, graph: GraphBuilder | None, run: Mapping[str, int] | None = None
) -> Path:
    root = tmp_path / "ws"
    make_workspace(root)
    write_json(root, "kookabug.json", {"format": "kookabug.workspace/0", "run": run or GRACE})
    if graph is not None:
        graph.write(root, TEST)
    return root


def start_api(
    tmp_path: Path,
    spawned: Spawned,
    graph: GraphBuilder,
    *,
    hooks: Mapping[str, Mapping[str, str]] | None = None,
    faults: Sequence[Mapping[str, Any]] = (),
) -> RunHandle:
    """이 프로세스의 감독자로 실행 시작 (`WorkspaceService.start_run`)."""
    root = workspace(tmp_path, graph)
    env = cli_env(tmp_path, list(faults) or None)
    service = WorkspaceService(
        root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    handle = service.start_run(
        cli_principal({}),
        TEST,
        StartOptions(
            plugin_modules=PLUGIN_MODULES,
            platform=PlatformSpec(
                "fake",
                input_log=str(tmp_path / "input.jsonl"),
                hooks={k: dict(v) for k, v in (hooks or {}).items()},
            ),
            runs_dir=root / "runs",
            shutdown_grace_ms=GRACE["shutdown_grace_ms"],
            worker_cancel_grace_ms=GRACE["worker_cancel_grace_ms"],
        ),
    )
    assert handle.start_error is None, handle.start_error
    assert handle.runner_ident is not None
    spawned.track(handle.runner_ident)
    return handle


def start_cli(
    tmp_path: Path,
    spawned: Spawned,
    env: Mapping[str, str],
    *,
    hooks: Mapping[str, Mapping[str, str]] | None = None,
    name: str = "cli",
) -> CliProcess:
    """`kookabug run` 하위 프로세스가 감독자다 (`tmp_path/ws`의 그래프)."""
    spec, _ = platform_file(tmp_path, hooks)
    root = tmp_path / "ws"
    return CliProcess.start(
        spawned,
        ["run", TEST, "--json", "--platform-fake", spec, *PLUGINS],
        cwd=root,
        env=env,
        out=tmp_path / name,
    )


def events(view_or_dir: RunView | Path) -> list[dict[str, Any]]:
    view = view_or_dir if isinstance(view_or_dir, RunView) else read_run(view_or_dir)
    return view.events


def has_log(run_dir: Path, message: str) -> bool:
    return any(e["event"] == "log" and e.get("message") == message for e in events(run_dir))


def has_event(run_dir: Path, kind: str) -> bool:
    return any(e["event"] == kind for e in events(run_dir))


def step(view: RunView, node: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    (start,) = [e for e in view.events if e["event"] == "step.start" and e["node"] == node]
    ends = [e for e in view.events if e["event"] == "step.end" and e["step"] == start["step"]]
    return start, (ends[0] if ends else None)


def worker_of(run_dir: Path) -> ProcessId:
    (start,) = [e for e in events(run_dir) if e["event"] == "worker.start"]
    ident = identify(start["pid"])
    assert ident is not None
    return ident


def job_gone(run_id: str) -> bool:
    try:
        Job.open(run_job_name(run_id)).close()
    except OSError:
        return True
    return False


def last_op(log: Path, device_name: tuple[str, str]) -> dict[str, Any]:
    device, name = device_name
    field = "key" if device == "keyboard" else "button"
    lines = [ln for ln in read_fake_input_log(log) if ln["device"] == device]
    return [ln for ln in lines if ln.get(field) == name][-1]


def cli_result(cli: CliProcess) -> dict[str, Any]:
    return json.loads(cli.stdout())


# ---------------------------------------------------------------- 1. 취소·멈춤


def test_cancel_and_pause_reach_runner_during_node(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "gate.signal"
    handle = start_api(tmp_path, spawned, gate_then_block(signal))
    run_dir = handle.run_dir
    wait_until(lambda: has_log(run_dir, "gate"))

    # 멈춤: 워커 노드 실행 중에 답이 온다 (노드는 아직 끝나지 않았다)
    began = time.monotonic()
    assert handle.pause() == "pausing"
    assert time.monotonic() - began < 2
    assert step(read_run(run_dir), "n_gate")[1] is None and not has_event(run_dir, "debug.pause")
    # 노드를 끝내면 다음 경계에서 멈춘다
    signal.touch()
    wait_until(lambda: has_event(run_dir, "debug.pause"))
    view = read_run(run_dir)
    _, gate_end = step(view, "n_gate")
    kinds = [e["event"] for e in view.events]
    assert gate_end is not None and view.events.index(gate_end) < kinds.index("debug.pause")
    assert "step.start" not in kinds[kinds.index("debug.pause") :]
    assert handle.resume() == "running"

    # 취소: 다른 워커 노드(block) 실행 중에 답이 오고, 실행은 취소 순서로 끝난다
    wait_until(lambda: has_log(run_dir, "blocking"))
    began = time.monotonic()
    assert handle.cancel() == "cancelling"
    assert time.monotonic() - began < 2
    outcome = handle.wait(30)
    assert outcome.exit_code == 0 and not outcome.hard_stopped
    view = read_run(run_dir)
    _, block_end = step(view, "n_block")
    assert block_end is not None and block_end["status"] == "cancelled"
    assert outcome.run_end is not None
    assert (outcome.run_end["code"], outcome.run_end["finalized_by"]) == ("cancelled", "runner")
    assert [e["event"] for e in view.events].count("debug.resume") == 1

    # 액터가 백엔드에서 멈춘 runner: 취소 답은 바로 오고, 감독자가 하드 종료 → 복구 경로
    other = tmp_path / "hung"
    hung = start_api(other, spawned, key_graph(), hooks={"after_down": {"ctrl": "hang"}})
    log = other / "input.jsonl"
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)))
    began = time.monotonic()
    assert hung.cancel() == "cancelling"
    assert time.monotonic() - began < 2
    outcome = hung.wait(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped
    assert outcome.run_end is not None
    assert (outcome.run_end["code"], outcome.run_end["finalized_by"]) == (
        "runner_died",
        "supervisor",
    )
    assert outcome.run_end["cancel_reason"] == "cancelled"


# ---------------------------------------------------------------- 2. 워커 사망


def test_worker_killed_record_finalized(tmp_path: Path, spawned: Spawned) -> None:
    # 워커 노드 실행 중 워커를 죽인다
    handle = start_api(tmp_path / "a", spawned, block_graph())
    wait_until(lambda: has_log(handle.run_dir, "blocking"))
    with Process.open(worker_of(handle.run_dir), terminate=True) as worker:
        worker.terminate(7)
    outcome = handle.wait(30)
    assert outcome.exit_code == 0  # runner가 스스로 마무리했다
    view = read_run(handle.run_dir)
    _, end = step(view, "n_block")
    assert end is not None and end["status"] == "error"
    assert end["error"]["code"] == "worker_died"
    (exit_event,) = [e for e in view.events if e["event"] == "worker.exit"]
    assert (exit_event["reason"], exit_event["exit_code"]) == ("unexpected", 7)
    assert outcome.run_end is not None
    assert (outcome.run_end["verdict"], outcome.run_end["finalized_by"]) == ("error", "runner")
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"
    assert not view.truncated and view.status == "finished"

    # hello 단계 사망: 아직 열린 스텝이 없다
    faults = [{"point": "worker.before_hello_reply", "role": "worker", "action": "exit:5"}]
    handle = start_api(tmp_path / "b", spawned, block_graph(), faults=faults)
    outcome = handle.wait(30)
    assert outcome.exit_code == 0
    assert outcome.run_end is not None
    assert (outcome.run_end["code"], outcome.run_end["finalized_by"]) == ("worker_died", "runner")
    view = read_run(handle.run_dir)
    assert not [e for e in view.events if e["event"] == "step.start"]
    assert outcome.run_json is not None and outcome.run_json["status"] == "finished"


# ---------------------------------------------------------------- 3. runner 사망 → 기록 마무리


def test_runner_killed_supervisor_finalizes_record(tmp_path: Path, spawned: Spawned) -> None:
    # 노드 실행 중 runner kill: 감독자(CLI)가 run.end runner_died, run.json, Job 정리
    a = tmp_path / "mid"
    workspace(a, block_graph())
    cli = start_cli(a, spawned, cli_env(a))
    wait_until(lambda: has_log(cli.run_dir(), "blocking"), message=cli.output)
    worker = worker_of(cli.run_dir())
    runner = cli.runner_ident()
    cli.kill_runner()
    assert cli.wait() == 2, cli.output()
    out = cli_result(cli)
    assert (out["code"], out["finalized_by"], out["runner_exit_code"]) == (
        "runner_died",
        "supervisor",
        1,
    )
    view = read_run(cli.run_dir())
    assert view.run_end is not None and view.events[-1] == view.run_end
    start, end = step(view, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    run_json = read_run_json(cli.run_dir() / "run.json")
    assert run_json is not None and run_json["status"] == "finished"
    assert run_json["code"] == "runner_died" and run_json["run_json_repaired"] is True
    assert_no_live([worker, runner])
    assert job_gone(out["run_id"])

    # run.end 직후 kill: runner의 run.end를 덮지 않고 run.json만 다시 만든다
    b = tmp_path / "after_end"
    value_graph = (
        tk()
        .entry("n_value")
        .node("n_value", "testkit.config_value", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    # 장벽에서 기다리는 동안 감독자 하드 종료가 먼저 끝내지 않게 마무리 유예를 넉넉히 둔다
    workspace(b, value_graph, run={**GRACE, "shutdown_grace_ms": 30_000})
    gate = barrier(b / "barriers" / "after_run_end")
    rules = [{"point": "runner.after_run_end", "role": "runner", "action": gate.action}]
    cli = start_cli(b, spawned, cli_env(b, rules))
    gate.wait_ready()
    runner = cli.runner_ident()
    cli.kill_runner()
    assert cli.wait() == 0, cli.output()  # 판정은 runner가 쓴 pass 그대로
    out = cli_result(cli)
    assert (out["verdict"], out["finalized_by"], out["runner_exit_code"]) == ("pass", "runner", 1)
    view = read_run(cli.run_dir())
    assert [e["event"] for e in view.events].count("run.end") == 1
    assert view.events[-1] == view.run_end
    run_json = read_run_json(cli.run_dir() / "run.json")
    assert run_json is not None and run_json["status"] == "finished"
    assert run_json["verdict"] == "pass" and run_json["run_json_repaired"] is True
    assert_no_live([runner])
    assert job_gone(out["run_id"])


# ---------------------------------------------------------------- 4. runner 사망 → 키 해제


@pytest.mark.parametrize(
    ("graph", "hooks", "held"),
    [
        pytest.param(
            key_graph("ctrl+shift"),
            {"after_down": {"shift": "hang"}},
            [("keyboard", "ctrl"), ("keyboard", "shift")],
            id="keys",
        ),
        pytest.param(
            tap_graph(), {"after_down": {"mouse:left": "hang"}}, [("mouse", "left")], id="mouse"
        ),
    ],
)
def test_runner_killed_supervisor_releases_held_key(
    tmp_path: Path,
    spawned: Spawned,
    graph: GraphBuilder,
    hooks: dict[str, dict[str, str]],
    held: list[tuple[str, str]],
) -> None:
    log = tmp_path / "input.jsonl"
    env = cli_env(tmp_path)  # 다음 실행도 같은 임대권·같은 입력 장치를 쓴다

    # 키·버튼을 누른 채 액터가 멈춘 runner를 죽인다 → 감독자(CLI)가 임대권 안에서 뗀다
    workspace(tmp_path, graph)
    cli = start_cli(tmp_path, spawned, env, hooks=hooks)
    wait_until(
        lambda: sum(ln["op"] == "down" for ln in read_fake_input_log(log)) == len(held),
        message=cli.output,
    )
    cli.kill_runner()
    assert cli.wait() == 2, cli.output()
    a_run = cli_result(cli)["run_id"]
    for item in held:
        last = last_op(log, item)
        assert (last["op"], last["by"]) == ("up", "supervisor"), read_fake_input_log(log)
    view = read_run(cli.run_dir())
    (recovered,) = [e for e in view.events if e["event"] == "input.recovered"]
    assert recovered["by"]["kind"] == "supervisor"
    assert view.run_end is not None and view.run_end["input_recovery"] == "recovered"
    marker = json.loads((cli.run_dir() / "input-recovery.json").read_text(encoding="utf-8"))
    assert marker["recovered_by"]["kind"] == "supervisor"

    # 다음 실행이 임대권을 얻을 때 복구가 다시 일어나지 않는다
    key_graph("alt").write(tmp_path / "ws", TEST)
    before = len(read_fake_input_log(log))
    done = run_cli(
        ["run", TEST, "--json", "--platform-fake", platform_file(tmp_path)[0], *PLUGINS],
        cwd=tmp_path / "ws",
        env=env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    b = json.loads(done.stdout)
    b_lines = read_fake_input_log(log)[before:]
    assert [(ln["op"], ln.get("key"), ln["run"]) for ln in b_lines] == [
        ("down", "alt", b["run_id"]),
        ("up", "alt", b["run_id"]),
    ]
    assert not [e for e in events(Path(b["run_dir"])) if e["event"] == "input.recovered"]
    assert a_run != b["run_id"]


def test_runner_killed_supervisor_releases_held_key_hard_stop_and_double_fault(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 하드 종료(취소 + 액터 정지): 감독자 하드 종료 → 복구 경로가 키를 뗀다
    hard = tmp_path / "hard"
    handle = start_api(hard, spawned, key_graph(), hooks={"after_down": {"ctrl": "hang"}})
    hard_log = hard / "input.jsonl"
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(hard_log)))
    handle.cancel()
    outcome = handle.wait(30)
    assert outcome.exit_code == 4 and outcome.hard_stopped
    last = last_op(hard_log, ("keyboard", "ctrl"))
    assert (last["op"], last["by"]) == ("up", "supervisor")

    # 대조 — 이중 고장: 감독자(CLI)까지 마무리 직전에 죽이면 그 자리 해제는 없다
    log = tmp_path / "input.jsonl"
    workspace(tmp_path, key_graph())
    finalize = barrier(tmp_path / "barriers" / "before_finalize")
    rules = [{"point": "recovery.before_finalize", "role": "supervisor", "action": finalize.action}]
    env = cli_env(tmp_path, rules)
    cli = start_cli(tmp_path, spawned, env, hooks={"after_down": {"ctrl": "hang"}})
    wait_until(
        lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)), message=cli.output
    )
    a_dir = cli.run_dir()
    cli.kill_runner()
    finalize.wait_ready()
    cli.kill()
    assert [ln["op"] for ln in read_fake_input_log(log)] == ["down"]
    lease = read_lease_file(env[STATE_DIR_ENV])
    assert lease is not None and lease["clean"] is False

    # 다음 실행이 임대권을 얻을 때 입력 전에 뗀다
    clean_env = {k: v for k, v in env.items() if k != "KOOKABUG_FAULTS"}
    done = run_cli(
        ["run", TEST, "--json", "--platform-fake", platform_file(tmp_path)[0], *PLUGINS],
        cwd=tmp_path / "ws",
        env=clean_env,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    b_run = json.loads(done.stdout)["run_id"]
    b_lines = [ln for ln in read_fake_input_log(log) if ln["run"] == b_run]
    assert [(ln["op"], ln["key"]) for ln in b_lines] == [
        ("up", "ctrl"),  # 앞 실행의 키 복구 (입력 전)
        ("down", "ctrl"),
        ("up", "ctrl"),
    ]
    marker = json.loads((a_dir / "input-recovery.json").read_text(encoding="utf-8"))
    assert marker["recovered_by"] == {"kind": "runner", "run_id": b_run}
    assert read_run(a_dir).status == "interrupted"  # 앞 실행 기록은 아무도 마무리하지 않았다


# ---------------------------------------------------------------- 5. 잘린 JSONL = 중단


PARTIAL_LOG = {
    "point": "journal.partial_line",
    "role": "runner",
    "when": {"event": "log", "nth": 1},
}


def test_truncated_jsonl_read_as_interrupted(tmp_path: Path, spawned: Spawned) -> None:
    # runner가 `log` 줄 앞 절반에서 멈춤 → runner kill → 감독자(CLI)도 마무리 직전에 kill
    a = tmp_path / "both"
    workspace(a, block_graph())
    partial = barrier(a / "barriers" / "partial")
    finalize = barrier(a / "barriers" / "before_finalize")
    rules = [
        {**PARTIAL_LOG, "action": partial.action},
        {"point": "recovery.before_finalize", "role": "supervisor", "action": finalize.action},
    ]
    cli = start_cli(a, spawned, cli_env(a, rules))
    partial.wait_ready()
    worker = worker_of(cli.run_dir())
    cli.kill_runner()
    finalize.wait_ready()
    cli.kill()
    view = read_run(cli.run_dir())
    assert view.truncated and view.truncated_bytes > 0
    assert view.run_start is not None and view.run_end is None
    assert view.status == "interrupted"
    start, end = step(view, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    assert not [e for e in view.events if e["event"] == "log"]  # 잘린 줄은 버렸다
    run_json = read_run_json(cli.run_dir() / "run.json")
    assert run_json is not None and run_json["status"] == "running"
    assert_no_live([worker])

    # 대조: 같은 runner 규칙, 감독자는 살아서 마무리 → 파일 전체가 유효 JSONL, runner_died
    b = tmp_path / "alive"
    workspace(b, block_graph())
    partial = barrier(b / "barriers" / "partial")
    cli = start_cli(b, spawned, cli_env(b, [{**PARTIAL_LOG, "action": partial.action}]))
    partial.wait_ready()
    cli.kill_runner()
    assert cli.wait() == 2, cli.output()
    raw = (cli.run_dir() / "events.jsonl").read_bytes()
    assert raw.endswith(b"\n")
    assert all(json.loads(line) for line in raw.splitlines())
    view = read_run(cli.run_dir())
    assert not view.truncated and view.run_end is not None
    assert (view.run_end["verdict"], view.run_end["code"]) == ("error", "runner_died")
    assert view.run_end["truncated_bytes"] > 0
    start, end = step(view, "n_block")
    assert end is None and view.steps[start["step"]].status == "interrupted"
    assert view.status == "finished"


# ---------------------------------------------------------------- 6. CLI ↔ 서비스 판정


USER = "user-config/settings.json"
LOCAL = "ws/.kookabug/local.json"
TEAM = "ws/kookabug.json"


def perms(fmt: str, **permissions: Any) -> dict[str, Any]:
    return {"format": f"kookabug.{fmt}/0", "permissions": permissions}


DECISION_ROWS: list[Any] = [
    pytest.param({}, "conn-1", ("deny", "deny", "preset"), id="default-preset-deny"),
    pytest.param(
        {USER: perms("user-settings", preset="runner")},
        "conn-1",
        ("allow", "allow", "preset"),
        id="user-preset-allow",
    ),
    pytest.param(
        {LOCAL: perms("local", toolsets={"run": "allow"})},
        "conn-1",
        ("allow", "allow", "toolset"),
        id="project-toolset-allow",
    ),
    pytest.param(
        {LOCAL: perms("local", toolsets={"run": "ask"})},
        "conn-1",
        ("ask", "deny", "unattended_ask"),
        id="unattended-ask",
    ),
    pytest.param(
        {
            USER: perms("user-settings", preset="full"),
            LOCAL: perms("local", rules=[{"verdict": "deny", "rule": "kb_run_start(tests/*)"}]),
        },
        "conn-1",
        ("deny", "deny", "rule"),
        id="rule-deny-over-preset",
    ),
    pytest.param(
        {
            USER: perms("user-settings", preset="full"),
            LOCAL: perms("local", rules=[{"verdict": "ask", "rule": "kb_run_start(other/*)"}]),
        },
        "conn-1",
        ("allow", "allow", "preset"),
        id="rule-not-matching",
    ),
    pytest.param(
        {USER: perms("user-settings", preset="full"), TEAM: perms("workspace", preset="read_only")},
        "conn-1",
        ("deny", "deny", "team_ceiling"),
        id="team-ceiling",
    ),
    pytest.param(
        {USER: perms("user-settings", preset="full"), "ws/.kookabug/local.json": "{"},
        "conn-1",
        ("deny", "deny", "policy_invalid"),
        id="invalid-policy",
    ),
    pytest.param(
        # 깨진 local.json은 사람에게도 실행 전 검증 오류(종료 코드 4)라 여기서는 팀 상한만 둔다
        {TEAM: perms("workspace", preset="read_only")},
        None,
        ("allow", "allow", "human"),
        id="human-not-judged",
    ),
]


@pytest.mark.parametrize(("files", "agent", "expected"), DECISION_ROWS)
def test_same_action_same_decision_cli_and_service(
    tmp_path: Path,
    files: dict[str, Any],
    agent: str | None,
    expected: tuple[str, str, str],
) -> None:
    root = workspace(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))
    for rel, data in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == TEAM:
            data = {**data, "run": GRACE}
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    env = cli_env(tmp_path, None, **({} if agent is None else {"KOOKABUG_AGENT": agent}))

    done = run_cli(["run", TEST, "--json"], cwd=root, env=env)
    out = json.loads(done.stdout)

    principal = cli_principal(env)
    service = WorkspaceService(root, environ=env)
    decision = service.authorize(principal, RUN_START_TOOL, TEST)
    assert out["principal"] == {
        "kind": principal.kind,
        "id": principal.id,
        "attended": principal.attended,
    }
    assert out["tool"] == RUN_START_TOOL and out["graph"] == TEST
    assert out["decision"] == {
        "verdict": decision.verdict,
        "final": decision.final,
        "layer": decision.layer,
        "source": decision.source,
        "reason": decision.reason,
        "diagnostics": [d.to_dict() for d in decision.diagnostics],
    }
    assert (decision.verdict, decision.final, decision.reason) == expected
    # 집행도 같다: 허용이면 실행(통과 0), 아니면 실행 없이 5
    if decision.final == "allow":
        assert done.returncode == 0 and out["verdict"] == "pass", done.stderr
    else:
        assert done.returncode == 5 and out["run_dir"] is None, done.stderr
        assert not (root / "runs").exists() or not list((root / "runs").iterdir())


@pytest.mark.parametrize(
    ("before", "after", "final"),
    [
        pytest.param(None, {"run": "allow"}, "deny", id="deny-then-allow"),
        pytest.param({"run": "allow"}, None, "allow", id="allow-then-deny"),
    ],
)
def test_same_action_same_decision_cli_and_service_reported_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    before: dict[str, str] | None,
    after: dict[str, str] | None,
    final: str,
) -> None:
    # 판정 직후 정책 파일이 바뀌어도 CLI가 보고하는 판정은 집행한 판정 하나다 (판정은 한 번)
    root = workspace(tmp_path, GraphBuilder().entry("n").node("n", "core.test.pass"))

    def local(toolsets: dict[str, str] | None) -> None:
        data: dict[str, Any] = {"format": "kookabug.local/0"}
        if toolsets is not None:
            data["permissions"] = {"toolsets": toolsets}
        write_json(root, ".kookabug/local.json", data)

    local(before)
    seen: list[Decision] = []
    authorize = WorkspaceService.authorize

    def authorize_then_change(
        service: WorkspaceService, principal: Principal, tool: str, arg: str = ""
    ) -> Decision:
        seen.append(authorize(service, principal, tool, arg))
        local(after)  # 판정에 쓴 뒤 정책을 반대로 바꾼다
        return seen[-1]

    env = cli_env(tmp_path, None, KOOKABUG_AGENT="conn-9")
    for name in list(os.environ):
        if name.upper().startswith("KOOKABUG_"):
            monkeypatch.delenv(name)
    for name, value in env.items():
        if name.startswith("KOOKABUG_"):
            monkeypatch.setenv(name, value)
    monkeypatch.setattr(WorkspaceService, "authorize", authorize_then_change)
    monkeypatch.chdir(root)

    out, err = io.StringIO(), io.StringIO()
    try:
        code = cli_main.run_command(
            cli_main.build_parser().parse_args(["run", TEST, "--json"]), out, err
        )
    finally:
        _faults.reset()  # CLI가 정한 감독자 역할을 pytest 프로세스에 남기지 않는다
    report = json.loads(out.getvalue())

    (decision,) = seen  # 판정 한 번
    assert decision.final == final
    assert report["decision"] == cli_main.decision_json(decision)
    if final == "allow":
        assert code == 0 and report["verdict"] == "pass", err.getvalue()
    else:
        assert code == 5 and report["run_dir"] is None
        assert not (root / "runs").exists() or not list((root / "runs").iterdir())
