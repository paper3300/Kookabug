"""설치 파일 빌드 (구현 계획 M1 2.12).

    $env:PYTHONPATH = "tools"; uv run python -m installer.build [--out build/installer] [--no-setup]

`<out>/stage`가 곧 설치 폴더 구조다:

    python/                PBS + 런타임 wheel + 우리 wheel(compileall) + 앱 로컬 VC++ 런타임
    bin/kookabug.exe       실행기 (Python 경로가 ..\\python\\python.exe 상대 경로)
    ocr-models/            OCR 모델·라이선스 근거 원문 (models.toml 해시)
    examples/sample-game/  예제 게임(sample_game)·화면 PNG·장면 표(frames)·예제 워크스페이스
    licenses/              LICENSE.txt, THIRD_PARTY_NOTICES.txt
    VERSION

단계
1. PBS: 캐시(`build/installer-cache`)에서 찾거나 받고, 크기·SHA256을 확인한 **그 바이트를** 푼다
2. 런타임: 라이선스 감사와 같은 `uv export`(`license_pipeline.export_runtime`, 해시 고정)의 서드파티
   wheel과 `uv build`로 만든 우리 wheel을 `--no-deps`·`--link-mode copy`로 설치한다(uv 캐시와 하드
   링크를 공유하면 뒤의 제거·RECORD 수정이 캐시를 건드린다). 설치된 집합 = runtime.txt + 우리 wheel
3. 실행기: uv가 만든 `python/Scripts/*.exe`의 Python 경로 자원(`UV_PYTHON_PATH`)을 상대 경로로
   바꾸고(RECORD 해시도) `bin/kookabug.exe`를 만든다. uv 실행기는 상대 경로를 자기 폴더 기준으로
   푼다 — 설치 뒤 고치는 단계가 없고 설치 폴더를 옮겨도 돈다
4. VC++ 런타임을 python.exe 옆에 복사 (빌드 머신 Visual Studio의 VC\\Redist)
5. 모델·예제·라이선스·VERSION
6. 빌드 입력 감사 (네이티브 표·제거 목록 — PBS 규칙 포함, 모델 해시)
7. 제거 목록의 파일·폴더와 그 RECORD 줄을 지운다
8. compileall
9. 최종 트리 감사 + 메타데이터 감사(스테이징 Python을 pip-licenses로 스캔) → NOTICES
10. iscc → `<out>/dist/kookabug-setup-<버전>.exe`. 요약은 `<out>/build.json`
"""

from __future__ import annotations

import argparse
import base64
import csv
import ctypes
import hashlib
import io
import json
import os
import posixpath
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

import license_audit as la
import license_pipeline as lp
import native_audit as na
from kookabug_sdk.console import utf8_stdio

INSTALLER_DIR: Final = Path(__file__).resolve().parent
TOOLS_DIR: Final = INSTALLER_DIR.parent
REPO_ROOT: Final = TOOLS_DIR.parent
INPUTS: Final = INSTALLER_DIR / "pbs.toml"
ISS: Final = INSTALLER_DIR / "kookabug.iss"
NATIVE_TABLE: Final = TOOLS_DIR / "native-licenses.toml"
ALLOWLIST: Final = TOOLS_DIR / "license-allowlist.toml"
MODELS_TABLE: Final = REPO_ROOT / lp.MODELS_TABLE
MODELS_DIR: Final = REPO_ROOT / lp.MODELS_DIR
SAMPLE_GAME: Final = REPO_ROOT / "fixtures" / "sample-game"
CLI_PYPROJECT: Final = REPO_ROOT / "python" / "kookabug_cli" / "pyproject.toml"
DEFAULT_OUT: Final = REPO_ROOT / "build" / "installer"
DEFAULT_CACHE: Final = REPO_ROOT / "build" / "installer-cache"
OUT_MARKER: Final = ".kookabug-installer-build"

# 설치 폴더 구조 (2.12)
PYTHON: Final = "python"
BIN: Final = "bin"
EXAMPLES: Final = "examples/sample-game"
LICENSES: Final = "licenses"
NOTICES: Final = "licenses/THIRD_PARTY_NOTICES.txt"
VERSION_FILE: Final = "VERSION"
LAUNCHER: Final = "kookabug.exe"
# Inno Setup이 설치 때 설치 폴더에 더하는 제거 프로그램 (스테이징에는 없다)
INNO_UNINSTALLER: Final = "unins000.exe"
# 예제 게임에서 설치본에 넣는 것 (테스트·도구·OCR 표본은 넣지 않는다)
EXAMPLE_PARTS: Final = ("README.md", "sample_game", "frames", "workspace")
EXAMPLE_IGNORE: Final = ("__pycache__", "runs", ".kookabug")


