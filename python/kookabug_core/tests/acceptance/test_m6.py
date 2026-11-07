"""M6 완료 기준 (구현 계획 v0 1장 M6 행, M6 계획 5장) 인수 테스트, Python 쪽.

1. 외부 레포의 샘플 플러그인이 설치·실행된다 — 레포·워크스페이스 밖 임시 git 레포(예제
   사본, 스키마 파일 없음, 태그) + 로컬 인덱스: `plugin add git+file://…@v0.1.0 --yes` →
   승인 뒤 스키마 생성·wheel 커밋 → `kookabug run` 예제 그래프 pass → run.json·실행 스냅샷
   잠금에 커밋·wheel·스키마 해시
2. 의존성이 충돌하는 두 플러그인이 격리된다 — a → b(격리, 공유 지문·digest 그대로) →
   c(공유에 붙음, a 노드 결과 그대로), 한 그래프에서 kbfix-dep 1.0.0·2.0.0
3. 설치 실패가 기존 환경을 깨지 않는다 — 깨진 픽스처·단계 고장·커밋 전 kill·같은 지문
   재사용 뒤 실패, 잠금 교체 직후 kill, 실행 중 설치(CLI↔daemon·시작↔커밋 교차)와 그 뒤 gc
4. 다른 PC에서 잠금 파일로 같은 환경이 재현된다 — 사본·새 uv 캐시·새 `.kookabug`·원천 git
   레포 지움 → sync → digest = 잠금 = 원본, 같은 결과. 변조 실패, sdist만 있는 의존성 거부,
   SDK가 바뀐 앱은 거부 → relock
(엄격) 에이전트는 설치·개발 모듈 실행을 못 한다, 신뢰 확인 전 코드 실행 없음·인증 정보 가림

실제 uv·venv·워커·runner·감독자·daemon·`kookabug mcp`(stdio)를 쓴다. 네트워크 없음: 세션
픽스처 하나가 SDK wheel·로컬 인덱스(127.0.0.1)·임시 uv 캐시를 만든다
(`helpers.plugins.plugin_world`). 다른 테스트 모듈을 import하지 않는다. 자세한 경우는 근거
테스트(`kookabug_core/tests/plugins/*`, `kookabug_daemon/tests/test_plugin_methods.py`·
`test_dev_modules_agent.py`, `kookabug_cli/tests/test_dev_modules_agent.py`,
`kookabug_mcp/tests/test_plugin_info.py`)에 있다. 실제 공개 레포·PyPI·다른 실제 PC·설치본
앱 화면은 `Docs/verification/m6-manual.md`다.
"""

from __future__ import annotations

import hashlib
import json
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.daemon_runs import EventLog
from helpers.graphs import GraphBuilder, link, make_workspace, write_json
from helpers.plugins import (
    YES,
    Rig,
    cli_env,
    git_source,
    hang_wheel,
    plugin_cli,
    plugin_world,
    rig,
    run_graph,
    run_node,
    sample_graph,
    tree_hashes,
)
from helpers.runner import RUNNER_CMD
from helpers.worker import PLUGIN_MODULES

from kb_testing.daemon import ThreadDaemon, daemon_env
from kb_testing.mcp_client import McpClient
from kb_testing.plugin_fixtures import PLUGINS, SAMPLE, git_repo, sdk_wheel
from kb_testing.proc import Spawned, direct_env, python_cmd, wait_until
from kookabug_core.permissions import TOOLSETS
from kookabug_core.plugins import SDK_WHEEL_ENV, PluginError, PluginOps
from kookabug_core.plugins.envs import IN_USE_DIR, MARKER, env_digest, find_env
from kookabug_core.plugins.lockfile import lock_sha256, revision_of
from kookabug_core.plugins.uv import remove_tree
from kookabug_core.record import read_run_json
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import StartOptions, Supervisor
from kookabug_core.win import identify, is_alive
from kookabug_daemon.client import DaemonClient, DaemonError

__all__ = ["plugin_world", "rig"]

pytestmark = [pytest.mark.process, pytest.mark.packaging, pytest.mark.timeout(900)]

GRAPH: Final = "tests/m6.graph.json"
RUN_WAIT_S: Final = 180.0
AGENT: Final = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-m6", "attended": True}
SECRET: Final = "kbsecret-m6-token"
BROKEN: Final = (
    "broken_import",
    "schema_drift",
    "unresolvable",
    "bad_effects",
    "id_core",
    "sdist_only",
    "sdk_too_new",
)


