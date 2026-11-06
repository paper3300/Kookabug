"""설치 플러그인 실행 연결 (M6 계획 B3, 3.6·D8·D9): 환경별 워커·워커 중첩 Job·hello 대조·사용 표식.

실제 uv·venv·워커·runner·감독자를 쓴다 (네트워크 없음 — 로컬 인덱스). 실행은 이 프로세스의
감독자(`Supervisor`, CLI·daemon과 같은 코드)나 실제 CLI·daemon(`ThreadDaemon`)으로 한다. 플랫폼은
없음·가짜 (실제 게임 입력 없음).
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from helpers.daemon_runs import EventLog
from helpers.daemon_targets import locked_file
from helpers.graphs import GraphBuilder, link
from helpers.plugins import (
    YES,
    PluginWorld,
    Rig,
    cli_env,
    plugin_cli,
    tree_hashes,
)
from helpers.runner import RUNNER_CMD

from kb_testing.daemon import ThreadDaemon
from kb_testing.plugin_fixtures import PLUGINS, plugin_wheel, sdk_wheel
from kb_testing.proc import PROCS_DIR, python_cmd, wait_until
from kookabug_core.plugins import SDK_WHEEL_ENV, PluginOps, runtime
from kookabug_core.plugins import ops as ops_module
from kookabug_core.plugins.envs import IN_USE_DIR, env_digest, is_broken
from kookabug_core.plugins.lockfile import lock_sha256
from kookabug_core.plugins.uv import remove_tree
from kookabug_core.record import read_run_json
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import RunHandle, RunOutcome, StartOptions, Supervisor
from kookabug_core.win import current, identify, is_alive

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(900)]

GRAPH: Final = "tests/p.graph.json"
RUN_WAIT_S: Final = 180.0


# ---------------------------------------------------------------- 도우미


def sample_graph(rig: Rig, rel: str = GRAPH, **plugins: str) -> str:
    """예제 플러그인 순수 노드(글자 뒤집기)를 읽어 비교하고 통과."""
    g = GraphBuilder(plugins={"sample": "0.1.0", **plugins})
    g.entry("n_cmp")
    g.node("n_rev", "sample.text.reverse", inputs={"text": "abc"})
    g.node(
        "n_cmp",
        "core.assert.compare",
        inputs={"a": link("n_rev.text"), "op": "==", "b": "cba"},
        next={"ok": "n_pass"},
    )
    g.node("n_pass", "core.test.pass")
    return g.write(rig.root, rel)


def dep_graph(rig: Rig, expect: Mapping[str, str], rel: str = GRAPH) -> str:
    """`<id>.dep.version`(그 환경의 kbfix-dep 판)을 차례로 비교하고 통과."""
    g = GraphBuilder(plugins={pid: version for pid, version in _versions(expect).items()})
    ids = sorted(expect)
    g.entry(f"n_cmp_{ids[0]}")
    for index, pid in enumerate(ids):
        after = f"n_cmp_{ids[index + 1]}" if index + 1 < len(ids) else "n_pass"
        g.node(f"n_{pid}", f"{pid}.dep.version")
        g.node(
            f"n_cmp_{pid}",
            "core.assert.compare",
            inputs={"a": link(f"n_{pid}.version"), "op": "==", "b": expect[pid]},
            next={"ok": after},
        )
    g.node("n_pass", "core.test.pass")
    return g.write(rig.root, rel)


def _versions(expect: Mapping[str, str]) -> dict[str, str]:
    known = {"conflict_a": "0.1.0", "conflict_b": "0.2.0", "compatible_c": "0.1.0"}
    return {pid: known[pid] for pid in expect}


def run_env(
    world: PluginWorld, faults: Sequence[Mapping[str, Any]] | None = None, **extra: str
) -> dict[str, str]:
    rules = [dict(f) for f in faults] if faults else None
    return {**cli_env(world, rules), **extra}


def start(
    rig: Rig,
    graph: str = GRAPH,
    *,
    faults: Sequence[Mapping[str, Any]] | None = None,
    extra: Mapping[str, str] | None = None,
    **opts: Any,
) -> RunHandle:
    env = run_env(rig.world, faults, **dict(extra or {}))
    supervisor = Supervisor(runner_cmd=RUNNER_CMD, env=env)
    options = StartOptions(platform=PlatformSpec("none"), **opts)
    return supervisor.start(rig.root, graph, options)


def run(rig: Rig, graph: str = GRAPH, **kwargs: Any) -> RunOutcome:
    return start(rig, graph, **kwargs).wait(RUN_WAIT_S)


def events(outcome: RunOutcome, kind: str) -> list[dict[str, Any]]:
    lines = (outcome.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [e for e in (json.loads(line) for line in lines if line) if e.get("event") == kind]


def markers(rig: Rig) -> list[Path]:
    return sorted(p for p in rig.envs.glob(f"*/{IN_USE_DIR}/*") if p.is_file())


def gate_rule(point: str, gate: Path, event: str | None = None) -> dict[str, Any]:
    rule: dict[str, Any] = {"point": point, "role": "runner", "action": f"wait:{gate}"}
    if event is not None:
        rule["when"] = {"event": event}
    return rule


def wait_file(path: Path, timeout: float = 120.0) -> None:
    wait_until(path.exists, timeout=timeout)


def dead(pid: int) -> bool:
    ident = identify(pid)
    return ident is None or not is_alive(ident)


def gone_while_runner_alive(handle: RunHandle, *pids: int) -> None:
    """runner가 마무리 지점에 멈춰 살아 있는(실행 Job이 아직 열린) 동안 워커 런처·실제 인터프리터가
    끝난다 — 실행 Job 정리가 아니라 워커 Job이 끝냈다. 종료는 비동기라 잠깐 기다린다."""
    runner = handle.runner_ident
    assert runner is not None and is_alive(runner)
    wait_until(lambda: all(dead(pid) for pid in pids), timeout=10)
    assert is_alive(runner)


_PROBE: Final = '''"""워커 검사 픽스처: import 중 멈춤(KBFIX_HANG_IMPORT)·끝나지 않는 노드
(KBFIX_HANG_NODE). 멈추기 전에 실제 인터프리터 PID와 부모(venv 런처) PID를 파일에 남긴다."""

import os
import time
from pathlib import Path

from kookabug_sdk import Context, node

_PIDS = Path({pids!r})


def _mark(kind: str) -> None:
    _PIDS.with_name(_PIDS.name + "." + kind).write_text(f"{{os.getpid()}} {{os.getppid()}}")


if os.environ.get("KBFIX_HANG_IMPORT") == "1":
    _mark("import")
    while True:
        time.sleep(1)


@node(
    type="conflict_a.dep.version",
    version=1,
    title="의존성 판",
    pure=True,
    outputs={{"version": str}},
)
def dep_version(ctx: Context) -> dict[str, str]:
    if os.environ.get("KBFIX_HANG_NODE") == "1":
        _mark("node")
        while True:
            time.sleep(0.05)
    import kbfix_dep  # pyright: ignore[reportMissingImports]

    return {{"version": str(kbfix_dep.__version__)}}  # pyright: ignore[reportUnknownMemberType]
'''


def probe_wheel(tmp_path: Path) -> tuple[Path, Path]:
    """conflict_a와 같은 노드 선언(스키마 digest 같음)에 멈춤 스위치를 단 wheel, PID 파일 앞부분."""
    pids = tmp_path / "pids"
    code = _PROBE.format(pids=str(pids)).encode("utf-8")
    wheel = plugin_wheel(
        PLUGINS / "conflict_a", tmp_path / "probe", overrides={"kbfix_conflict_a/nodes.py": code}
    )
    return wheel, pids


def read_pids(path: Path) -> tuple[int, int]:
    interpreter, launcher = path.read_text(encoding="utf-8").split()
    return int(interpreter), int(launcher)


# ---------------------------------------------------------------- 실행


def test_sample_graph_runs_from_installed_env(rig: Rig) -> None:
    rig.add("sample")
    env = rig.env_dir("shared")
    files = tree_hashes(env)
    lock = rig.lock()
    entry = lock["plugins"][0]
    sample_graph(rig, **{"sample": "0.1.0"})
    outcome = run(rig)
    assert outcome.verdict == "pass", outcome.run_end
    # run.json: 설치 플러그인은 환경·wheel·스키마 해시, 조건에 정규 잠금 해시
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    plugins = {p["id"]: p for p in run_json["plugins"]}
    assert plugins["sample"] == {
        "id": "sample",
        "version": "0.1.0",
        "env": "shared",
        "wheel_sha256": entry["wheel_sha256"],
        "schema_sha256": entry["schema_sha256"],
    }
    assert run_json["conditions"]["plugin_lock_sha256"] == lock_sha256(lock)
    # 잠금 사본이 스냅샷에
    assert (outcome.run_dir / "snapshot" / "kookabug.lock").read_bytes() == rig.lock_bytes()
    # 워커는 환경 인터프리터 (runner·daemon은 플러그인을 import하지 않는다), 끝나면 표식 없음
    starts = events(outcome, "worker.start")
    assert len(starts) == 1
    stderr = (outcome.run_dir / "logs" / "worker-shared.stderr.log").read_text("utf-8", "replace")
    assert "Traceback" not in stderr
    assert markers(rig) == []
    assert tree_hashes(env) == files and env_digest(env) == lock["environments"]["shared"]["digest"]


def test_two_envs_in_one_run(rig: Rig) -> None:
    rig.add("conflict_a")
    rig.add("conflict_b")  # kbfix-dep 2 → 격리
    lock = rig.lock()
    assert {p["id"]: p["env"] for p in lock["plugins"]} == {
        "conflict_a": "shared",
        "conflict_b": "iso-conflict_b",
    }
    dep_graph(rig, {"conflict_a": "1.0.0", "conflict_b": "2.0.0"})
    outcome = run(rig)
    assert outcome.verdict == "pass", outcome.run_end
    starts = events(outcome, "worker.start")
    exits = events(outcome, "worker.exit")
    assert len(starts) == 2 and len({e["pid"] for e in starts}) == 2
    assert sorted(e["reason"] for e in exits) == ["shutdown", "shutdown"]
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    assert {p["id"]: p.get("env") for p in run_json["plugins"]} == {
        "conflict_a": "shared",
        "conflict_b": "iso-conflict_b",
        "core": None,
    }
    assert markers(rig) == []


def test_hang_before_hello_kills_launcher_and_interpreter(rig: Rig, tmp_path: Path) -> None:
    wheel, pids = probe_wheel(tmp_path)
    rig.ops().add(str(wheel), confirm=YES)
    dep_graph(rig, {"conflict_a": "1.0.0"})
    gate = tmp_path / "finish"
    handle = start(
        rig,
        faults=[gate_rule("runner.before_worker_shutdown", gate)],
        extra={"KBFIX_HANG_IMPORT": "1"},
        worker_start_timeout_ms=4_000,
    )
    wait_file(Path(f"{pids}.import"))
    interpreter, launcher = read_pids(Path(f"{pids}.import"))
    assert interpreter != launcher  # venv python.exe는 런처, 실제 인터프리터가 자식
    # 시작 기한이 지나면 runner가 워커 Job을 끝낸다 — runner가 아직 살아 있는(마무리 전) 때 확인
    wait_file(Path(f"{gate}.ready"))
    gone_while_runner_alive(handle, interpreter, launcher)
    Path(f"{gate}.go").write_text("")
    outcome = handle.wait(RUN_WAIT_S)
    assert outcome.run_end is not None
    assert outcome.run_end["verdict"] == "error"
    assert outcome.run_end["code"] == "worker_start_timeout", outcome.run_end
    assert markers(rig) == []


def test_cancel_kills_real_worker(rig: Rig, tmp_path: Path) -> None:
    wheel, pids = probe_wheel(tmp_path)
    rig.ops().add(str(wheel), confirm=YES)
    dep_graph(rig, {"conflict_a": "1.0.0"})
    gate = tmp_path / "finish"
    handle = start(
        rig,
        faults=[gate_rule("runner.before_worker_shutdown", gate)],
        extra={"KBFIX_HANG_NODE": "1"},
        worker_cancel_grace_ms=1_000,
        shutdown_grace_ms=10_000,
    )
    wait_file(Path(f"{pids}.node"))
    interpreter, launcher = read_pids(Path(f"{pids}.node"))
    assert interpreter != launcher
    handle.cancel()
    # 유예가 지나도 노드가 끝나지 않으면 워커 Job을 끝낸다 — 실제 인터프리터까지
    wait_file(Path(f"{gate}.ready"))
    gone_while_runner_alive(handle, interpreter, launcher)
    Path(f"{gate}.go").write_text("")
    outcome = handle.wait(RUN_WAIT_S)
    assert outcome.run_end is not None
    assert (outcome.run_end["verdict"], outcome.run_end["code"]) == ("error", "cancelled")
    assert [e["reason"] for e in events(outcome, "worker.exit")] == ["killed_after_grace"]
    assert markers(rig) == []


def _edit_lock(rig: Rig, edit: Any) -> bytes:
    path = rig.root / "kookabug.lock"
    original = path.read_bytes()
    data = json.loads(original)
    edit(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    return original


def test_schema_mismatch_and_permission_exceeded_rejected(rig: Rig) -> None:
    rig.add("sample")
    env = rig.env_dir("shared")
    files = tree_hashes(env)
    sample_graph(rig)
    # (1) 잠금의 schema_sha256과 워커의 노드 스키마가 다르다 (runner가 digest를 다시 계산한다)
    original = _edit_lock(rig, lambda d: d["plugins"][0].update(schema_sha256="0" * 64))
    outcome = run(rig)
    assert outcome.run_end is not None
    assert (outcome.run_end["verdict"], outcome.run_end["code"]) == (
        "error",
        "plugin_schema_mismatch",
    ), outcome.run_end
    assert [e["reason"] for e in events(outcome, "worker.exit")] == ["start_failed"]
    (rig.root / "kookabug.lock").write_bytes(original)
    # (2) 노드 effects가 잠금의 permissions 밖 (워커가 알린 머리의 permissions는 믿지 않는다)
    _edit_lock(rig, lambda d: d["plugins"][0]["manifest"].update(permissions=[]))
    outcome = run(rig)
    assert outcome.run_end is not None
    assert (outcome.run_end["verdict"], outcome.run_end["code"]) == (
        "error",
        "plugin_permission_exceeded",
    ), outcome.run_end
    (rig.root / "kookabug.lock").write_bytes(original)
    assert run(rig).verdict == "pass"
    assert tree_hashes(env) == files and markers(rig) == []


def _diagnostics(outcome: RunOutcome) -> list[str]:
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    return [d["code"] for d in run_json.get("diagnostics", [])]


def test_acquire_exhaustion_keeps_lock_hash_and_schemas(rig: Rig) -> None:
    """사용 표식을 계속 만들지 못해 재시도를 다 써도 잠금 해시·노드 스키마는 남는다 (B4: run.json
    `plugin_lock_sha256` 형식, `unknown_node_type` 없이 `plugin_env_missing`만)."""
    rig.add("conflict_a")
    (rig.env_dir("shared") / IN_USE_DIR).write_bytes(b"not a folder")
    result = runtime.acquire(rig.root, {"conflict_a"}, current(), environ=rig.world.environ)
    assert result.envs == [] and result.markers == []
    assert [p.code for p in result.problems] == ["plugin_env_missing"]
    assert result.lock_sha256 == lock_sha256(rig.lock())
    assert set(result.unready) == {"conflict_a"}
    assert result.versions == {"conflict_a": "0.1.0"}


def test_env_missing_or_stale_is_validation_error(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")
    sample_graph(rig)
    # 그래프 plugins 판이 잠금과 다르면 경고만 (실행은 통과)
    warned = sample_graph(rig, "tests/w.graph.json", sample="0.0.9")
    outcome = run(rig, warned)
    assert outcome.verdict == "pass", outcome.run_end
    assert "plugin_version_differs" in _diagnostics(outcome)
    # (1) 조건 다름: 앱 SDK가 바뀌었다 → 워커 없이 검증 오류(4), 자동 sync 없음
    other_sdk = sdk_wheel(tmp_path / "sdk-next", version="0.1.1")
    env_before = tree_hashes(rig.env_dir("shared"))
    outcome = run(rig, extra={SDK_WHEEL_ENV: str(other_sdk)})
    assert outcome.run_end is not None and outcome.run_end["code"] == "graph_invalid"
    assert "plugin_env_stale" in _diagnostics(outcome)
    assert events(outcome, "worker.start") == []
    # (2) 잠금에 없는 플러그인
    g = GraphBuilder(plugins={"nope": "1.0.0"})
    g.entry("n_x").node("n_x", "nope.thing", next={"ok": "n_pass"}).node("n_pass", "core.test.pass")
    g.write(rig.root, "tests/nope.graph.json")
    outcome = run(rig, "tests/nope.graph.json")
    assert outcome.run_end is not None and outcome.run_end["code"] == "graph_invalid"
    assert "plugin_not_installed" in _diagnostics(outcome)
    # (3) 환경 없음 (클론한 프로젝트처럼) — CLI는 실행 전 검증 오류 종료 4, 환경을 만들지 않는다
    remove_tree(rig.env_dir("shared"))
    assert env_before
    spec = tmp_path / "platform.json"
    spec.write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        python_cmd(
            "-m", "kookabug_cli", "run", GRAPH, "--workspace", rig.root, "--platform-fake", spec
        ),
        env=run_env(rig.world),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "plugin_env_missing" in proc.stdout + proc.stderr
    assert not any(rig.envs.iterdir())


def test_broken_first_env_skipped_by_run_and_install(rig: Rig) -> None:
    """이름 순 첫째 완성 환경이 깨졌으면(검증 실패) 실행·설치는 그 폴더를 고치지 않고 깨짐으로
    기록한 뒤 다음 후보를 쓰거나 새로 만든다 (B2 남은 리스크, 조율자 방향)."""
    rig.add("conflict_a")
    broken = rig.env_dir("shared")
    target = broken / "Lib" / "site-packages" / "kbfix_dep" / "__init__.py"
    target.write_text('__version__ = "tampered"\n', encoding="utf-8")
    files = tree_hashes(broken)
    dep_graph(rig, {"conflict_a": "1.0.0"})
    # 실행: 깨진 환경을 건너뛰고 쓸 환경이 없다 → 검증 오류 (변조된 코드는 돌지 않는다)
    outcome = run(rig)
    assert outcome.run_end is not None and outcome.run_end["code"] == "graph_invalid"
    assert "plugin_env_missing" in _diagnostics(outcome)
    assert is_broken(broken) and tree_hashes(broken) == files
    # sync가 새 환경을 만들고, 다음 실행은 새 환경으로 통과
    assert rig.ops().sync(confirm=YES)["created"] == ["shared"]
    fresh = rig.env_dir("shared")
    assert fresh != broken
    assert run(rig).verdict == "pass"
    # 설치 ⑦(가)도 깨진 폴더를 재사용하지 않는다: 지우고 같은 내용을 다시 설치하면 새 환경
    rig.ops().remove("conflict_a", confirm=YES)
    remove_tree(fresh)
    rig.add("conflict_a")
    again = rig.env_dir("shared")
    assert again not in (broken, fresh)
    assert tree_hashes(broken) == files and is_broken(broken)


# ---------------------------------------------------------------- 실행 중 설치 (H1)


@pytest.fixture
def shared_run(rig: Rig) -> Iterator[tuple[Path, dict[str, str]]]:
    """conflict_a를 공유 환경에 설치하고 그 그래프를 쓴다. (옛 환경, 그 파일 해시)."""
    rig.add("conflict_a")
    dep_graph(rig, {"conflict_a": "1.0.0"})
    old = rig.env_dir("shared")
    yield old, tree_hashes(old)


def _joined(rig: Rig, old: Path) -> Path:
    """compatible_c가 공유에 붙어 새 지문의 공유 환경이 생겼다."""
    lock = rig.lock()
    assert {p["id"]: p["env"] for p in lock["plugins"]}["compatible_c"] == "shared"
    fresh = rig.env_dir("shared")
    assert fresh != old
    return fresh


def test_cli_run_while_daemon_installs(
    rig: Rig, tmp_path: Path, shared_run: tuple[Path, dict[str, str]]
) -> None:
    """CLI 실행(사용 표식을 만든 뒤 멈춤) 중 다른 프로세스(daemon 역할 — 같은 `PluginOps`)가 설치
    커밋·gc: 실행이 쓰는 옛 환경은 그대로, 실행 통과. 실행이 끝난 뒤에야 gc가 옛 환경을 지운다."""
    old, files = shared_run
    gate = tmp_path / "marked"
    spec = tmp_path / "platform.json"
    spec.write_text("{}", encoding="utf-8")
    env = run_env(rig.world, [gate_rule("runner.plugins", gate, "marked")])
    with (tmp_path / "cli.out").open("wb") as out:
        cli = subprocess.Popen(
            python_cmd(
                "-m", "kookabug_cli", "run", GRAPH, "--workspace", rig.root, "--platform-fake", spec
            ),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_file(Path(f"{gate}.ready"))
            assert len(markers(rig)) == 1 and markers(rig)[0].parent.parent == old
            rig.add("compatible_c")  # 이 프로세스 = daemon의 설치 거래
            fresh = _joined(rig, old)
            removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
            assert old.name not in removed and old.is_dir()  # 사용 표식이 지킨다
            Path(f"{gate}.go").write_text("")
            assert cli.wait(RUN_WAIT_S) == 0, (tmp_path / "cli.out").read_text("utf-8", "replace")
        finally:
            if cli.poll() is None:
                cli.kill()
    assert tree_hashes(old) == files and markers(rig) == []
    removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
    assert old.name in removed and fresh.is_dir()


def test_daemon_run_while_cli_installs(
    rig: Rig, tmp_path: Path, shared_run: tuple[Path, dict[str, str]]
) -> None:
    """daemon 실행(사람 연결의 run.start, 사전 검증은 커밋된 wheel의 스키마) 중 CLI `plugin add`."""
    old, files = shared_run
    gate = tmp_path / "marked"
    spec = tmp_path / "platform.json"
    spec.write_text("{}", encoding="utf-8")
    env = run_env(rig.world, [gate_rule("runner.plugins", gate, "marked")])
    service = WorkspaceService(
        rig.root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    with (
        ThreadDaemon(rig.root, service=service, platform_fake=spec) as daemon,
        daemon.client() as client,
    ):
        started = client.call("run.start", {"path": GRAPH})
        client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        wait_file(Path(f"{gate}.ready"))
        assert [m.parent.parent for m in markers(rig)] == [old]
        proc = plugin_cli(rig, "add", rig.world.wheel("compatible_c"), "--yes")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        _joined(rig, old)
        Path(f"{gate}.go").write_text("")
        log = EventLog(client, started["run_id"]).until_ended(RUN_WAIT_S)
    assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass", log.ended
    assert tree_hashes(old) == files and markers(rig) == []


@pytest.mark.parametrize("order", ["runner_reads_first", "commit_first"])
def test_run_start_crossing_install_commit(
    rig: Rig, tmp_path: Path, shared_run: tuple[Path, dict[str, str]], order: str
) -> None:
    """스냅샷의 잠금 읽기(op.lock) ↔ 설치 ⑨ 잠금 교체(op.lock)의 교차 양쪽 순서: 실행은 반쯤 바뀐
    잠금을 보지 않고, 어느 쪽이든 고른 환경이 온전하며 통과한다. 옛 환경 파일은 그대로."""
    old, files = shared_run
    committing = threading.Event()
    release = threading.Event()
    failure: list[BaseException] = []

    def fault(stage: str) -> None:
        if stage == "before_commit" and order == "commit_first":
            committing.set()  # op.lock 안 (잠금 교체 직전)
            release.wait(60)

    def install() -> None:
        try:
            ops = PluginOps(rig.root, environ=rig.world.environ, fault=fault)
            ops.add(str(rig.world.wheel("compatible_c")), confirm=YES)
        except BaseException as exc:
            failure.append(exc)

    if order == "runner_reads_first":
        # runner가 op.lock 안에서 옛 잠금을 읽은 뒤 멈춘 사이 설치가 커밋 → runner는 표식을 만들기
        # 전에 잠금이 바뀐 것을 보고 새 잠금으로 다시 고른다
        gate = tmp_path / "read"
        handle = start(rig, faults=[gate_rule("runner.plugins", gate, "read")])
        wait_file(Path(f"{gate}.ready"))
        install()
        assert not failure, failure
        Path(f"{gate}.go").write_text("")
    else:
        # 설치가 op.lock을 쥔 채 교체 직전에 멈춘 사이 runner 시작 → runner는 op.lock을 기다렸다가
        # 새 잠금을 읽는다
        worker = threading.Thread(target=install)
        worker.start()
        assert committing.wait(300)
        handle = start(rig)
        time.sleep(2.0)
        release.set()
        worker.join(300)
        assert not failure, failure
    outcome = handle.wait(RUN_WAIT_S)
    assert outcome.verdict == "pass", outcome.run_end
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    new_lock = rig.lock()
    assert run_json["conditions"]["plugin_lock_sha256"] == lock_sha256(new_lock)
    assert (outcome.run_dir / "snapshot" / "kookabug.lock").read_bytes() == rig.lock_bytes()
    fresh = _joined(rig, old)
    assert tree_hashes(old) == files and fresh.is_dir() and markers(rig) == []


# ---------------------------------------------------------------- 검증 중 삭제 (B3 2라운드)


def test_gc_during_digest_retries_new_snapshot(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """표식 전 검증(digest) 중 다른 프로세스가 설치를 커밋하고 gc가 옛 환경을 지우는 합법적인
    순서: 예외로 끝나지 않고 op.lock 재확인 → 새 스냅샷으로 다시 골라 새 환경을 쓴다. 깨짐 기록 없음
    (review_B3_1 High 재현을 제품 회귀로)."""
    rig.add("conflict_a")
    old = rig.env_dir("shared")
    original = Path.read_bytes
    crossed: list[str] = []

    def read_bytes(path: Path) -> bytes:
        if not crossed and path.is_relative_to(old / "Lib" / "site-packages"):
            crossed.append(str(path))
            rig.add("compatible_c")
            assert old.name in rig.ops().gc(confirm=YES)["removed"]["envs"]
            assert not old.exists()
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = runtime.acquire(rig.root, {"conflict_a"}, current(), environ=rig.world.environ)
    try:
        assert crossed
        assert not result.problems, result.problems
        assert [env.folder for env in result.envs] == [_joined(rig, old)]
        assert result.lock_bytes == rig.lock_bytes() and len(result.markers) == 1
        assert not is_broken(old)
    finally:
        result.release()
    assert markers(rig) == []


def test_transient_read_failure_not_recorded_broken(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """잠금·폴더가 그대로인데 읽기가 한 번 실패하면 이번 실행만 환경 없음 — 깨짐으로 영구 기록하지
    않아 다음 실행은 같은 환경을 쓴다."""
    rig.add("conflict_a")
    env = rig.env_dir("shared")
    original = Path.read_bytes
    failed: list[str] = []

    def read_bytes(path: Path) -> bytes:
        if not failed and path.is_relative_to(env / "Lib" / "site-packages"):
            failed.append(str(path))
            raise PermissionError(13, "잠깐 잠김", str(path))
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read_bytes)
        result = runtime.acquire(rig.root, {"conflict_a"}, current(), environ=rig.world.environ)
    assert failed and result.envs == [] and result.markers == []
    assert [p.code for p in result.problems] == ["plugin_env_missing"]
    assert not is_broken(env) and markers(rig) == []
    again = runtime.acquire(rig.root, {"conflict_a"}, current(), environ=rig.world.environ)
    try:
        assert not again.problems and [e.folder for e in again.envs] == [env]
    finally:
        again.release()


def test_real_runner_recovers_when_gc_removes_digest_input(rig: Rig, tmp_path: Path) -> None:
    """실제 runner가 옛 환경 파일을 읽기 직전에 멈춘 사이 설치 커밋·gc → runner는 새 환경으로 통과
    (제품 runner에 읽기 장벽만 더한 진입점 `procs/runner_read_gate.py`)."""
    rig.add("conflict_a")
    old = rig.env_dir("shared")
    dep_graph(rig, {"conflict_a": "1.0.0"})
    gate = tmp_path / "digest"
    supervisor = Supervisor(
        runner_cmd=python_cmd(PROCS_DIR / "runner_read_gate.py"),
        env=run_env(rig.world, KB_GATE_ENV=str(old), KB_GATE=str(gate)),
    )
    handle = supervisor.start(rig.root, GRAPH, StartOptions(platform=PlatformSpec("none")))
    try:
        wait_file(Path(f"{gate}.ready"))
        rig.add("compatible_c")
        assert old.name in rig.ops().gc(confirm=YES)["removed"]["envs"]
    finally:
        Path(f"{gate}.go").write_text("", encoding="utf-8")
    outcome = handle.wait(RUN_WAIT_S)
    assert outcome.verdict == "pass", outcome.run_end
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    assert run_json["conditions"]["plugin_lock_sha256"] == lock_sha256(rig.lock())
    assert not old.exists() and markers(rig) == []


# ---------------------------------------------------------- gc 보존 = runner 선택 (B3 3라운드)


def test_real_file_lock_sync_gc_keeps_runnable_replacement(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 파일 잠금(공유 모드 0)으로 옛 환경을 읽지 못하는 동안: sync가 새 환경을 만들고(이름 순
    뒤) 실행 pass → gc는 runner와 같은 선택(`envs.select`)으로 새 환경과 읽지 못한 옛 환경을 모두
    남겨 다시 실행 pass. 잠금을 푼 뒤 gc는 중복(같은 지문 둘째)을 정리하고 실행은 계속 pass
    (review_B3_2 High 재현을 제품 회귀로)."""
    rig.add("conflict_a")
    old = rig.env_dir("shared")
    dep_graph(rig, {"conflict_a": "1.0.0"})
    with locked_file(old / "Lib" / "site-packages" / "kbfix_dep" / "__init__.py"):
        with monkeypatch.context() as patch:
            # 새 폴더가 옛 폴더 뒤에 정렬되는 정상 작업 ID (venv를 옮기지 않는다)
            patch.setattr(
                ops_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="f" * 32))
            )
            assert rig.ops().sync(confirm=YES)["created"] == ["shared"]
        (fresh,) = [p for p in rig.envs.iterdir() if p.is_dir() and p != old]
        assert old.name < fresh.name
        assert run(rig).verdict == "pass"
        removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
        assert removed == [] and fresh.is_dir() and old.is_dir()
        assert not is_broken(old)
        assert run(rig).verdict == "pass"
    # 잠금을 푼 뒤: 옛 환경이 다시 이름 순 첫째로 읽히므로 둘째(새 환경)가 중복으로 정리된다
    removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
    assert removed == [fresh.name] and old.is_dir() and not is_broken(old)
    assert rig.env_dir("shared") == old
    assert run(rig).verdict == "pass" and markers(rig) == []


