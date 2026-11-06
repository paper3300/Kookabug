"""설치 파일 무인 설치·최종 트리 감사·스모크·제거 (구현 계획 M1 2.12, M2 2.14).

    $env:PYTHONPATH = "tools"
    uv run python -m installer.smoke --setup build/installer/dist/kookabug-setup-test-<버전>.exe `
        [--dir "<임시>\\설치 폴더 공백 한글"] [--json build/installer/smoke.json] [--keep]

0. 판 확인: 기본은 **테스트 전용 판**(`build.TEST`: 제품과 다른 appId·이름·GUID·기본 폴더)만
   설치한다. 설치 파일 버전 정보의 ProductName으로 가리고, 그 판의 제거 등록이 이미 있으면 멈춘다
1. 무인 설치: NSIS `/S /currentuser /D=<폴더>`. 설치 흔적(HKCU 제거 등록 전체·`Software\\<GUID>`·
   시작 메뉴 바로 가기·설치 파일 사본 폴더·사용자 PATH)을 앞뒤로 찍는다. 제거 등록에는 그 판의
   GUID 키 하나만 새로 생기고 다른 키는 그대로다
2. 최종 트리 감사 (`native_audit.audit_final_tree`, 모델 해시·Electron 네이티브 표·ffmpeg 고정
   바이너리 예외 포함), NOTICES 절, 앱 번들 검사(E2E 검사 훅 없음, kookabug-platform 포함)
3. Python 없는 환경 흉내: PATH = 설치 `bin` + Windows 폴더만, `PYTHONHOME`·`PYTHONPATH`·
   `VIRTUAL_ENV`·`KOOKABUG_OCR_MODELS` 등 삭제. 그 PATH에서 python·uv를 찾을 수 없어야 한다
4. `kookabug --version`(VERSION 파일과 같음), `kookabug doctor --profile headless --json`(전부 통과,
   설치본 Python·설치 폴더 VC++ 런타임), 예제 헤드리스 스모크 그래프 `kookabug run`(통과),
   영상(M3: 예제 사본을 영상 `on`으로 돌려 OS Media Foundation H.264 조각이 남음. 인코더가 없는
   PC면 `unavailable`과 이유 — 실행은 그대로 통과), 녹화기(M4: 훅 프로세스가 설치 트리 Python으로
   떠 `hook.hello`까지, 입력 없이), MCP(M5: 예제 사본에 설치본 daemon을 띄우고 `kookabug mcp
   --unattended --agent-id <ID>` → initialize·tools/list(기본 core만)·`kb_project_info`가 그 주체를
   사람 없음으로 돌려줌, `kookabug agent-host --help`)
5. 앱 스모크: 예제 워크스페이스 사본으로 `Kookabug.exe --smoke` (daemon 띄우기·session.hello·
   graph.open·graph.save 무수정 wrote: false·daemon.shutdown, 종료 코드 0). 끝난 뒤 설치 폴더에서
   돌던 프로세스(daemon)가 남지 않는다
6. DLL 의존성 검사 (`dllcheck`)
7. 제거 (`--keep`이 없으면): 제거 프로그램 → 설치 폴더 없음, 설치 흔적이 처음과 똑같음 (테스트
   흔적 없음, 다른 등록 손실 없음)

단계마다 `{id, ok, detail}`. 종료 코드 0 = 전부 통과, 1 = 실패.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import license_audit as la
import native_audit as na
from installer import build, dllcheck, shelllink
from kookabug_sdk.console import utf8_stdio

SMOKE_GRAPH: Final = "tests/smoke_headless.graph.json"
FAKE_PLATFORM: Final = "fake-platform.json"
WORKSPACE: Final = f"{build.EXAMPLES}/workspace"
INSTALL_TIMEOUT_S: Final = 600
UNINSTALL_TIMEOUT_S: Final = 300
RUN_TIMEOUT_S: Final = 300
APP_SMOKE_TIMEOUT_S: Final = 180
# 앱 스모크 뒤 설치 폴더의 프로세스(daemon)가 끝나기를 기다리는 시간
PROCESS_EXIT_WAIT_S: Final = 20
# 설치본 NOTICES에 반드시 있어야 하는 절 (Python 패키지·JS 의존성·글꼴·네이티브·예외·고정 바이너리
# 예외·LicenseRef·원문·모델·제거 프로그램·VC++·Electron 고지)
NOTICE_SECTIONS: Final = (
    "numpy ",
    "(JavaScript)",
    "@xyflow/react ",
    "@fontsource/noto-sans-kr ",
    "SIL OPEN FONT LICENSE",
    "# 네이티브 파일 (DLL·pyd·exe)과 그 안의 구성요소",
    "# 패키지별 라이선스 예외",
    "# 고정 바이너리 한정 라이선스 예외",
    "# SPDX 밖 배포 조건 (LicenseRef)",
    "# 네이티브 파일 근거 원문",
    "# OCR 모델",
    "# OS 구성요소 사용",
    "GNU LESSER GENERAL PUBLIC LICENSE",
    "install:LICENSES.chromium.html",
    "Electron contributors",
    "NSIS 3.04",
    "Microsoft Visual C++",
)
# 실행 중 Python·uv·Kookabug 설정이 새지 않게 지우는 환경 변수
CLEARED_ENV: Final = (
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "UV_PROJECT_ENVIRONMENT",
    "KOOKABUG_OCR_MODELS",
    "KOOKABUG_CLI",
    "KOOKABUG_DAEMON_ARGS",
    "KOOKABUG_E2E_HOOKS",
)


@dataclass
class Step:
    id: str
    ok: bool
    detail: str
    seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"detail": self.detail, "id": self.id, "ok": self.ok, "seconds": self.seconds}


@dataclass
class SmokeReport:
    root: Path
    steps: list[Step] = field(default_factory=list)
    sizes: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    def step(self, step_id: str, body: Callable[[], tuple[bool, str]]) -> Step:
        started = time.perf_counter()
        try:
            ok, detail = body()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        step = Step(step_id, ok, detail, round(time.perf_counter() - started, 1))
        self.steps.append(step)
        print(f"[{'통과' if ok else '실패'}] {step_id} ({step.seconds} s): {detail}", flush=True)
        return step

    def get(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "root": str(self.root),
            "sizes": self.sizes,
            "steps": [s.to_json() for s in self.steps],
        }


# ---------------------------------------------------------------- 환경


def windows_dirs() -> list[str]:
    """Windows 시스템 폴더. `C:\\Windows` 자신은 넣지 않는다 — Python 런처(py.exe)가 거기 깔린다."""
    windows = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    return [
        str(windows / "System32"),
        str(windows / "System32" / "Wbem"),
        str(windows / "System32" / "WindowsPowerShell" / "v1.0"),
    ]


def python_free_env(root: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Python이 없는 PC 흉내: PATH = 설치 bin + Windows 폴더."""
    env = {k: v for k, v in (os.environ if base is None else base).items()}
    for key in list(env):
        if key.upper() in CLEARED_ENV or key.upper().startswith("UV_"):
            del env[key]
    env["PATH"] = os.pathsep.join([str(root / build.BIN), *windows_dirs()])
    return env


