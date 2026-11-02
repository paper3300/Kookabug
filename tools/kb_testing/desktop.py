"""데스크톱 검사 표시·실행 조건과 대화형 데스크톱 탐지 (구현 계획 M1 2.13).

표시: `desktop`(대화형 데스크톱: 창·WGC·예제 게임), `desktop_input`(실제 마우스·키보드,
desktop 포함), `soak`(장시간, desktop 포함).

실행 조건 `KOOKABUG_DESKTOP_TESTS`:
- `off`: 전부 건너뜀
- `auto`(기본): 세션당 한 번 탐지하고, 실패하면 이유를 적어 건너뜀
- `require`: 탐지 실패 = 검사 실패
`desktop_input`은 `KOOKABUG_DESKTOP_INPUT=1`, `soak`은 `KOOKABUG_SOAK=1`일 때만 돈다 (모드와 무관).

탐지는 별도 프로세스(`python -m kb_testing.desktop --json -`)에서 한다. 임시 창·WGC 세션이 pytest
프로세스에 남지 않게 하고, CI `desktop-probe` 잡과 같은 코드를 쓰기 위해서다. 입력은 보내지 않는다.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal

MODE_ENV: Final = "KOOKABUG_DESKTOP_TESTS"
INPUT_ENV: Final = "KOOKABUG_DESKTOP_INPUT"
SOAK_ENV: Final = "KOOKABUG_SOAK"
MARKERS: Final = ("desktop", "desktop_input", "soak")
DESKTOP_TIMEOUT_S: Final = 60
PROBE_TIMEOUT_S: Final = 30
FRAME_TIMEOUT_S: Final = 5.0
FOREGROUND_TIMEOUT_S: Final = 1.0
CHECK_IDS: Final = ("window_station", "input_desktop", "wgc_frame", "foreground")

TOOLS_DIR = Path(__file__).resolve().parents[1]


class Mode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    REQUIRE = "require"


def mode_from_env(env: Mapping[str, str]) -> Mode:
    raw = env.get(MODE_ENV, "").strip().lower() or Mode.AUTO.value
    try:
        return Mode(raw)
    except ValueError:
        raise ValueError(f"{MODE_ENV}는 off·auto·require 중 하나다: {raw!r}") from None


def _flag(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip() == "1"


# ---------------------------------------------------------------- 탐지 보고


@dataclass(frozen=True)
class ProbeCheck:
    id: str
    ok: bool
    detail: str
    elapsed_ms: int


@dataclass(frozen=True)
class ProbeReport:
    ok: bool
    checks: tuple[ProbeCheck, ...]
    elapsed_ms: int
    python: str
    windows: str
    session_id: int | None

    @property
    def reason(self) -> str:
        """실패한 검사의 `id: 사유` (통과면 빈 문자열)."""
        return "; ".join(f"{c.id}: {c.detail}" for c in self.checks if not c.ok)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checks"] = [asdict(c) for c in self.checks]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProbeReport:
        return cls(
            ok=bool(data["ok"]),
            checks=tuple(ProbeCheck(**c) for c in data["checks"]),
            elapsed_ms=int(data["elapsed_ms"]),
            python=str(data["python"]),
            windows=str(data["windows"]),
            session_id=data["session_id"],
        )

    @classmethod
    def failed(cls, check_id: str, detail: str) -> ProbeReport:
        """탐지 자체가 돌지 못했을 때."""
        return cls(
            ok=False,
            checks=(ProbeCheck(check_id, False, detail, 0),),
            elapsed_ms=0,
            python=platform.python_version(),
            windows=platform.version(),
            session_id=None,
        )


# ---------------------------------------------------------------- 실행 조건


@dataclass(frozen=True)
class Decision:
    action: Literal["run", "skip", "fail"]
    reason: str = ""


def decide(
    markers: Collection[str], env: Mapping[str, str], probe: Callable[[], ProbeReport]
) -> Decision:
    """검사 하나의 표시와 환경으로 실행·건너뜀·실패를 정한다. 탐지는 필요할 때만 부른다."""
    marks = set(markers) & set(MARKERS)
    if not marks:
        return Decision("run")
    mode = mode_from_env(env)
    if mode is Mode.OFF:
        return Decision("skip", f"데스크톱 검사 끔 ({MODE_ENV}=off)")
    if "desktop_input" in marks and not _flag(env, INPUT_ENV):
        return Decision("skip", f"실제 입력 검사는 {INPUT_ENV}=1일 때만 돈다")
    if "soak" in marks and not _flag(env, SOAK_ENV):
        return Decision("skip", f"장시간 검사는 {SOAK_ENV}=1일 때만 돈다")
    report = probe()
    if report.ok:
        return Decision("run")
    reason = f"대화형 데스크톱 탐지 실패 — {report.reason}"
    if mode is Mode.REQUIRE:
        return Decision("fail", f"{reason} ({MODE_ENV}=require)")
    return Decision("skip", reason)


def probe_in_subprocess(timeout: float = PROBE_TIMEOUT_S) -> ProbeReport:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(TOOLS_DIR), env.get("PYTHONPATH", "")) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "kb_testing.desktop", "--json", "-", "--no-fail"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeReport.failed("probe", f"탐지 프로세스가 {timeout:g}초 안에 끝나지 않았다")
    try:
        return ProbeReport.from_dict(json.loads(proc.stdout))
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        tail = (proc.stderr or proc.stdout).strip()[-500:]
        return ProbeReport.failed("probe", f"탐지 결과를 읽을 수 없다 ({exc}): {tail}")


_session_report: ProbeReport | None = None


def session_probe() -> ProbeReport:
    """세션당 한 번 탐지한다."""
    global _session_report
    if _session_report is None:
        _session_report = probe_in_subprocess()
    return _session_report


def session_probe_result() -> ProbeReport | None:
    """이 세션에서 탐지했으면 그 결과 (요약 출력용)."""
    return _session_report


def require_desktop(markers: Sequence[str] = ("desktop",)) -> None:
    """픽스처·검사 안에서 데스크톱 조건을 확인한다 (표시 없이 쓰는 헬퍼용)."""
    import pytest

    decision = decide(markers, os.environ, session_probe)
    if decision.action == "skip":
        pytest.skip(decision.reason)
    if decision.action == "fail":
        pytest.fail(decision.reason, pytrace=False)


# ---------------------------------------------------------------- Win32 (탐지 전용)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

UOI_FLAGS = 1
UOI_NAME = 2
WSF_VISIBLE = 0x0001
DESKTOP_READOBJECTS = 0x0001
DESKTOP_SWITCHDESKTOP = 0x0100
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
COLOR_WINDOW = 5
PM_REMOVE = 0x0001
SW_SHOW = 5


class USEROBJECTFLAGS(ctypes.Structure):
    _fields_ = (
        ("fInherit", wintypes.BOOL),
        ("fReserved", wintypes.BOOL),
        ("dwFlags", wintypes.DWORD),
    )


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    )


def _sig(fn: Any, restype: Any, *argtypes: Any) -> Any:
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


_GetProcessWindowStation = _sig(_user32.GetProcessWindowStation, wintypes.HANDLE)
_GetUserObjectInformationW = _sig(
    _user32.GetUserObjectInformationW,
    wintypes.BOOL,
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
_OpenInputDesktop = _sig(
    _user32.OpenInputDesktop, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
)
_CloseDesktop = _sig(_user32.CloseDesktop, wintypes.BOOL, wintypes.HANDLE)
_DefWindowProcW = _sig(
    _user32.DefWindowProcW,
    wintypes.LPARAM,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_RegisterClassExW = _sig(_user32.RegisterClassExW, wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
_UnregisterClassW = _sig(
    _user32.UnregisterClassW, wintypes.BOOL, wintypes.LPCWSTR, wintypes.HINSTANCE
)
_CreateWindowExW = _sig(
    _user32.CreateWindowExW,
    wintypes.HWND,
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
)
_DestroyWindow = _sig(_user32.DestroyWindow, wintypes.BOOL, wintypes.HWND)
_PeekMessageW = _sig(
    _user32.PeekMessageW,
    wintypes.BOOL,
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
)
_TranslateMessage = _sig(_user32.TranslateMessage, wintypes.BOOL, ctypes.POINTER(wintypes.MSG))
_DispatchMessageW = _sig(_user32.DispatchMessageW, wintypes.LPARAM, ctypes.POINTER(wintypes.MSG))
_GetForegroundWindow = _sig(_user32.GetForegroundWindow, wintypes.HWND)
_SetForegroundWindow = _sig(_user32.SetForegroundWindow, wintypes.BOOL, wintypes.HWND)
_BringWindowToTop = _sig(_user32.BringWindowToTop, wintypes.BOOL, wintypes.HWND)
_ShowWindow = _sig(_user32.ShowWindow, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
_GetWindowThreadProcessId = _sig(
    _user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
)
_AttachThreadInput = _sig(
    _user32.AttachThreadInput, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL
)
_GetCurrentThreadId = _sig(_kernel32.GetCurrentThreadId, wintypes.DWORD)
_GetModuleHandleW = _sig(_kernel32.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
_ProcessIdToSessionId = _sig(
    _kernel32.ProcessIdToSessionId, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)
)


_wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0


class _WtsInfoExHead(ctypes.Structure):
    # WTSINFOEXW { DWORD Level; union { WTSINFOEX_LEVEL1_W } }의 앞부분. 공용체는 8바이트 정렬
    _fields_ = (
        ("Level", wintypes.DWORD),
        ("_pad", wintypes.DWORD),
        ("SessionId", wintypes.ULONG),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", wintypes.LONG),
    )


_WTSQuerySessionInformationW = _sig(
    _wtsapi32.WTSQuerySessionInformationW,
    wintypes.BOOL,
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
)
_WTSFreeMemory = _sig(_wtsapi32.WTSFreeMemory, None, ctypes.c_void_p)


def _last_error() -> str:
    code = ctypes.get_last_error()
    return f"Win32 오류 {code}: {ctypes.FormatError(code).strip()}"


def _object_name(handle: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    needed = wintypes.DWORD()
    if not _GetUserObjectInformationW(handle, UOI_NAME, buf, ctypes.sizeof(buf), needed):
        return "?"
    return buf.value


def _check_window_station() -> tuple[bool, str]:
    station = _GetProcessWindowStation()
    if not station:
        return False, f"창 스테이션 없음 ({_last_error()})"
    name = _object_name(station)
    flags = USEROBJECTFLAGS()
    if not _GetUserObjectInformationW(
        station, UOI_FLAGS, ctypes.byref(flags), ctypes.sizeof(flags), None
    ):
        return False, f"{name}: 플래그를 읽을 수 없다 ({_last_error()})"
    visible = bool(flags.dwFlags & WSF_VISIBLE)
    ok = name.casefold() == "winsta0" and visible
    return ok, f"{name}, {'대화형' if visible else '비대화형(서비스 세션)'}"


def session_locked() -> bool | None:
    """이 세션이 잠겨 있는가 (WTS 세션 플래그, 모르면 None).

    Windows 10·11의 잠금 화면(LockApp)은 Default 데스크톱 위에 뜨므로 `OpenInputDesktop`만으로는
    잠금을 알 수 없다.
    """
    buf = ctypes.c_void_p()
    size = wintypes.DWORD()
    if not _WTSQuerySessionInformationW(
        None, WTS_CURRENT_SESSION, WTS_SESSION_INFO_EX, ctypes.byref(buf), ctypes.byref(size)
    ):
        return None
    try:
        info = ctypes.cast(buf, ctypes.POINTER(_WtsInfoExHead)).contents
        if info.Level != 1 or info.SessionFlags not in (WTS_SESSIONSTATE_LOCK, 1):
            return None
        return info.SessionFlags == WTS_SESSIONSTATE_LOCK
    finally:
        _WTSFreeMemory(buf)


def _check_input_desktop() -> tuple[bool, str]:
    desk = _OpenInputDesktop(0, False, DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP)
    if not desk:
        return (
            False,
            f"입력 데스크톱을 열 수 없다 — 잠금 화면·UAC 화면이거나 세션 없음 ({_last_error()})",
        )
    try:
        name = _object_name(desk)
    finally:
        _CloseDesktop(desk)
    locked = session_locked()
    if locked:
        return False, f"입력 데스크톱 {name}, 세션이 잠겨 있다"
    state = "세션 잠금 상태 모름" if locked is None else "세션 열림"
    return name.casefold() == "default", f"입력 데스크톱 {name}, {state}"


class _TempWindow:
    """탐지용 임시 창. 자기 스레드에서 만들고 메시지를 돌린다."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.hwnd = 0
        self.thread_id = 0
        self.error = ""
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="kb-desktop-probe", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def _run(self) -> None:
        hinst = _GetModuleHandleW(None)
        cls_name = f"KookabugDesktopProbe{os.getpid()}"
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        # 메시지 처리는 기본 창 프로시저 그대로
        wc.lpfnWndProc = ctypes.cast(_DefWindowProcW, ctypes.c_void_p).value
        wc.hInstance = hinst
        wc.hbrBackground = COLOR_WINDOW + 1
        wc.lpszClassName = cls_name
        try:
            if not _RegisterClassExW(ctypes.byref(wc)):
                self.error = f"창 클래스 등록 실패 ({_last_error()})"
                return
            hwnd = _CreateWindowExW(
                0,
                cls_name,
                self.title,
                WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                120,
                120,
                360,
                220,
                None,
                None,
                hinst,
                None,
            )
            if not hwnd:
                self.error = f"창 생성 실패 ({_last_error()})"
                return
            self.hwnd = hwnd
            self.thread_id = _GetCurrentThreadId()
            self._ready.set()
            msg = wintypes.MSG()
            while not self._stop.is_set():
                while _PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    _TranslateMessage(ctypes.byref(msg))
                    _DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.01)
            _DestroyWindow(hwnd)
        finally:
            self._ready.set()
            _UnregisterClassW(cls_name, hinst)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(5)


