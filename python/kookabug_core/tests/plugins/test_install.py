"""wheel 원천 설치 거래 (M6 계획 3.5·D4·D5·D7): 잠금 기록·보관 wheel·공유/격리·거부."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from helpers.plugins import (
    YES,
    Rig,
    calls_with,
    env_run,
    git_source,
    run_node,
    tree_hashes,
    tree_mtimes,
)

from kb_testing.plugin_fixtures import PLUGINS, SAMPLE, git, git_env, git_repo, plugin_wheel
from kookabug_core.plugins import PluginError
from kookabug_core.plugins.envs import MARKER, fingerprint
from kookabug_core.plugins.manifest import same_requirements
from kookabug_core.plugins.uv import find_uv, uv_env
from kookabug_sdk.schema import SCHEMA_FILE, schema_digest

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(600)]


def test_add_wheel_records_modules_and_committed_wheel(rig: Rig) -> None:
    wheel = rig.world.wheel("sample")
    result = rig.add("sample")
    assert result["env"] == "shared" and result["reused"] is False
    lock = rig.lock()
    assert lock["format"] == "kookabug.lock/0"
    assert lock["python"] == "3.14" and lock["platform"] == "x86_64-pc-windows-msvc"
    entry = lock["plugins"][0]
    assert entry["id"] == "sample" and entry["dist"] == "kookabug-plugin-sample"
    assert entry["manifest"]["modules"] == [
        "kookabug_plugin_sample.nodes.text",
        "kookabug_plugin_sample.nodes.widgets",
    ]
    assert entry["manifest"]["permissions"] == ["capture"]
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert entry["wheel_sha256"] == sha == entry["source"]["sha256"]
    assert entry["source"]["kind"] == "wheel"
    # 보관 wheel: plugins/wheels/<전체 sha256>/<원래 wheel 파일명>, 바이트 그대로
    assert entry["wheel"] == f"plugins/wheels/{sha}/{wheel.name}"
    archived = rig.root / "plugins" / "wheels" / sha / wheel.name
    assert archived.read_bytes() == wheel.read_bytes()
    env = lock["environments"]["shared"]
    assert env["plugins"] == ["sample"] and env["packages"] == []
    # 설치된 노드가 실제로 돈다
    out = run_node(
        rig.env_dir("shared"), entry["manifest"]["modules"], "sample.text.reverse", {"text": "abc"}
    )
    assert out["outputs"] == {"text": "cba"}
    # staging은 비었다
    assert not any((rig.root / ".kookabug" / "plugins" / "staging").iterdir())
    assert rig.ops().verify()["ok"]


def test_conflict_auto_isolates(rig: Rig) -> None:
    rig.add("conflict_a")
    before = rig.lock()["environments"]["shared"]
    shared_dir = rig.env_dir("shared")
    shared_files = tree_hashes(shared_dir)
    result = rig.add("conflict_b")
    assert result["env"] == "iso-conflict_b"
    lock = rig.lock()
    entry = next(p for p in lock["plugins"] if p["id"] == "conflict_b")
    assert entry["env"] == "iso-conflict_b"
    assert entry["isolated_because"] == "conflict"
    assert entry["conflicts"] == ["kbfix-dep"]
    # 공유 환경은 그대로 (지문·digest·파일)
    assert lock["environments"]["shared"] == before
    assert tree_hashes(shared_dir) == shared_files
    iso = lock["environments"]["iso-conflict_b"]
    assert [p["version"] for p in iso["packages"]] == ["2.0.0"]
    out_a = run_node(shared_dir, ["kbfix_conflict_a.nodes"], "conflict_a.dep.version")
    out_b = run_node(
        rig.env_dir("iso-conflict_b"), ["kbfix_conflict_b.nodes"], "conflict_b.dep.version"
    )
    assert (out_a["outputs"]["version"], out_b["outputs"]["version"]) == ("1.0.0", "2.0.0")


def test_compatible_joins_shared_keeps_old_results(rig: Rig) -> None:
    rig.add("conflict_a")
    old = run_node(rig.env_dir("shared"), ["kbfix_conflict_a.nodes"], "conflict_a.dep.version")
    old_fp = rig.lock()["environments"]["shared"]["fingerprint"]
    result = rig.add("compatible_c")
    assert result["env"] == "shared"
    lock = rig.lock()
    shared = lock["environments"]["shared"]
    assert shared["plugins"] == ["compatible_c", "conflict_a"]
    assert shared["fingerprint"] != old_fp
    # 기존 공유 고정 판(kbfix-dep 1.0.0)이 제약이라 그대로다
    assert [(p["name"], p["version"]) for p in shared["packages"]] == [("kbfix-dep", "1.0.0")]
    env = rig.env_dir("shared")
    assert run_node(env, ["kbfix_conflict_a.nodes"], "conflict_a.dep.version") == old
    c = run_node(env, ["kbfix_compatible_c.nodes"], "compatible_c.dep.version")
    assert c["outputs"]["version"] == "1.0.0"


def test_conflict_shared_fails(rig: Rig) -> None:
    rig.add("conflict_a")
    lock = rig.lock_bytes()
    envs = tree_hashes(rig.envs)
    with pytest.raises(PluginError) as caught:
        rig.add("conflict_b", isolation="shared")
    assert caught.value.code == "plugin_conflict"
    assert caught.value.fields["conflicts"] == ["kbfix-dep"]
    assert rig.lock_bytes() == lock
    assert tree_hashes(rig.envs) == envs  # 해석 단계에서 끝났다: 새 환경도 없다


def test_sdk_incompatible(rig: Rig) -> None:
    with pytest.raises(PluginError) as caught:
        rig.add("sdk_too_new")
    assert caught.value.code == "sdk_incompatible"
    assert caught.value.fields["plugin"] == "conflict_a"
    assert rig.lock_bytes() is None
    assert not rig.envs.exists() or not any(rig.envs.iterdir())


def test_sdist_only_dependency_refused_keeps_env(rig: Rig) -> None:
    rig.add("sample")
    lock = rig.lock_bytes()
    envs = tree_hashes(rig.envs)
    with pytest.raises(PluginError) as caught:
        rig.add("sdist_only")
    assert caught.value.code == "sdist_only_dependency"
    assert caught.value.fields["packages"] == ["kbfix-sdistonly"]
    assert rig.lock_bytes() == lock
    assert tree_hashes(rig.envs) == envs
    # 빌드하지 않았다: 인덱스에서 sdist를 받지 않았다
    assert not [r for r in rig.world.index.requests if r.endswith(".tar.gz")]


def test_archived_wheel_path_is_valid_wheel_name(rig: Rig, tmp_path: Path) -> None:
    rig.add("sample")
    entry = rig.lock()["plugins"][0]
    archived = rig.root.joinpath(*entry["wheel"].split("/"))
    assert archived.parent.name == entry["wheel_sha256"]
    env = uv_env({**rig.world.environ, "LOCALAPPDATA": str(tmp_path / "cache")})
    uv = find_uv(rig.world.environ)
    python = rig.env_dir("shared") / "Scripts" / "python.exe"
    proc = subprocess.run(
        [
            str(uv),
            "pip",
            "install",
            "--dry-run",
            "--no-deps",
            "--offline",
            "--reinstall",
            "--python",
            str(python),
            str(archived),
        ],
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_reserved_and_bad_manifests_refused(rig: Rig) -> None:
    for name in ("id_core", "bad_effects"):
        with pytest.raises(PluginError) as caught:
            rig.add(name)
        assert caught.value.code == "manifest_invalid", name
    with pytest.raises(PluginError) as caught:
        rig.add("unresolvable")
    assert caught.value.code == "resolve_failed"
    assert rig.lock_bytes() is None


def test_same_id_twice_taken(rig: Rig) -> None:
    rig.add("conflict_a")
    lock = rig.lock_bytes()
    with pytest.raises(PluginError) as caught:
        rig.add("conflict_a_v2")
    assert caught.value.code == "plugin_id_taken"
    assert rig.lock_bytes() == lock


def test_remove_keeps_other_env_files(rig: Rig) -> None:
    rig.add("conflict_a")
    rig.add("conflict_b")
    iso = rig.env_dir("iso-conflict_b")
    iso_files = tree_hashes(iso)
    result = rig.ops().remove("conflict_a", confirm=lambda _: True)
    assert result["removed"] == "conflict_a"
    lock = rig.lock()
    assert [p["id"] for p in lock["plugins"]] == ["conflict_b"]
    assert "shared" not in lock["environments"]
    assert tree_hashes(iso) == iso_files
    assert rig.ops().verify()["ok"]


# ---------------------------------------------------------------- 2라운드: SDK 전이 요구·min_core


@pytest.mark.parametrize("isolation", ["auto", "isolated"])
def test_transitive_sdk_requirement_incompatible_refused(rig: Rig, isolation: str) -> None:
    # 플러그인 자신의 SDK 범위는 앱과 맞지만, 의존성이 kookabug-sdk>=0.2를 요구한다 (인덱스에
    # 가짜 0.2.0이 있다). 공유·격리 해석 모두 앱 SDK가 제약이라 커밋 전에 거부한다
    rig.add("sample")
    lock = rig.lock_bytes()
    envs = tree_hashes(rig.envs)
    with pytest.raises(PluginError) as caught:
        rig.add("sdk_consumer", isolation=isolation)
    assert caught.value.code == "sdk_incompatible"
    assert caught.value.fields["plugin"] == "compatible_c"
    assert rig.lock_bytes() == lock
    assert tree_hashes(rig.envs) == envs


def test_transitive_sdk_requirement_compatible_installs(rig: Rig) -> None:
    rig.add("sdk_user")
    lock = rig.lock()
    shared = lock["environments"]["shared"]
    # SDK는 잠금 `sdk` 하나로 나타낸다: 일반 패키지 목록에는 없다
    assert [p["name"] for p in shared["packages"]] == ["kbfix-dep", "kbfix-sdk-user"]
    installed = env_run(
        rig.env_dir("shared"),
        "from importlib.metadata import version; print(version('kookabug-sdk'))",
    ).strip()
    assert installed == lock["sdk"]["version"]
    assert rig.ops().verify()["ok"]


def _min_core_wheel(rig: Rig, tmp_path: Path, min_core: str) -> Path:
    return plugin_wheel(
        PLUGINS / "compatible_c",
        tmp_path / f"mc-{min_core}",
        pyproject_edit=lambda d: d["tool"]["kookabug"].update(min_core=min_core),
    )


@pytest.mark.parametrize(
    ("app", "min_core"),
    [
        ("0.1.0", "0.1.0.post1"),
        ("0.1.0rc1", "0.1.0rc2"),
        ("0.1.0.dev0", "0.1.0.post1"),
        ("0.1.0.dev0", "0.1.0rc1"),
        ("0.1.0", "0.1.1.dev0"),
    ],
)
def test_min_core_pep440_refused_before_confirm(
    rig: Rig, tmp_path: Path, app: str, min_core: str
) -> None:
    ops = rig.ops()
    ops._app = replace(ops.app, core_version=app)  # pyright: ignore[reportPrivateUsage]
    asked: list[object] = []

    def confirm(preview: object) -> bool:
        asked.append(preview)
        return True

    with pytest.raises(PluginError) as caught:
        ops.add(str(_min_core_wheel(rig, tmp_path, min_core)), confirm=confirm)
    assert caught.value.code == "core_too_old"
    assert asked == [] and ops.calls == []  # 신뢰 확인 전, 자식 명령도 없음


@pytest.mark.parametrize(
    ("app", "min_core"),
    [("0.1.0.dev0", "0.1.0"), ("0.1.0", "0.1.0"), ("0.1.0.post1", "0.1.0"), ("0.2.0", "0.1.0rc1")],
)
def test_min_core_allowed_reaches_confirm(
    rig: Rig, tmp_path: Path, app: str, min_core: str
) -> None:
    ops = rig.ops()
    ops._app = replace(ops.app, core_version=app)  # pyright: ignore[reportPrivateUsage]
    asked: list[object] = []

    def confirm(preview: object) -> bool:
        asked.append(preview)
        return False

    with pytest.raises(PluginError) as caught:
        ops.add(str(_min_core_wheel(rig, tmp_path, min_core)), confirm=confirm)
    assert caught.value.code == "cancelled"
    assert len(asked) == 1


# ------------------------------------------------------------------ git·path 원천 (B2)


def _installed_dists(env_dir: Path) -> dict[str, str]:
    code = (
        "import json\nfrom importlib import metadata\n"
        "print(json.dumps({d.metadata['Name']: d.version for d in metadata.distributions()}))\n"
    )
    return json.loads(env_run(env_dir, code).strip().splitlines()[-1])


def test_git_build_with_generated_schema(rig: Rig, tmp_path: Path) -> None:
    """예제 소스(스키마 파일 없음, 진입 모듈 ≠ 최상위)를 레포 밖 git에서 받아 승인 뒤 staging 빌드
    환경에서 스키마를 만들고 wheel을 확정한다. 지문은 그 wheel 해시로, 실행 환경엔 빌드 도구가
    없다."""
    repo = git_repo(SAMPLE, tmp_path / "repos" / "sample")
    schema_in_src = repo / "src" / "kookabug_plugin_sample" / SCHEMA_FILE
    assert not schema_in_src.exists()
    commit = git(repo, "rev-parse", "HEAD", env=git_env(tmp_path / "home"))
    ops = rig.ops()
    result = ops.add(git_source(repo), confirm=YES)
    assert result["env"] == "shared" and result["reused"] is False
    lock = rig.lock()
    entry = lock["plugins"][0]
    assert entry["source"] == {
        "kind": "git",
        "url": repo.as_uri(),
        "ref": "v0.1.0",
        "commit": commit,
    }
    # 원천 레포는 그대로 (스키마 파일을 원천에 쓰지 않음)
    assert not schema_in_src.exists()
    assert git(repo, "status", "--porcelain", env=git_env(tmp_path / "home")) == ""
    # 커밋된 wheel: 안에 생성된 스키마, 그 digest = 잠금
    name = "kookabug_plugin_sample-0.1.0-py3-none-any.whl"
    assert entry["wheel"] == f"plugins/wheels/{entry['wheel_sha256']}/{name}"
    archived = rig.root / "plugins" / "wheels" / entry["wheel_sha256"] / name
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == entry["wheel_sha256"]
    with zipfile.ZipFile(archived) as zf:
        document = json.loads(zf.read(f"kookabug_plugin_sample/{SCHEMA_FILE}"))
    assert schema_digest(document) == entry["schema_sha256"]
    assert document["plugin"]["modules"] == entry["manifest"]["modules"]
    # 최종 지문 = 확정된 wheel 해시로 계산
    env = lock["environments"]["shared"]
    assert env["fingerprint"] == fingerprint(
        python=lock["python"],
        platform=lock["platform"],
        sdk=lock["sdk"],
        packages=env["packages"],
        plugin_wheels=[entry["wheel_sha256"]],
    )
    # 빌드는 staging 빌드 환경에서 (실행 환경이 아님)
    builds = calls_with(ops, "kookabug_sdk.cli", "build")
    assert len(builds) == 1 and "staging" in builds[0][0] and "build-env" in builds[0][0]
    assert len(calls_with(ops, "build", "--wheel")) == 1
    env_dir = rig.env_dir("shared")
    assert not calls_with(ops, str(env_dir / "Scripts" / "python.exe"), "kookabug_sdk.cli")
    # 실행 환경: SDK + 플러그인뿐 (빌드 도구·빌드 산출물 없음)
    dists = {k.lower(): v for k, v in _installed_dists(env_dir).items()}
    assert set(dists) == {"kookabug-sdk", "kookabug-plugin-sample"}
    assert not (env_dir / "Lib" / "site-packages" / "kbfix_backend.py").exists()
    assert not any((rig.root / ".kookabug" / "plugins" / "staging").iterdir())
    out = run_node(env_dir, entry["manifest"]["modules"], "sample.text.reverse", {"text": "git"})
    assert out["outputs"] == {"text": "tig"}
    assert ops.verify()["ok"]


def test_regenerated_same_wheel_reuses_env_read_only(rig: Rig, tmp_path: Path) -> None:
    """같은 소스를 다시 빌드하면 같은 wheel 바이트 → 같은 지문 → 기존 환경은 읽기 검증만."""
    repo = git_repo(SAMPLE, tmp_path / "repos" / "sample")
    rig.ops().add(git_source(repo), confirm=YES)
    lock_before = rig.lock_bytes()
    folder = rig.env_dir("shared")
    files, mtimes = tree_hashes(folder), tree_mtimes(folder)
    ops = rig.ops()
    result = ops.upgrade("sample", confirm=YES)
    assert result["reused"] is True and result["replaced"] == "0.1.0"
    assert calls_with(ops, "kookabug_sdk.cli", "build")  # 다시 빌드했다
    assert rig.lock_bytes() == lock_before  # 같은 wheel → 같은 잠금
    assert rig.env_dir("shared") == folder
    assert not [c for c in ops.calls if any(str(folder).lower() in a.lower() for a in c)]
    assert tree_hashes(folder) == files
    assert tree_mtimes(folder) == mtimes
    assert (folder / MARKER).is_file()
    # 폴더 원천도 같은 파일이면 같은 wheel 바이트 → 같은 환경 (원본 폴더에는 쓰지 않는다)
    rig.ops().remove("sample", confirm=YES)
    result = rig.ops().add(str(repo), confirm=YES)
    assert result["reused"] is True
    assert rig.lock()["plugins"][0]["source"] == {"kind": "path", "path": str(repo.resolve())}
    assert tree_hashes(folder) == files
    assert git(repo, "status", "--porcelain", env=git_env(tmp_path / "home")) == ""


def test_upgrade_git_ref_keeps_shared_neighbors(rig: Rig, tmp_path: Path) -> None:
    """upgrade --ref: 같은 원천의 새 태그를 같은 거래로 설치. 공유 환경의 이웃 결과는 그대로."""
    repo = git_repo(SAMPLE, tmp_path / "repos" / "sample")
    env = git_env(tmp_path / "home")
    rig.add("conflict_a")
    rig.ops().add(git_source(repo), confirm=YES)
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.1.0"', 'version = "0.2.0"'),
        encoding="utf-8",
        newline="\n",
    )
    git(repo, "commit", "--quiet", "-am", "0.2.0", env=env)
    git(repo, "tag", "v0.2.0", env=env)
    previews: list[dict[str, object]] = []
    result = rig.ops().upgrade(
        "sample", ref="v0.2.0", confirm=lambda p: previews.append(p.to_json()) or True
    )
    assert previews[0]["replaces"] == "0.1.0" and previews[0]["version"] == "0.2.0"
    assert result["env"] == "shared" and result["replaced"] == "0.1.0"
    lock = rig.lock()
    entry = next(p for p in lock["plugins"] if p["id"] == "sample")
    assert entry["version"] == "0.2.0" and entry["source"]["ref"] == "v0.2.0"
    assert entry["source"]["commit"] == git(repo, "rev-parse", "HEAD", env=env)
    assert [p["version"] for p in lock["environments"]["shared"]["packages"]] == ["1.0.0"]
    out = run_node(rig.env_dir("shared"), ["kbfix_conflict_a.nodes"], "conflict_a.dep.version")
    assert out["outputs"]["version"] == "1.0.0"
    assert rig.ops().verify()["ok"]
    # 잠금에 없는 ID
    with pytest.raises(PluginError) as caught:
        rig.ops().upgrade("missing", confirm=YES)
    assert caught.value.code == "plugin_not_found"


# ------------------------------------------------------------------ 2라운드 회귀 (review_B2_1)

_URL_DEP = "kbfix-dep @ https://changed.invalid/kbfix_dep-2.0.0-py3-none-any.whl"


def test_direct_url_dependency_refused_before_confirm(rig: Rig, tmp_path: Path) -> None:
    """의존성의 직접 URL 참조는 ② 정적 검사에서 거부 (폴더·wheel 원천 모두, 확인 전)."""
    project = tmp_path / "url-dep"
    shutil.copytree(PLUGINS / "build_marker", project)
    config = project / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("dependencies = [", f'dependencies = ["{_URL_DEP}", '), "utf-8")
    wheel = plugin_wheel(
        PLUGINS / "conflict_a",
        tmp_path / "w",
        pyproject_edit=lambda d: d["project"]["dependencies"].append(_URL_DEP.replace("dep", "x")),
    )
    asked: list[object] = []
    for source in (str(project), str(wheel)):
        ops = rig.ops()
        with pytest.raises(PluginError) as caught:
            ops.add(source, confirm=lambda p: asked.append(p) or True)
        assert caught.value.code == "manifest_invalid", caught.value.message
        assert "직접 URL" in caught.value.message
        assert asked == [] and ops.calls == []
    assert rig.lock_bytes() is None


def test_built_dependency_changed_to_url_fails(rig: Rig, tmp_path: Path) -> None:
    """빌드 백엔드가 승인한 의존성(`kbfix-dep`)을 직접 URL로 바꿔 쓰면 ⑥ 대조에서 build_failed."""
    project = tmp_path / "changed-metadata"
    shutil.copytree(PLUGINS / "build_marker", project)
    config = project / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("dependencies = [", 'dependencies = ["kbfix-dep", '), "utf-8")
    backend = project / "_backend" / "kbfix_backend.py"
    body = backend.read_text("utf-8").replace("_EPOCH = ", f"_REWRITE = {_URL_DEP!r}\n\n_EPOCH = ")
    body = body.replace(
        'f"Requires-Dist: {r}"', "f\"Requires-Dist: {_REWRITE if r == 'kbfix-dep' else r}\""
    )
    backend.write_text(body, encoding="utf-8")
    previews: list[dict[str, object]] = []
    with pytest.raises(PluginError) as caught:
        rig.ops().add(str(project), confirm=lambda p: previews.append(p.to_json()) or True)
    assert previews[0]["dependencies"] == ["kbfix-dep"]
    assert caught.value.code == "build_failed", caught.value.message
    assert rig.lock_bytes() is None
    assert not (rig.root / "plugins" / "wheels").exists()


def test_requirement_compare_includes_direct_url() -> None:
    base = ("kbfix-dep", "kookabug-sdk<0.2,>=0.1.0.dev0")
    assert same_requirements(base, ("kookabug-sdk>=0.1.0.dev0,<0.2", "KBFIX_dep"))
    assert not same_requirements(base, (_URL_DEP, base[1]))
    other = _URL_DEP.replace("changed", "approved")
    assert not same_requirements((_URL_DEP,), (other,))
