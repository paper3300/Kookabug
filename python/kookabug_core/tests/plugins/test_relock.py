"""앱 SDK가 바뀐 뒤 (M6 계획 D10·3.7 `relock`).

sync·add는 조건이 다른 잠금을 바꾸지 않는다 (`plugin_env_stale`). 앱 조건으로 옮기는 것은 사람이
승인하는 `relock` 거래: 모든 플러그인의 SDK 범위 재검사 → 새 환경 → 새 잠금. 실패면 그대로.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.plugins import YES, Rig, env_run, plugin_cli, run_node, tree_hashes

from kb_testing.plugin_fixtures import sdk_wheel
from kookabug_core.plugins import SDK_WHEEL_ENV, PluginError, PluginOps
from kookabug_core.plugins.lockfile import lock_sha256

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(600)]


def _new_app(rig: Rig, tmp_path: Path, version: str) -> tuple[PluginOps, dict[str, str]]:
    """SDK 판만 바뀐 앱 (같은 Python)."""
    wheel = sdk_wheel(tmp_path / f"sdk-{version}", version=version)
    environ = {**rig.world.environ, SDK_WHEEL_ENV: str(wheel)}
    return PluginOps(rig.root, environ=environ), environ


def _state(rig: Rig) -> tuple[bytes | None, dict[str, str]]:
    return rig.lock_bytes(), tree_hashes(rig.envs)


def test_sdk_changed_sync_refused_lock_bytes_same(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")
    before = _state(rig)
    ops, environ = _new_app(rig, tmp_path, "0.1.1")
    with pytest.raises(PluginError) as caught:
        ops.sync(confirm=YES)
    assert caught.value.code == "plugin_env_stale"
    assert "relock" in caught.value.message
    assert ops.calls == []
    assert _state(rig) == before
    # CLI: 종료 2, 아무것도 안 바뀜
    proc = plugin_cli(rig, "sync", "--yes", "--json", KOOKABUG_SDK_WHEEL=environ[SDK_WHEEL_ENV])
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["error"]["code"] == "plugin_env_stale"
    assert _state(rig) == before
    # 목록은 stale로 보인다
    status = ops.status()
    assert status["stale_reason"] and status["plugins"][0]["env_status"] == "stale"


def test_relock_succeeds(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")
    rig.add("conflict_a")
    old_lock = rig.lock()
    old_dir = rig.env_dir("shared")
    old_files = tree_hashes(old_dir)
    ops, environ = _new_app(rig, tmp_path, "0.1.1")
    asked: list[dict[str, object]] = []
    result = ops.relock(confirm=lambda p: asked.append(p) or True)
    assert result["changed"] is True
    assert asked[0]["to"] == {"python": old_lock["python"], "sdk": "0.1.1"}
    lock = rig.lock()
    assert lock["sdk"]["version"] == "0.1.1" and lock["sdk"] != old_lock["sdk"]
    # 플러그인 항목(wheel·스키마·원천)은 그대로, 환경은 새 지문 (기존 판 그대로)
    assert lock["plugins"] == old_lock["plugins"]
    shared = lock["environments"]["shared"]
    assert shared["packages"] == old_lock["environments"]["shared"]["packages"]
    assert shared["fingerprint"] != old_lock["environments"]["shared"]["fingerprint"]
    # 빌드 없음, 옛 환경 폴더는 그대로 (gc 몫)
    assert not [c for c in ops.calls if any("kookabug_sdk.cli" in a for a in c)]
    assert tree_hashes(old_dir) == old_files
    new_ops = PluginOps(rig.root, environ=environ)
    assert new_ops.verify()["ok"]
    assert new_ops.sync(confirm=lambda _: pytest.fail("묻지 않아야 한다"))["created"] == []
    new_dir = new_ops.status()["environments"]["shared"]["folder"]
    env_dir = rig.envs / new_dir
    assert env_dir != old_dir
    code = "from importlib import metadata\nprint(metadata.version('kookabug-sdk'))\n"
    assert env_run(env_dir, code).strip() == "0.1.1"
    modules = next(p for p in lock["plugins"] if p["id"] == "sample")["manifest"]["modules"]
    out = run_node(env_dir, modules, "sample.text.reverse", {"text": "sdk"})
    assert out["outputs"] == {"text": "kds"}
    # 옛 앱으로 보면 이제 조건 다름
    with pytest.raises(PluginError) as caught:
        rig.ops().sync(confirm=YES)
    assert caught.value.code == "plugin_env_stale"


def test_relock_refused_when_range_excludes_new_sdk(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")  # kookabug-sdk>=0.1.0.dev0,<0.2
    before = _state(rig)
    ops, _ = _new_app(rig, tmp_path, "0.2.0")
    asked: list[object] = []
    with pytest.raises(PluginError) as caught:
        ops.relock(confirm=lambda p: asked.append(p) or True)
    assert caught.value.code == "sdk_incompatible"
    assert caught.value.fields.get("plugin") == "sample"
    assert asked == []  # 신뢰 확인 전에 거부
    assert _state(rig) == before


def test_relock_requires_confirmed_lock_hash(rig: Rig, tmp_path: Path) -> None:
    """화면 카드가 본 정규 잠금 해시(`lock_sha256`)가 거래 안에서 읽은 잠금과 다르면 아무것도
    안 하고 `revision_conflict` (B5 검수 H: 카드에 없던 플러그인을 확인 실행하지 않는다). 맞으면
    진행."""
    rig.add("sample")
    seen = lock_sha256(rig.lock())
    rig.add("compatible_c")  # 카드를 본 뒤 잠금이 바뀌었다
    before = _state(rig)
    ops, _ = _new_app(rig, tmp_path, "0.1.1")
    with pytest.raises(PluginError) as caught:
        ops.relock(confirm=YES, lock_sha256=seen)
    assert caught.value.code == "revision_conflict"
    assert ops.calls == []
    assert _state(rig) == before
    assert ops.relock(confirm=YES, lock_sha256=lock_sha256(rig.lock()))["changed"] is True
