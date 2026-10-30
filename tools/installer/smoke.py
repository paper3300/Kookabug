"""설치 파일 무인 설치·최종 트리 감사·헤드리스 스모크·제거 (구현 계획 M1 2.12).

    $env:PYTHONPATH = "tools"
    uv run python -m installer.smoke --setup build/installer/dist/kookabug-setup-test-<버전>.exe `
        [--dir "<임시>\\설치 폴더 공백 한글"] [--json build/installer/smoke.json] [--keep]

0. 판 확인: 기본은 **테스트 전용 판**(`build.TEST`: 제품과 다른 AppId·이름·폴더·제거 등록 이름)만
   설치한다. 설치 파일 버전 정보의 ProductName으로 가리고, 그 판의 제거 등록이 이미 있으면 멈춘다
1. 무인 설치: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR=<폴더> /LOG=<로그>`.
   HKCU 제거 등록에 그 판의 키 하나만 새로 생기고(InstallLocation = 설치 폴더) 다른 키는 그대로
2. 최종 트리 감사 (`native_audit.audit_final_tree`, 모델 해시 포함)
3. Python 없는 환경 흉내: PATH = 설치 `bin` + Windows 폴더만, `PYTHONHOME`·`PYTHONPATH`·
   `VIRTUAL_ENV`·`KOOKABUG_OCR_MODELS` 등 삭제. 그 PATH에서 python·uv를 찾을 수 없어야 한다
4. `kookabug --version`(VERSION 파일과 같음), `kookabug doctor --profile headless --json`(전부 통과,
   설치본 Python·설치 폴더 VC++ 런타임), 예제 헤드리스 스모크 그래프 `kookabug run`(통과)
5. DLL 의존성 검사 (`dllcheck`)
6. 제거 (`--keep`이 없으면): 제거 프로그램 → 설치 폴더 없음, 사용자 PATH에 bin 없음, HKCU 제거
   등록이 처음과 똑같음 (테스트 흔적 없음, 다른 등록 손실 없음)

단계마다 `{id, ok, detail}`. 종료 코드 0 = 전부 통과, 1 = 실패.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import license_audit as la
import native_audit as na
from installer import build, dllcheck
from kookabug_sdk.console import utf8_stdio

SMOKE_GRAPH: Final = "tests/smoke_headless.graph.json"
FAKE_PLATFORM: Final = "fake-platform.json"
WORKSPACE: Final = f"{build.EXAMPLES}/workspace"
INSTALL_TIMEOUT_S: Final = 600
UNINSTALL_TIMEOUT_S: Final = 300
RUN_TIMEOUT_S: Final = 300
# 설치본 NOTICES에 반드시 있어야 하는 절 (Python 패키지·네이티브·예외·LicenseRef·원문·모델·
# 제거 프로그램·VC++ 고지)
NOTICE_SECTIONS: Final = (
    "numpy ",
    "# 네이티브 파일 (DLL·pyd·exe)과 그 안의 구성요소",
    "# 패키지별 라이선스 예외",
    "# SPDX 밖 배포 조건 (LicenseRef)",
    "# 네이티브 파일 근거 원문",
    "# OCR 모델",
    "Inno Setup License",
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
    log.parent.mkdir(parents=True, exist_ok=True)  # 로그를 못 쓰면 설치가 시작하지 않는다
    proc = subprocess.run(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CURRENTUSER",
            f"/DIR={target}",
            f"/LOG={log}",
        ],
        timeout=INSTALL_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"설치 종료 코드 {proc.returncode} (로그 {log})")


def user_path() -> str:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            value, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return ""
    return str(value)


def path_has(paths: str, folder: Path) -> bool:
    want = os.path.normcase(str(folder).rstrip("\\"))
    return any(os.path.normcase(p.rstrip("\\")) == want for p in paths.split(";") if p)


UNINSTALL_ROOT: Final = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


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
            values: dict[str, str] = {}
            with winreg.OpenKey(root, name) as key:
                vi = 0
                while True:
                    try:
                        vname, value, _ = winreg.EnumValue(key, vi)
                    except OSError:
                        break
                    vi += 1
                    values[vname] = str(value)
            out[name] = values
    return out


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
    """설치 파일 버전 정보의 ProductName (`kookabug.iss`의 VersionInfoProductName = 판 이름)."""
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
    # Inno Setup은 버전 문자열을 고정 길이 틀에 넣어 뒤가 공백으로 채워져 있다
    return ctypes.wstring_at(ptr.value or 0, max(length.value - 1, 0)).rstrip("\0 ")


def check_setup(setup: Path, variant: build.Variant) -> tuple[bool, str]:
    """설치 전 확인: 설치 파일이 그 판이고, 그 판의 제거 등록이 아직 없다. 제품 판이면 기존 제품
    설치(제거 등록)가 있을 때 멈춘다 — 같은 AppId로 덮어써 실제 설치의 등록을 잃게 하지 않는다."""
    name = setup_product_name(setup)
    if name != variant.app_name:
        return False, f"설치 파일 판이 {name!r}이다 (기대 {variant.app_name!r}). 설치하지 않는다"
    if variant.uninstall_key in uninstall_entries():
        return False, f"{variant.uninstall_key}가 이미 등록돼 있다. 설치하지 않는다"
    return True, f"{name} ({variant.uninstall_key})"


def uninstaller(root: Path) -> Path | None:
    found = sorted(root.glob("unins*.exe"))
    return found[0] if found else None


def uninstall(root: Path, *, timeout_s: float = UNINSTALL_TIMEOUT_S) -> None:
    """제거 프로그램은 임시 폴더로 자신을 복사해 다시 띄우고 먼저 끝날 수 있으므로, 설치 폴더가
    사라질 때까지 기다린다."""
    exe = uninstaller(root)
    if exe is None:
        raise RuntimeError(f"{root}에 제거 프로그램이 없다")
    proc = subprocess.run(
        [str(exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"제거 종료 코드 {proc.returncode}")
    deadline = time.monotonic() + timeout_s
    while root.exists() and time.monotonic() < deadline:
        time.sleep(0.5)


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
    return True, f"네이티브 파일 {len(report.files)}개, 문제 없음"


def notices_step(root: Path) -> tuple[bool, str]:
    text = (root / build.NOTICES).read_text(encoding="utf-8")
    missing = [s for s in NOTICE_SECTIONS if s not in text]
    return not missing, f"{len(text)}자, 빠진 절 {missing or '없음'}"


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
    env = python_free_env(root)
    report.step("env.python_free", lambda: check_env(root, env))
    report.step("cli.version", lambda: version_step(root, env))
    report.step("cli.doctor_headless", lambda: doctor_step(root, env))
    report.step("cli.smoke_graph", lambda: graph_step(root, env))
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

    기본은 테스트 전용 판(`build.TEST`)만 받는다: AppId·이름·폴더가 제품과 달라 이 PC의 실제 설치와
    겹치지 않는다. HKCU 제거 등록 전체를 앞뒤로 비교해, 설치 중에는 그 판의 키만 새로 생기고 제거
    뒤에는 처음과 똑같아야 한다."""
    report = SmokeReport(target)
    report.sizes["setup_bytes"] = setup.stat().st_size
    before = uninstall_entries()

    def do_install() -> tuple[bool, str]:
        install(setup, target, log)
        return True, str(target)

    def registration() -> tuple[bool, str]:
        now = uninstall_entries()
        added = sorted(set(now) - set(before))
        changed = sorted(k for k in before if now.get(k) != before[k])
        location = now.get(variant.uninstall_key, {}).get("InstallLocation", "")
        here = os.path.normcase(location.rstrip("\\")) == os.path.normcase(str(target))
        ok = added == [variant.uninstall_key] and not changed and here
        return ok, f"새 키 {added}, 바뀐 키 {changed or '없음'}, InstallLocation={location!r}"

    def on_path() -> tuple[bool, str]:
        bin_dir = target / build.BIN
        return path_has(user_path(), bin_dir), f"사용자 PATH에 {bin_dir}"

    def do_uninstall() -> tuple[bool, str]:
        uninstall(target)
        return True, "제거 프로그램 끝"

    def registry_restored() -> tuple[bool, str]:
        now = uninstall_entries()
        added = sorted(set(now) - set(before))
        lost = sorted(set(before) - set(now))
        changed = sorted(k for k in before if k in now and now[k] != before[k])
        ok = not added and not lost and not changed
        return (
            ok,
            f"남은 키 {added or '없음'}, 사라진 키 {lost or '없음'}, 바뀐 키 {changed or '없음'}",
        )

    if not report.step("setup.variant", lambda: check_setup(setup, variant)).ok:
        return report
    if report.step("install", do_install).ok:
        report.step("install.registration", registration)
        report.step("install.path", on_path)
        smoke_installed(report)
    if not keep and uninstaller(target) is not None:
        report.step("uninstall", do_uninstall)
        report.step("uninstall.clean", lambda: removed_step(target))
        report.step("uninstall.registry", registry_restored)
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
