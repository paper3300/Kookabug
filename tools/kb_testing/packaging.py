"""패키징 검사 헬퍼.

소스 트리 import로는 배포 누락을 증명할 수 없으므로, wheel·sdist를 실제로 만들고
**레포 밖** 깨끗한 venv에 설치해 `python -I`로 확인한다.

    sdk = build_dists(REPO_ROOT / "python" / "kookabug_sdk", tmp_path / "dist-sdk")
    nodes = build_dists(REPO_ROOT / "python" / "kookabug_nodes", tmp_path / "dist-nodes")
    py = make_clean_venv(tmp_path / "venv")
    install(py, sdk.wheel, nodes.wheel)  # 워크스페이스 의존성도 wheel로 함께 넘긴다
    run_isolated(py, "import kookabug_nodes", cwd=tmp_path)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = "3.14"


@dataclass(frozen=True)
class Dists:
    wheel: Path
    sdist: Path

    def wheel_files(self) -> list[str]:
        with zipfile.ZipFile(self.wheel) as zf:
            return sorted(zf.namelist())

    def sdist_files(self) -> list[str]:
        with tarfile.open(self.sdist) as tf:
            return sorted(m.name for m in tf.getmembers() if m.isfile())


def uv_exe() -> str:
    path = shutil.which("uv")
    if path is None:
        raise RuntimeError("uv를 PATH에서 찾을 수 없다")
    return path


def is_inside_repo(path: Path) -> bool:
    return path.resolve().is_relative_to(REPO_ROOT)


def assert_outside_repo(path: Path) -> None:
    if is_inside_repo(path):
        raise AssertionError(f"레포 밖이어야 한다: {path}")


def clean_env() -> dict[str, str]:
    """워크스페이스 venv가 새지 않는 환경 변수."""
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def run(
    cmd: Sequence[str | Path], cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        env=clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"명령 실패 ({proc.returncode}): {' '.join(str(c) for c in cmd)}\n"
            f"--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}"
        )
    return proc


def build_dists(project_dir: Path, out_dir: Path) -> Dists:
    """`uv build`로 wheel과 sdist를 out_dir에 만든다 (out_dir는 비어 있어야 한다)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if any(out_dir.iterdir()):
        raise AssertionError(f"빈 폴더여야 한다: {out_dir}")
    run([uv_exe(), "build", project_dir, "--out-dir", out_dir, "--quiet"], cwd=project_dir)
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise AssertionError(f"wheel·sdist가 하나씩이어야 한다: {sorted(out_dir.iterdir())}")
    return Dists(wheel=wheels[0], sdist=sdists[0])


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if os.name == "nt" else venv / "bin" / "python"


def make_clean_venv(venv: Path, python: str = DEFAULT_PYTHON) -> Path:
    """레포 밖에 빈 venv를 만들고 그 python 경로를 돌려준다."""
    assert_outside_repo(venv)
    run([uv_exe(), "venv", venv, "--python", python, "--quiet"], cwd=venv.parent)
    return venv_python(venv)


def workspace_names() -> frozenset[str]:
    """레포 uv 워크스페이스 멤버의 배포 이름 (정규화)."""
    names: set[str] = set()
    for pyproject in (REPO_ROOT / "python").glob("*/pyproject.toml"):
        with pyproject.open("rb") as f:
            names.add(canonicalize_name(tomllib.load(f)["project"]["name"]))
    return frozenset(names)


def _same_file(url: str, path: Path) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return False
    local = Path(
        url2pathname(parsed.path if not parsed.netloc else f"//{parsed.netloc}{parsed.path}")
    )
    return os.path.normcase(local.resolve()) == os.path.normcase(path.resolve())


def _wheel_name_version(wheel: Path) -> tuple[str, str]:
    name, version = wheel.name.split("-")[:2]
    return canonicalize_name(name), version


_INSTALLED_CODE = """\
import json, importlib.metadata as m
out = {}
for d in m.distributions():
    try:
        url = json.loads(d.read_text("direct_url.json") or "{}").get("url", "")
    except ValueError:
        url = ""
    out[d.metadata["Name"]] = {"version": d.version, "url": url}
print(json.dumps(out))
"""


def installed_distributions(python: Path) -> dict[str, dict[str, str]]:
    """venv에 설치된 배포: {정규화 이름: {"version", "url"(direct_url.json, 없으면 "")}}."""
    proc = run([python, "-I", "-c", _INSTALLED_CODE], cwd=python.parent)
    return {canonicalize_name(k): v for k, v in json.loads(proc.stdout).items()}


def install(
    python: Path,
    *wheels: Path,
    no_deps: bool = False,
    local_names: Iterable[str] | None = None,
) -> None:
    """직접 빌드한 wheel을 venv에 설치한다.

    검사 대상 wheel은 전부 **직접 설치 인자**로 넘긴다. 직접 지정한 파일은 인덱스의 같은 이름
    배포본보다 우선한다 (`--find-links`는 인덱스와 경쟁하므로 쓰지 않는다). 설치 뒤에는
    - 넘긴 wheel마다 설치된 버전과 출처(direct_url.json)가 그 파일인지
    - `local_names`(기본: 워크스페이스 멤버) 중 설치된 것이 모두 직접 넘긴 wheel인지
    확인해, 인덱스의 동명 배포본이 섞이면 실패한다. 서드파티 의존성만 인덱스에서 받는다.
    """
    given: dict[str, tuple[str, Path]] = {}
    for wheel in wheels:
        if wheel.suffix != ".whl":
            raise AssertionError(f"wheel 파일만 받는다: {wheel}")
        name, version = _wheel_name_version(wheel)
        given[name] = (version, wheel.resolve())

    cmd: list[str | Path] = [uv_exe(), "pip", "install", "--python", python, "--quiet"]
    if no_deps:
        cmd.append("--no-deps")
    cmd += [path for _, path in given.values()]
    run(cmd, cwd=python.parent)

    installed = installed_distributions(python)
    for name, (version, path) in given.items():
        got = installed.get(name)
        if got is None or got["version"] != version or not _same_file(got["url"], path):
            raise AssertionError(f"{name}: {path.name}이(가) 아니라 {got}이(가) 설치됐다")
    local = {canonicalize_name(n) for n in (local_names or workspace_names())}
    from_elsewhere = sorted((local & installed.keys()) - given.keys())
    if from_elsewhere:
        raise AssertionError(
            f"로컬 wheel로 넘기지 않은 패키지가 다른 출처에서 설치됐다: {from_elsewhere}"
        )


def run_isolated(
    python: Path, code: str, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """`python -I -c code`를 레포 밖 cwd에서 실행한다 (레포 소스가 import되지 않게)."""
    assert_outside_repo(cwd)
    return run([python, "-I", "-c", code], cwd=cwd, check=check)