class BuildError(Exception):
    pass


# ---------------------------------------------------------------- 입력 표


@dataclass(frozen=True)
class PythonDist:
    tag: str
    version: str
    file: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class VcRedist:
    crt_folder: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class Inputs:
    python: PythonDist
    vc_redist: VcRedist
    uv_version: str


def load_inputs(path: Path = INPUTS) -> Inputs:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        py, vc = data["python"], data["vc_redist"]
        return Inputs(
            PythonDist(
                tag=str(py["tag"]),
                version=str(py["version"]),
                file=str(py["file"]),
                url=str(py["url"]),
                sha256=str(py["sha256"]).lower(),
                size=int(py["size"]),
            ),
            VcRedist(crt_folder=str(vc["crt_folder"]), files=tuple(map(str, vc["files"]))),
            uv_version=str(data["uv"]["version"]),
        )
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError, ValueError) as exc:
        raise BuildError(f"{path}: 빌드 입력 표를 읽을 수 없다 ({exc})") from exc


def cli_version() -> str:
    with CLI_PYPROJECT.open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def check_uv_version(uv: str, want: str) -> None:
    """설치본 실행기는 빌드에 쓴 uv의 스텁이다. 구성요소 표(uv-trampoline SBOM·원문)가 가리키는 판과
    다르면 멈춘다."""
    out = run([uv, "--version"], cwd=REPO_ROOT, capture=True).split()
    got = out[1] if len(out) > 1 else ""
    if got != want:
        raise BuildError(
            f"uv {got}로는 빌드하지 않는다: 실행기 구성요소 표는 uv {want} 기준이다 (pbs.toml [uv])"
        )


def file_version(version: str) -> str:
    """Windows 파일 버전(숫자 네 자리): `0.1.0.dev0` → `0.1.0.0`."""
    release = Version(version).release
    return ".".join(str(n) for n in (*release, 0, 0, 0)[:4])


# ---------------------------------------------------------------- 공용


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified(path: Path, sha256: str, size: int) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256_file(path) == sha256


def clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(cmd: Sequence[str | Path], *, cwd: Path, capture: bool = False) -> str:
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=cwd,
        env=clean_env(),
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = f"\n{proc.stdout}\n{proc.stderr}" if capture else ""
        raise BuildError(f"명령 실패 (종료 코드 {proc.returncode}): {cmd[0]}{detail}")
    return proc.stdout if capture else ""


def max_rel_path(root: Path) -> int:
    """설치 폴더 기준 가장 긴 상대 경로의 길이 (Windows 구분자). 설치 파일이 설치 폴더 길이를
    MAX_PATH 안으로 막는 데 쓴다."""
    return max((len(str(p.relative_to(root))) for p in root.rglob("*")), default=0)


def tree_size(root: Path) -> tuple[int, int]:
    """(바이트, 파일 수)."""
    total = count = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
            count += 1
    return total, count


# ---------------------------------------------------------------- 1. PBS


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as resp, dest.open("wb") as f:
        shutil.copyfileobj(resp, f)


def fetch_python(
    dist: PythonDist, cache: Path, *, download: Callable[[str, Path], None] = _download
) -> Path:
    """캐시에 같은 파일(크기·SHA256)이 있으면 그것, 없으면 받아서 확인한 뒤 캐시에 둔다."""
    target = cache / dist.file
    if verified(target, dist.sha256, dist.size):
        return target
    cache.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    print(f"받기: {dist.url}", flush=True)
    download(dist.url, part)
    if not verified(part, dist.sha256, dist.size):
        part.unlink(missing_ok=True)
        raise BuildError(f"{dist.file}: 받은 파일의 크기·SHA256이 pbs.toml과 다르다")
    part.replace(target)
    return target


def extract_python(archive: Path, dist: PythonDist, stage: Path) -> Path:
    """크기·SHA256이 표와 같을 때만 `stage/python`에 푼다. 확인한 바이트를 그대로 푼다(확인과 풀기
    사이에 파일이 바뀌어도 확인하지 않은 내용을 풀지 않는다)."""
    data = archive.read_bytes()
    if len(data) != dist.size or sha256_bytes(data) != dist.sha256:
        raise BuildError(f"{archive.name}: 크기·SHA256이 pbs.toml과 다르다. 풀지 않는다")
    dest = stage / PYTHON
    if dest.exists():
        raise BuildError(f"{dest}가 이미 있다")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        outside = [n for n in tar.getnames() if n.split("/", 1)[0] != PYTHON]
        if outside:
            raise BuildError(f"{archive.name}: python/ 밖 항목이 있다 ({outside[:3]})")
        tar.extractall(stage, filter="data")
    return dest


