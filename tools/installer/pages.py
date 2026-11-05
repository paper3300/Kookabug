"""설치 파일의 첫 화면 읽기 (M2 사람 확인 S3 결함: 설치 범위 화면).

설치 파일을 **보이지 않는 새 데스크톱**에서 띄워(사용자 화면에 창이 뜨지 않는다) 설치
마법사가 처음 보이는 화면의 컨트롤(종류·글자·켜짐·컨트롤 ID·라디오 단추 여부)을 읽고,
아무것도 누르지 않은 채 Job으로 끝낸다. 설치는 하지 않는다. NSIS가 푸는 플러그인 임시 폴더는
따로 만든 TEMP에 두고 지운다.

    uv run python -X utf8 tools/installer/pages.py <setup.exe>
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes as w
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from kookabug_core.win.job import Job

__all__ = ["BACK_ID", "Control", "Page", "first_page"]

BACK_ID: Final = 3
"""NSIS 마법사의 "뒤로" 단추 컨트롤 ID (다음 1, 취소 2)."""

_GENERIC_ALL: Final = 0x10000000
_CREATE_SUSPENDED: Final = 0x00000004
_CREATE_UNICODE_ENVIRONMENT: Final = 0x00000400
_WM_GETTEXT: Final = 0x000D
_GWL_STYLE: Final = -16
_BS_TYPEMASK: Final = 0x0F
_RADIO_STYLES: Final = frozenset({0x04, 0x09})  # BS_RADIOBUTTON, BS_AUTORADIOBUTTON

_WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("lpReserved", w.LPWSTR),
        ("lpDesktop", w.LPWSTR),
        ("lpTitle", w.LPWSTR),
        ("dwX", w.DWORD),
        ("dwY", w.DWORD),
        ("dwXSize", w.DWORD),
        ("dwYSize", w.DWORD),
        ("dwXCountChars", w.DWORD),
        ("dwYCountChars", w.DWORD),
        ("dwFillAttribute", w.DWORD),
        ("dwFlags", w.DWORD),
        ("wShowWindow", w.WORD),
        ("cbReserved2", w.WORD),
        ("lpReserved2", w.LPVOID),
        ("hStdInput", w.HANDLE),
        ("hStdOutput", w.HANDLE),
        ("hStdError", w.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", w.HANDLE),
        ("hThread", w.HANDLE),
        ("dwProcessId", w.DWORD),
        ("dwThreadId", w.DWORD),
    ]


def _dlls() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.CreateDesktopW.restype = w.HANDLE
    u32.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPVOID, w.DWORD, w.DWORD, w.LPVOID]
    u32.SetThreadDesktop.argtypes = [w.HANDLE]
    u32.CloseDesktop.argtypes = [w.HANDLE]
    u32.EnumDesktopWindows.argtypes = [w.HANDLE, _WNDENUMPROC, w.LPARAM]
    u32.EnumChildWindows.argtypes = [w.HWND, _WNDENUMPROC, w.LPARAM]
    u32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    u32.IsWindowVisible.argtypes = [w.HWND]
    u32.IsWindowEnabled.argtypes = [w.HWND]
    u32.GetDlgCtrlID.argtypes = [w.HWND]
    u32.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
    u32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    u32.SendMessageW.restype = w.LPARAM
    k32.CreateProcessW.argtypes = [
        w.LPCWSTR,
        w.LPWSTR,
        w.LPVOID,
        w.LPVOID,
        w.BOOL,
        w.DWORD,
        w.LPVOID,
        w.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInformation),
    ]
    k32.ResumeThread.argtypes = [w.HANDLE]
    k32.CloseHandle.argtypes = [w.HANDLE]
    return k32, u32


@dataclass(frozen=True, slots=True)
class Control:
    """마법사 창의 보이는 자식 컨트롤 하나."""

    cls: str
    text: str
    ctrl_id: int
    enabled: bool
    radio: bool


@dataclass(frozen=True, slots=True)
class Page:
    """설치 마법사가 처음 보인 화면 (단추가 있는 첫 대화 상자 — 설치 파일 확인 표시는 지나친 뒤)."""

    title: str
    controls: tuple[Control, ...]

    def by_id(self, ctrl_id: int) -> list[Control]:
        return [c for c in self.controls if c.ctrl_id == ctrl_id]

    @property
    def radios(self) -> list[Control]:
        return [c for c in self.controls if c.radio]

    @property
    def edits(self) -> list[str]:
        return [c.text for c in self.controls if c.cls == "Edit"]


def _text(u32: ctypes.WinDLL, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(1024)
    u32.SendMessageW(hwnd, _WM_GETTEXT, len(buf), ctypes.addressof(buf))
    return buf.value


def _class(u32: ctypes.WinDLL, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def _snapshot(u32: ctypes.WinDLL, desk: int, pids: set[int]) -> list[Page]:
    pages: list[Page] = []

    def top(hwnd: int, _l: int) -> bool:
        pid = w.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids or not u32.IsWindowVisible(hwnd):
            return True
        if _class(u32, hwnd) != "#32770":
            return True
        controls: list[Control] = []

        def child(h: int, _l: int) -> bool:
            if u32.IsWindowVisible(h):
                cls = _class(u32, h)
                style = int(u32.GetWindowLongW(h, _GWL_STYLE)) & _BS_TYPEMASK
                controls.append(
                    Control(
                        cls=cls,
                        text=_text(u32, h),
                        ctrl_id=int(u32.GetDlgCtrlID(h)),
                        enabled=bool(u32.IsWindowEnabled(h)),
                        radio=cls == "Button" and style in _RADIO_STYLES,
                    )
                )
            return True

        u32.EnumChildWindows(hwnd, _WNDENUMPROC(child), 0)
        pages.append(Page(_text(u32, hwnd), tuple(controls)))
        return True

    u32.EnumDesktopWindows(desk, _WNDENUMPROC(top), 0)
    return pages


def _ready(page: Page) -> bool:
    """마법사 화면: "다음"(ID 1)·"취소"(ID 2) 단추가 보인다 (설치 파일 확인 표시에는 단추가
    없다)."""
    return bool(page.by_id(1)) and bool(page.by_id(2))


def first_page(setup: Path, *, timeout_s: float = 60.0, settle_s: float = 1.0) -> Page:
    """`setup`을 보이지 않는 데스크톱에서 띄워 처음 보인 마법사 화면을 읽고 끝낸다. 화면이
    `settle_s` 동안 그대로일 때 확정한다(전환 중 화면을 읽지 않게). `timeout_s` 안에 나오지
    않으면 TimeoutError."""
    k32, u32 = _dlls()
    name = f"kb-setup-probe-{os.getpid()}-{time.monotonic_ns()}"
    desk = u32.CreateDesktopW(name, None, None, 0, _GENERIC_ALL, None)
    if not desk:
        raise ctypes.WinError(ctypes.get_last_error())
    temp = Path(tempfile.mkdtemp(prefix="kb-setup-probe-"))
    job = Job.create()
    try:
        env = {**os.environ, "TEMP": str(temp), "TMP": str(temp)}
        block = "".join(f"{k}={v}\0" for k, v in env.items()) + "\0"
        env_buf = ctypes.create_unicode_buffer(block, len(block))
        si = _StartupInfo()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = f"winsta0\\{name}"
        pi = _ProcessInformation()
        cmd = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(setup)]))
        flags = _CREATE_SUSPENDED | _CREATE_UNICODE_ENVIRONMENT
        if not k32.CreateProcessW(
            None, cmd, None, None, False, flags, env_buf, None, ctypes.byref(si), ctypes.byref(pi)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            job.assign(int(pi.dwProcessId))
            k32.ResumeThread(pi.hThread)
            return _watch(u32, int(desk), job, int(pi.dwProcessId), timeout_s, settle_s)
        finally:
            k32.CloseHandle(pi.hThread)
            k32.CloseHandle(pi.hProcess)
    finally:
        job.terminate()
        job.close()
        u32.CloseDesktop(desk)
        _remove(temp)


def _watch(
    u32: ctypes.WinDLL, desk: int, job: Job, pid: int, timeout_s: float, settle_s: float
) -> Page:
    """그 데스크톱의 창은 그 데스크톱에 붙은 스레드에서만 읽을 수 있다 — 새 스레드에서 읽는다."""
    result: list[Page] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            if not u32.SetThreadDesktop(desk):
                raise ctypes.WinError(ctypes.get_last_error())
            end = time.monotonic() + timeout_s
            seen: Page | None = None
            since = 0.0
            while time.monotonic() < end:
                pids = {pid, *job.process_ids()}
                pages = [p for p in _snapshot(u32, desk, pids) if _ready(p)]
                now = time.monotonic()
                if seen is not None and len(pages) == 1 and pages[0] == seen:
                    if now - since >= settle_s:
                        result.append(seen)
                        return
                elif pages:
                    seen, since = pages[0], now
                time.sleep(0.1)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, name="setup-page-probe", daemon=True)
    thread.start()
    thread.join(timeout_s + 10)
    if errors:
        raise errors[0]
    if not result:
        raise TimeoutError(f"{timeout_s}초 안에 설치 마법사 화면이 보이지 않았다")
    return result[0]


def _remove(path: Path) -> None:
    for _ in range(20):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.25)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("사용: pages.py <setup.exe>", file=sys.stderr)
        return 2
    page = first_page(Path(args[0]))
    print(json.dumps(asdict(page), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