# ---------------------------------------------------------------- 도우미


def dep_graph(root: Path, expect: Mapping[str, str], rel: str = GRAPH) -> str:
    """`<id>.dep.version`(그 환경의 kbfix-dep 판)을 차례로 비교하고 통과하는 그래프."""
    known = {"conflict_a": "0.1.0", "conflict_b": "0.2.0", "compatible_c": "0.1.0"}
    g = GraphBuilder(plugins={pid: known[pid] for pid in expect})
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
    return g.write(root, rel)


def state(rig: Rig) -> tuple[bytes | None, dict[str, str], dict[str, str]]:
    """잠금 바이트·환경 폴더 파일 전체·커밋된 wheel (작업이 바꾸면 안 되는 것)."""
    return rig.lock_bytes(), tree_hashes(rig.envs), tree_hashes(rig.root / "plugins" / "wheels")


def assert_kept(rig: Rig, before: tuple[bytes | None, dict[str, str], dict[str, str]]) -> None:
    lock, envs, wheels = before
    assert rig.lock_bytes() == lock
    now = tree_hashes(rig.envs)
    assert {k: now.get(k) for k in envs} == envs  # 기존 파일 전체 (새 폴더는 생겨도 된다)
    now_wheels = tree_hashes(rig.root / "plugins" / "wheels")
    assert {k: now_wheels.get(k) for k in wheels} == wheels


def env_files(folder: Path) -> dict[str, str]:
    """환경 폴더 파일 전체 (실행의 사용 표식 `.in-use/`는 빼고)."""
    return {k: v for k, v in tree_hashes(folder).items() if not k.startswith(f"{IN_USE_DIR}/")}


def staging(rig: Rig) -> Path:
    return rig.root / ".kookabug" / "plugins" / "staging"


def markers(rig: Rig) -> list[Path]:
    return sorted(p for p in rig.envs.glob(f"*/{IN_USE_DIR}/*") if p.is_file())


def fault_wait(point: str, role: str, event: str, path: Path) -> dict[str, Any]:
    return {"point": point, "role": role, "when": {"event": event}, "action": f"wait:{path}"}


def platform_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "platform.json"
    spec.write_text("{}", encoding="utf-8")
    return spec


def cli_run(
    root: Path, graph: str, env: dict[str, str], spec: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        python_cmd(
            "-m", "kookabug_cli", "run", graph, "--json", "--workspace", root,
            "--platform-fake", spec,
        ),
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=300,
        check=False,
    )  # fmt: skip