def check_python_version(python: Path, dist: PythonDist) -> None:
    out = run(
        [python, "-I", "-c", "import platform; print(platform.python_version())"],
        cwd=python.parent,
        capture=True,
    ).strip()
    if out != dist.version:
        raise BuildError(f"PBS Python 버전이 {out}이다 (pbs.toml {dist.version})")


# ---------------------------------------------------------------- 2. 런타임


@dataclass(frozen=True)
class RuntimeSet:
    runtime_txt: Path
    wheels: tuple[Path, ...]


def install_runtime(uv: str, python: Path, work: Path, project: Path = REPO_ROOT) -> RuntimeSet:
    work.mkdir(parents=True, exist_ok=True)
    runtime = work / "runtime.txt"
    hashed = work / "runtime-hashes.txt"
    lp.export_runtime(uv, project, runtime)
    lp.export_runtime(uv, project, hashed, hashes=True)
    common: list[str | Path] = [
        uv,
        "pip",
        "install",
        "--python",
        python,
        "--no-config",
        "--no-deps",
        "--link-mode",
        "copy",
        "--quiet",
    ]
    if lp.has_requirements(runtime):
        run(
            [*common, "--only-binary", ":all:", "--require-hashes", "-r", hashed],
            cwd=work,
        )
    wheels_dir = work / "wheels"
    run(
        [uv, "build", "--all-packages", "--wheel", "--out-dir", wheels_dir, "--quiet"],
        cwd=project,
    )
    wheels = tuple(sorted(wheels_dir.glob("*.whl")))
    if not wheels:
        raise BuildError(f"{wheels_dir}에 우리 wheel이 없다")
    run([*common, "--no-index", *wheels], cwd=work)
    return RuntimeSet(runtime, wheels)


def installed_set(site: Path) -> dict[NormalizedName, str]:
    return {
        canonicalize_name(d.metadata["Name"]): d.version
        for d in metadata.distributions(path=[str(site)])
    }


def wheel_name_version(wheel: Path) -> tuple[NormalizedName, str]:
    name, version = wheel.name.split("-")[:2]
    return canonicalize_name(name), version


def check_runtime_set(
    site: Path, runtime_txt: Path, marker_env: Mapping[str, str], wheels: Sequence[Path]
) -> list[str]:
    """설치된 배포 = 감사 runtime.txt(대상 마커에서 활성) + 우리 wheel. 이름·버전 모두."""
    baseline = la.select_active(la.parse_runtime(runtime_txt.read_text("utf-8")), marker_env)
    expected: dict[NormalizedName, str] = {
        name: str(req.version) for name, req in baseline.active.items()
    }
    expected.update(wheel_name_version(w) for w in wheels)
    got = installed_set(site)
    problems = [f"[설치 누락] {n}=={v}" for n, v in sorted(expected.items()) if n not in got]
    problems += [f"[설치 집합 밖] {n}=={v}" for n, v in sorted(got.items()) if n not in expected]
    problems += [
        f"[버전 불일치] {n}: 기대 {expected[n]}, 설치 {v}"
        for n, v in sorted(got.items())
        if n in expected and Version(v) != Version(expected[n])
    ]
    return problems


def read_marker_env(python: Path, work: Path) -> dict[str, str]:
    out = work / "marker_env.json"
    lp.write_marker_env(python, out, cwd=work)
    return la.load_marker_env(json.loads(out.read_text(encoding="utf-8")))


# ---------------------------------------------------------------- 3. 실행기

RT_RCDATA: Final = 10
PYTHON_PATH_RESOURCE: Final = "UV_PYTHON_PATH"
KIND_RESOURCE: Final = "UV_TRAMPOLINE_KIND"
SCRIPT_KIND: Final = b"\x01"
_LOAD_AS_DATA: Final = 0x2 | 0x20  # LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE

_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
_ENUMLANG = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMODULE,
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.WORD,
    wintypes.LPARAM,
)
if _k32 is not None:
    _k32.LoadLibraryExW.restype = wintypes.HMODULE
    _k32.LoadLibraryExW.argtypes = (wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD)
    _k32.FreeLibrary.argtypes = (wintypes.HMODULE,)
    _k32.FindResourceW.restype = wintypes.HANDLE
    _k32.FindResourceW.argtypes = (wintypes.HMODULE, wintypes.LPCWSTR, wintypes.LPVOID)
    _k32.LoadResource.restype = wintypes.HANDLE
    _k32.LoadResource.argtypes = (wintypes.HMODULE, wintypes.HANDLE)
    _k32.LockResource.restype = wintypes.LPVOID
    _k32.LockResource.argtypes = (wintypes.HANDLE,)
    _k32.SizeofResource.restype = wintypes.DWORD
    _k32.SizeofResource.argtypes = (wintypes.HMODULE, wintypes.HANDLE)
    _k32.EnumResourceLanguagesW.restype = wintypes.BOOL
    _k32.EnumResourceLanguagesW.argtypes = (
        wintypes.HMODULE,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        _ENUMLANG,
        wintypes.LPARAM,
    )
    _k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    _k32.BeginUpdateResourceW.argtypes = (wintypes.LPCWSTR, wintypes.BOOL)
    _k32.UpdateResourceW.restype = wintypes.BOOL
    _k32.UpdateResourceW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.LPCWSTR,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _k32.EndUpdateResourceW.restype = wintypes.BOOL
    _k32.EndUpdateResourceW.argtypes = (wintypes.HANDLE, wintypes.BOOL)


