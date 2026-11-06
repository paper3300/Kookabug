"""다른 PC에서 잠금으로 같은 환경 재현 (M6 계획 3.7 `sync`, D4·D10, 완료 기준 4).

"다른 PC" = 워크스페이스 사본(`.kookabug` 빼고) + 새 uv 캐시(`LOCALAPPDATA` 바꿈) + 원천 git 레포
지움. 인덱스 서버는 같은 것(PyPI 역할). sync는 빌드하지 않고 커밋된 wheel을 잠금 경로 그대로 깔며
잠금 파일을 쓰지 않는다.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from helpers.plugins import YES, Rig, calls_with, git_source, plugin_cli, run_node, tree_hashes

from kb_testing.plugin_fixtures import SAMPLE, git_repo
from kookabug_core.plugins import PluginError, PluginOps
from kookabug_core.plugins.envs import env_digest, find_env, is_broken
from kookabug_core.plugins.lockfile import lock_sha256
from kookabug_core.plugins.uv import remove_tree

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(900)]


def _other_pc(rig: Rig, tmp_path: Path, name: str = "pc2") -> tuple[Path, dict[str, str]]:
    root = tmp_path / name / "ws"
    shutil.copytree(rig.root, root, ignore=shutil.ignore_patterns(".kookabug"))
    environ = {**rig.world.environ, "LOCALAPPDATA": str(tmp_path / name / "appdata")}
    return root.resolve(), environ


def _install_mixed(rig: Rig, tmp_path: Path) -> Path:
    """git 원천(생성 스키마) 예제 + 공유(kbfix-dep 1) + 격리(kbfix-dep 2)."""
    repo = git_repo(SAMPLE, tmp_path / "repos" / "sample")
    rig.ops().add(git_source(repo), confirm=YES)
    rig.add("conflict_a")
    rig.add("conflict_b")
    return repo


def _env(root: Path, lock: dict[str, object], name: str) -> Path:
    fp = lock["environments"][name]["fingerprint"]  # pyright: ignore[reportIndexIssue]
    found = find_env(root / ".kookabug" / "plugins" / "envs", name, fp)
    assert found is not None, name
    return found


def test_other_pc_same_digest_without_rebuild(rig: Rig, tmp_path: Path) -> None:
    repo = _install_mixed(rig, tmp_path)
    lock = rig.lock()
    assert set(lock["environments"]) == {"shared", "iso-conflict_b"}
    remove_tree(repo)  # 원천 git 레포가 없어도 재현된다
    root, environ = _other_pc(rig, tmp_path)
    lock_bytes = (root / "kookabug.lock").read_bytes()
    ops = PluginOps(root, environ=environ)
    asked: list[dict[str, object]] = []
    result = ops.sync(confirm=lambda p: asked.append(p) or True)
    assert sorted(result["created"]) == ["iso-conflict_b", "shared"]
    assert len(asked) == 1 and asked[0]["lock_sha256"] == lock_sha256(lock)
    # 빌드 없음
    assert not calls_with(ops, "kookabug_sdk.cli")
    assert not [c for c in ops.calls if "build" in c[1:3]]
    # uv에 넘긴 플러그인 wheel = 잠금에 기록된 plugins/wheels/<sha256>/<원래 이름> 경로 그대로
    for plugin in lock["plugins"]:
        archived = str(root.joinpath(*plugin["wheel"].split("/")))
        installs = [c for c in calls_with(ops, "install", "--no-deps") if archived in c]
        assert len(installs) == 1, (plugin["id"], ops.calls)
        assert "staging" not in archived
    # digest = 잠금 = 원래 PC, 잠금 파일은 그대로
    assert (root / "kookabug.lock").read_bytes() == lock_bytes
    assert ops.verify()["ok"]
    for name, env in lock["environments"].items():
        assert env_digest(_env(root, lock, name)) == env_digest(rig.env_dir(name)) == env["digest"]
    # 같은 결과
    a = run_node(_env(root, lock, "shared"), ["kbfix_conflict_a.nodes"], "conflict_a.dep.version")
    b = run_node(
        _env(root, lock, "iso-conflict_b"), ["kbfix_conflict_b.nodes"], "conflict_b.dep.version"
    )
    assert (a["outputs"]["version"], b["outputs"]["version"]) == ("1.0.0", "2.0.0")
    modules = next(p for p in lock["plugins"] if p["id"] == "sample")["manifest"]["modules"]
    out = run_node(_env(root, lock, "shared"), modules, "sample.text.reverse", {"text": "pc2"})
    assert out["outputs"] == {"text": "2cp"}
    # 다시 sync: 할 일 없음, 묻지 않음, uv 없음
    again = PluginOps(root, environ=environ)
    result = again.sync(confirm=lambda _: pytest.fail("묻지 않아야 한다"))
    assert result["created"] == [] and sorted(result["ready"]) == ["iso-conflict_b", "shared"]
    assert again.calls == []


def _snapshot(root: Path) -> tuple[bytes, dict[str, str]]:
    return (root / "kookabug.lock").read_bytes(), tree_hashes(
        root / ".kookabug" / "plugins" / "envs"
    )


def _complete_envs(root: Path, lock: dict[str, object]) -> list[str]:
    envs = root / ".kookabug" / "plugins" / "envs"
    return [
        name
        for name, env in lock["environments"].items()  # pyright: ignore[reportAttributeAccessIssue]
        if find_env(envs, name, env["fingerprint"]) is not None
    ]


def test_tampered_wheel_or_hash_fails_nothing_changes(rig: Rig, tmp_path: Path) -> None:
    rig.add("conflict_a")
    lock = rig.lock()
    entry = lock["plugins"][0]
    # (1) 커밋된 wheel 바이트 변조 → 코드 실행·환경 만들기 전에 실패
    root, environ = _other_pc(rig, tmp_path, "pc-wheel")
    wheel = root.joinpath(*entry["wheel"].split("/"))
    wheel.write_bytes(wheel.read_bytes() + b"x")
    before = _snapshot(root)
    ops = PluginOps(root, environ=environ)
    with pytest.raises(PluginError) as caught:
        ops.sync(confirm=YES)
    assert caught.value.code == "verify_failed"
    assert ops.calls == []
    assert _snapshot(root) == before and _complete_envs(root, lock) == []
    # (2) 잠금의 wheel 해시·의존성 해시 변조 → 실패, 잠금 파일·환경 그대로
    for tamper in ("wheel_sha256", "package_hash"):
        root, environ = _other_pc(rig, tmp_path, f"pc-{tamper}")
        data = json.loads((root / "kookabug.lock").read_text(encoding="utf-8"))
        if tamper == "wheel_sha256":
            data["plugins"][0]["wheel_sha256"] = "0" * 64
        else:
            data["environments"]["shared"]["packages"][0]["hashes"] = ["sha256:" + "0" * 64]
        (root / "kookabug.lock").write_text(json.dumps(data), encoding="utf-8")
        before = _snapshot(root)
        ops = PluginOps(root, environ=environ)
        with pytest.raises(PluginError) as caught:
            ops.sync(confirm=YES)
        assert caught.value.code == "verify_failed", (tamper, caught.value.message)
        assert ops.calls == []
        assert _snapshot(root) == before and _complete_envs(root, data) == []
    # (3) 같은 지문 폴더의 파일 변조 → 읽기 검증 실패: 그 폴더는 손대지 않고 깨짐으로 기록(gc
    # 몫)한 뒤 건너뛰고 새 환경을 만든다 (B3 조율자 방향 — 깨진 첫째 후보가 sync를 막지 않는다)
    folder = rig.env_dir("shared")
    target = folder / "Lib" / "site-packages" / "kbfix_dep" / "__init__.py"
    target.write_text('__version__ = "tampered"\n', encoding="utf-8")
    files = tree_hashes(folder)
    lock_bytes = rig.lock_bytes()
    ops = rig.ops()
    result = ops.sync(confirm=YES)
    assert result["created"] == ["shared"]
    assert tree_hashes(folder) == files and rig.lock_bytes() == lock_bytes
    assert is_broken(folder)
    fresh = rig.env_dir("shared")
    assert fresh != folder
    assert env_digest(fresh) == lock["environments"]["shared"]["digest"]
    assert all(str(folder) not in arg for call in ops.calls for arg in call)
    # 다시 sync는 새 환경을 읽기 검증만 한다
    again = rig.ops()
    assert again.sync(confirm=YES)["created"] == [] and again.calls == []
    # gc는 깨진 폴더를 지운다 (새 환경은 남는다)
    removed = rig.ops().gc(confirm=YES)["removed"]["envs"]
    assert folder.name in removed and not folder.exists() and fresh.is_dir()
    assert not is_broken(folder)


def test_sync_does_not_write_lock(rig: Rig, tmp_path: Path) -> None:
    rig.add("conflict_a")
    root, environ = _other_pc(rig, tmp_path)
    lock_path = root / "kookabug.lock"
    stat = lock_path.stat()
    data = lock_path.read_bytes()
    # 대화형이 아니고 신뢰한 잠금도 아니면 --yes가 필요하다 (종료 6, 아무것도 안 바뀜)
    pc2 = Rig(rig.world, root)
    appdata = environ["LOCALAPPDATA"]
    proc = plugin_cli(pc2, "sync", "--json", LOCALAPPDATA=appdata)
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert not (root / ".kookabug" / "plugins" / "envs").exists()
    proc = plugin_cli(pc2, "sync", "--yes", "--json", LOCALAPPDATA=appdata)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["created"] == ["shared"]
    assert lock_path.read_bytes() == data
    assert lock_path.stat().st_mtime_ns == stat.st_mtime_ns
    # 신뢰한 잠금은 기억된다 (.kookabug/local.json, 잠금 파일이 아님) → 다음엔 --yes 없이도 된다
    local = json.loads((root / ".kookabug" / "local.json").read_text(encoding="utf-8"))
    assert local["plugin_trust"]["locks"] == [lock_sha256(json.loads(data))]
    proc = plugin_cli(pc2, "sync", "--json", LOCALAPPDATA=appdata)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert lock_path.read_bytes() == data
    # 에이전트는 sync도 못 한다
    proc = plugin_cli(
        pc2, "sync", "--yes", "--json", KOOKABUG_AGENT="agent-1", LOCALAPPDATA=appdata
    )
    assert proc.returncode == 5


def test_untrusted_lock_plugins_shown_in_add_preview(rig: Rig, tmp_path: Path) -> None:
    """신뢰 확인 안 한 잠금(클론)에 더하면 같은 공유 환경을 다시 만들며 기존 플러그인 코드도 돈다
    → 미리보기에 그 ID가 보이고, 승인하면 새 잠금을 신뢰한 것으로 기억한다."""
    rig.add("conflict_a")
    root, environ = _other_pc(rig, tmp_path)
    previews: list[dict[str, object]] = []
    ops = PluginOps(root, environ=environ)
    ops.add(
        str(rig.world.wheel("compatible_c")), confirm=lambda p: previews.append(p.to_json()) or True
    )
    assert previews[0]["untrusted"] == ["conflict_a"]
    lock = json.loads((root / "kookabug.lock").read_text(encoding="utf-8"))
    local = json.loads((root / ".kookabug" / "local.json").read_text(encoding="utf-8"))
    assert local["plugin_trust"]["locks"] == [lock_sha256(lock)]
    # 원래 PC(자기가 만든 잠금)는 묻지 않는다
    previews.clear()
    rig.ops().add(
        str(rig.world.wheel("compatible_c")), confirm=lambda p: previews.append(p.to_json()) or True
    )
    assert previews[0]["untrusted"] == []


def test_remove_on_untrusted_clone_trust_covers_all_shown(rig: Rig, tmp_path: Path) -> None:
    """다른 환경이 준비 안 된 클론에서 remove: 확인에 남는 플러그인 **전체**(다른 환경 포함)가
    나온다. 거절하면 아무것도 신뢰하지 않아 sync가 묻고, 승인하면 그 잠금(=모든 플러그인)을 신뢰한
    것이라 sync가 다시 묻지 않는다. 확인에 다 나오지 않은 잠금은 신뢰로 기억하지 않는다(방어)."""
    rig.add("conflict_a")  # shared
    rig.add("conflict_b")  # iso-conflict_b
    root, environ = _other_pc(rig, tmp_path)
    ops = PluginOps(root, environ=environ)
    with pytest.raises(PluginError) as caught:
        ops.remove("conflict_a", confirm=lambda _: False)
    assert caught.value.code == "cancelled"
    asked: list[dict[str, object]] = []
    with pytest.raises(PluginError) as caught:
        PluginOps(root, environ=environ).sync(confirm=lambda p: asked.append(p) or False)
    assert caught.value.code == "cancelled" and len(asked) == 1  # 신뢰 안 함 → 묻는다
    removed: list[dict[str, object]] = []
    PluginOps(root, environ=environ).remove(
        "conflict_a", confirm=lambda p: removed.append(p) or True
    )
    assert removed[0]["untrusted"] == ["conflict_b"]  # 다른 환경의 플러그인도 보였다
    result = PluginOps(root, environ=environ).sync(confirm=lambda _: pytest.fail("이미 신뢰"))
    assert result["created"] == ["iso-conflict_b"]
    # 방어: 확인에 다 나오지 않았으면 기억하지 않는다
    clone, environ2 = _other_pc(rig, tmp_path, "pc3")
    ops = PluginOps(clone, environ=environ2)
    before = json.loads((clone / "kookabug.lock").read_text(encoding="utf-8"))
    after = {**before, "plugins": before["plugins"][1:]}
    assert ops._remember(before, after, shown=[]) is False  # pyright: ignore[reportPrivateUsage]
    assert not (clone / ".kookabug" / "local.json").exists()


def test_explicit_none_confirmation_is_compared(rig: Rig) -> None:
    """확인 인자의 명시적 None("확인할 때 잠금이 없었다")은 비교 생략이 아니다: 잠금이 있으면
    sync·remove 모두 `revision_conflict`이고 아무것도 바뀌지 않는다. 생략(CLI)은 그대로 진행
    (B4 2라운드)."""
    empty = rig.ops().sync(confirm=YES, lock_sha256=None)  # 잠금 없음 = 확인한 것과 같다
    assert empty["created"] == [] and empty["lock_sha256"] is None
    rig.add("sample")
    before = rig.lock_bytes()
    for call in (
        lambda ops: ops.sync(confirm=YES, lock_sha256=None),
        lambda ops: ops.remove("sample", confirm=YES, base_revision=None),
    ):
        with pytest.raises(PluginError) as caught:
            call(rig.ops())
        assert caught.value.code == "revision_conflict"
        assert rig.lock_bytes() == before
    assert rig.ops().remove("sample", confirm=YES)["removed"] == "sample"