def test_gc_keeps_unreadable_candidates_without_broken_record(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """고를 환경이 없고 후보를 읽지 못하면 gc는 그 후보를 남기고 깨짐으로 기록하지 않는다."""
    rig.add("conflict_a")
    env = rig.env_dir("shared")
    original = Path.read_bytes

    def blocked(path: Path) -> bytes:
        if path.is_relative_to(env / "Lib" / "site-packages"):
            raise PermissionError(13, "읽기 잠김", str(path))
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", blocked)
        assert rig.ops().gc(confirm=YES)["removed"]["envs"] == []
    assert env.is_dir() and not is_broken(env)


def test_marker_written_after_create_failure_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """표식 파일을 만든 뒤 쓰기가 실패해도 만든 표식은 모두 지워진다 (review_B3_2 Low)."""
    folders = [tmp_path / name for name in ("a", "b")]
    for folder in folders:
        folder.mkdir()
    result = runtime.RunPlugins(envs=[runtime.EnvUse(p.name, p, ()) for p in folders])
    ident = current()
    second = folders[1] / IN_USE_DIR / runtime.marker_name(ident)
    original = Path.write_bytes

    def write(path: Path, data: bytes) -> int:
        if path == second:
            original(path, data)
            raise OSError("만든 뒤 쓰기 실패")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", write)
    assert runtime._mark(result, ident) is False  # pyright: ignore[reportPrivateUsage]
    assert result.markers == []
    assert list(tmp_path.glob(f"*/{IN_USE_DIR}/*")) == []
