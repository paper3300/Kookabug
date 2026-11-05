"""설치 파일 빌드 (구현 계획 M1 2.12, M2 2.14).

    $env:PYTHONPATH = "tools"; uv run python -m installer.build [--out build/installer] [--no-setup]

`<out>/stage`는 M1 폴더 구조(CLI 쪽)다:

    python/                PBS + 런타임 wheel + 우리 wheel(compileall) + 앱 로컬 VC++ 런타임
    bin/kookabug.exe       실행기 (Python 경로가 ..\\python\\python.exe 상대 경로)
    ocr-models/            OCR 모델·라이선스 근거 원문 (models.toml 해시)
    examples/sample-game/  예제 게임(sample_game)·화면 PNG·장면 표(frames)·예제 워크스페이스
    licenses/              LICENSE.txt, ffmpeg-SOURCE.txt (THIRD_PARTY_NOTICES.txt는 최종 트리에)
    VERSION

`<out>/electron-<판>/win-unpacked`(`tree_root`, 판 = product·test)가 최종 설치 트리다: 스테이징
트리 + 데스크톱 앱(Kookabug.exe·KookabugTest.exe, resources/app.asar, Electron 배포물). 설치
파일은 감사한 이 트리 그대로를 NSIS로 묶는다.

단계
1. PBS: 캐시(`build/installer-cache`)에서 찾거나 받고, 크기·SHA256을 확인한 **그 바이트를** 푼다
2. 런타임: 라이선스 감사와 같은 `uv export`(`license_pipeline.export_runtime`, 해시 고정)의 서드파티
   wheel과 `uv build`로 만든 우리 wheel을 `--no-deps`·`--link-mode copy`로 설치한다(uv 캐시와 하드
   링크를 공유하면 뒤의 제거·RECORD 수정이 캐시를 건드린다). 설치된 집합 = runtime.txt + 우리 wheel.
   우리 패키지는 전부 들어간다 — daemon의 target 편집이 선택 설치로 쓰는 kookabug-platform 포함
3. 실행기: uv가 만든 `python/Scripts/*.exe`의 Python 경로 자원(`UV_PYTHON_PATH`)을 상대 경로로
   바꾸고(RECORD 해시도) `bin/kookabug.exe`를 만든다. uv 실행기는 상대 경로를 자기 폴더 기준으로
   푼다 — 설치 뒤 고치는 단계가 없고 설치 폴더를 옮겨도 돈다
4. VC++ 런타임을 python.exe 옆에 복사 (빌드 머신 Visual Studio의 VC\\Redist)
5. 모델·예제·라이선스·VERSION
6. 빌드 입력 감사 (네이티브 표·제거 목록 — PBS 규칙 포함, 모델 해시)
7. 제거 목록의 파일·폴더와 그 RECORD 줄을 지운다
8. compileall
9. 데스크톱 앱 배포 빌드(`build:release`, E2E 검사 훅 없음 확인) → 앱 폴더(배포 빌드 + package.json)
10. electron-builder `--dir`: 앱 폴더 + Electron + 스테이징 트리(extraFiles) → win-unpacked
    (스테이징 파일이 그대로 옮겨졌는지 대조, Electron 판이 고정판인지 확인)
11. 최종 트리 감사(Electron 네이티브 표·ffmpeg 고정 바이너리 예외 포함) + 메타데이터 감사(설치본
    Python을 pip-licenses로 스캔, JS prod 의존성·글꼴)
    → win-unpacked/licenses/THIRD_PARTY_NOTICES.txt
12. 판마다 electron-builder `--prepackaged win-unpacked`
    → `<out>/dist/kookabug-setup[-test]-<버전>.exe`. 요약은 `<out>/build.json`
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
import struct
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
# 예제 게임에서 설치본에 넣는 것 (테스트·도구·OCR 표본은 넣지 않는다)
EXAMPLE_PARTS: Final = ("README.md", "sample_game", "frames", "workspace")
EXAMPLE_IGNORE: Final = ("__pycache__", "runs", ".kookabug")
# ffmpeg.dll 고정 바이너리 예외의 대응 소스·패치·빌드 정보
# (license-allowlist.toml [[pinned_binary]] source)
FFMPEG_SOURCE: Final = TOOLS_DIR / "third_party_licenses" / "ffmpeg-SOURCE.txt"
FFMPEG_SOURCE_IN_INSTALL: Final = "licenses/ffmpeg-SOURCE.txt"
# 설치본에 반드시 있어야 하는 우리 패키지. daemon의 target 편집 메서드는 kookabug-platform을
# 의존성이 아니라 선택 설치로 쓴다(M2 T6) — 설치 파일은 반드시 넣는다
REQUIRED_PACKAGES: Final = (
    "kookabug-cli",
    "kookabug-core",
    "kookabug-daemon",
    "kookabug-mcp",
    "kookabug-nodes",
    "kookabug-platform",
    "kookabug-sdk",
)

# 데스크톱 앱 (M2)
DESKTOP_DIR: Final = REPO_ROOT / "apps" / "desktop"
DESKTOP_PACKAGE: Final = "@kookabug/desktop"
EB_CONFIG: Final = DESKTOP_DIR / "electron-builder.yml"
NSIS_INCLUDE: Final = DESKTOP_DIR / "packaging" / "installer.nsh"
# 제품 판 앱 실행 파일 (electron-builder.yml executableName, 테스트 판은 Variant.app_exe).
# apps/desktop/src/main/cli-locate.ts의 PACKAGED_CLI는 이 파일 옆의 bin/kookabug.exe다
APP_EXE: Final = "Kookabug.exe"
APP_ASAR: Final = "resources/app.asar"
# NSIS가 설치 때 설치 폴더에 더하는 제품 판 제거 프로그램 (win-unpacked에는 없다).
# 이름은 "Uninstall <executableName>.exe" (Variant.uninstaller)
UNINSTALLER: Final = "Uninstall Kookabug.exe"
# 확정 앱 아이콘 A1 (electron-builder.yml win.icon). 실행 파일·설치 파일에 이 이미지들이
# 들어가야 한다
APP_ICON: Final = REPO_ROOT / "Docs" / "Design" / "앱 아이콘 (L3)" / "확정 A1" / "kookabug.ico"
# Electron 고정판 배포물 (apps/desktop devDependencies electron)
ELECTRON_DIST: Final = DESKTOP_DIR / "node_modules" / "electron" / "dist"
# Electron 배포물에서 배포하지 않는 것: 기본 앱(default_app.asar)과 판 파일(version).
# electron-builder는 사용자 지정 배포물(electronDist)을 통째로 복사하므로 미리 뺀 사본을 준다
# (prepare_electron_dist)
ELECTRON_LEFTOVERS: Final = ("resources/default_app.asar", "version")
# 앱 폴더에 넣는 배포 빌드 (dist 기준). 소스 맵·번들 메타는 넣지 않는다
APP_DIST_PARTS: Final = ("main/main.cjs", "preload/preload.cjs", "renderer")
APP_DIST_IGNORE: Final = ("*.map",)
# 배포 빌드에 있으면 안 되는 E2E 검사 전용 훅의 글귀 (apps/desktop/src/main/e2e-hooks.ts, T11·T12)
E2E_HOOK_MARKERS: Final = (
    "__kookabugE2E",
    "KOOKABUG_E2E_HOOKS",
    "dropDaemonConnection",
    "delayResponses",
    "ResponseDelays",
)


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
    shutil.copy2(FFMPEG_SOURCE, stage / FFMPEG_SOURCE_IN_INSTALL)
    (stage / VERSION_FILE).write_text(version + "\n", encoding="utf-8")


def check_required_packages(site: Path) -> list[str]:
    got = installed_set(site)
    return [
        f"[우리 패키지 없음] {name}"
        for name in REQUIRED_PACKAGES
        if canonicalize_name(name) not in got
    ]


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
    js_rows: list[tuple[str, str, str]] = field(default_factory=list)


def render_installer_notices(
    runtime: Sequence[la.RuntimeRequirement],
    marker_env: Mapping[str, str],
    scanned: Mapping[NormalizedName, la.ScannedPackage],
    policy: la.Policy,
    final: na.NativeReport,
    own: frozenset[NormalizedName],
    js: Sequence[la.ScannedPackage] = (),
) -> NoticesResult:
    """설치본 NOTICES: 서드파티 Python 패키지 절(설치본 Python 스캔) + JavaScript 절(앱 번들에 든
    prod 의존성·글꼴) + 최종 트리 감사의 절(네이티브 파일·패키지별 예외·고정 바이너리 예외·
    LicenseRef·근거 원문·OCR 모델). 우리 패키지(워크스페이스 멤버)는 감사의 기준 집합에 없으므로
    서드파티 절에 싣지 않고 라이선스만 허용인지 본다 (Apache-2.0은 licenses/LICENSE.txt, SDK의
    MIT는 그 dist-info의 LICENSE)."""
    problems: list[str] = []
    others: dict[NormalizedName, la.ScannedPackage] = {}
    for name, pkg in scanned.items():
        if name not in own:
            others[name] = pkg
        elif not la.judge_package(name, pkg.license, policy).ok:
            problems.append(f"[우리 패키지 라이선스] {pkg.display_name}: {pkg.license!r}")
    result = la.audit(runtime, marker_env, others, js, policy, extra_notices=final.notice_sections)
    return NoticesResult(
        notices=result.notices,
        problems=[*problems, *result.problems],
        notes=result.notes,
        python_rows=result.python_rows,
        js_rows=result.js_rows,
    )


def scan_desktop_js(pnpm: str) -> list[la.ScannedPackage]:
    """앱 번들에 든 JS prod 의존성 (`pnpm licenses list --prod`, apps/desktop)."""
    out = run([pnpm, "licenses", "list", "--prod", "--json"], cwd=DESKTOP_DIR, capture=True)
    if out.strip() == lp.PNPM_EMPTY_OUTPUT:
        return []
    try:
        return la.parse_pnpm_licenses(json.loads(out))
    except ValueError as exc:
        raise BuildError(f"pnpm licenses 출력이 JSON이 아니다: {out[:200]!r}") from exc


def audit_final(
    root: Path,
    table: na.NativeTable,
    policy: la.Policy,
    models: Sequence[na.ModelEntry],
    *,
    uv: str,
    runtime_txt: Path,
    work: Path,
    js: Sequence[la.ScannedPackage] = (),
    uninstaller: str = UNINSTALLER,
) -> tuple[na.NativeReport, NoticesResult]:
    final = na.audit_final_tree(root, table, policy, models=models, installer_files=(uninstaller,))
    python = root / PYTHON / "python.exe"
    scan = work / "py.json"
    lp.scan_python(uv, python, scan, cwd=work)
    notices = render_installer_notices(
        la.parse_runtime(runtime_txt.read_text(encoding="utf-8")),
        read_marker_env(python, work),
        la.parse_pip_licenses(json.loads(scan.read_text(encoding="utf-8"))),
        policy,
        final,
        workspace_names(),
        js,
    )
    return final, notices


# ---------------------------------------------------------------- 9. 데스크톱 앱


def semver(version: str) -> str:
    """PEP 440 판 → electron-builder(semver) 판: `0.1.0.dev0` → `0.1.0-dev.0`, `1.2.0` → `1.2.0`."""
    v = Version(version)
    core = ".".join(str(n) for n in (*v.release, 0, 0)[:3])
    if v.dev is not None:
        return f"{core}-dev.{v.dev}"
    if v.pre is not None:
        label = {"a": "alpha", "b": "beta", "rc": "rc"}[v.pre[0]]
        return f"{core}-{label}.{v.pre[1]}"
    return core


def pinned_electron() -> str:
    """apps/desktop/package.json에 고정한 Electron 판."""
    data = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))
    return str(data["devDependencies"]["electron"])


def build_desktop(pnpm: str) -> None:
    """데스크톱 앱 배포 빌드 (`build.mjs --release`: E2E 검사 전용 훅이 번들에서 빠진다)."""
    run([pnpm, "--filter", DESKTOP_PACKAGE, "run", "build:release"], cwd=REPO_ROOT)


def e2e_hook_markers(files: Mapping[str, bytes]) -> list[str]:
    """배포 번들에 남은 E2E 검사 전용 훅 글귀 (`경로: 글귀`). 비어 있어야 한다."""
    return [
        f"{name}: {marker}"
        for name, data in sorted(files.items())
        if name.endswith((".cjs", ".js", ".mjs"))
        for marker in E2E_HOOK_MARKERS
        if marker.encode("utf-8") in data
    ]


def read_asar(path: Path) -> dict[str, bytes]:
    """Electron asar 묶음의 파일 (경로 posix → 바이트). 형식: [u32 4][u32 머리 크기][u32 내용 크기]
    [u32 JSON 길이][JSON 머리 {"files": ...}] 뒤에 파일 바이트가 이어진다. 묶음 밖(unpacked) 파일은
    `<묶음>.unpacked/`에서 읽고 링크는 건너뛴다."""
    data = path.read_bytes()
    try:
        header_size = struct.unpack_from("<I", data, 4)[0]
        json_len = struct.unpack_from("<I", data, 12)[0]
        header = json.loads(data[16 : 16 + json_len].decode("utf-8"))
    except (struct.error, ValueError) as exc:
        raise BuildError(f"{path}: asar 머리를 읽을 수 없다 ({exc})") from exc
    base = 8 + header_size
    out: dict[str, bytes] = {}

    def walk(node: Mapping[str, Any], prefix: str) -> None:
        for name, item in node.get("files", {}).items():
            rel = f"{prefix}{name}"
            if "files" in item:
                walk(item, rel + "/")
            elif item.get("unpacked"):
                out[rel] = (path.parent / f"{path.name}.unpacked" / rel).read_bytes()
            elif "offset" in item:
                start = base + int(item["offset"])
                out[rel] = data[start : start + int(item["size"])]

    walk(header, "")
    return out


def icon_images(path: Path = APP_ICON) -> list[tuple[int, bytes]]:
    """ICO 파일의 (가로 픽셀, 이미지 바이트) 목록."""
    ico = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    if (reserved, kind) != (0, 1) or count == 0:
        raise BuildError(f"{path}가 ICO가 아니다")
    out: list[tuple[int, bytes]] = []
    for i in range(count):
        width, _, _, _, _, _, size, offset = struct.unpack_from("<BBBBHHII", ico, 6 + i * 16)
        out.append((width or 256, ico[offset : offset + size]))
    return out


def missing_icon_images(exe: Path, icon: Path = APP_ICON) -> list[int]:
    """`exe` 자원에 들어 있지 않은 확정 아이콘 이미지의 크기들 (비어 있어야 한다)."""
    data = exe.read_bytes()
    return [width for width, image in icon_images(icon) if image not in data]


def prepare_app_dir(
    dist: Path, app: Path, version: str, product_name: str = "Kookabug"
) -> list[str]:
    """electron-builder 앱 폴더: 배포 빌드(소스 맵 제외) + package.json(의존성 없음). 번들에 E2E
    검사 훅이 남아 있으면 멈춘다. `product_name`은 앱 이름(사용자 데이터 폴더 이름)이라 판마다
    다르다. 넣은 파일 목록(앱 폴더 기준)."""
    if app.exists():
        shutil.rmtree(app)
    for part in APP_DIST_PARTS:
        src = dist / part
        if not src.exists():
            raise BuildError(f"{src}가 없다 (데스크톱 앱 배포 빌드 확인)")
        dest = app / "dist" / part
        if src.is_dir():
            shutil.copytree(src, dest, ignore=shutil.ignore_patterns(*APP_DIST_IGNORE))
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    package = {
        "name": "kookabug",
        "productName": product_name,
        "version": semver(version),
        "description": "Kookabug",
        "main": "dist/main/main.cjs",
        "license": "Apache-2.0",
        "author": "Kookabug contributors",
    }
    (app / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    files = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    left = e2e_hook_markers(files)
    if left:
        raise BuildError("배포 번들에 E2E 검사 훅이 남아 있다:\n  " + "\n  ".join(left))
    return sorted(files)


# ---------------------------------------------------------------- 10·12. electron-builder


@dataclass(frozen=True)
class Variant:
    """설치 파일의 판. 테스트 판은 appId·이름·GUID(제거 등록 키)·기본 폴더·실행 파일 이름이 모두
    제품과 달라 자동 검사(무인 설치·제거)가 이 PC의 실제 설치와 실행 중인 제품 앱을 건드리지
    않는다."""

    key: str
    app_guid: str
    app_name: str
    app_id: str
    file_prefix: str
    # 실행 파일 이름 (확장자 없음, electron-builder executableName)
    exe_name: str

    @property
    def app_exe(self) -> str:
        return f"{self.exe_name}.exe"

    @property
    def uninstaller(self) -> str:
        """NSIS 제거 프로그램 파일 이름 (설치 폴더 맨 위)."""
        return f"Uninstall {self.exe_name}.exe"

    @property
    def dir_name(self) -> str:
        """기본 설치 폴더 이름 (`%LOCALAPPDATA%\\Programs\\<이름>`, installer.nsh APP_FILENAME)."""
        return self.app_name

    @property
    def uninstall_key(self) -> str:
        """HKCU 제거 등록 키 이름 (`...\\Uninstall\\<GUID>`, electron-builder nsis.guid)."""
        return self.app_guid

    @property
    def install_key(self) -> str:
        """HKCU 설치 정보 키 (`Software\\<GUID>`: InstallLocation·바로 가기 이름)."""
        return rf"Software\{self.app_guid}"

    @property
    def shortcut(self) -> str:
        """시작 메뉴 바로 가기 파일 이름."""
        return f"{self.app_name}.lnk"

    @property
    def updater_dir(self) -> str:
        """기본 스크립트가 설치 파일 사본을 두는 %LOCALAPPDATA% 아래 폴더.
        installer.nsh가 설치 끝에 지운다."""
        return f"{self.app_name}-updater"

    def setup_name(self, version: str) -> str:
        return f"{self.file_prefix}-{version}"


PRODUCT: Final = Variant(
    "product",
    "8B1C6E52-3F0A-4D6B-9C1E-5A7F2D4B0E91",
    "Kookabug",
    "org.kookabug.desktop",
    "kookabug-setup",
    "Kookabug",
)
TEST: Final = Variant(
    "test",
    "5E0D7A3C-9B41-4F2E-8C6A-1D3B7E9F2A64",
    "Kookabug Test",
    "org.kookabug.desktop.test",
    "kookabug-setup-test",
    "KookabugTest",
)
VARIANTS: Final = {v.key: v for v in (PRODUCT, TEST)}


def tree_root(out: Path, variant: Variant) -> Path:
    """판의 최종 설치 트리 위치 (CI artifact·README가 이 경로를 쓴다)."""
    return out / f"electron-{variant.key}" / "win-unpacked"


def ci_artifacts(out: Path = DEFAULT_OUT) -> list[Path]:
    """CI installer 잡이 반드시 올리는 파일 (제품 판 설치 파일·요약·스모크 결과·제품 판 NOTICES)."""
    version = cli_version()
    return [
        out / "dist" / f"{PRODUCT.setup_name(version)}.exe",
        out / "build.json",
        out / "smoke.json",
        tree_root(out, PRODUCT) / NOTICES,
    ]


def variant_of_tree(root: Path) -> Variant:
    """설치 트리의 판 (맨 위 앱 실행 파일 이름으로). 모르면 제품 판."""
    for variant in VARIANTS.values():
        if (root / variant.app_exe).is_file():
            return variant
    return PRODUCT


def setup_name(version: str, variant: Variant = PRODUCT) -> str:
    return variant.setup_name(version)


def find_pnpm(explicit: Path | None = None) -> str:
    for candidate in (explicit, os.environ.get("PNPM"), shutil.which("pnpm")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise BuildError("pnpm을 찾을 수 없다 (Node 24·pnpm 필요)")


def eb_env() -> dict[str, str]:
    env = clean_env()
    # 서명은 보류(H5): 인증서를 찾지 않는다. 하드 링크로 복사하지 않는다(뒤에서 트리를 고친다)
    env["CSC_IDENTITY_AUTO_DISCOVERY"] = "false"
    env["USE_HARD_LINKS"] = "false"
    return env


def run_eb(pnpm: str, config: Mapping[str, Any], work: Path, name: str, *args: str) -> None:
    """`electron-builder --config <work>/<name>.json ...` (apps/desktop에서). 설정은 기본 설정
    파일을 extends 한다."""
    cfg = work / f"{name}.json"
    cfg.write_text(
        json.dumps({"extends": str(EB_CONFIG), **config}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    cmd = [pnpm, "exec", "electron-builder", "--config", str(cfg), "--win", *args]
    print("$ " + " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=DESKTOP_DIR,
        env=eb_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    (work / f"{name}.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise BuildError(
            f"electron-builder 실패 (종료 코드 {proc.returncode}, 로그 {work / name}.log):\n"
            + (proc.stdout + proc.stderr)[-4000:]
        )


def prepare_electron_dist(dest: Path, source: Path = ELECTRON_DIST) -> list[str]:
    """electron-builder에 줄 Electron 배포물: 고정판 배포물에서 배포하지 않는 것
    (ELECTRON_LEFTOVERS)을 뺀 사본. `version`은 스테이징의 `VERSION`과 대소문자만 달라
    Windows에서 같은 파일이 된다 — electron-builder가 Electron 배포물을 먼저 복사하고
    extraFiles가 덮어써 이름이 `version`으로 남는다. 같은 볼륨이면 하드 링크(electron-builder는
    USE_HARD_LINKS=false로 다시 복사한다). 넣은 파일 목록."""
    if not (source / "electron.exe").is_file():
        raise BuildError(f"{source}에 Electron 배포물이 없다 (pnpm install 확인)")
    if dest.exists():
        shutil.rmtree(dest)
    skip = {rel.casefold() for rel in ELECTRON_LEFTOVERS}
    files: list[str] = []
    for src in sorted(source.rglob("*")):
        rel = src.relative_to(source).as_posix()
        if not src.is_file() or rel.casefold() in skip:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, target)
        except OSError:
            shutil.copy2(src, target)
        files.append(rel)
    return files


def variant_config(variant: Variant) -> dict[str, Any]:
    """판마다 다른 electron-builder 설정 (appId·이름·실행 파일 이름)."""
    return {
        "appId": variant.app_id,
        "productName": variant.app_name,
        "executableName": variant.exe_name,
    }


def package_dir(
    pnpm: str,
    app: Path,
    stage: Path,
    out: Path,
    work: Path,
    electron_dist: Path,
    variant: Variant,
) -> Path:
    """electron-builder `--dir`: 앱 폴더 + Electron + 스테이징 트리 → `<out>/win-unpacked`.
    실행 파일 이름·버전 정보·아이콘이 판마다 다르므로 판마다 만든다."""
    config = {
        **variant_config(variant),
        "electronDist": str(electron_dist),
        "electronVersion": pinned_electron(),
        "directories": {"app": str(app), "output": str(out)},
        "extraFiles": [{"from": str(stage), "to": ".", "filter": ["**/*"]}],
    }
    run_eb(pnpm, config, work, f"eb-dir-{variant.key}", "--dir")
    root = out / "win-unpacked"
    if not (root / variant.app_exe).is_file():
        raise BuildError(f"electron-builder가 {root / variant.app_exe}를 만들지 않았다")
    return root


def tree_files(root: Path) -> dict[str, int]:
    """상대 경로(posix) → 크기."""
    return {
        p.relative_to(root).as_posix(): p.stat().st_size for p in root.rglob("*") if p.is_file()
    }


def compare_stage(stage: Path, root: Path) -> list[str]:
    """스테이징 트리의 파일이 최종 트리에 같은 크기로 다 있는가.
    extraFiles 복사가 파일을 빠뜨리거나 바꾸지 않았는지 본다."""
    want, got = tree_files(stage), tree_files(root)
    problems = [f"[스테이징 파일 없음] {rel}" for rel in sorted(want) if rel not in got]
    problems += [
        f"[스테이징 파일 크기 다름] {rel}: {size} → {got[rel]}"
        for rel, size in sorted(want.items())
        if rel in got and got[rel] != size
    ]
    return problems


def check_layout(root: Path, app_exe: str = APP_EXE) -> list[str]:
    """최종 트리의 맨 위 구조: M1 폴더(CLI 쪽) + 데스크톱 앱."""
    need = [
        f"{PYTHON}/python.exe",
        f"{BIN}/{LAUNCHER}",
        na.MODELS_IN_INSTALL,
        EXAMPLES,
        f"{LICENSES}/LICENSE.txt",
        FFMPEG_SOURCE_IN_INSTALL,
        VERSION_FILE,
        app_exe,
        APP_ASAR,
    ]
    problems = [f"[설치 트리 구조] {rel}가 없다" for rel in need if not (root / rel).exists()]
    names = {p.relative_to(root).as_posix() for p in root.rglob("*")}
    # Windows는 대소문자를 가리지 않으므로 실제 이름으로 본다 (version ↔ VERSION)
    problems += [f"[설치 트리 구조] {rel}가 남았다" for rel in ELECTRON_LEFTOVERS if rel in names]
    if (root / VERSION_FILE).exists() and VERSION_FILE not in names:
        problems.append(f"[설치 트리 구조] {VERSION_FILE}의 이름이 다르다")
    return problems


def check_electron_version(root: Path) -> str:
    """배포되는 실행 파일의 Electron 판 = 고정판 (고정 바이너리 예외가 이 판을 본다)."""
    found = na.electron_version(root)
    want = pinned_electron()
    if found is None or found != want:
        raise BuildError(f"{root}의 앱 실행 파일 Electron 판이 {found}다 (고정 {want})")
    return found


PAGE_MARKERS: Final = ("installer: no install mode page", "uninstaller: no install mode page")
"""설치·제거 프로그램 컴파일이 설치 범위 화면 대신 빈 매크로를 거쳤다는 표식
(no-install-mode-page.nsh)."""


def nsis_header(root: Path, include: Path = NSIS_INCLUDE, marker: Path | None = None) -> str:
    """판마다 만드는 NSIS 머리 파일: installer.nsh가 쓰는 값.
    가장 긴 상대 경로(KB_MAX_REL_PATH)와 제거할 맨 위 항목(kbRemoveTree), 페이지 표식 파일
    (KB_PAGE_MARKER, `check_page_markers`)."""
    lines = ["; tools/installer/build.py가 만든다. 직접 고치지 않는다"]
    if marker is not None:
        if any(c in str(marker) for c in '"$`'):
            raise BuildError(f"NSIS 스크립트에 넣을 수 없는 경로: {marker}")
        lines.append(f'!define KB_PAGE_MARKER "{marker}"')
    lines += [
        f"!define KB_MAX_REL_PATH {max_rel_path(root)}",
        "!macro kbRemoveTree",
    ]
    for item in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if any(c in item.name for c in '"$`'):
            raise BuildError(f"NSIS 스크립트에 넣을 수 없는 이름: {item.name!r}")
        if item.is_dir():
            lines.append(f'  RMDir /r "$INSTDIR\\{item.name}"')
        else:
            lines.append(f'  Delete "$INSTDIR\\{item.name}"')
    lines += ["!macroend", f'!include "{include}"', ""]
    return "\n".join(lines)


def check_page_markers(marker: Path) -> list[str]:
    """설치·제거 프로그램 컴파일이 모두 설치 범위 화면 매크로를 빈 것으로 바꿔 거쳤나 (M2 사람
    확인 S3 결함). 기본 스크립트가 바뀌어 그 훅을 안 거치면 화면이 다시 들어갈 수 있다 — 빌드를
    멈춘다."""
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    return [
        f"[설치 범위 화면] NSIS 컴파일에 '{want}' 표식이 없다 ({marker}) — "
        "installer.nsh의 customWelcomePage·customUnWelcomePage 훅을 확인한다"
        for want in PAGE_MARKERS
        if lines.count(want) != 1
    ]


def build_setup(
    pnpm: str, root: Path, app: Path, out: Path, work: Path, version: str, variant: Variant
) -> Path:
    """감사한 트리(`root`) 그대로 NSIS 설치 파일을 만든다 (`--prepackaged`)."""
    header = work / f"nsis-{variant.key}.nsh"
    marker = work / f"nsis-{variant.key}-pages.txt"
    marker.unlink(missing_ok=True)
    header.write_text(nsis_header(root, marker=marker), encoding="utf-8")
    target = out / f"nsis-{variant.key}"
    if target.exists():
        shutil.rmtree(target)
    config = {
        **variant_config(variant),
        "directories": {"app": str(app), "output": str(target)},
        "nsis": {
            "guid": variant.app_guid,
            "artifactName": f"{variant.setup_name(version)}.${{ext}}",
            "include": str(header),
        },
    }
    run_eb(pnpm, config, work, f"eb-nsis-{variant.key}", "nsis", "--prepackaged", str(root))
    problems = check_page_markers(marker)
    if problems:
        raise BuildError("\n".join(problems))
    built = target / f"{variant.setup_name(version)}.exe"
    if not built.is_file():
        raise BuildError(f"electron-builder가 {built}를 만들지 않았다")
    dist = out / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    exe = dist / built.name
    shutil.move(built, exe)
    shutil.rmtree(target, ignore_errors=True)
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
class TreeResult:
    """판 하나의 최종 설치 트리 (electron-builder win-unpacked).
    감사한 그대로 설치 파일에 들어간다."""

    variant: Variant
    root: Path
    app: Path
    final: na.NativeReport
    notices: NoticesResult
    app_files: list[str]


@dataclass
class BuildResult:
    stage: Path
    trees: dict[str, TreeResult]
    """판 키 → 최종 설치 트리. 실행 파일 이름·버전 정보가 판마다 달라 판마다 만든다."""
    setups: dict[str, Path]
    """판 키(`product`·`test`) → 설치 파일."""
    summary: dict[str, Any]

    @property
    def root(self) -> Path:
        """첫 판(제품 판이 있으면 제품 판)의 최종 설치 트리."""
        return next(iter(self.trees.values())).root


def build_tree(
    variant: Variant,
    *,
    pnpm: str,
    stage: Path,
    out: Path,
    work: Path,
    electron_dist: Path,
    version: str,
    table: na.NativeTable,
    policy: la.Policy,
    models: Sequence[na.ModelEntry],
    uv: str,
    runtime_txt: Path,
    js: Sequence[la.ScannedPackage],
) -> TreeResult:
    """판 하나: 앱 폴더 → `--dir` → 구성·Electron 판·아이콘 확인 → 최종 트리 감사 → NOTICES."""
    app = out / f"app-{variant.key}"
    app_files = prepare_app_dir(DESKTOP_DIR / "dist", app, version, variant.app_name)
    root = package_dir(
        pnpm, app, stage, tree_root(out, variant).parent, work, electron_dist, variant
    )
    if root != tree_root(out, variant):
        raise BuildError(f"electron-builder 출력이 {tree_root(out, variant)}가 아니다: {root}")
    problems = [*compare_stage(stage, root), *check_layout(root, variant.app_exe)]
    missing = missing_icon_images(root / variant.app_exe)
    if missing:
        problems.append(f"[앱 아이콘] {variant.app_exe}에 확정 아이콘 이미지 {missing}가 없다")
    if problems:
        raise BuildError("최종 설치 트리 구성이 틀렸다:\n  " + "\n  ".join(problems))
    check_electron_version(root)
    final, notices = audit_final(
        root,
        table,
        policy,
        models,
        uv=uv,
        runtime_txt=runtime_txt,
        work=work,
        js=js,
        uninstaller=variant.uninstaller,
    )
    problems = [*final.problems, *notices.problems]
    if problems:
        raise BuildError(f"최종 트리 감사 실패({variant.key}):\n  " + "\n  ".join(problems))
    (root / NOTICES).write_text(notices.notices, encoding="utf-8")
    return TreeResult(variant, root, app, final, notices, app_files)


def build(
    out: Path = DEFAULT_OUT,
    *,
    cache: Path = DEFAULT_CACHE,
    archive: Path | None = None,
    vc_redist: Path | None = None,
    models_dir: Path = MODELS_DIR,
    pnpm: Path | None = None,
    variants: Sequence[str] = (PRODUCT.key,),
) -> BuildResult:
    """스테이징 트리 하나로 판마다 최종 설치 트리를 만들어 감사하고 `variants`의 설치 파일을 만든다
    (비면 제품 판 트리와 감사까지만)."""
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
    pnpm_exe = find_pnpm(pnpm)
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
    problems += check_required_packages(site)
    if problems:
        raise BuildError("설치 집합이 감사 runtime.txt와 다르다:\n  " + "\n  ".join(problems))
    compile_tree(python)
    lap("stage", t0)

    t0 = time.perf_counter()
    build_desktop(pnpm_exe)
    electron_dist = out / "electron-dist"
    prepare_electron_dist(electron_dist)
    js = scan_desktop_js(pnpm_exe)
    lap("desktop", t0)

    trees: dict[str, TreeResult] = {}
    setups: dict[str, Path] = {}
    for key in variants or (PRODUCT.key,):
        variant = VARIANTS[key]
        t0 = time.perf_counter()
        tree = build_tree(
            variant,
            pnpm=pnpm_exe,
            stage=stage,
            out=out,
            work=work,
            electron_dist=electron_dist,
            version=version,
            table=table,
            policy=policy,
            models=models,
            uv=uv,
            runtime_txt=runtime.runtime_txt,
            js=js,
        )
        trees[key] = tree
        lap(f"tree.{key}", t0)
        if key in variants:
            t0 = time.perf_counter()
            setups[key] = build_setup(pnpm_exe, tree.root, tree.app, out, work, version, variant)
            missing = missing_icon_images(setups[key])
            if missing:
                raise BuildError(f"{setups[key].name}에 확정 아이콘 이미지 {missing}가 없다")
            lap(f"nsis.{key}", t0)

    stage_bytes, stage_files = tree_size(stage)
    first = next(iter(trees.values()))
    timings["total"] = round(time.perf_counter() - started, 1)

    def tree_json(tree: TreeResult) -> dict[str, Any]:
        size, files = tree_size(tree.root)
        return {
            "path": str(tree.root),
            "app_exe": tree.variant.app_exe,
            "bytes": size,
            "files": files,
            "max_rel_path": max_rel_path(tree.root),
        }

    summary: dict[str, Any] = {
        "version": version,
        "app_version": semver(version),
        "electron": pinned_electron(),
        "python": {"tag": inputs.python.tag, "version": inputs.python.version},
        "vc_redist": {"folder": str(crt), "files": vc_files},
        "launchers": launchers,
        "app_files": first.app_files,
        "stage": {"path": str(stage), "bytes": stage_bytes, "files": stage_files},
        "tree": tree_json(first),
        "trees": {key: tree_json(tree) for key, tree in trees.items()},
        "setups": {
            key: {"path": str(path), "bytes": path.stat().st_size} for key, path in setups.items()
        },
        "audit": {
            "native_files_input": len(report.files),
            "native_files_final": len(first.final.files),
            "native_entries": len(table.entries),
            "pinned": [f"{nf.rel} ({pin.package} {pin.version})" for nf, pin in first.final.pinned],
            "removed": removed,
            "input_notes": report.notes,
            "final_notes": first.final.notes,
            "python_packages": [list(r) for r in first.notices.python_rows],
            "js_packages": [list(r) for r in first.notices.js_rows],
        },
        "seconds": timings,
    }
    (out / "build.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return BuildResult(stage, trees, setups, summary)


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
    parser.add_argument("--pnpm", type=Path, help="pnpm (기본: PATH)")
    parser.add_argument(
        "--no-setup", action="store_true", help="최종 설치 트리와 감사까지만 (NSIS 생략)"
    )
    parser.add_argument(
        "--test-setup",
        action="store_true",
        help="테스트 전용 판(다른 appId·이름·GUID·폴더)도 만든다 (무인 설치 검사용)",
    )
    parser.add_argument(
        "--check-artifacts",
        action="store_true",
        help="빌드하지 않고 CI 필수 artifact(ci_artifacts)가 --out 아래에 다 있는지만 본다",
    )
    args = parser.parse_args(argv)
    if args.check_artifacts:
        missing = [p for p in ci_artifacts(args.out.resolve()) if not p.is_file()]
        for path in ci_artifacts(args.out.resolve()):
            print(f"{'없음' if path in missing else '있음'}: {path}")
        return 1 if missing else 0
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
            pnpm=args.pnpm,
            variants=variants,
        )
    except (BuildError, la.AuditInputError, lp.PipelineError) as exc:
        print(f"설치 파일 빌드 실패: {exc}", file=sys.stderr)
        return 1
    s = result.summary
    print(f"최종 설치 트리: {s['tree']['path']} ({s['tree']['bytes'] / 2**20:.1f} MiB)")
    for key, path in result.setups.items():
        print(f"설치 파일({key}): {path} ({s['setups'][key]['bytes'] / 2**20:.1f} MiB)")
    print(f"시간(초): {s['seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