@contextmanager
def _temp_window() -> Iterator[_TempWindow]:
    win = _TempWindow(f"Kookabug desktop probe {os.getpid()}")
    try:
        yield win
    finally:
        win.close()


def _check_wgc_frame(win: _TempWindow) -> tuple[bool, str]:
    try:
        from windows_capture import WindowsCapture
    except ImportError as exc:
        return False, f"windows_capture를 불러올 수 없다 ({exc})"
    from kb_testing.sample_game import keep_process_mta

    try:
        keep_process_mta()  # 제품 캡처와 같은 MTA 수명 규칙 (sample_game.keep_process_mta)
    except OSError as exc:
        return False, f"프로세스 MTA를 유지할 수 없다 ({exc})"
    got = threading.Event()
    seen: dict[str, Any] = {}
    try:
        capture = WindowsCapture(cursor_capture=False, window_hwnd=win.hwnd)
    except Exception as exc:
        return False, f"WGC 세션 생성 실패 ({exc})"

    @capture.event
    def on_frame_arrived(frame: Any, control: Any) -> None:
        seen.setdefault("size", (frame.width, frame.height))
        got.set()
        control.stop()

    @capture.event
    def on_closed() -> None:
        seen.setdefault("closed", True)
        got.set()

    try:
        control = capture.start_free_threaded()
    except Exception as exc:
        return False, f"WGC 시작 실패 ({exc})"
    try:
        got.wait(FRAME_TIMEOUT_S)
    finally:
        control.stop()
        deadline = time.monotonic() + 2
        while not control.is_finished() and time.monotonic() < deadline:
            time.sleep(0.02)
    if "size" in seen:
        w, h = seen["size"]
        return True, f"임시 창 한 프레임 {w}x{h}"
    if seen.get("closed"):
        return False, "첫 프레임 전에 WGC 세션이 닫혔다"
    return False, f"{FRAME_TIMEOUT_S:g}초 안에 WGC 프레임이 오지 않았다"


