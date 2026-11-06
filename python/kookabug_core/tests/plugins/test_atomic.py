"""설치 거래 원자성 (M6 계획 3.5 — 엄격: 사용자 파일 손상).

⑨(잠금 바꿔 넣기) 앞 어디서 실패·취소·죽음이 나도 잠금 바이트·기존 환경 폴더의 모든 파일·커밋된
wheel은 그대로이고, 자동 정리는 staging 안만이다. 같은 지문의 완성 환경은 읽기 검증만 한다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from helpers.plugins import (
    Rig,
    cache_hashes,
    cli_env,
    hang_wheel,
    sample_graph_passes,
    tree_hashes,
    tree_mtimes,
    write_then_hang_wheel,
)

from kb_testing.proc import Spawned, python_cmd, wait_until
from kookabug_core.plugins import PluginError
from kookabug_core.plugins.envs import MARKER
from kookabug_core.win import identify, is_alive

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(900)]

# 새 공유 환경을 만드는 단계부터 차례로 (env_complete 뒤로는 같은 지문 재사용 경로를 지난다)
STAGES = (
    "fetched",
    "manifest",
    "confirmed",
    "resolved",
    "env_venv",
    "env_synced",
    "env_installed",
    "env_verified",
    "env_complete",
    "env_reused",
    "archived",
    "before_commit",
)
BROKEN = (
    "broken_import",
    "schema_drift",
    "unresolvable",
    "bad_effects",
    "id_core",
    "sdist_only",
    "sdk_too_new",
)


def _staging(rig: Rig) -> Path:
    return rig.root / ".kookabug" / "plugins" / "staging"


def _assert_kept(
    rig: Rig, lock: bytes | None, envs: dict[str, str], wheels: dict[str, str]
) -> None:
    assert rig.lock_bytes() == lock
    now = tree_hashes(rig.envs)
    assert {k: now.get(k) for k in envs} == envs  # 기존 환경 파일 전체 (새 폴더는 생겨도 된다)
    now_wheels = tree_hashes(rig.root / "plugins" / "wheels")
    assert {k: now_wheels.get(k) for k in wheels} == wheels


def test_failure_at_each_stage_keeps_lock_and_envs(rig: Rig) -> None:
    rig.add("sample")
    lock = rig.lock_bytes()
    envs = tree_hashes(rig.envs)
    wheels = tree_hashes(rig.root / "plugins" / "wheels")
    seen: list[str] = []
    for stage in STAGES:
        rig.fail_at, rig.faults = stage, []
        with pytest.raises((PluginError, RuntimeError)):
            rig.add("conflict_a")
        if stage in rig.faults:
            seen.append(stage)
        _assert_kept(rig, lock, envs, wheels)
        assert not any(_staging(rig).iterdir()), stage
    # 만드는 단계와 재사용 단계를 모두 지났다
    assert set(seen) == set(STAGES), seen
    rig.fail_at = None
    for name in BROKEN:
        with pytest.raises(PluginError):
            rig.add(name)
        _assert_kept(rig, lock, envs, wheels)
        assert not any(_staging(rig).iterdir()), name
    assert [p["id"] for p in rig.lock()["plugins"]] == ["sample"]
    assert rig.ops().verify()["ok"]
    assert sample_graph_passes(rig)  # 기존 그래프가 실제 실행(환경별 워커)으로 통과 (B3)


def _reuse_setup(rig: Rig) -> tuple[Path, dict[str, str], dict[str, int]]:
    rig.add("sample")
    folder = rig.env_dir("shared")
    rig.ops().remove("sample", confirm=lambda _: True)
    assert "shared" not in rig.lock()["environments"]
    return folder, tree_hashes(folder), tree_mtimes(folder)


def test_same_fingerprint_reuse_is_read_only(rig: Rig) -> None:
    folder, files, mtimes = _reuse_setup(rig)
    ops = rig.ops()
    result = ops.add(str(rig.world.wheel("sample")), confirm=lambda _: True)
    assert result["reused"] is True
    assert rig.env_dir("shared") == folder
    # uv·검증 어느 호출에도 재사용 폴더 경로가 없다
    assert ops.calls
    assert not [c for c in ops.calls if any(str(folder).lower() in a.lower() for a in c)]
    assert tree_hashes(folder) == files
    assert tree_mtimes(folder) == mtimes  # .kb-env.json 수정 시각 포함
    assert (folder / MARKER).is_file()
    assert ops.verify()["ok"]


@pytest.mark.parametrize("stage", ["env_reused", "archived", "before_commit"])
def test_reuse_then_failure_keeps_existing_files(rig: Rig, stage: str) -> None:
    folder, files, mtimes = _reuse_setup(rig)
    lock = rig.lock_bytes()
    rig.fail_at = stage
    with pytest.raises(RuntimeError):
        rig.add("sample")
    assert stage in rig.faults and "env_reused" in rig.faults
    assert rig.lock_bytes() == lock
    assert tree_hashes(folder) == files
    assert tree_mtimes(folder) == mtimes


def _start_cli(
    rig: Rig, spawned: Spawned, wheel: Path, faults: list[dict[str, object]] | None = None
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


def _fault_wait(stage: str, path: Path) -> list[dict[str, object]]:
    return [
        {
            "point": "plugins.stage",
            "role": "plugin",
            "when": {"event": stage},
            "action": f"wait:{path}",
        }
    ]


def test_kill_before_commit_cleans_staging_only(rig: Rig, spawned: Spawned, tmp_path: Path) -> None:
    rig.add("sample")
    lock = rig.lock_bytes()
    envs = tree_hashes(rig.envs)
    wheels = tree_hashes(rig.root / "plugins" / "wheels")

    # (1) ⑦(나) 중: 검증 인터프리터가 import 중 멈춘 채로 CLI를 죽인다 → Job이 손자까지 끝낸다
    pid_file = tmp_path / "hang.pid"
    wheel = hang_wheel(rig.world, tmp_path / "hang", pid_file)
    cli = _start_cli(rig, spawned, wheel)
    wait_until(pid_file.is_file, timeout=120, message="검증 인터프리터가 멈춘 곳에 오지 않았다")
    real, launcher = (int(x) for x in pid_file.read_text().split())
    idents = [i for i in (identify(real), identify(launcher)) if i is not None]
    assert idents
    cli.kill()
    cli.wait(30)
    wait_until(
        lambda: not any(is_alive(i) for i in idents),
        timeout=30,
        message="Job이 검증 인터프리터를 끝내지 않았다",
    )
    _assert_kept(rig, lock, envs, wheels)
    left = [p for p in rig.envs.iterdir() if p.name not in {k.split("/")[0] for k in envs}]
    assert left and all(not (p / MARKER).exists() for p in left)  # 미완성 = 없는 것
    assert any(_staging(rig).iterdir())

    # (2) ⑧ 뒤 kill: 새 공유 환경(완성)·보관 wheel은 남지만 잠금은 그대로
    signal = tmp_path / "archived"
    cli = _start_cli(rig, spawned, rig.world.wheel("conflict_b"), _fault_wait("archived", signal))
    wait_until(Path(f"{signal}.ready").is_file, timeout=180, message="⑧에 오지 않았다")
    cli.kill()
    cli.wait(30)
    _assert_kept(rig, lock, envs, wheels)
    b_sha = hashlib.sha256(rig.world.wheel("conflict_b").read_bytes()).hexdigest()
    assert (rig.root / "plugins" / "wheels" / b_sha).is_dir()
    before = {k.split("/")[0] for k in envs} | {p.name for p in left}
    fresh = [p for p in rig.envs.iterdir() if p.name not in before]
    assert len(fresh) == 1 and (fresh[0] / MARKER).is_file()

    # 다음 작업: staging만 지운다 (남은 환경·wheel은 gc 몫)
    rig.add("compatible_c")
    assert not any(_staging(rig).iterdir())
    assert all(p.exists() for p in left) and fresh[0].exists()
    assert (rig.root / "plugins" / "wheels" / b_sha).is_dir()
    assert [p["id"] for p in rig.lock()["plugins"]] == ["compatible_c", "sample"]
    now = tree_hashes(rig.envs)
    assert {k: now.get(k) for k in envs} == envs
    assert sample_graph_passes(rig)


def test_kill_right_after_lock_replace_keeps_new_install(
    rig: Rig, spawned: Spawned, tmp_path: Path
) -> None:
    signal = tmp_path / "committed"
    cli = _start_cli(rig, spawned, rig.world.wheel("sample"), _fault_wait("committed", signal))
    wait_until(Path(f"{signal}.ready").is_file, timeout=180, message="⑨ 뒤에 오지 않았다")
    cli.kill()
    cli.wait(30)
    assert [p["id"] for p in rig.lock()["plugins"]] == ["sample"]
    assert any(_staging(rig).iterdir())  # ⑩ 전에 죽었다
    # 다음 작업(다른 플러그인 추가)도 새 잠금·wheel·환경을 건드리지 않는다
    shared = rig.env_dir("shared")
    files = tree_hashes(shared)
    rig.add("conflict_b")
    assert not any(_staging(rig).iterdir())
    assert [p["id"] for p in rig.lock()["plugins"]] == ["conflict_b", "sample"]
    assert tree_hashes(shared) == files
    assert rig.ops().verify()["ok"]
    assert sample_graph_passes(rig)  # 그 플러그인 그래프를 실제로 실행 (B3)
    assert tree_hashes(shared) == files
    # CLI verify도 통과
    proc = subprocess.run(
        python_cmd("-m", "kookabug_cli", "plugin", "verify", "--json", "--workspace", rig.root),
        env=cli_env(rig.world),
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


# ---------------------------------------------------------------- 2라운드: 환경끼리 파일 공유 없음


def _cache_kept(rig: Rig, before: dict[str, str]) -> None:
    """기존 캐시 파일은 바이트 그대로 (새 거래가 더한 캐시 항목은 있어도 된다)."""
    now = cache_hashes(rig.world.environ)
    assert {k: now.get(k) for k in before} == before


def _private_cache(rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 이 검사만의 빈 uv 캐시: 캐시 파일 불변을 이 검사가 만든 것만으로 본다
    monkeypatch.setitem(rig.world.environ, "LOCALAPPDATA", str(tmp_path / "private-appdata"))


def test_in_place_write_in_new_env_keeps_old_env_and_cache(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _private_cache(rig, tmp_path, monkeypatch)
    rig.add("conflict_a")
    old = rig.env_dir("shared")
    old_files = tree_hashes(old)
    cache = cache_hashes(rig.world.environ)
    assert any(k.endswith("kbfix_dep/__init__.py") for k in cache)
    lock = rig.lock_bytes()
    # 새 공유 환경의 검증 import가 자기 kbfix_dep 파일을 제자리에 쓰고 실패한다
    with pytest.raises(PluginError) as caught:
        rig.add("self_write")
    assert caught.value.code == "verify_failed"
    assert rig.lock_bytes() == lock
    assert tree_hashes(old) == old_files
    _cache_kept(rig, cache)
    # 새 환경 폴더(미완성)만 바뀌었다
    fresh = [p for p in rig.envs.iterdir() if p != old]
    assert len(fresh) == 1 and not (fresh[0] / MARKER).exists()
    damaged = fresh[0] / "Lib" / "site-packages" / "kbfix_dep" / "__init__.py"
    assert "damaged" in damaged.read_text(encoding="utf-8")


def test_in_place_write_then_kill_keeps_old_env_and_cache(
    rig: Rig, spawned: Spawned, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _private_cache(rig, tmp_path, monkeypatch)
    rig.add("conflict_a")
    old = rig.env_dir("shared")
    old_files = tree_hashes(old)
    cache = cache_hashes(rig.world.environ)
    lock = rig.lock_bytes()
    pid_file = tmp_path / "write.pid"
    cli = _start_cli(rig, spawned, write_then_hang_wheel(tmp_path / "wh", pid_file))
    wait_until(pid_file.is_file, timeout=120, message="검증 import가 쓰기 뒤에 오지 않았다")
    cli.kill()
    cli.wait(30)
    assert rig.lock_bytes() == lock
    assert tree_hashes(old) == old_files
    _cache_kept(rig, cache)
