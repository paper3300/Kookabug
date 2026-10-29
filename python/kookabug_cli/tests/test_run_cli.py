"""`kookabug run` 실제 실행 (구현 계획 M0b 2.11).

종료 코드, 권한, 진행 출력, `--json`, Ctrl+C 처리기, cp1252 콘솔.
CLI는 하위 프로세스로 띄운다 (CLI가 감독자이고 runner·워커를 띄운다). 워크스페이스는 `tmp_path/ws`.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import CLI, cli_env, run_cli
from helpers.graphs import GraphBuilder, make_workspace, subgraph_interface, write_json
from helpers.run import tk
from helpers.runner import RUNNER_CMD
from helpers.worker import PLUGIN_MODULES

from kb_testing.console import run_legacy_console
from kb_testing.proc import Spawned, read_fake_input_log, wait_until
from kookabug_cli.main import InterruptHandler, exit_code_of
from kookabug_core.record import read_run
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import WorkspaceService, cli_principal
from kookabug_core.supervisor import StartOptions, Supervisor

pytestmark = pytest.mark.process

TEST = "tests/t.graph.json"
FAST = {"shutdown_grace_ms": 2000, "worker_cancel_grace_ms": 1000}


def ws_root(tmp_path: Path, graph: GraphBuilder | None = None, **config: Any) -> Path:
    root = tmp_path / "ws"
    make_workspace(root)
    write_json(root, "kookabug.json", {"format": "kookabug.workspace/0", "run": FAST, **config})
    if graph is not None:
        graph.write(root, TEST)
    return root


def plugin_args() -> list[str]:
    return [a for m in PLUGIN_MODULES for a in ("--plugin-module", m)]


def graph_for(case: str) -> GraphBuilder:
    if case == "pass":
        return GraphBuilder().entry("n").node("n", "core.test.pass")
    if case == "fail":
        return GraphBuilder().entry("n").node("n", "core.test.fail", inputs={"reason": "일부러"})
    if case == "error":
        return tk().entry("n").node("n", "testkit.boom", inputs={"message": "터짐"})
    if case == "skipped":
        return GraphBuilder().entry("n").node("n", "core.test.skip", inputs={"reason": "건너뜀"})
    assert case == "invalid"
    return GraphBuilder().entry("n").node("n", "core.no_such_node")


@pytest.mark.parametrize(
    ("case", "code"),
    [("pass", 0), ("fail", 1), ("error", 2), ("skipped", 3), ("invalid", 4)],
    ids=["pass-0", "fail-1", "error-2", "skipped-3", "invalid-4"],
)
def test_exit_codes(tmp_path: Path, case: str, code: int) -> None:
    root = ws_root(tmp_path, graph_for(case))
    done = run_cli(["run", TEST, "--json", *plugin_args()], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == code, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert out["exit_code"] == code
    assert out["verdict"] == {0: "pass", 1: "fail", 2: "error", 3: "skipped", 4: "error"}[code]
    if case == "invalid":
        assert out["code"] == "graph_invalid"
        run_json = json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))
        assert any(d["code"] == "unknown_node_type" for d in run_json["diagnostics"]), run_json
    if case == "error":
        assert out["code"] == "node_error" and out["failure_path"] == ["n"]
    # 실행 폴더·저널·run.json이 남았다 (감독자 복구 경로까지 돈 뒤)
    view = read_run(out["run_dir"])
    assert view.run_end is not None and view.run_end["finalized_by"] == "runner"


def assert_no_run(root: Path) -> None:
    assert not (root / "runs").exists() or not list((root / "runs").iterdir())


def test_permission_denied_exit_5_no_run_folder(tmp_path: Path) -> None:
    root = ws_root(tmp_path, graph_for("pass"))
    env = cli_env(tmp_path, KOOKABUG_AGENT="conn-7")
    done = run_cli(["run", TEST, "--json"], cwd=root, env=env)
    assert done.returncode == 5, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert out["principal"] == {"kind": "agent", "id": "conn-7", "attended": False}
    decision = out["decision"]
    # 기본 프리셋 graph_author는 kb_run_start를 거부한다
    assert (decision["final"], decision["source"]) == ("deny", "preset:graph_author")
    assert out["run_dir"] is None and out["error"]
    assert_no_run(root)
    # 사람(KOOKABUG_AGENT 없음)은 판정하지 않고 허용한다
    done = run_cli(["run", TEST, "--json"], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["decision"]["reason"] == "human"


def test_agent_ask_exit_5_no_run_folder(tmp_path: Path) -> None:
    root = ws_root(tmp_path, graph_for("pass"))
    write_json(
        root,
        ".kookabug/local.json",
        {"format": "kookabug.local/0", "permissions": {"toolsets": {"run": "ask"}}},
    )
    env = cli_env(tmp_path, KOOKABUG_AGENT="conn-7")
    done = run_cli(["run", TEST, "--json"], cwd=root, env=env)
    assert done.returncode == 5, done.stdout + done.stderr
    decision = json.loads(done.stdout)["decision"]
    # CLI 에이전트는 사람 없는 실행이다: ask는 승인을 받을 수 없어 거부로 집행한다
    assert (decision["verdict"], decision["final"]) == ("ask", "deny")
    assert decision["reason"] == "unattended_ask"
    assert_no_run(root)
    # 텍스트 출력도 같은 종료 코드 (stderr에 사유)
    done = run_cli(["run", TEST], cwd=root, env=env)
    assert done.returncode == 5 and "kb_run_start" in done.stderr
    assert_no_run(root)


SUB = "subgraphs/login.graph.json"


def test_progress_lines_and_failure_path_titles(tmp_path: Path) -> None:
    root = ws_root(tmp_path)
    (
        GraphBuilder("subgraph", interface=subgraph_interface(exits={"done": "ok"}))
        .entry("n_cmp")
        .node(
            "n_cmp",
            "core.assert.compare",
            inputs={"a": 1, "op": "==", "b": 2},
            next={"ok": "n_exit"},
            title="서버 이름 확인",
        )
        .exit("n_exit", "done")
        .write(root, SUB)
    )
    (
        GraphBuilder()
        .entry("n_log")
        .node(
            "n_log",
            "core.log.message",
            inputs={"text": "시작"},
            next={"done": "n_call"},
            title="시작 알림",
        )
        .node("n_call", "core.graph.call", config={"graph": SUB}, title="로그인")
        .write(root, TEST)
    )
    done = run_cli(["run", TEST], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == 1, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert "  [성공] 시작 알림 → done" in "\n".join(lines)
    (inner,) = [ln for ln in lines if ln.startswith("  [") and "로그인 > 서버 이름 확인" in ln]
    assert inner.startswith("  [실패]") and "→ fail" in inner
    assert "판정: 실패 (unhandled_fail)" in lines
    assert "실패 위치: 로그인 > 서버 이름 확인" in lines
    (folder,) = [ln for ln in lines if ln.startswith("실행 폴더: ")]
    assert read_run(folder.removeprefix("실행 폴더: ")).run_end is not None

    # --quiet: 스텝 줄 없이 요약만
    done = run_cli(["run", TEST, "--quiet"], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == 1
    assert not [ln for ln in done.stdout.splitlines() if ln.startswith("  [")]
    assert "실패 위치: 로그인 > 서버 이름 확인" in done.stdout


def test_json_output_single_object(tmp_path: Path) -> None:
    root = ws_root(tmp_path, graph_for("fail"))
    done = run_cli(
        ["run", TEST, "--json", "--set", "x=1", "--deadline-ms", "60000"],
        cwd=root,
        env=cli_env(tmp_path),
    )
    assert done.returncode == 1, done.stderr
    assert done.stdout.count("\n") == 1  # 한 줄, 진행 줄 없음
    out = json.loads(done.stdout)
    assert (out["verdict"], out["code"], out["reason"]) == ("fail", "test_fail", "일부러")
    assert out["failure_path"] == ["n"] and out["failure_titles"] == ["n"]
    assert out["graph"] == TEST and Path(out["workspace"]) == root.resolve()
    assert out["decision"]["final"] == "allow" and out["runner_exit_code"] == 0
    run_json = json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))
    assert run_json["conditions"]["deadline_ms"] == 60000
    assert run_json["status"] == "finished" and run_json["verdict"] == "fail"


class FakeHandle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.calls.append(("cancel", threading.current_thread().name))
        self.cancelled.set()

    def hard_stop(self) -> None:
        self.calls.append(("hard_stop", threading.current_thread().name))


def key_graph() -> GraphBuilder:
    return (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", inputs={"key": "ctrl"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_ctrl_c_handler_cancels_then_force_stops(tmp_path: Path, spawned: Spawned) -> None:
    # 처리기 자체: 첫 번째는 다른 스레드에서 cancel(기다리는 호출), 두 번째부터 hard_stop(즉시)
    fake = FakeHandle()
    handler = InterruptHandler(fake)
    handler()
    assert fake.cancelled.wait(5)
    handler()
    handler()
    assert [c for c, _ in fake.calls] == ["cancel", "hard_stop", "hard_stop"]
    assert fake.calls[0][1] == "cli-cancel"
    assert fake.calls[1][1] == threading.current_thread().name

    # 실제 실행: 키를 누른 채 액터가 멈춘 runner. 첫 번째로 취소해도 마무리하지 못하고, 마무리
    # 유예(60초)를 기다리지 않고 두 번째가 runner를 바로 끝낸다 → 감독자 복구 경로가 키를 뗀다
    root = ws_root(tmp_path, key_graph())
    log = tmp_path / "input.jsonl"
    supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=cli_env(tmp_path))
    service = WorkspaceService(root, supervisor=supervisor)
    handle = service.start_run(
        cli_principal({}),
        TEST,
        StartOptions(
            plugin_modules=PLUGIN_MODULES,
            platform=PlatformSpec(
                "fake", input_log=str(log), hooks={"after_down": {"ctrl": "hang"}}
            ),
            shutdown_grace_ms=60_000,
            runs_dir=root / "runs",
        ),
    )
    assert handle.runner_ident is not None
    spawned.track(handle.runner_ident)
    wait_until(lambda: any(ln["op"] == "down" for ln in read_fake_input_log(log)))
    handler = InterruptHandler(handle)
    handler()
    wait_until(
        lambda: any(e["event"] == "cancel.requested" for e in read_run(handle.run_dir).events)
    )
    assert handle.runner is not None and handle.runner.alive()  # 액터가 멈춰 끝나지 못한다
    handler()
    outcome = handle.wait(30)
    assert outcome.hard_stopped and outcome.exit_code == 4
    assert outcome.run_end is not None and outcome.run_end["code"] == "runner_died"
    assert outcome.run_end["cancel_reason"] == "cancelled"
    assert exit_code_of(outcome) == 2
    last = read_fake_input_log(log)[-1]
    assert (last["op"], last["key"], last["by"]) == ("up", "ctrl", "supervisor")


def test_korean_output_under_cp1252(tmp_path: Path) -> None:
    graph = (
        GraphBuilder()
        .entry("n_log")
        .node(
            "n_log",
            "core.log.message",
            inputs={"text": "한글 로그"},
            next={"done": "n_pass"},
            title="한글 제목 노드",
        )
        .node("n_pass", "core.test.pass", title="통과 확인")
    )
    root = ws_root(tmp_path, graph)
    done = run_legacy_console([*CLI, "run", TEST], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "  [성공] 한글 제목 노드 → done" in done.stdout
    assert "판정: 통과 (test_pass)" in done.stdout
    # 오류 경로(stderr)도 한국어
    done = run_legacy_console([*CLI, "run", "없는.graph.json"], cwd=root, env=cli_env(tmp_path))
    assert done.returncode == 6 and "그래프 파일이 없다" in done.stderr


def test_recovery_failure_after_run_end_is_error_exit(tmp_path: Path) -> None:
    # runner가 run.end(pass)를 쓴 직후 죽고, 감독자 복구 경로는 마무리 직전에 실패한다 → run.json은
    # running으로 남는다. 그래프 판정(pass)은 보존하되 CLI는 마무리 실패를 알리고 오류로 끝난다
    rules = [
        {"point": "runner.after_run_end", "role": "runner", "action": "exit:9"},
        {"point": "recovery.before_finalize", "role": "supervisor", "action": "raise"},
    ]
    root = ws_root(tmp_path, graph_for("pass"))
    env = cli_env(tmp_path, rules)

    done = run_cli(["run", TEST], cwd=root, env=env)
    assert done.returncode == 2, done.stdout + done.stderr
    assert "판정: 통과 (test_pass)" in done.stdout
    assert "기록 마무리 실패: RuntimeError" in done.stdout
    assert "오류: 기록 마무리 실패: RuntimeError" in done.stderr

    done = run_cli(["run", TEST, "--json"], cwd=root, env=env)
    assert done.returncode == 2, done.stdout + done.stderr
    out = json.loads(done.stdout)
    assert (out["verdict"], out["code"], out["finalized_by"]) == ("pass", "test_pass", "runner")
    assert out["exit_code"] == 2 and out["runner_exit_code"] == 9
    assert out["recover_error"] and "recovery.before_finalize" in out["recover_error"]
    assert out["error"].startswith("기록 마무리 실패")
    run_json = json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))
    assert run_json["status"] == "running"