def check_env(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    path = env["PATH"]
    found = {name: shutil.which(name, path=path) for name in ("python", "python3", "py", "uv")}
    leaked = {k: v for k, v in found.items() if v is not None}
    kookabug = shutil.which("kookabug", path=path)
    expected = root / build.BIN / build.LAUNCHER
    ok = not leaked and kookabug is not None and Path(kookabug).resolve() == expected.resolve()
    return ok, f"kookabug={kookabug}, 남은 Python·uv={leaked or '없음'}"


def run_cli(
    root: Path, env: Mapping[str, str], args: Sequence[str], *, cwd: Path
) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("kookabug", path=env["PATH"])
    if exe is None:
        raise RuntimeError("PATH에서 kookabug를 찾을 수 없다")
    return subprocess.run(
        [exe, *args],
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=RUN_TIMEOUT_S,
        check=False,
    )


# ---------------------------------------------------------------- 설치·제거


def install(setup: Path, target: Path, log: Path) -> None:
    """NSIS 무인 설치. `/D=`는 마지막 인자이고 따옴표를 쓰지 않는다(공백 포함 경로 그대로).
    NSIS에는 설치 로그 옵션이 없어 명령과 종료 코드를 `log`에 남긴다."""
    line = subprocess.list2cmdline([str(setup), "/S", "/currentuser"]) + f" /D={target}"
    proc = subprocess.run(line, timeout=INSTALL_TIMEOUT_S, check=False)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f"{line}\n종료 코드 {proc.returncode}\n", encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"설치 종료 코드 {proc.returncode} (로그 {log})")


ENV_KEY: Final = "Environment"


@dataclass(frozen=True)
class RegValue:
    """사용자 PATH 값 그대로: 있는지, 문자열(펼치지 않은 원문), 레지스트리 형식."""

    exists: bool
    value: str = ""
    kind: int | None = None


def read_user_path(key_path: str = ENV_KEY) -> RegValue:
    """HKCU 사용자 PATH를 형식과 함께 읽는다 (REG_EXPAND_SZ는 펼치지 않은 원문)."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return RegValue(False)
    return RegValue(True, str(value), kind)


def write_user_path(saved: RegValue, key_path: str = ENV_KEY) -> None:
    """백업한 값으로 되돌린다 (없었으면 값을 지운다). 바뀐 환경을 알린다."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if saved.exists:
            winreg.SetValueEx(key, "Path", 0, saved.kind or winreg.REG_EXPAND_SZ, saved.value)
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, "Path")
    if key_path == ENV_KEY:
        broadcast_environment()


_user32 = ctypes.WinDLL("user32", use_last_error=True)
# LRESULT SendMessageTimeoutW(HWND, UINT, WPARAM, LPARAM, UINT fuFlags, UINT uTimeout, PDWORD_PTR)
# 결과 인자는 포인터 크기(DWORD_PTR)다. DWORD(4바이트)를 넘기면 Win64에서 옆 메모리까지 쓴다
# (T13 검수 2차 Low). 결과를 쓰지 않으므로 None(NULL)을 넘긴다
SendMessageTimeoutW = _user32.SendMessageTimeoutW
SendMessageTimeoutW.argtypes = (
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
)
SendMessageTimeoutW.restype = wintypes.LPARAM  # LRESULT
HWND_BROADCAST: Final = 0xFFFF
WM_SETTINGCHANGE: Final = 0x001A
SMTO_ABORTIFHUNG: Final = 0x0002


def broadcast_environment() -> None:
    """사용자 환경 변수가 바뀌었음을 알린다 (탐색기 등이 PATH를 다시 읽는다)."""
    text = ctypes.create_unicode_buffer("Environment")
    SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        ctypes.cast(text, ctypes.c_void_p).value or 0,
        SMTO_ABORTIFHUNG,
        500,
        None,
    )


class UserPathGuard:
    """실제 사용자 PATH를 건드리는 검사의 보호막: 들어갈 때 값·형식·존재를 백업하고, 나올 때 바이트
    단위로 같은지 본다. 다르면 백업으로 되돌리고 그 사실을 `restored`·`detail`에 남긴다."""

    def __init__(self, key_path: str = ENV_KEY) -> None:
        self.key_path = key_path
        self.saved = read_user_path(key_path)
        self.after: RegValue | None = None
        self.restored = False

    @property
    def same(self) -> bool:
        return self.after == self.saved

    @property
    def detail(self) -> str:
        a = self.after
        shape = f"{len(self.saved.value)}자·형식 {self.saved.kind}·있음 {self.saved.exists}"
        if a is None or self.same:
            return f"사용자 PATH 처음과 같음 ({shape})"
        now = f"{len(a.value)}자·형식 {a.kind}·있음 {a.exists}"
        return f"사용자 PATH가 달라졌다 ({shape} → {now}), 백업으로 되돌림={self.restored}"

    def check(self) -> bool:
        self.after = read_user_path(self.key_path)
        if not self.same:
            write_user_path(self.saved, self.key_path)
            self.restored = read_user_path(self.key_path) == self.saved
        return self.same

    def __enter__(self) -> UserPathGuard:
        return self

    def __exit__(self, *exc: object) -> None:
        if self.after is None:
            self.check()


def user_path() -> str:
    return read_user_path().value


def path_has(paths: str, folder: Path) -> bool:
    want = os.path.normcase(str(folder).rstrip("\\"))
    return any(os.path.normcase(p.rstrip("\\")) == want for p in paths.split(";") if p)