def _kernel32() -> Any:
    if _k32 is None:
        raise BuildError("실행기 자원 수정은 Windows에서만 할 수 있다")
    return _k32


@contextmanager
def _image(exe: Path) -> Iterator[int]:
    k = _kernel32()
    handle = k.LoadLibraryExW(str(exe), None, _LOAD_AS_DATA)
    if not handle:
        raise BuildError(f"{exe}: 읽을 수 없다 (Win32 오류 {ctypes.get_last_error()})")
    try:
        yield handle
    finally:
        k.FreeLibrary(handle)


def _resource(exe: Path, name: str) -> bytes | None:
    k = _kernel32()
    with _image(exe) as handle:
        res = k.FindResourceW(handle, name, RT_RCDATA)
        if not res:
            return None
        size = k.SizeofResource(handle, res)
        return ctypes.string_at(k.LockResource(k.LoadResource(handle, res)), size)


def launcher_python(exe: Path) -> str | None:
    """uv 실행기의 Python 경로 자원. uv 실행기가 아니면 None."""
    data = _resource(exe, PYTHON_PATH_RESOURCE)
    return None if data is None else data.decode("utf-8")


def is_script_launcher(exe: Path) -> bool:
    """콘솔 스크립트 실행기인가 (uv venv의 python.exe 같은 인터프리터 실행기는 아니다)."""
    return _resource(exe, KIND_RESOURCE) == SCRIPT_KIND and launcher_python(exe) is not None


def set_launcher_python(exe: Path, python: str) -> None:
    """Python 경로 자원을 바꾼다 (같은 언어 ID로 덮어써 자원이 둘이 되지 않게)."""
    k = _kernel32()
    langs: list[int] = []

    @_ENUMLANG
    def collect(_h: int, _t: int, _n: int, lang: int, _p: int) -> bool:
        langs.append(lang)
        return True

    with _image(exe) as handle:
        k.EnumResourceLanguagesW(handle, RT_RCDATA, PYTHON_PATH_RESOURCE, collect, 0)
    if len(langs) != 1:
        raise BuildError(f"{exe}: {PYTHON_PATH_RESOURCE} 자원이 하나가 아니다 ({langs})")
    data = python.encode("utf-8")
    buf = ctypes.create_string_buffer(data, len(data))
    update = k.BeginUpdateResourceW(str(exe), False)
    if not update:
        raise BuildError(f"{exe}: 자원을 고칠 수 없다 (Win32 오류 {ctypes.get_last_error()})")
    ok = k.UpdateResourceW(update, RT_RCDATA, PYTHON_PATH_RESOURCE, langs[0], buf, len(data))
    if not k.EndUpdateResourceW(update, not ok) or not ok:
        raise BuildError(f"{exe}: 자원을 쓰지 못했다 (Win32 오류 {ctypes.get_last_error()})")
    if launcher_python(exe) != python:
        raise BuildError(f"{exe}: 고친 Python 경로를 다시 읽으니 다르다")


def record_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _read_record(record: Path) -> list[list[str]]:
    return list(csv.reader(record.read_text(encoding="utf-8").splitlines()))


def _write_record(record: Path, rows: Sequence[Sequence[str]]) -> None:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    record.write_text(out.getvalue(), encoding="utf-8", newline="")


def update_record_hashes(site: Path, changed: Sequence[Path]) -> int:
    """바꾼 파일을 가리키는 RECORD 줄의 해시·크기를 다시 쓴다. 고친 줄 수."""
    targets = {os.path.normcase(p.resolve()): p for p in changed}
    fixed = 0
    for record in sorted(site.glob("*.dist-info/RECORD")):
        rows = _read_record(record)
        dirty = False
        for row in rows:
            if not row or not row[0]:
                continue
            key = os.path.normcase((site / row[0]).resolve())
            path = targets.get(key)
            if path is None:
                continue
            while len(row) < 3:
                row.append("")
            row[1], row[2] = record_hash(path), str(path.stat().st_size)
            dirty = True
            fixed += 1
        if dirty:
            _write_record(record, rows)
    return fixed