def _check_foreground(win: _TempWindow) -> tuple[bool, str]:
    """임시 창을 포그라운드로 가져온다. 입력은 보내지 않는다. 끝나면 앞 창을 되돌린다."""
    previous = _GetForegroundWindow()
    fg_thread = _GetWindowThreadProcessId(previous, None) if previous else 0
    me = _GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and _AttachThreadInput(me, fg_thread, True))
    try:
        _ShowWindow(win.hwnd, SW_SHOW)
        _BringWindowToTop(win.hwnd)
        _SetForegroundWindow(win.hwnd)
    finally:
        if attached:
            _AttachThreadInput(me, fg_thread, False)
    deadline = time.monotonic() + FOREGROUND_TIMEOUT_S
    while time.monotonic() < deadline:
        if _GetForegroundWindow() == win.hwnd:
            break
        time.sleep(0.02)
    ok = _GetForegroundWindow() == win.hwnd
    if ok and previous:
        _SetForegroundWindow(previous)
    if ok:
        return True, "임시 창을 포그라운드로 가져왔다"
    return False, "포그라운드를 가져올 수 없다 (포그라운드 잠금 또는 대화형 데스크톱 아님)"


def _timed(check_id: str, fn: Callable[[], tuple[bool, str]]) -> ProbeCheck:
    start = time.perf_counter()
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return ProbeCheck(check_id, ok, detail, round((time.perf_counter() - start) * 1000))