def notification(
    client: DaemonClient, method: str, timeout: float = 300.0, **match: Any
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise AssertionError(f"{method} {match} 알림이 오지 않았다")
        try:
            message = client.notifications.get(timeout=left)
        except queue.Empty:
            continue
        params = message.get("params", {})
        if message.get("method") == method and all(params.get(k) == v for k, v in match.items()):
            return params


def daemon_install(client: DaemonClient, source: Path | str) -> dict[str, Any]:
    """앱이 하는 대로: 미리보기(①②) → 신뢰 확인 → 설치 → 끝 알림."""
    shown = client.call("plugins.preview", {"source": str(source)})
    client.call("plugins.install", {"op_id": shown["op_id"]})
    done = notification(client, "plugins.done", op_id=shown["op_id"])
    assert done["ok"] is True, done
    return done


# ---------------------------------------------------------------- 1. 외부 레포


def test_external_repo_plugin_installs_and_runs(rig: Rig, tmp_path: Path) -> None:
    repo = git_repo(SAMPLE, tmp_path / "outside" / "repos" / "kookabug-plugin-sample")
    assert not list(repo.rglob("kookabug.schema.json"))  # 생성 파일은 커밋하지 않았다
    proc = plugin_cli(rig, "add", git_source(repo, "v0.1.0"), "--yes", "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lock = rig.lock()
    (entry,) = lock["plugins"]
    assert entry["id"] == "sample" and entry["source"]["kind"] == "git"
    assert entry["source"]["ref"] == "v0.1.0" and len(entry["source"]["commit"]) == 40
    # 진입 모듈 ≠ 최상위 패키지 — 설치는 머리의 modules로 워커를 띄운다
    modules = entry["manifest"]["modules"]
    assert modules == ["kookabug_plugin_sample.nodes.text", "kookabug_plugin_sample.nodes.widgets"]
    wheel = rig.root.joinpath(*entry["wheel"].split("/"))
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == entry["wheel_sha256"]
    assert entry["wheel"].startswith(f"plugins/wheels/{entry['wheel_sha256']}/")
    # 실행 환경에는 승인 뒤 만든 스키마가 있고 빌드 도구는 없다
    env = rig.env_dir(entry["env"])
    site = env / "Lib" / "site-packages"
    assert (site / "kookabug_plugin_sample" / "kookabug.schema.json").is_file()
    assert not list(site.glob("uv_build*"))

    sample_graph(rig.root, GRAPH)
    run = cli_run(rig.root, GRAPH, cli_env(rig.world), platform_spec(tmp_path))
    assert run.returncode == 0, run.stdout + run.stderr
    out = json.loads(run.stdout)
    assert out["verdict"] == "pass", out
    run_dir = Path(out["run_dir"])
    run_json = read_run_json(run_dir / "run.json")
    assert run_json is not None
    recorded = next(p for p in run_json["plugins"] if p["id"] == "sample")
    assert recorded["env"] == entry["env"]
    assert recorded["wheel_sha256"] == entry["wheel_sha256"]
    assert recorded["schema_sha256"] == entry["schema_sha256"]
    assert run_json["conditions"]["plugin_lock_sha256"] == lock_sha256(lock)
    snapshot = json.loads((run_dir / "snapshot" / "kookabug.lock").read_text(encoding="utf-8"))
    assert snapshot["plugins"][0]["source"]["commit"] == entry["source"]["commit"]


# ---------------------------------------------------------------- 2. 충돌 격리


def test_conflicting_plugins_isolated(rig: Rig) -> None:
    rig.add("conflict_a")
    shared = rig.lock()["environments"]["shared"]
    shared_dir = rig.env_dir("shared")
    shared_files = tree_hashes(shared_dir)

    rig.add("conflict_b")  # kbfix-dep>=2 — 공유의 1.x를 바꿔야 하므로 그것만 격리
    lock = rig.lock()
    b = next(p for p in lock["plugins"] if p["id"] == "conflict_b")
    assert b["env"] == "iso-conflict_b" and b["isolated_because"] == "conflict"
    assert "kbfix-dep" in b["conflicts"]
    assert lock["environments"]["shared"]["fingerprint"] == shared["fingerprint"]
    assert lock["environments"]["shared"]["digest"] == shared["digest"]
    assert tree_hashes(shared_dir) == shared_files

    rig.add("compatible_c")  # kbfix-dep>=1,<3 — 공유(1.0.0)에 붙는다
    lock = rig.lock()
    assert {p["id"]: p["env"] for p in lock["plugins"]} == {
        "compatible_c": "shared",
        "conflict_a": "shared",
        "conflict_b": "iso-conflict_b",
    }
    assert [p["version"] for p in lock["environments"]["shared"]["packages"]
            if p["name"] == "kbfix-dep"] == ["1.0.0"]  # fmt: skip
    assert tree_hashes(shared_dir) == shared_files  # 옛 공유 환경 파일은 그대로 (gc 몫)
    # 한 그래프에서 두 환경(워커 둘): a·c는 1.0.0, b는 2.0.0 — a 노드 결과는 그대로
    graph = dep_graph(
        rig.root, {"conflict_a": "1.0.0", "conflict_b": "2.0.0", "compatible_c": "1.0.0"}
    )
    outcome = run_graph(rig, graph)
    assert outcome.verdict == "pass", outcome.run_end
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    assert {p["id"]: p.get("env") for p in run_json["plugins"] if p["id"] != "core"} == {
        "compatible_c": "shared",
        "conflict_a": "shared",
        "conflict_b": "iso-conflict_b",
    }


# ---------------------------------------------------------------- 3. 실패해도 기존 환경 그대로


def _start_add(
    rig: Rig, spawned: Spawned, wheel: Path, faults: list[dict[str, Any]] | None = None
) -> subprocess.Popen[bytes]:
    return spawned.popen(
        python_cmd(
            "-m", "kookabug_cli", "plugin", "add", wheel, "--yes", "--json", "--workspace", rig.root
        ),
        env=cli_env(rig.world, faults),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_failed_installs_keep_environment(rig: Rig, spawned: Spawned, tmp_path: Path) -> None:
    rig.add("sample")
    sample_graph(rig.root, GRAPH)
    before = state(rig)

    # 깨진 픽스처 전부: 잠금·기존 환경 파일·커밋된 wheel 그대로, staging도 남지 않는다
    for name in BROKEN:
        with pytest.raises(PluginError):
            rig.add(name)
        assert_kept(rig, before)
        assert not any(staging(rig).iterdir()), name
    # 단계 고장 (만드는 단계·검증·보관·커밋 직전)
    for stage in ("resolved", "env_installed", "env_verified", "archived", "before_commit"):
        rig.fail_at, rig.faults = stage, []
        with pytest.raises((PluginError, RuntimeError)):
            rig.add("conflict_a")
        assert stage in rig.faults
        assert_kept(rig, before)
    rig.fail_at = None

    # 커밋 전 kill: ⑦(나) 검증 import에서 멈춘 CLI를 죽인다 → Job이 손자까지, 잠금 그대로,
    # 미완성 폴더는 "없는 것"으로 남고 다음 작업이 staging만 지운다
    known = {p.name for p in rig.envs.iterdir()}  # 앞 단계 고장이 남긴 폴더 포함 (gc 몫)
    pid_file = tmp_path / "hang.pid"
    cli = _start_add(rig, spawned, hang_wheel(rig.world, tmp_path / "hang", pid_file))
    wait_until(pid_file.is_file, timeout=180, message="검증 인터프리터가 멈춘 곳에 오지 않았다")
    real, launcher = (int(x) for x in pid_file.read_text().split())
    idents = [i for i in (identify(real), identify(launcher)) if i is not None]
    cli.kill()
    cli.wait(30)
    wait_until(lambda: not any(is_alive(i) for i in idents), timeout=30, message="Job 정리")
    assert_kept(rig, before)
    left = [p for p in rig.envs.iterdir() if p.name not in known]
    assert left and all(not (p / MARKER).exists() for p in left)
    assert any(staging(rig).iterdir())

    # 같은 지문 재사용(읽기 검증만) 뒤 실패: 재사용 폴더 파일 전체 불변
    rig.ops().remove("sample", confirm=YES)
    reused = find_env(rig.envs, "shared", before_fp := _fp(before[0]))
    assert reused is not None
    reused_files = tree_hashes(reused)
    removed_lock = rig.lock_bytes()
    rig.fail_at = "archived"
    with pytest.raises(RuntimeError):
        rig.add("sample")
    assert "env_reused" in rig.faults
    rig.fail_at = None
    assert rig.lock_bytes() == removed_lock and tree_hashes(reused) == reused_files
    assert not any(staging(rig).iterdir())  # 이 작업의 ⓪이 kill이 남긴 staging을 지웠다
    assert all(p.exists() for p in left)  # 미완성 폴더는 gc 몫

    # 다시 설치하면 같은 지문의 그 폴더를 그대로 쓰고, 기존 그래프가 실제 실행으로 통과
    result = rig.ops().add(str(rig.world.wheel("sample")), confirm=YES)
    assert result["reused"] is True and rig.env_dir("shared") == reused
    assert rig.lock()["environments"]["shared"]["fingerprint"] == before_fp
    assert tree_hashes(reused) == reused_files
    assert rig.ops().verify()["ok"]
    assert run_graph(rig, GRAPH).verdict == "pass"


def _fp(lock_bytes: bytes | None) -> str:
    assert lock_bytes is not None
    return json.loads(lock_bytes)["environments"]["shared"]["fingerprint"]


def test_kill_right_after_commit_install_stays_valid(
    rig: Rig, spawned: Spawned, tmp_path: Path
) -> None:
    signal = tmp_path / "committed"
    cli = _start_add(
        rig,
        spawned,
        rig.world.wheel("sample"),
        [fault_wait("plugins.stage", "plugin", "committed", signal)],
    )
    wait_until(Path(f"{signal}.ready").is_file, timeout=180, message="⑨ 뒤에 오지 않았다")
    cli.kill()
    cli.wait(30)
    assert [p["id"] for p in rig.lock()["plugins"]] == ["sample"]
    assert any(staging(rig).iterdir())  # ⑩ 전에 죽었다
    shared = rig.env_dir("shared")
    files = tree_hashes(shared)
    rig.add("conflict_b")  # 다음 작업: staging만 지운다
    assert not any(staging(rig).iterdir())
    assert sorted(p["id"] for p in rig.lock()["plugins"]) == ["conflict_b", "sample"]
    assert tree_hashes(shared) == files
    proc = plugin_cli(rig, "verify", "--json")
    assert proc.returncode == 0 and json.loads(proc.stdout)["ok"] is True, proc.stdout
    assert run_graph(rig, sample_graph(rig.root, GRAPH)).verdict == "pass"
    assert tree_hashes(shared) == files


def test_runs_survive_concurrent_installs(rig: Rig, tmp_path: Path) -> None:
    rig.add("conflict_a")
    graph = dep_graph(rig.root, {"conflict_a": "1.0.0"})
    old = rig.env_dir("shared")
    old_files = env_files(old)
    old_digest = env_digest(old)
    spec = platform_spec(tmp_path)

    # (1) CLI 실행(사용 표식을 만든 뒤 멈춤) 중 daemon 설치 (앱과 같은 plugins.preview → install)
    gate = tmp_path / "cli-marked"
    env = cli_env(rig.world, [fault_wait("runner.plugins", "runner", "marked", gate)])
    with (tmp_path / "cli.out").open("wb") as out:
        cli = subprocess.Popen(
            python_cmd(
                "-m", "kookabug_cli", "run", graph, "--workspace", rig.root, "--platform-fake", spec
            ),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_until(Path(f"{gate}.ready").exists, timeout=120)
            assert [m.parent.parent for m in markers(rig)] == [old]
            with (
                ThreadDaemon(rig.root, plugin_environ=rig.world.environ) as daemon,
                daemon.client() as ui,
            ):
                daemon_install(ui, rig.world.wheel("compatible_c"))
                # 실행 중 gc: 사용 표식이 옛 환경을 지킨다
                candidates = ui.call("plugins.list")["gc_candidates"]
                ui.call("plugins.gc", {"candidates": candidates})
                done = notification(ui, "plugins.done", kind="gc")
                assert done["ok"] is True, done
            assert old.is_dir() and env_files(old) == old_files
            Path(f"{gate}.go").write_text("")
            assert cli.wait(RUN_WAIT_S) == 0, (tmp_path / "cli.out").read_text("utf-8", "replace")
        finally:
            if cli.poll() is None:
                cli.kill()
    assert env_files(old) == old_files and env_digest(old) == old_digest
    joined = rig.env_dir("shared")
    assert joined != old

    # (2) daemon 실행(사람 연결 run.start) 중 CLI plugin add
    gate = tmp_path / "daemon-marked"
    env = cli_env(rig.world, [fault_wait("runner.plugins", "runner", "marked", gate)])
    joined_files = env_files(joined)
    service = WorkspaceService(
        rig.root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    with (
        ThreadDaemon(rig.root, service=service, platform_fake=spec) as daemon,
        daemon.client() as client,
    ):
        started = client.call("run.start", {"path": graph})
        client.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        wait_until(Path(f"{gate}.ready").exists, timeout=120)
        assert [m.parent.parent for m in markers(rig)] == [joined]
        proc = plugin_cli(rig, "add", rig.world.wheel("conflict_b"), "--yes")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        Path(f"{gate}.go").write_text("")
        log = EventLog(client, started["run_id"]).until_ended(RUN_WAIT_S)
    assert log.ended is not None and log.ended["outcome"]["verdict"] == "pass", log.ended
    assert env_files(joined) == joined_files

    # (3) 실행 시작 ↔ 설치 커밋 교차: 설치가 op.lock을 쥔 채 교체 직전에 멈춘 사이 실행 시작
    committing, release = threading.Event(), threading.Event()
    failure: list[BaseException] = []

    def fault(stage: str) -> None:
        if stage == "before_commit":
            committing.set()
            release.wait(120)

    def install() -> None:
        try:
            ops = PluginOps(rig.root, environ=rig.world.environ, fault=fault)
            ops.add(str(rig.world.wheel("sample")), confirm=YES)
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(target=install)
    worker.start()
    assert committing.wait(300)
    handle = Supervisor(runner_cmd=RUNNER_CMD, env=cli_env(rig.world)).start(
        rig.root, graph, StartOptions(platform=PlatformSpec("none"))
    )
    time.sleep(2.0)
    release.set()
    worker.join(300)
    assert not failure, failure
    outcome = handle.wait(RUN_WAIT_S)
    assert outcome.verdict == "pass", outcome.run_end
    run_json = read_run_json(outcome.run_dir / "run.json")
    assert run_json is not None
    assert run_json["conditions"]["plugin_lock_sha256"] == lock_sha256(rig.lock())

    # 그 뒤 gc: 실행이 끝났으니 지금 잠금이 쓰지 않는 옛 환경을 지우고, 실행은 그대로 통과
    assert markers(rig) == []
    removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
    assert old.name in removed and not old.exists()
    assert run_graph(rig, graph).verdict == "pass"
    assert rig.ops().verify()["ok"]


# ---------------------------------------------------------------- 4. 다른 PC 재현


def _other_pc(rig: Rig, tmp_path: Path, name: str) -> tuple[Path, dict[str, str]]:
    root = tmp_path / name / "ws"
    shutil.copytree(rig.root, root, ignore=shutil.ignore_patterns(".kookabug", "runs"))
    environ = {**rig.world.environ, "LOCALAPPDATA": str(tmp_path / name / "appdata")}
    return root.resolve(), environ


def _env_of(root: Path, lock: dict[str, Any], name: str) -> Path:
    found = find_env(
        root / ".kookabug" / "plugins" / "envs", name, lock["environments"][name]["fingerprint"]
    )
    assert found is not None, name
    return found


def test_lock_reproduces_on_other_pc(rig: Rig, tmp_path: Path) -> None:
    repo = git_repo(SAMPLE, tmp_path / "outside" / "repos" / "sample")
    rig.ops().add(git_source(repo), confirm=YES)  # 생성 파일(스키마)이 있는 git 원천
    rig.add("conflict_a")
    rig.add("conflict_b")  # 격리
    graph = dep_graph(rig.root, {"conflict_a": "1.0.0", "conflict_b": "2.0.0"})
    lock = rig.lock()
    assert set(lock["environments"]) == {"shared", "iso-conflict_b"}
    remove_tree(repo)  # 원천 git 레포가 없어도 재현된다

    root, environ = _other_pc(rig, tmp_path, "pc2")
    lock_bytes = (root / "kookabug.lock").read_bytes()
    ops = PluginOps(root, environ=environ)
    result = ops.sync(confirm=YES)
    assert sorted(result["created"]) == ["iso-conflict_b", "shared"]
    assert not [c for c in ops.calls if any("kookabug_sdk.cli" in a for a in c)]  # 빌드 없음
    assert (root / "kookabug.lock").read_bytes() == lock_bytes  # 잠금 파일을 쓰지 않는다
    for name, env in lock["environments"].items():
        assert (
            env_digest(_env_of(root, lock, name)) == env["digest"] == env_digest(rig.env_dir(name))
        )
    assert ops.verify()["ok"]
    # 같은 결과 (실제 감독자·runner·환경별 워커)
    env = direct_env(environ)
    for target, rel in ((root, graph), (root, sample_graph(root, "tests/s.graph.json"))):
        handle = Supervisor(runner_cmd=RUNNER_CMD, env=env).start(
            target, rel, StartOptions(platform=PlatformSpec("none"))
        )
        assert handle.wait(RUN_WAIT_S).verdict == "pass", rel

    # 변조: 커밋된 wheel 바이트가 잠금과 다르면 sync 실패, 아무것도 바뀌지 않는다
    bad, bad_environ = _other_pc(rig, tmp_path, "pc3")
    entry = lock["plugins"][0]
    wheel = bad.joinpath(*entry["wheel"].split("/"))
    wheel.write_bytes(wheel.read_bytes() + b"tampered")
    bad_lock = (bad / "kookabug.lock").read_bytes()
    with pytest.raises(PluginError):
        PluginOps(bad, environ=bad_environ).sync(confirm=YES)
    assert (bad / "kookabug.lock").read_bytes() == bad_lock
    envs = bad / ".kookabug" / "plugins" / "envs"
    assert not envs.exists() or not [p for p in envs.iterdir() if (p / MARKER).is_file()]


def test_sdist_only_refused_before_commit(rig: Rig) -> None:
    rig.add("sample")
    before = state(rig)
    with pytest.raises(PluginError) as caught:
        rig.add("sdist_only")  # 전이 의존성이 sdist만 → 빌드 없이 거부 (재현을 보장할 수 없다)
    assert caught.value.code == "sdist_only_dependency"
    assert_kept(rig, before)
    assert not any(staging(rig).iterdir())


def test_sdk_changed_refused_then_relock(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")
    before = state(rig)
    wheel = sdk_wheel(tmp_path / "sdk-next", version="0.1.1")
    environ = {**rig.world.environ, SDK_WHEEL_ENV: str(wheel)}
    new_app = PluginOps(rig.root, environ=environ)
    with pytest.raises(PluginError) as caught:
        new_app.sync(confirm=YES)
    assert caught.value.code == "plugin_env_stale" and new_app.calls == []
    assert_kept(rig, before)
    proc = plugin_cli(rig, "sync", "--yes", "--json", KOOKABUG_SDK_WHEEL=str(wheel))
    assert proc.returncode == 2 and json.loads(proc.stdout)["error"]["code"] == "plugin_env_stale"
    assert_kept(rig, before)
    # 사람이 승인하는 relock: 새 SDK로 새 환경·새 잠금, 플러그인 항목은 그대로
    old_lock = rig.lock()
    assert PluginOps(rig.root, environ=environ).relock(confirm=YES)["changed"] is True
    lock = rig.lock()
    assert lock["sdk"]["version"] == "0.1.1" and lock["plugins"] == old_lock["plugins"]
    assert PluginOps(rig.root, environ=environ).verify()["ok"]
    env_dir = (
        rig.envs / PluginOps(rig.root, environ=environ).status()["environments"]["shared"]["folder"]
    )
    modules = lock["plugins"][0]["manifest"]["modules"]
    assert run_node(env_dir, modules, "sample.text.reverse", {"text": "m6"})["outputs"] == {
        "text": "6m"
    }


# ---------------------------------------------------------------- (엄격) 에이전트


def test_agents_cannot_install_or_run_dev_modules(
    rig: Rig, spawned: Spawned, tmp_path: Path
) -> None:
    rig.add("sample")
    before = state(rig)
    lock = rig.lock()

    # MCP (실제 kookabug mcp stdio): 툴셋을 다 켜도 설치·제거·준비 도구가 없다
    with ThreadDaemon(
        rig.root,
        environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "user")},
        agent_toolsets=("core",),
        plugin_environ=rig.world.environ,
    ) as daemon:
        mcp = McpClient.start(spawned, rig.root, tmp_path / "mcp", env=daemon_env(tmp_path))
        try:
            mcp.initialize()
            mcp.data("kb_toolset_enable", {"toolsets": [t for t in TOOLSETS if t != "core"]})
            names = mcp.tool_names()
            assert names and not [
                n
                for n in names
                if any(w in n for w in ("plugin", "install", "sync", "relock", "gc"))
            ], names
            assert mcp.close() == 0
        finally:
            mcp.__exit__(None, None, None)
        # daemon agent 연결: 변경 메서드는 판정 전 permission_denied, 목록은 된다
        with daemon.client(AGENT) as agent:
            calls: dict[str, dict[str, Any]] = {
                "plugins.preview": {"source": str(rig.world.wheel("compatible_c"))},
                "plugins.install": {"op_id": "0" * 32},
                "plugins.upgrade": {"id": "sample"},
                "plugins.remove": {"id": "sample", "base_revision": revision_of(rig.lock_bytes())},
                "plugins.sync": {"lock_sha256": lock_sha256(lock)},
                "plugins.relock": {"lock_sha256": lock_sha256(lock)},
                "plugins.gc": {"candidates": {"envs": [], "wheels": [], "staging": []}},
            }
            for method, params in calls.items():
                with pytest.raises(DaemonError) as caught:
                    agent.call(method, params)
                assert caught.value.kind == "permission_denied", method
            assert [p["id"] for p in agent.call("plugins.list")["plugins"]] == ["sample"]
    assert_kept(rig, before)

    # CLI KOOKABUG_AGENT: plugin add 종료 5
    proc = plugin_cli(rig, "add", rig.world.wheel("compatible_c"), "--yes", KOOKABUG_AGENT="m6")
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert_kept(rig, before)

    # KOOKABUG_AGENT + run --plugin-module: 실행 시작 전 종료 5, 모듈 import 표식 없음
    ws = tmp_path / "dev-ws"
    make_workspace(ws)
    perms = {"permissions": {"preset": "runner"}}
    write_json(ws, "kookabug.json", {"format": "kookabug.workspace/0", **perms})
    write_json(ws, ".kookabug/local.json", {"format": "kookabug.local/0", **perms})
    GraphBuilder().entry("n").node("n", "core.test.pass").write(ws, "tests/t.graph.json")
    mark = tmp_path / "dev-module-imported.txt"
    (tmp_path / "m6_dev_module.py").write_text(
        f"from pathlib import Path\nPath({str(mark)!r}).write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )
    env = {**cli_env(rig.world), "KOOKABUG_AGENT": "m6", "PYTHONPATH": str(tmp_path)}
    run = subprocess.run(
        python_cmd(
            "-m", "kookabug_cli", "run", "tests/t.graph.json", "--json", "--workspace", ws,
            "--platform-fake", platform_spec(tmp_path), "--plugin-module", "m6_dev_module",
        ),
        env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=120, check=False,
    )  # fmt: skip
    assert run.returncode == 5, run.stdout + run.stderr
    assert "dev_modules_agent" in run.stdout and not mark.exists()

    # 개발 모듈 daemon: 에이전트 연결의 run.start는 runner를 띄우기 전에 거부, 사람은 된다
    with (
        ThreadDaemon(
            ws, plugin_modules=PLUGIN_MODULES, platform_fake=platform_spec(tmp_path)
        ) as dev,
        dev.client(AGENT) as agent,
    ):
        with pytest.raises(DaemonError) as caught:
            agent.call("run.start", {"path": "tests/t.graph.json"})
        assert caught.value.kind == "permission_denied"
        assert caught.value.data["reason"] == "dev_modules_agent"
    runs = ws / "runs"
    assert not runs.exists() or not any(runs.iterdir())


# ---------------------------------------------------------------- (엄격) 신뢰 전·인증 정보


def test_preview_runs_no_code_and_hides_credentials(rig: Rig, tmp_path: Path) -> None:
    # 신뢰 확인 전(미리보기·취소): 빌드 백엔드·플러그인 import가 돌지 않는다 (git·폴더 원천)
    marks = tmp_path / "marks"
    marks.mkdir()
    repo = git_repo(PLUGINS / "build_marker", tmp_path / "outside" / "repos" / "build_marker")
    environ = {**rig.world.environ, "KBFIX_MARKER_DIR": str(marks)}
    for source in (git_source(repo), str(repo)):
        ops = rig.ops()
        ops.environ = environ
        with pytest.raises(PluginError) as caught:
            ops.add(source, confirm=lambda _: False)
        assert caught.value.code == "cancelled"
        assert not any(marks.iterdir())
        assert all(Path(c[0]).stem.lower() == "git" for c in ops.calls), ops.calls
    assert rig.lock_bytes() is None
    ops = rig.ops()
    ops.environ = environ
    ops.add(git_source(repo), confirm=YES)  # 승인한 뒤에만
    assert {p.name for p in marks.iterdir()} == {"backend", "import"}

    # 인증 정보: 인덱스 URL·git·https wheel의 사용자 정보는 잠금·작업 로그·응답에 없다
    index = rig.world.index.url.replace("http://", f"http://kb:{SECRET}@")
    config = json.loads((rig.root / "kookabug.json").read_text(encoding="utf-8"))
    config["plugin_index"] = {"url": index}
    (rig.root / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    assert SECRET not in json.dumps(rig.add("conflict_a"))
    for source, sha in (
        (f"git+https://kb:{SECRET}@127.0.0.1:9/team/repo.git@v1", None),
        (f"https://kb:{SECRET}@127.0.0.1:9/kbfix-0.1.0-py3-none-any.whl?token={SECRET}", "0" * 64),
    ):
        with pytest.raises(PluginError) as caught:
            rig.ops().add(source, sha256=sha, confirm=YES)
        assert SECRET not in json.dumps(caught.value.to_json(), ensure_ascii=False)
    proc = plugin_cli(
        rig, "add", f"git+https://kb:{SECRET}@127.0.0.1:9/r.git@v1", "--yes", "--json"
    )
    assert proc.returncode == 2 and SECRET not in proc.stdout + proc.stderr
    texts = [rig.lock_bytes() or b""]
    texts += [p.read_bytes() for p in (rig.root / ".kookabug" / "plugins" / "logs").glob("*.log")]
    assert texts[1:] and not [t for t in texts if SECRET.encode() in t]