def same_file(text: str, path: Path) -> bool:
    """두 경로가 같은 파일인가. 8.3 짧은 이름(`PAPER3~1`)과 긴 이름이 섞여도 같다고 본다 —
    문자열 `normcase`는 별칭을 펴지 않는다. 파일이 없으면 펼친 경로끼리 비교한다."""
    if not text:
        return False
    other = Path(text)
    with contextlib.suppress(OSError):
        return other.samefile(path)
    return os.path.normcase(str(other.resolve())) == os.path.normcase(str(path.resolve()))


UNINSTALL_ROOT: Final = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def _key_values(key: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    index = 0
    while True:
        try:
            name, value, _ = winreg.EnumValue(key, index)
        except OSError:
            break
        index += 1
        values[name] = str(value)
    return values


def uninstall_entries() -> dict[str, dict[str, str]]:
    """HKCU 제거 등록 전체: 키 이름 → 문자열 값들. 테스트 앞뒤로 비교해 흔적·손실을 본다."""
    out: dict[str, dict[str, str]] = {}
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_ROOT)
    except FileNotFoundError:
        return out
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            with winreg.OpenKey(root, name) as key:
                out[name] = _key_values(key)
    return out


def hkcu_values(path: str) -> dict[str, str] | None:
    """HKCU 키의 값들. 키가 없으면 None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return _key_values(key)
    except FileNotFoundError:
        return None


def start_menu() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def traces(variant: build.Variant) -> dict[str, Any]:
    """설치가 남길 수 있는 흔적 (앞뒤 비교용): 제거 등록 전체, 그 판의 설치 정보 키, 시작 메뉴 바로
    가기, 설치 파일 사본 폴더, 사용자 PATH(값·형식·존재)."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return {
        "uninstall": uninstall_entries(),
        "install_key": hkcu_values(variant.install_key),
        "shortcut": (start_menu() / variant.shortcut).exists(),
        "updater": (local / variant.updater_dir).exists(),
        "path": read_user_path(),
    }


def variant_cleaned(variant: build.Variant, root: Path) -> bool:
    """그 판의 제거가 끝났는가: 설치 폴더·제거 등록·설치 정보 키·시작 메뉴 바로 가기가 모두 없다.
    NSIS 제거 프로그램은 폴더를 지운 **뒤** 바로 가기와 등록 키를 지운다."""
    return (
        not root.exists()
        and variant.uninstall_key not in uninstall_entries()
        and hkcu_values(variant.install_key) is None
        and not (start_menu() / variant.shortcut).exists()
    )


_version = ctypes.WinDLL("version", use_last_error=True)
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, wintypes.LPDWORD)
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.GetFileVersionInfoW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
)
_version.VerQueryValueW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = (
    wintypes.LPCVOID,
    wintypes.LPCWSTR,
    ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.UINT),
)


def setup_product_name(setup: Path) -> str | None:
    """설치 파일 버전 정보의 ProductName (electron-builder productName = 판 이름)."""
    size = _version.GetFileVersionInfoSizeW(str(setup), None)
    if not size:
        return None
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(str(setup), 0, size, buf):
        return None
    ptr, length = wintypes.LPVOID(), wintypes.UINT()
    if not _version.VerQueryValueW(
        buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length)
    ):
        return None
    lang, codepage = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
    query = rf"\StringFileInfo\{lang:04x}{codepage:04x}\ProductName"
    if not _version.VerQueryValueW(buf, query, ctypes.byref(ptr), ctypes.byref(length)):
        return None
    return ctypes.wstring_at(ptr.value or 0, max(length.value - 1, 0)).rstrip("\0 ")


def check_setup(setup: Path, variant: build.Variant) -> tuple[bool, str]:
    """설치 전 확인: 설치 파일이 그 판이고, 그 판의 제거 등록이 아직 없다. 제품 판이면 기존 제품
    설치(제거 등록)가 있을 때 멈춘다 — 같은 GUID로 덮어써 실제 설치의 등록을 잃게 하지 않는다."""
    name = setup_product_name(setup)
    if name != variant.app_name:
        return False, f"설치 파일 판이 {name!r}이다 (기대 {variant.app_name!r}). 설치하지 않는다"
    if variant.uninstall_key in uninstall_entries():
        return False, f"{variant.uninstall_key}가 이미 등록돼 있다. 설치하지 않는다"
    return True, f"{name} ({variant.uninstall_key})"


def uninstaller(root: Path) -> Path | None:
    """설치 폴더의 제거 프로그램 (판마다 이름이 다르다)."""
    for variant in build.VARIANTS.values():
        exe = root / variant.uninstaller
        if exe.is_file():
            return exe
    return None


def uninstall(
    root: Path,
    *,
    variant: build.Variant | None = None,
    timeout_s: float = UNINSTALL_TIMEOUT_S,
) -> bool:
    """제거 프로그램을 돌리고 제거가 **끝날 때까지** 기다린다. 제거 프로그램은 임시 폴더로 자신을
    복사해 다시 띄우고 먼저 끝나며, 폴더를 지운 뒤에 바로 가기·등록 키를 지운다. 그래서 폴더만이
    아니라 그 판의 등록·바로 가기까지 다 없어질 때까지 본다(`variant_cleaned`). 기한 안에
    끝났으면 True."""
    exe = uninstaller(root)
    if exe is None:
        raise RuntimeError(f"{root}에 제거 프로그램이 없다")
    if variant is None:
        variant = next(v for v in build.VARIANTS.values() if exe.name == v.uninstaller)
    proc = subprocess.run(
        [str(exe), "/S", "/currentuser"],
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"제거 종료 코드 {proc.returncode}")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if variant_cleaned(variant, root):
            return True
        time.sleep(0.5)
    return variant_cleaned(variant, root)


# ---------------------------------------------------------------- 프로세스


def processes_under(root: Path) -> list[tuple[int, str]]:
    """실행 파일이 `root` 아래에 있는 프로세스 (PID, 경로)."""
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath } | "
        "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.ExecutablePath }"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    want = os.path.normcase(str(root.resolve())).rstrip("\\") + "\\"
    out: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        pid, _, exe = line.partition("\t")
        if exe and os.path.normcase(exe).startswith(want) and pid.strip().isdigit():
            out.append((int(pid), exe))
    return out


@dataclass
class StandIn:
    """실행 중인 제품 앱의 대역 프로세스 (`build.PRODUCT.app_exe` 이름)."""

    proc: subprocess.Popen[bytes]
    exe: Path

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self) -> None:
        if self.alive:
            self.proc.kill()
            self.proc.wait(timeout=30)
        shutil.rmtree(self.exe.parent, ignore_errors=True)


