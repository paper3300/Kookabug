import json
import zipfile
from pathlib import Path

import pytest

from kb_testing import packaging as pk

PYPROJECT = """\
[project]
name = "kb-helper-probe"
version = "0.0.1"
requires-python = ">=3.14"

[build-system]
requires = ["uv_build>=0.13.6,<0.14"]
build-backend = "uv_build"
"""


def _make_probe_project(root: Path) -> Path:
    pkg = root / "src" / "kb_helper_probe"
    pkg.mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (pkg / "__init__.py").write_text("VALUE = 42\n", encoding="utf-8")
    (pkg / "data.json").write_text('{"ok": true}\n', encoding="utf-8")
    return root


@pytest.mark.packaging
def test_build_and_install_into_clean_venv_outside_repo(tmp_path: Path) -> None:
    assert not pk.is_inside_repo(tmp_path)
    project = _make_probe_project(tmp_path / "probe")

    dists = pk.build_dists(project, tmp_path / "dist")
    assert "kb_helper_probe/data.json" in dists.wheel_files()
    assert any(f.endswith("src/kb_helper_probe/data.json") for f in dists.sdist_files())

    py = pk.make_clean_venv(tmp_path / "venv")
    assert py.is_file()
    pk.install(py, dists.wheel)

    code = (
        "import json, importlib.resources as r, kb_helper_probe as m; "
        "print(json.dumps({'file': m.__file__, 'value': m.VALUE, "
        "'data': json.loads(r.files('kb_helper_probe').joinpath('data.json').read_text())}))"
    )
    out = json.loads(pk.run_isolated(py, code, cwd=tmp_path).stdout)
    assert out["value"] == 42
    assert out["data"] == {"ok": True}
    # 레포나 프로젝트 소스가 아니라 venv에 설치된 파일을 import했다
    installed = Path(out["file"]).resolve()
    assert installed.is_relative_to((tmp_path / "venv").resolve())
    assert not pk.is_inside_repo(installed)


def _fake_wheel(folder: Path, name: str, version: str, requires: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{version}-py3-none-any.whl"
    info = f"{name}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n"
    if requires:
        metadata += f"Requires-Dist: {requires}\n"
    wheel_meta = "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{name}/__init__.py", f"VERSION = {version!r}\n")
        zf.writestr(f"{info}/METADATA", metadata)
        zf.writestr(f"{info}/WHEEL", wheel_meta)
        zf.writestr(f"{info}/RECORD", "")
    return path


def _imported_version(py: Path, module: str, cwd: Path) -> str:
    return pk.run_isolated(py, f"import {module}; print({module}.VERSION)", cwd=cwd).stdout.strip()


@pytest.mark.packaging
def test_local_wheel_wins_over_index_with_same_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 로컬 빌드 1.0과 인덱스의 동명 2.0이 경쟁한다
    dep_local = _fake_wheel(tmp_path / "local", "kb_compete_dep", "1.0")
    app = _fake_wheel(tmp_path / "app", "kb_compete_app", "1.0", requires="kb-compete-dep")
    index = tmp_path / "simple"
    remote = _fake_wheel(index / "kb-compete-dep", "kb_compete_dep", "2.0")
    (remote.parent / "index.html").write_text(
        f'<a href="{remote.name}">{remote.name}</a>', encoding="utf-8"
    )
    for key in ("UV_INDEX", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL", "UV_FIND_LINKS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("UV_DEFAULT_INDEX", index.as_uri())
    local = {"kb-compete-app", "kb-compete-dep"}

    # 대조: 의존성을 인덱스에 맡기면 2.0이 들어온다 (경쟁이 실제로 성립한다)
    py_index = pk.make_clean_venv(tmp_path / "venv-index")
    pk.run([pk.uv_exe(), "pip", "install", "--python", py_index, "--quiet", app], cwd=tmp_path)
    assert _imported_version(py_index, "kb_compete_dep", tmp_path) == "2.0"

    # 로컬 패키지를 넘기지 않아 인덱스에서 오면 헬퍼가 실패한다
    py_missing = pk.make_clean_venv(tmp_path / "venv-missing")
    with pytest.raises(AssertionError, match="kb-compete-dep"):
        pk.install(py_missing, app, local_names=local)

    # 함께 넘기면 로컬 1.0이 선택되고, 출처도 그 파일이다
    py = pk.make_clean_venv(tmp_path / "venv")
    pk.install(py, app, dep_local, local_names=local)
    assert _imported_version(py, "kb_compete_dep", tmp_path) == "1.0"
    installed = pk.installed_distributions(py)
    assert installed["kb-compete-dep"]["version"] == "1.0"
    assert installed["kb-compete-dep"]["url"].endswith("/local/kb_compete_dep-1.0-py3-none-any.whl")


def test_workspace_names_are_the_uv_members() -> None:
    assert pk.workspace_names() == {"kookabug-sdk", "kookabug-nodes", "kookabug-core"}


def test_helpers_refuse_venv_inside_repo() -> None:
    with pytest.raises(AssertionError):
        pk.make_clean_venv(pk.REPO_ROOT / "build" / "never-created-venv")
    with pytest.raises(AssertionError):
        pk.run_isolated(Path("python.exe"), "pass", cwd=pk.REPO_ROOT)