def relocate_launchers(stage: Path) -> list[str]:
    """`python/Scripts`의 uv 실행기를 `..\\<python.exe|pythonw.exe>`로 바꾸고, `bin/kookabug.exe`를
    `..\\python\\python.exe`로 만든다. 바꾼 실행기 이름 목록."""
    scripts = stage / PYTHON / "Scripts"
    changed: list[Path] = []
    for exe in sorted(scripts.glob("*.exe")):
        current = launcher_python(exe)
        if current is None or not is_script_launcher(exe):
            continue
        set_launcher_python(exe, "..\\" + Path(current).name)
        changed.append(exe)
    update_record_hashes(stage / na.SITE_PACKAGES_IN_INSTALL, changed)
    source = scripts / LAUNCHER
    if source not in changed:
        raise BuildError(f"{source}가 없거나 uv 실행기가 아니다 (kookabug-cli 설치 확인)")
    (stage / BIN).mkdir(parents=True, exist_ok=True)
    launcher = stage / BIN / LAUNCHER
    shutil.copy2(source, launcher)
    set_launcher_python(launcher, f"..\\{PYTHON}\\python.exe")
    return [exe.name for exe in changed]


# ---------------------------------------------------------------- 4. VC++ 런타임


def _version_key(name: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in name.split("."))
    except ValueError:
        return None


def find_vc_redist(vc: VcRedist) -> Path:
    """설치된 Visual Studio의 `VC\\Redist\\MSVC\\<가장 높은 버전>\\x64\\<crt_folder>`."""
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    vswhere = Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        raise BuildError(f"vswhere가 없다 ({vswhere}). --vc-redist로 CRT 폴더를 준다")
    out = run(
        [vswhere, "-all", "-products", "*", "-property", "installationPath"],
        cwd=vswhere.parent,
        capture=True,
    )
    found: list[tuple[tuple[int, ...], Path]] = []
    for line in out.splitlines():
        msvc = Path(line.strip()) / "VC" / "Redist" / "MSVC"
        for crt in msvc.glob(f"*/x64/{vc.crt_folder}"):
            key = _version_key(crt.parents[1].name)
            if key is not None:
                found.append((key, crt))
    if not found:
        raise BuildError(f"Visual Studio의 VC\\Redist\\MSVC\\*\\x64\\{vc.crt_folder}가 없다")
    return max(found)[1]


def copy_vc_runtime(crt: Path, vc: VcRedist, python_dir: Path) -> list[str]:
    sources = [src for pattern in vc.files for src in sorted(crt.glob(pattern))]
    if "msvcp140.dll" not in {src.name.casefold() for src in sources}:
        raise BuildError(f"{crt}에 msvcp140.dll이 없다")
    for src in sources:
        shutil.copy2(src, python_dir / src.name)
    return [src.name for src in sources]


# ---------------------------------------------------------------- 5. 모델·예제·라이선스


def model_files(models: Sequence[na.ModelEntry]) -> list[str]:
    files: list[str] = []
    for m in models:
        for name in (m.file, *(t.file for t in m.texts)):
            if name not in files:
                files.append(name)
    return files