def standin_dir(target: Path) -> Path:
    """대역 폴더: 설치 폴더 이름 뒤에 글자를 붙인 옆 폴더. 설치 폴더 경계(\\) 없이 경로 앞부분만
    비교하는 확인은 이 폴더의 프로세스를 설치 폴더 안의 것으로 잘못 본다."""
    return target.with_name(target.name + "2")


def start_product_standin(target: Path) -> StandIn:
    """제품 판 대역을 띄운다: `standin_dir(target)/Kookabug.exe`(제품 판 실행 파일 이름)로 복사한
    Python이 잠자고 있는 프로세스. 테스트 판 설치·제거는 이것을 끄면 안 된다 (이름으로 끄면 제품
    앱의 저장 안 한 편집을 잃는다). 실제 제품 앱은 띄우지도 끄지도 않는다."""
    base = Path(sys.base_prefix)
    folder = standin_dir(target)
    folder.mkdir(parents=True, exist_ok=False)
    for dll in [*base.glob("python3*.dll"), *base.glob("vcruntime140*.dll")]:
        shutil.copy2(dll, folder / dll.name)
    exe = folder / build.PRODUCT.app_exe
    shutil.copy2(base / "python.exe", exe)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}
    env["PYTHONHOME"] = str(base)
    proc = subprocess.Popen(
        [str(exe), "-S", "-c", "import time; time.sleep(1800)"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(0.5)
    if proc.poll() is not None:
        raise RuntimeError(f"제품 판 대역이 바로 끝났다 (종료 코드 {proc.returncode})")
    return StandIn(proc, exe)


def shortcut_target(link: Path) -> tuple[str, str]:
    """.lnk의 (대상 경로, 아이콘 위치). WScript.Shell은 ANSI 코드 페이지 밖 글자를 `?`로 바꿔
    (cp1252 러너에서 한글 설치 폴더) IShellLinkW로 읽는다 (`shelllink`)."""
    return shelllink.read_shortcut(link)


def wait_no_processes(root: Path, timeout_s: float = PROCESS_EXIT_WAIT_S) -> list[tuple[int, str]]:
    deadline = time.monotonic() + timeout_s
    left = processes_under(root)
    while left and time.monotonic() < deadline:
        time.sleep(1)
        left = processes_under(root)
    return left


# ---------------------------------------------------------------- 단계


def audit_step(root: Path) -> tuple[bool, str]:
    report = na.audit_final_tree(
        root,
        na.load_native_table_file(build.NATIVE_TABLE),
        la.load_policy_file(build.ALLOWLIST),
        models=na.load_model_table_file(build.MODELS_TABLE),
    )
    if report.problems:
        return False, f"{len(report.problems)}건: " + " | ".join(report.problems[:20])
    pinned = [f"{nf.rel} ({pin.package} {pin.version})" for nf, pin in report.pinned]
    return True, f"네이티브 파일 {len(report.files)}개, 고정 바이너리 예외 {pinned}, 문제 없음"


def notices_step(root: Path) -> tuple[bool, str]:
    text = (root / build.NOTICES).read_text(encoding="utf-8")
    missing = [s for s in NOTICE_SECTIONS if s not in text]
    return not missing, f"{len(text)}자, 빠진 절 {missing or '없음'}"


def bundle_step(root: Path) -> tuple[bool, str]:
    """설치된 앱 번들에 E2E 검사 전용 훅이 없고(배포 빌드), 우리 패키지가 다 있다
    (kookabug-platform 포함)."""
    variant = build.variant_of_tree(root)
    exe = root / variant.app_exe
    icon = build.missing_icon_images(exe) if exe.is_file() else ["실행 파일 없음"]
    files = build.read_asar(root / build.APP_ASAR)
    main = files.get("dist/main/main.cjs", b"")
    hooks = build.e2e_hook_markers(files)
    # 대조: 빈 번들을 본 것이 아니다 (연결 관리 코드는 배포 빌드에도 있다)
    real = b"dropConnection" in main and b"session.hello" in main
    missing = build.check_required_packages(root / na.SITE_PACKAGES_IN_INSTALL)
    ok = not hooks and real and not missing and not icon
    detail = f"번들 파일 {len(files)}개, E2E 훅 {hooks or '없음'}, "
    detail += (
        f"우리 패키지 빠짐 {missing or '없음'}, {variant.app_exe} 확정 아이콘 빠짐 {icon or '없음'}"
    )
    return ok, detail


def version_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    want = (root / build.VERSION_FILE).read_text(encoding="utf-8").strip()
    proc = run_cli(root, env, ["--version"], cwd=root)
    out = proc.stdout.strip()
    return (
        proc.returncode == 0 and out == f"kookabug {want}",
        f"{out!r} (종료 코드 {proc.returncode})",
    )


def doctor_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    proc = run_cli(root, env, ["doctor", "--profile", "headless", "--json"], cwd=root)
    try:
        body = json.loads(proc.stdout)
    except ValueError:
        return False, f"JSON이 아니다 (종료 코드 {proc.returncode}): {proc.stderr[-2000:]}"
    checks = {c["id"]: c for c in body.get("checks", [])}
    failed = [f"{c['id']}: {c['detail']}" for c in checks.values() if not c["ok"]]
    python = checks.get("python", {}).get("detail", "")
    installed = "(Python" in python and "설치본 아님" not in python and "설치본" in python
    ok = proc.returncode == 0 and body.get("ok") is True and not failed and installed
    detail = f"검사 {len(checks)}개, 실패 {failed or '없음'}; python: {python}"
    dll = checks.get("dll.origin", {}).get("detail")
    return ok, f"{detail}; dll: {dll}"


def graph_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    workspace = root / WORKSPACE
    proc = run_cli(
        root,
        env,
        ["run", SMOKE_GRAPH, "--platform-fake", FAKE_PLATFORM, "--json"],
        cwd=workspace,
    )
    try:
        body = json.loads(proc.stdout)
    except ValueError:
        return False, f"JSON이 아니다 (종료 코드 {proc.returncode}): {proc.stderr[-2000:]}"
    ok = proc.returncode == 0 and body.get("verdict") == "pass"
    return ok, f"{body.get('verdict')} ({body.get('code')}), 실행 폴더 {body.get('run_dir')}"


VIDEO_GRAPH: Final = "tests/video_smoke.graph.json"
VIDEO_SMOKE: Final[dict[str, Any]] = {
    "format": "kookabug.graph/0",
    "kind": "test",
    "meta": {"title": "영상 스모크"},
    "nodes": {
        "n_entry": {"next": {"start": "n_launch"}, "type": "core.graph.entry", "version": 1},
        "n_launch": {
            "in": {"path": "SampleRPG", "timeout_ms": 5000, "window_title": "SampleRPG"},
            "next": {"attached": "n_wait"},
            "type": "core.app.launch",
            "version": 1,
        },
        # 차가운 Media Foundation 첫 열기(약 1초, 빈 구간 starting) 뒤에도 칸이 남게 기다린다
        "n_wait": {
            "in": {"ms": 3000},
            "next": {"done": "n_pass"},
            "type": "core.flow.delay",
            "version": 1,
        },
        "n_pass": {"type": "core.test.pass", "version": 1},
    },
    "plugins": {"core": "0.1.0"},
}


VIDEO_TEST_ENV: Final = "KOOKABUG_VIDEO_TEST"
"""숨은 영상 검사 설정 (`kookabug_core.record.video.TEST_ENV`). 인코더 탐지에서는 뺀다."""
OS_MEDIA_MISSING: Final = frozenset({"mf_missing", "h264_encoder_missing"})
"""`probe_media`의 이유 중 OS 구성요소 부재 (N 판 등). `backend_missing`은 설치 트리 결함이다."""
_PROBE_SCRIPT: Final = (
    "import json\n"
    "from kookabug_platform.video import probe_media\n"
    "p = probe_media()\n"
    "print(json.dumps({'available': p.available, 'reason': p.reason, 'detail': p.detail}))\n"
)


@dataclass(frozen=True, slots=True)
class MediaFound:
    """설치 환경에서 따로 탐지한 영상 인코더 (`probe_media`, 파일을 쓰지 않는다)."""

    available: bool
    reason: str | None
    detail: str

    @property
    def os_missing(self) -> bool:
        """OS에 Media Foundation H.264 인코더가 없다 (영상 없는 실행만 통과로 볼 수 있다)."""
        return not self.available and self.reason in OS_MEDIA_MISSING


def probe_installed_media(root: Path, env: Mapping[str, str]) -> MediaFound:
    """설치본 Python으로 `probe_media()`를 부른다. 검사 설정(`KOOKABUG_VIDEO_TEST`)은 빼서 주입과
    무관한 이 PC의 실제 인코더를 본다. 탐지하지 못하면(`probe_failed`) 인코더 부재로 보지 않는다 —
    그때는 영상이 실제로 써져야 통과다."""
    clean = {k: v for k, v in env.items() if k.upper() != VIDEO_TEST_ENV}
    try:
        proc = subprocess.run(
            [str(root / "python" / "python.exe"), "-X", "utf8", "-c", _PROBE_SCRIPT],
            env=clean,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return MediaFound(False, "probe_failed", f"설치본 Python을 실행하지 못했다: {exc}")
    try:
        body = json.loads(proc.stdout.strip().splitlines()[-1])
        return MediaFound(bool(body["available"]), body["reason"], str(body["detail"]))
    except (ValueError, KeyError, IndexError) as exc:
        detail = f"탐지 실패 ({exc}, 종료 코드 {proc.returncode}): {proc.stderr[-800:]}"
        return MediaFound(False, "probe_failed", detail)


def video_step(
    root: Path,
    env: Mapping[str, str],
    *,
    probe: Callable[[Path, Mapping[str, str]], MediaFound] = probe_installed_media,
) -> tuple[bool, str]:
    """설치본 runner의 영상 (M3 2.5, 검수 M9): 예제 사본(워크스페이스 영상 정책 `on`)에서 3초짜리
    그래프를 가짜 플랫폼으로 돌린다. FFmpeg DLL이 없는 트리라 OS Media Foundation H.264로 써야 한다.

    인코더가 없다는 판단은 실행 결과가 아니라 설치 환경에서 따로 탐지한 결과(`probe`)로만 한다.
    OS에 인코더가 없으면(`mf_missing`·`h264_encoder_missing`) 영상 없는 pass(`unavailable`)가 통과,
    그 밖에는 pass 실행이고 `recorded`(남은 조각이 MP4)여야 통과다. 인코더가 있는데 실행이
    `unavailable`·`failed`·`omitted`·`none`이면 실패다 (계획 2.5 "인코더가 있는데 쓰기가 실패하면
    실패")."""
    found = probe(root, env)
    base = Path(tempfile.mkdtemp(prefix="kb-video-"))
    try:
        examples = base / "examples"
        shutil.copytree(
            root / build.EXAMPLES, examples, ignore=shutil.ignore_patterns(".kookabug", "runs")
        )
        workspace = examples / "workspace"
        config_file = workspace / "kookabug.json"
        config = json.loads(config_file.read_text(encoding="utf-8"))
        config["record"] = {**config.get("record", {}), "video": "on"}
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        graph = workspace / VIDEO_GRAPH
        graph.write_text(json.dumps(VIDEO_SMOKE, ensure_ascii=False), encoding="utf-8")
        proc = run_cli(
            root,
            env,
            ["run", VIDEO_GRAPH, "--platform-fake", FAKE_PLATFORM, "--json"],
            cwd=workspace,
        )
        try:
            body = json.loads(proc.stdout)
            run_dir = Path(body["run_dir"])
            video = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["video"]
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return (
                False,
                f"실행 결과를 읽지 못했다 ({exc}): {proc.stdout[-1500:]} {proc.stderr[-1500:]}",
            )
        status = video.get("status")
        heads = [p.read_bytes()[4:8] for p in sorted((run_dir / "video").glob("seg-*.mp4"))]
        detail = (
            f"판정 {body.get('verdict')}, 영상 {video}, 조각 머리 {heads}; "
            f"인코더 탐지 {found.available} ({found.reason or 'ok'}: {found.detail})"
        )
        if body.get("verdict") != "pass":
            return False, detail
        if found.os_missing:
            ok = status == "unavailable"
            return ok, f"{detail} (이 PC에 영상 인코더 없음 — 영상 없이 실행)"
        ok = (
            status == "recorded" and video.get("kept", 0) >= 1 and heads and set(heads) == {b"ftyp"}
        )
        return bool(ok), detail
    finally:
        shutil.rmtree(base, ignore_errors=True)


def app_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    """`Kookabug.exe --smoke <예제 워크스페이스 사본>`: 설치 폴더의 CLI로 daemon을 띄우고 붙어서
    열고 무수정 저장한다. 사용자 데이터 폴더·워크스페이스 사본은 임시 폴더라 사용자 프로필에
    남지 않는다. 끝난 뒤 설치 폴더에서 돌던 프로세스(daemon)가 남지 않아야 한다."""
    base = Path(tempfile.mkdtemp(prefix="kb-app-"))
    try:
        workspace = base / "ws"
        shutil.copytree(
            root / WORKSPACE, workspace, ignore=shutil.ignore_patterns(".kookabug", "runs")
        )
        graph = workspace / SMOKE_GRAPH
        before = graph.read_bytes()
        mtime = graph.stat().st_mtime_ns
        report = base / "app-smoke.json"
        proc = subprocess.run(
            [
                str(root / build.variant_of_tree(root).app_exe),
                f"--user-data-dir={base / 'user-data'}",
                "--smoke",
                str(workspace),
                "--smoke-report",
                str(report),
            ],
            cwd=base,
            env=dict(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=APP_SMOKE_TIMEOUT_S,
            check=False,
        )
        left = wait_no_processes(root)
        try:
            body = json.loads(report.read_text(encoding="utf-8"))
        except OSError, ValueError:
            body = {}
        steps = [f"{s['id']}={'ok' if s['ok'] else 'FAIL'}" for s in body.get("steps", [])]
        unchanged = graph.read_bytes() == before and graph.stat().st_mtime_ns == mtime
        ok = proc.returncode == 0 and body.get("ok") is True and unchanged and not left
        logs = sorted((workspace / ".kookabug" / "logs").glob("daemon-*.log"))
        detail = (
            f"종료 코드 {proc.returncode}, 단계 {steps}, 그래프 바이트·mtime 그대로={unchanged}, "
            f"남은 프로세스 {left or '없음'}"
        )
        if not ok:
            tail = logs[-1].read_text(encoding="utf-8", errors="replace")[-1500:] if logs else ""
            detail += f"; stdout {proc.stdout[-1500:]!r}; stderr {proc.stderr[-1500:]!r}"
            detail += f"; daemon 로그 {tail!r}"
        return ok, detail
    finally:
        shutil.rmtree(base, ignore_errors=True)


_HOOK_SCRIPT: Final = (
    "import json, sys, tempfile, time\n"
    "from pathlib import Path\n"
    "from kookabug_daemon.recorder_hook import HookClient, hook_command\n"
    "stops = []\n"
    "logs = Path(tempfile.mkdtemp(prefix='kb-hook-smoke-'))\n"
    "client = HookClient(mono_base_ns=time.monotonic_ns(), on_update=lambda u: None,\n"
    "                    on_stop=stops.append, logs_dir=logs)\n"
    "out = {'command': hook_command()[0]}\n"
    "try:\n"
    "    hello = client.start(timeout=30)\n"
    "    out['hello'] = {k: hello.get(k) for k in ('protocol', 'hooks', 'pid')}\n"
    "    out['pid'] = client.pid\n"
    "finally:\n"
    "    client.stop()\n"
    "process = client._process\n"
    "out['exit'] = None if process is None else process.exit_code()\n"
    "out['stops'] = [s.reason for s in stops]\n"
    "err = logs / 'hook.stderr.log'\n"
    "text = err.read_text(encoding='utf-8', errors='replace') if err.exists() else ''\n"
    "out['stderr'] = text[-800:]\n"
    "print(json.dumps(out, ensure_ascii=False))\n"
)


def recorder_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    """설치본 녹화기 (M4 계획 T13): 훅 프로세스가 설치 트리의 Python으로 떠 `hook.hello`(저수준
    마우스·키보드 훅 걸림, 프로토콜 일치)까지 오고 정상으로 끝난다. 입력은 보내지 않는다 — 그 사이
    사람이 친 키가 잡혀도 내용은 보지 않는다. 검사 표식 옵션(`KOOKABUG_TESTING`)은 뺀다."""
    from kookabug_core.recorder.contract import HOOK_PROTOCOL

    clean = {k: v for k, v in env.items() if k.upper() != "KOOKABUG_TESTING"}
    python = root / "python" / "python.exe"
    try:
        proc = subprocess.run(
            [str(python), "-X", "utf8", "-c", _HOOK_SCRIPT],
            env=clean,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"설치본 Python을 실행하지 못했다: {exc}"
    try:
        body = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return False, f"결과를 읽지 못했다 ({exc}): {proc.stdout[-800:]} {proc.stderr[-1500:]}"
    hello = body.get("hello") or {}
    command = Path(str(body.get("command", "")))
    in_tree = same_file(str(command), python)
    ok = (
        in_tree
        and hello.get("protocol") == HOOK_PROTOCOL
        and hello.get("hooks") == {"mouse": True, "keyboard": True}
        and hello.get("pid") == body.get("pid")
        and body.get("exit") == 0
        and not body.get("stops")
    )
    return ok, (
        f"훅 명령 {command} (설치 트리={in_tree}), hello {hello}, 종료 코드 {body.get('exit')}, "
        f"멈춤 {body.get('stops')}, stderr {body.get('stderr')!r}"
    )


MCP_AGENT_ID: Final = "smoke-mcp"
MCP_IDLE_TIMEOUT_S: Final = 20


class _McpPipe:
    """설치본 `kookabug mcp`와 줄 단위 JSON-RPC (요청 하나에 응답 한 줄)."""

    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self.proc = proc
        self.ids = 0

    def send(
        self, method: str, params: Mapping[str, Any] | None = None, *, notify: bool = False
    ) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        if not notify:
            self.ids += 1
            message["id"] = self.ids
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.send(method, params)
        assert self.proc.stdout is not None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(
                    f"{method}: 응답 전에 stdout이 닫혔다 (종료 코드 {self.proc.poll()})"
                )
            reply = json.loads(line.decode("utf-8"))
            if reply.get("id") == self.ids:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply["result"]


def mcp_step(root: Path, env: Mapping[str, str]) -> tuple[bool, str]:
    """설치본 MCP (M5): 예제 워크스페이스 사본에 설치본 daemon(짧은 유휴 종료)을 띄우고, 설치본
    `kookabug mcp --unattended --agent-id`로 붙어 initialize·tools/list·`kb_project_info`.
    daemon이 본 주체가 그 ID·사람 없음이어야 한다. `agent-host`는 도움말만 본다(에이전트를 띄우지
    않음). 끝난 뒤 설치 폴더에서 돌던 프로세스가 남지 않아야 한다."""
    exe = shutil.which("kookabug", path=env["PATH"])
    if exe is None:
        return False, "PATH에서 kookabug를 찾을 수 없다"
    base = Path(tempfile.mkdtemp(prefix="kb-mcp-"))
    daemon: subprocess.Popen[bytes] | None = None
    mcp: subprocess.Popen[bytes] | None = None
    try:
        workspace = base / "ws"
        shutil.copytree(
            root / WORKSPACE, workspace, ignore=shutil.ignore_patterns(".kookabug", "runs")
        )
        user = {**env, "KOOKABUG_USER_CONFIG_DIR": str(base / "user")}
        with (base / "daemon.out").open("wb") as out, (base / "daemon.err").open("wb") as err:
            daemon = subprocess.Popen(
                [exe, "daemon", "--workspace", str(workspace), "--json",
                 "--idle-timeout-s", str(MCP_IDLE_TIMEOUT_S)],
                cwd=base, env=user, stdout=out, stderr=err,
            )  # fmt: skip
        deadline = time.monotonic() + RUN_TIMEOUT_S
        while not (base / "daemon.out").read_bytes().strip():
            if daemon.poll() is not None or time.monotonic() > deadline:
                text = (base / "daemon.err").read_text("utf-8", errors="replace")[-1500:]
                return False, f"daemon이 시작하지 못했다 (종료 코드 {daemon.poll()}): {text}"
            time.sleep(0.2)
        started = json.loads((base / "daemon.out").read_text("utf-8").splitlines()[0])
        with (base / "mcp.err").open("wb") as err:
            mcp = subprocess.Popen(
                [exe, "mcp", "--workspace", str(workspace), "--unattended",
                 "--agent-id", MCP_AGENT_ID],
                cwd=base, env=user, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
            )  # fmt: skip
        killer = threading.Timer(RUN_TIMEOUT_S, mcp.kill)
        killer.start()
        try:
            pipe = _McpPipe(mcp)
            init = pipe.request(
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "kb-smoke", "version": "0"}},
            )  # fmt: skip
            pipe.send("notifications/initialized", notify=True)
            tools = sorted(t["name"] for t in pipe.request("tools/list")["tools"])
            info = pipe.request("tools/call", {"name": "kb_project_info", "arguments": {}})
            assert mcp.stdin is not None
            mcp.stdin.close()
            code = mcp.wait(30)
        finally:
            killer.cancel()
        principal = (info.get("structuredContent") or {}).get("principal")
        host = run_cli(root, env, ["agent-host", "--help"], cwd=base)
        daemon.wait(MCP_IDLE_TIMEOUT_S + 30)
        left = wait_no_processes(root)
        expected = {"kind": "agent", "id": MCP_AGENT_ID, "attended": False}
        ok = (
            started.get("status") in ("started", "already_running")
            and init.get("protocolVersion") == "2025-06-18"
            and "kb_project_info" in tools
            and "kb_graph_patch" not in tools  # 기본 툴셋은 core만
            and info.get("isError") is False
            and principal == expected
            and code == 0
            and host.returncode == 0
            and "agent-host" in host.stdout
            and not left
        )
        detail = (
            f"daemon {started.get('status')}, 판 {init.get('protocolVersion')}, "
            f"도구 {len(tools)}개, "
            f"주체 {principal}, mcp 종료 코드 {code}, agent-host --help {host.returncode}, "
            f"남은 프로세스 {left or '없음'}"
        )
        if not ok:
            for name in ("daemon.err", "mcp.err"):
                text = (base / name).read_text("utf-8", errors="replace")[-1200:]
                detail += f"; {name} {text!r}"
        return ok, detail
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return False, f"MCP 스모크 실패: {exc!r}"
    finally:
        for proc in (mcp, daemon):
            if proc is not None and proc.poll() is None:
                proc.kill()
        shutil.rmtree(base, ignore_errors=True)


def dll_step(root: Path) -> tuple[bool, str]:
    report = dllcheck.check_tree(root)
    if report.problems:
        return False, f"{len(report.problems)}건: " + " | ".join(report.problems[:20])
    return True, f"네이티브 파일 {report.files}개, 참고 {len(report.notes)}건"


def removed_step(root: Path) -> tuple[bool, str]:
    left = root.exists()
    on_path = path_has(user_path(), root / build.BIN)
    return not left and not on_path, f"설치 폴더 남음={left}, 사용자 PATH에 bin 남음={on_path}"


def smoke_installed(report: SmokeReport) -> None:
    """설치된 폴더에 감사·스모크·DLL 검사를 건다 (설치·제거 없이)."""
    root = report.root
    report.sizes["install_bytes"], report.sizes["install_files"] = build.tree_size(root)
    report.step("audit.final_tree", lambda: audit_step(root))
    report.step("licenses.notices", lambda: notices_step(root))
    report.step("packaging.app_bundle", lambda: bundle_step(root))
    env = python_free_env(root)
    report.step("env.python_free", lambda: check_env(root, env))
    report.step("cli.version", lambda: version_step(root, env))
    report.step("cli.doctor_headless", lambda: doctor_step(root, env))
    report.step("cli.smoke_graph", lambda: graph_step(root, env))
    report.step("cli.video", lambda: video_step(root, env))
    report.step("recorder.hook", lambda: recorder_step(root, env))
    report.step("cli.mcp", lambda: mcp_step(root, env))
    report.step("app.smoke", lambda: app_step(root, env))
    report.step("dll.check", lambda: dll_step(root))


def run_all(
    setup: Path,
    target: Path,
    *,
    log: Path,
    keep: bool = False,
    variant: build.Variant = build.TEST,
) -> SmokeReport:
    """설치 → 감사·스모크 → 제거 → 남은 것 없음. 실패해도 제거는 한다(`keep`이 아니면).

    기본은 테스트 전용 판(`build.TEST`)만 받는다: appId·이름·GUID·폴더가 제품과 달라 이 PC의 실제
    설치와 겹치지 않는다. 설치 흔적(`traces`)을 앞뒤로 비교해, 설치 중에는 그 판의 키만 새로 생기고
    제거 뒤에는 처음과 똑같아야 한다."""
    report = SmokeReport(target)
    report.sizes["setup_bytes"] = setup.stat().st_size
    guard = UserPathGuard()
    before = traces(variant)
    standin: StandIn | None = None

    def start_standin() -> tuple[bool, str]:
        nonlocal standin
        standin = start_product_standin(target)
        return True, f"{standin.exe} (PID {standin.proc.pid})"

    def standin_alive(when: str) -> tuple[bool, str]:
        alive = standin is not None and standin.alive
        return alive, f"{when} 뒤 제품 판 대역 살아 있음={alive}"

    def do_install() -> tuple[bool, str]:
        install(setup, target, log)
        return True, str(target)

    def registration() -> tuple[bool, str]:
        now = uninstall_entries()
        added = sorted(set(now) - set(before["uninstall"]))
        changed = sorted(k for k in before["uninstall"] if now.get(k) != before["uninstall"][k])
        command = now.get(variant.uninstall_key, {}).get("UninstallString", "")
        location = (hkcu_values(variant.install_key) or {}).get("InstallLocation", "")
        here = os.path.normcase(location.rstrip("\\")) == os.path.normcase(str(target))
        points = os.path.normcase(str(target / variant.uninstaller)) in os.path.normcase(command)
        ok = added == [variant.uninstall_key] and not changed and here and points
        return ok, (
            f"새 키 {added}, 바뀐 키 {changed or '없음'}, InstallLocation={location!r}, "
            f"UninstallString={command!r}"
        )

    def on_path() -> tuple[bool, str]:
        bin_dir = target / build.BIN
        return path_has(user_path(), bin_dir), f"사용자 PATH에 {bin_dir}"

    def shortcut() -> tuple[bool, str]:
        """시작 메뉴 바로 가기가 설치한 앱 실행 파일(확정 아이콘이 든)을 가리킨다. 유니코드로
        저장되어 있어야 다른 로캘에서도 한글 설치 폴더를 가리킨다."""
        link = start_menu() / variant.shortcut
        local = Path(os.environ.get("LOCALAPPDATA", "")) / variant.updater_dir
        exe = target / variant.app_exe
        aim, icon = shortcut_target(link) if link.exists() else ("", "")
        unicode = link.exists() and shelllink.is_unicode(link)
        points = same_file(aim, exe)
        icon_file, _, icon_index = icon.rpartition(",") if "," in icon else (icon, "", "0")
        icon_ok = same_file(icon_file, exe) and icon_index.strip() == "0"
        ok = link.exists() and unicode and points and icon_ok
        ok = ok and local.exists() == before["updater"]
        detail = f"시작 메뉴 {link.name} 있음={link.exists()}, 유니코드={unicode}, "
        detail += f"대상 {aim!r}, 아이콘 {icon!r}, "
        return ok, detail + f"설치 파일 사본 폴더 남음={local.exists()}"

    def do_uninstall() -> tuple[bool, str]:
        done = uninstall(target, variant=variant)
        return done, f"제거 프로그램 끝, 폴더·등록·바로 가기 정리 끝={done}"

    def restored() -> tuple[bool, str]:
        now = traces(variant)
        added = sorted(set(now["uninstall"]) - set(before["uninstall"]))
        lost = sorted(set(before["uninstall"]) - set(now["uninstall"]))
        changed = sorted(
            k
            for k in before["uninstall"]
            if k in now["uninstall"] and now["uninstall"][k] != before["uninstall"][k]
        )
        others = [k for k in ("install_key", "shortcut", "updater", "path") if now[k] != before[k]]
        ok = not added and not lost and not changed and not others
        return ok, (
            f"남은 키 {added or '없음'}, 사라진 키 {lost or '없음'}, 바뀐 키 {changed or '없음'}, "
            f"달라진 흔적 {others or '없음'}"
        )

    if not report.step("setup.variant", lambda: check_setup(setup, variant)).ok:
        return report
    try:
        if variant is not build.PRODUCT:
            report.step("isolation.product_standin", start_standin)
        if report.step("install", do_install).ok:
            if standin is not None:
                report.step("isolation.after_install", lambda: standin_alive("설치"))
            report.step("install.registration", registration)
            report.step("install.path", on_path)
            report.step("install.shortcut", shortcut)
            smoke_installed(report)
        if not keep and uninstaller(target) is not None:
            report.step("uninstall", do_uninstall)
            if standin is not None:
                report.step("isolation.after_uninstall", lambda: standin_alive("제거"))
            report.step("uninstall.clean", lambda: removed_step(target))
            report.step("uninstall.registry", restored)
    finally:
        if standin is not None:
            standin.stop()
        if not keep:
            report.step("path.guard", lambda: (guard.check(), guard.detail))
    return report


def default_target() -> Path:
    return Path(tempfile.mkdtemp(prefix="kookabug-install-")) / "설치 폴더 공백 한글"


def main(argv: Sequence[str] | None = None) -> int:
    utf8_stdio()
    parser = argparse.ArgumentParser(description="Kookabug 설치 파일 스모크")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--setup", type=Path, help="설치 파일 (설치 → 스모크 → 제거)")
    source.add_argument("--installed", type=Path, help="이미 설치된 폴더 (스모크만)")
    parser.add_argument(
        "--dir", type=Path, help="설치 폴더 (기본: 임시 폴더의 '설치 폴더 공백 한글')"
    )
    parser.add_argument("--json", type=Path, help="결과 JSON 파일")
    parser.add_argument("--keep", action="store_true", help="끝나도 제거하지 않는다")
    parser.add_argument(
        "--variant",
        choices=tuple(build.VARIANTS),
        default=build.TEST.key,
        help="설치 파일 판 (기본 test. product는 제품 설치가 없는 PC에서만 설치한다)",
    )
    args = parser.parse_args(argv)
    if args.installed is not None:
        report = SmokeReport(args.installed.resolve())
        smoke_installed(report)
    else:
        target = (args.dir or default_target()).resolve()
        log = target.parent / "install.log"
        report = run_all(
            args.setup.resolve(),
            target,
            log=log,
            keep=args.keep,
            variant=build.VARIANTS[args.variant],
        )
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    sizes = ", ".join(f"{k}={v}" for k, v in report.sizes.items())
    print(f"스모크 {'통과' if report.ok else '실패'} ({sizes})")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
