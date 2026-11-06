"""사람이 부르는 정리 (M6 계획 3.6·U13): 잠금이 쓰는 것·살아 있는 사용 표식이 있는 것은 남긴다."""

from __future__ import annotations

import subprocess
import sys

import pytest
from helpers.plugins import Rig, tree_hashes

from kookabug_core.plugins.envs import IN_USE_DIR, MARKER
from kookabug_core.plugins.gc import marker_name
from kookabug_core.win import current, identify

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(600)]


def _yes(_: object) -> bool:
    return True


def test_gc_keeps_locked_and_in_use(rig: Rig) -> None:
    rig.add("sample")
    old = rig.env_dir("shared")
    rig.add("conflict_a")  # 공유 환경이 새 지문으로 바뀐다 → old는 잠금이 안 쓴다
    new = rig.env_dir("shared")
    assert old != new
    # old를 쓰는 실행이 아직 있다 (이 프로세스의 사용 표식)
    marker = old / IN_USE_DIR / marker_name(current())
    marker.parent.mkdir()
    marker.touch()
    new_files = tree_hashes(new)
    result = rig.ops().gc(confirm=_yes)
    assert result["removed"]["envs"] == [] and not result["failed"]
    assert old.exists() and new.exists()
    marker.unlink()
    result = rig.ops().gc(confirm=_yes)
    assert result["removed"]["envs"] == [old.name]
    assert not old.exists()
    assert tree_hashes(new) == new_files
    assert rig.ops().verify()["ok"]


def test_stale_marker_of_dead_process_ignored(rig: Rig) -> None:
    rig.add("sample")
    old = rig.env_dir("shared")
    rig.add("conflict_a")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ident = identify(proc.pid)
        assert ident is not None
    finally:
        proc.kill()
        proc.wait()
    marker = old / IN_USE_DIR / marker_name(ident)
    marker.parent.mkdir()
    marker.touch()
    result = rig.ops().gc(confirm=_yes)
    assert result["removed"]["envs"] == [old.name]


def test_gc_removes_uncommitted_envs_and_wheels(rig: Rig) -> None:
    rig.add("sample")
    lock = rig.lock_bytes()
    kept_env = rig.env_dir("shared")
    kept_files = tree_hashes(kept_env)
    wheels = rig.root / "plugins" / "wheels"
    kept_wheels = {p.name for p in wheels.iterdir()}
    # ⑨ 직전에 실패한 거래: 완성 환경과 보관 wheel이 남는다 (자동으로 지우지 않는다)
    rig.fail_at = "before_commit"
    with pytest.raises(RuntimeError):
        rig.add("conflict_b", isolation="isolated")
    rig.fail_at = None
    left_env = [p for p in rig.envs.iterdir() if p.name.startswith("iso-conflict_b-")]
    assert len(left_env) == 1 and (left_env[0] / MARKER).is_file()
    left_wheels = {p.name for p in wheels.iterdir()} - kept_wheels
    assert len(left_wheels) == 1
    # 확인에서 취소하면 아무것도 지우지 않는다
    assert rig.ops().gc(confirm=lambda _: False)["cancelled"] is True
    assert left_env[0].exists()
    result = rig.ops().gc(confirm=_yes)
    assert result["removed"]["envs"] == [left_env[0].name]
    assert result["removed"]["wheels"] == sorted(left_wheels)
    assert not left_env[0].exists()
    assert {p.name for p in wheels.iterdir()} == kept_wheels
    assert rig.lock_bytes() == lock
    assert tree_hashes(kept_env) == kept_files
    assert rig.ops().verify()["ok"]