def run_probe() -> ProbeReport:
    """이 프로세스에서 탐지한다. 실패한 검사가 있어도 나머지를 돌려 이유를 전부 남긴다."""
    start = time.perf_counter()
    checks = [
        _timed("window_station", _check_window_station),
        _timed("input_desktop", _check_input_desktop),
    ]
    with _temp_window() as win:
        if not win.hwnd:
            detail = win.error or "임시 창을 만들 수 없다"
            checks += [ProbeCheck(c, False, detail, 0) for c in ("wgc_frame", "foreground")]
        else:
            checks.append(_timed("wgc_frame", lambda: _check_wgc_frame(win)))
            checks.append(_timed("foreground", lambda: _check_foreground(win)))
    session = wintypes.DWORD()
    session_id = session.value if _ProcessIdToSessionId(os.getpid(), session) else None
    return ProbeReport(
        ok=all(c.ok for c in checks),
        checks=tuple(checks),
        elapsed_ms=round((time.perf_counter() - start) * 1000),
        python=platform.python_version(),
        windows=platform.version(),
        session_id=session_id,
    )


# ---------------------------------------------------------------- 명령줄


def summary_markdown(report: ProbeReport) -> str:
    lines = [
        "### 데스크톱 탐지 (WGC·SendInput 가능 여부)",
        "",
        f"결과: **{'통과' if report.ok else '실패'}** · 세션 {report.session_id} · "
        f"Windows {report.windows} · Python {report.python} · {report.elapsed_ms} ms",
        "",
        "| 검사 | 결과 | 내용 | ms |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {c.id} | {'통과' if c.ok else '실패'} | {c.detail} | {c.elapsed_ms} |"
        for c in report.checks
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    from kookabug_sdk.console import utf8_stdio

    # argparse의 --help·오류 메시지도 한국어라 cp1252 콘솔에서 먼저 UTF-8로 바꾼다
    utf8_stdio()
    parser = argparse.ArgumentParser(description="대화형 데스크톱 탐지 (입력은 보내지 않는다)")
    parser.add_argument("--json", help="결과 JSON을 쓸 파일 (- = 표준 출력)")
    parser.add_argument("--summary", help="마크다운 요약을 덧붙일 파일 (CI 잡 요약)")
    parser.add_argument("--no-fail", action="store_true", help="탐지가 실패해도 종료 코드 0")
    args = parser.parse_args(argv)

    report = run_probe()
    text = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    if args.json == "-":
        print(text)
    else:
        if args.json:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        print(summary_markdown(report))
    if args.summary:
        with Path(args.summary).open("a", encoding="utf-8") as f:
            f.write(summary_markdown(report))
    return 0 if report.ok or args.no_fail else 1


if __name__ == "__main__":
    sys.exit(main())