def copy_models(source: Path, models: Sequence[na.ModelEntry], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in model_files(models):
        src = source / name
        if not src.is_file():
            raise BuildError(
                f"OCR 모델 {src}가 없다. `uv run python tools/fetch_ocr_models.py`로 받는다"
            )
        shutil.copy2(src, dest / name)


def copy_examples(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for part in EXAMPLE_PARTS:
        src = source / part
        if src.is_dir():
            shutil.copytree(src, dest / part, ignore=shutil.ignore_patterns(*EXAMPLE_IGNORE))
        else:
            shutil.copy2(src, dest / part)


def write_metadata(stage: Path, version: str) -> None:
    (stage / LICENSES).mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "LICENSE", stage / LICENSES / "LICENSE.txt")
    (stage / VERSION_FILE).write_text(version + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 7. 제거


def strip_tree(stage: Path, table: na.NativeTable) -> list[str]:
    """제거 목록이 맞히는 파일·폴더(폴더 규칙이면 그 폴더 전체)와 그것을 가리키는 RECORD 줄을
    지운다. 지운 것 목록 (`scope:상대 경로`)."""
    layout = na.Layout.install(stage)
    site = layout.roots[na.SITE_PACKAGES]
    targets: dict[Path, str] = {}
    for scope, rel, _ in na.iter_files(layout):
        rule = na.find_strip(table, scope, rel)
        if rule is None:
            continue
        parts = rel.split("/")
        prefix = next(
            p
            for p in ("/".join(parts[: i + 1]) for i in range(len(parts)))
            if na.glob_match(p, rule.glob)
        )
        targets[layout.roots[scope] / prefix] = f"{scope}:{prefix}"

    removed_dirs = [t for t in targets if t.is_dir()]
    for record in sorted(site.glob("*.dist-info/RECORD")):
        if any(record.is_relative_to(d) for d in removed_dirs):
            continue  # 통째로 지우는 배포
        rows = _read_record(record)
        kept = [
            row
            for row in rows
            if not row
            or not row[0]
            or na.find_strip(table, na.SITE_PACKAGES, posixpath.normpath(row[0].replace("\\", "/")))
            is None
        ]
        if len(kept) != len(rows):
            _write_record(record, kept)

    for path in sorted(targets, key=lambda p: len(p.parts)):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    return sorted(targets.values())


# ---------------------------------------------------------------- 8. compileall


def compile_tree(python: Path) -> None:
    run(
        [python, "-I", "-m", "compileall", "-q", "-j", "0", python.parent / "Lib"],
        cwd=python.parent,
    )


# ---------------------------------------------------------------- 6·9. 감사와 NOTICES


def audit_input(
    stage: Path, table: na.NativeTable, policy: la.Policy, models: Sequence[na.ModelEntry]
) -> na.NativeReport:
    """빌드 입력 감사: 제거 전 스테이징 트리. 금지 파일은 제거 목록에 있을 때만 허용하고, wheel·PBS
    제거 규칙은 반드시 무언가를 맞혀야 한다."""
    return na.audit_build_input(
        na.Layout.install(stage),
        table,
        policy,
        models=models,
        models_dir=stage / na.MODELS_IN_INSTALL,
        origins=na.ORIGINS,
    )


def workspace_names(repo: Path = REPO_ROOT) -> frozenset[NormalizedName]:
    names: set[NormalizedName] = set()
    for pyproject in (repo / "python").glob("*/pyproject.toml"):
        with pyproject.open("rb") as f:
            names.add(canonicalize_name(tomllib.load(f)["project"]["name"]))
    return frozenset(names)


@dataclass
class NoticesResult:
    notices: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    python_rows: list[tuple[str, str, str]] = field(default_factory=list)


def render_installer_notices(
    runtime: Sequence[la.RuntimeRequirement],
    marker_env: Mapping[str, str],
    scanned: Mapping[NormalizedName, la.ScannedPackage],
    policy: la.Policy,
    final: na.NativeReport,
    own: frozenset[NormalizedName],
) -> NoticesResult:
    """설치본 NOTICES: 서드파티 Python 패키지 절(스테이징 Python 스캔) + 최종 트리 감사의 절
    (네이티브 파일·패키지별 예외·LicenseRef·근거 원문·OCR 모델). 우리 패키지(워크스페이스 멤버)는
    감사의 기준 집합에 없으므로 서드파티 절에 싣지 않고 라이선스만 허용인지 본다 (Apache-2.0은
    licenses/LICENSE.txt, SDK의 MIT는 그 dist-info의 LICENSE)."""
    problems: list[str] = []
    others: dict[NormalizedName, la.ScannedPackage] = {}
    for name, pkg in scanned.items():
        if name not in own:
            others[name] = pkg
        elif not la.judge_package(name, pkg.license, policy).ok:
            problems.append(f"[우리 패키지 라이선스] {pkg.display_name}: {pkg.license!r}")
    result = la.audit(runtime, marker_env, others, [], policy, extra_notices=final.notice_sections)
    return NoticesResult(
        notices=result.notices,
        problems=[*problems, *result.problems],
        notes=result.notes,
        python_rows=result.python_rows,
    )


def audit_final(
    stage: Path,
    table: na.NativeTable,
    policy: la.Policy,
    models: Sequence[na.ModelEntry],
    *,
    uv: str,
    runtime_txt: Path,
    work: Path,
) -> tuple[na.NativeReport, NoticesResult]:
    final = na.audit_final_tree(
        stage, table, policy, models=models, installer_files=(INNO_UNINSTALLER,)
    )
    python = stage / PYTHON / "python.exe"
    scan = work / "py.json"
    lp.scan_python(uv, python, scan, cwd=work)
    notices = render_installer_notices(
        la.parse_runtime(runtime_txt.read_text(encoding="utf-8")),
        read_marker_env(python, work),
        la.parse_pip_licenses(json.loads(scan.read_text(encoding="utf-8"))),
        policy,
        final,
        workspace_names(),
    )
    return final, notices


# ---------------------------------------------------------------- 10. iscc


def find_iscc(explicit: Path | None = None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    if os.environ.get("ISCC"):
        candidates.append(Path(os.environ["ISCC"]))
    if found := shutil.which("iscc"):
        candidates.append(Path(found))
    for base in (
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"),
    ):
        candidates.append(Path(base) / "Inno Setup 6" / "ISCC.exe")
    for path in candidates:
        if path.is_file():
            return path
    raise BuildError("Inno Setup 6의 ISCC.exe가 없다 (winget install JRSoftware.InnoSetup)")


@dataclass(frozen=True)
class Variant:
    """설치 파일의 판. 테스트 판은 AppId·이름·기본 폴더·제거 등록 이름이 모두 제품과 달라 자동
    검사(무인 설치·제거)가 이 PC의 실제 설치를 건드리지 않는다."""

    key: str
    app_guid: str
    app_name: str
    dir_name: str
    file_prefix: str

    @property
    def uninstall_key(self) -> str:
        """HKCU 제거 등록 키 이름 (Inno Setup: `{AppId}_is1`)."""
        return f"{{{self.app_guid}}}_is1"

    def setup_name(self, version: str) -> str:
        return f"{self.file_prefix}-{version}"


PRODUCT: Final = Variant(
    "product", "8B1C6E52-3F0A-4D6B-9C1E-5A7F2D4B0E91", "Kookabug", "Kookabug", "kookabug-setup"
)
TEST: Final = Variant(
    "test",
    "5E0D7A3C-9B41-4F2E-8C6A-1D3B7E9F2A64",
    "Kookabug Test",
    "Kookabug-Test",
    "kookabug-setup-test",
)
VARIANTS: Final = {v.key: v for v in (PRODUCT, TEST)}


def setup_name(version: str, variant: Variant = PRODUCT) -> str:
    return variant.setup_name(version)


def run_iscc(iscc: Path, stage: Path, dist: Path, version: str, variant: Variant = PRODUCT) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    run(
        [
            iscc,
            "/Q",
            f"/DAppVersion={version}",
            f"/DFileVersion={file_version(version)}",
            f"/DStageDir={stage}",
            f"/DOutputDir={dist}",
            f"/DOutputBase={variant.setup_name(version)}",
            f"/DMaxRelPath={max_rel_path(stage)}",
            f"/DAppGuid={variant.app_guid}",
            f"/DAppName={variant.app_name}",
            f"/DDirName={variant.dir_name}",
            ISS,
        ],
        cwd=ISS.parent,
    )
    exe = dist / f"{variant.setup_name(version)}.exe"
    if not exe.is_file():
        raise BuildError(f"iscc가 {exe}를 만들지 않았다")
    return exe


# ---------------------------------------------------------------- 전체


def prepare_out(out: Path) -> None:
    """빌드 폴더를 비운다. 이 스크립트가 만든 폴더만 지운다."""
    if out.exists():
        if any(out.iterdir()) and not (out / OUT_MARKER).exists():
            raise BuildError(f"{out}가 비어 있지 않고 빌드 폴더 표시가 없다. 지우지 않는다")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / OUT_MARKER).write_text("", encoding="utf-8")


@dataclass
class BuildResult:
    stage: Path
    setups: dict[str, Path]
    """판 키(`product`·`test`) → 설치 파일."""
    summary: dict[str, Any]


def build(
    out: Path = DEFAULT_OUT,
    *,
    cache: Path = DEFAULT_CACHE,
    archive: Path | None = None,
    vc_redist: Path | None = None,
    models_dir: Path = MODELS_DIR,
    iscc: Path | None = None,
    variants: Sequence[str] = (PRODUCT.key,),
) -> BuildResult:
    """스테이징 트리 하나로 `variants`의 설치 파일을 만든다 (비면 iscc를 건너뛴다)."""
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise BuildError(f"알 수 없는 판: {unknown} ({', '.join(VARIANTS)} 중)")
    started = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, t0: float) -> None:
        timings[name] = round(time.perf_counter() - t0, 1)

    inputs = load_inputs()
    version = cli_version()
    table = na.load_native_table_file(NATIVE_TABLE)
    policy = la.load_policy_file(ALLOWLIST)
    models = na.load_model_table_file(MODELS_TABLE)
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv를 PATH에서 찾을 수 없다")
    iscc_exe = find_iscc(iscc) if variants else None
    check_uv_version(uv, inputs.uv_version)
    crt = vc_redist or find_vc_redist(inputs.vc_redist)

    prepare_out(out)
    stage, work = out / "stage", out / "work"
    stage.mkdir()
    work.mkdir()

    t0 = time.perf_counter()
    if archive is None:
        archive = fetch_python(inputs.python, cache)
    python = extract_python(archive, inputs.python, stage) / "python.exe"
    check_python_version(python, inputs.python)
    lap("python", t0)

    t0 = time.perf_counter()
    runtime = install_runtime(uv, python, work)
    launchers = relocate_launchers(stage)
    vc_files = copy_vc_runtime(crt, inputs.vc_redist, python.parent)
    copy_models(models_dir, models, stage / na.MODELS_IN_INSTALL)
    copy_examples(SAMPLE_GAME, stage / EXAMPLES)
    write_metadata(stage, version)
    lap("install", t0)

    t0 = time.perf_counter()
    report = audit_input(stage, table, policy, models)
    if report.problems:
        raise BuildError("빌드 입력 감사 실패:\n  " + "\n  ".join(report.problems))
    removed = strip_tree(stage, table)
    # PBS가 넣은 pip는 제거 뒤에야 빠지므로 설치 집합은 여기서 본다
    site = stage / na.SITE_PACKAGES_IN_INSTALL
    marker_env = read_marker_env(python, work)
    problems = check_runtime_set(site, runtime.runtime_txt, marker_env, runtime.wheels)
    if problems:
        raise BuildError("설치 집합이 감사 runtime.txt와 다르다:\n  " + "\n  ".join(problems))
    compile_tree(python)
    final, notices = audit_final(
        stage, table, policy, models, uv=uv, runtime_txt=runtime.runtime_txt, work=work
    )
    problems = [*final.problems, *notices.problems]
    if problems:
        raise BuildError("최종 트리 감사 실패:\n  " + "\n  ".join(problems))
    (stage / NOTICES).write_text(notices.notices, encoding="utf-8")
    lap("audit", t0)

    stage_bytes, stage_files = tree_size(stage)
    setups: dict[str, Path] = {}
    if iscc_exe is not None:
        for key in variants:
            t0 = time.perf_counter()
            setups[key] = run_iscc(iscc_exe, stage, out / "dist", version, VARIANTS[key])
            lap(f"iscc.{key}", t0)
    timings["total"] = round(time.perf_counter() - started, 1)
    summary: dict[str, Any] = {
        "version": version,
        "python": {"tag": inputs.python.tag, "version": inputs.python.version},
        "vc_redist": {"folder": str(crt), "files": vc_files},
        "launchers": launchers,
        "stage": {
            "path": str(stage),
            "bytes": stage_bytes,
            "files": stage_files,
            "max_rel_path": max_rel_path(stage),
        },
        "setups": {
            key: {"path": str(path), "bytes": path.stat().st_size} for key, path in setups.items()
        },
        "audit": {
            "native_files_input": len(report.files),
            "native_files_final": len(final.files),
            "native_entries": len(table.entries),
            "removed": removed,
            "input_notes": report.notes,
            "final_notes": final.notes,
            "python_packages": [list(r) for r in notices.python_rows],
        },
        "seconds": timings,
    }
    (out / "build.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return BuildResult(stage, setups, summary)


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="Kookabug 설치 파일 빌드")
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="빌드 폴더 (지우고 다시 만든다)"
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="PBS 받은 파일 캐시")
    parser.add_argument("--pbs-archive", type=Path, help="받아 둔 PBS tar.gz (해시는 똑같이 확인)")
    parser.add_argument("--vc-redist", type=Path, help="Microsoft.VC143.CRT 폴더 (기본: vswhere)")
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR, help="받아 둔 OCR 모델")
    parser.add_argument("--iscc", type=Path, help="ISCC.exe (기본: PATH·Inno Setup 6 설치 폴더)")
    parser.add_argument("--no-setup", action="store_true", help="스테이징까지만 (iscc 생략)")
    parser.add_argument(
        "--test-setup",
        action="store_true",
        help="테스트 전용 판(다른 AppId·이름·폴더)도 만든다 (무인 설치 검사용)",
    )
    args = parser.parse_args(argv)
    variants: tuple[str, ...] = () if args.no_setup else (PRODUCT.key,)
    if args.test_setup:
        variants += (TEST.key,)
    try:
        result = build(
            args.out.resolve(),
            cache=args.cache.resolve(),
            archive=args.pbs_archive,
            vc_redist=args.vc_redist,
            models_dir=args.models_dir,
            iscc=args.iscc,
            variants=variants,
        )
    except (BuildError, la.AuditInputError, lp.PipelineError) as exc:
        print(f"설치 파일 빌드 실패: {exc}", file=sys.stderr)
        return 1
    s = result.summary
    print(f"스테이징: {s['stage']['path']} ({s['stage']['bytes'] / 2**20:.1f} MiB)")
    for key, path in result.setups.items():
        print(f"설치 파일({key}): {path} ({s['setups'][key]['bytes'] / 2**20:.1f} MiB)")
    print(f"시간(초): {s['seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
