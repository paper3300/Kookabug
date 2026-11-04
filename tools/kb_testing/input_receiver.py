"""검사용 입력 수신 창 (M4 계획 2.1 검수 H1·2차 N3, 녹화 훅 지연 검사).

경로로 띄우는 독립 스크립트다(ctypes·표준 라이브러리만): `python input_receiver.py --log FILE ...`.
받은 순간의 단조 시각(`time.monotonic_ns()` — 프로세스 사이에 같은 시계)을 로그 파일에 한 줄씩
쓴다. 첫 줄은 `{"hwnd": ...}`. 제어 폴더(`--control`)에 파일을 두면 50 ms 타이머가 읽고 지운다:

- `hang` (내용: 초): UI 스레드 전체를 그만큼 멈춘다 (메시지를 처리하지 않음)
- `korean`: 이 스레드 자판을 한국어로 올린다 / `native`·`alpha`: IME 변환 모드를 바꾼다
- `quit`: 창을 닫는다

`--hung`이면 창을 만든 뒤 메시지를 처리하지 않는다 (IME 조회 대상 바꿔 끼우기용 멈춘 창).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
imm32 = ctypes.WinDLL("imm32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

WM_DESTROY, WM_TIMER = 0x0002, 0x0113
WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN = 0x0100, 0x0104, 0x0201
WS_OVERLAPPEDWINDOW, WS_VISIBLE = 0x00CF0000, 0x10000000
KLF_ACTIVATE = 0x00000001
IME_CMODE_NATIVE = 0x0001


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = (
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
user32.SetTimer.restype = ctypes.c_size_t
user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID)
user32.GetMessageW.argtypes = (
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
)
user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DestroyWindow.argtypes = (wintypes.HWND,)
user32.PostQuitMessage.argtypes = (ctypes.c_int,)
user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
user32.LoadKeyboardLayoutW.argtypes = (wintypes.LPCWSTR, wintypes.UINT)
user32.SetProcessDpiAwarenessContext.argtypes = (wintypes.HANDLE,)
imm32.ImmGetContext.restype = wintypes.HANDLE
imm32.ImmGetContext.argtypes = (wintypes.HWND,)
imm32.ImmSetOpenStatus.argtypes = (wintypes.HANDLE, wintypes.BOOL)
imm32.ImmSetConversionStatus.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD)
imm32.ImmReleaseContext.argtypes = (wintypes.HWND, wintypes.HANDLE)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", required=True)
    parser.add_argument("--control", default=None)
    parser.add_argument("--title", default="kookabug input receiver")
    parser.add_argument("--x", type=int, default=100)
    parser.add_argument("--y", type=int, default=100)
    parser.add_argument("--w", type=int, default=400)
    parser.add_argument("--h", type=int, default=300)
    parser.add_argument("--hung", action="store_true")
    args = parser.parse_args()
    user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-4))  # Per-Monitor V2
    log = Path(args.log).open("a", encoding="utf-8", buffering=1)  # noqa: SIM115 — 프로세스 내내 연다
    control = Path(args.control) if args.control else None

    def write(item: dict[str, object]) -> None:
        log.write(json.dumps(item) + "\n")

    def set_mode(hwnd: int, native: bool) -> None:
        himc = imm32.ImmGetContext(hwnd)
        if himc:
            imm32.ImmSetOpenStatus(himc, True)
            imm32.ImmSetConversionStatus(himc, IME_CMODE_NATIVE if native else 0, 0)
            imm32.ImmReleaseContext(hwnd, himc)

    def check_control(hwnd: int) -> None:
        if control is None:
            return
        for name in ("hang", "korean", "native", "alpha", "quit"):
            path = control / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").strip()
            path.unlink()
            write({"control": name, "t_ns": time.monotonic_ns()})
            if name == "hang":
                time.sleep(float(text or "5"))
                write({"control": "unhang", "t_ns": time.monotonic_ns()})
            elif name == "korean":
                user32.LoadKeyboardLayoutW("00000412", KLF_ACTIVATE)
            elif name in ("native", "alpha"):
                set_mode(hwnd, name == "native")
            elif name == "quit":
                user32.DestroyWindow(hwnd)

    def proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_LBUTTONDOWN):
            write({"msg": msg, "wparam": int(wparam), "t_ns": time.monotonic_ns()})
        elif msg == WM_TIMER:
            check_control(hwnd)
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(proc)
    module = kernel32.GetModuleHandleW(None)
    klass = WNDCLASSW()
    klass.lpfnWndProc = wndproc
    klass.hInstance = module
    klass.lpszClassName = f"KookabugInputReceiver{int(time.monotonic_ns())}"
    user32.RegisterClassW(ctypes.byref(klass))
    hwnd = user32.CreateWindowExW(
        0,
        klass.lpszClassName,
        args.title,
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        args.x,
        args.y,
        args.w,
        args.h,
        None,
        None,
        module,
        None,
    )
    write({"hwnd": int(hwnd or 0), "pid": int(kernel32.GetCurrentProcessId())})
    if not hwnd:
        return 2
    if args.hung:
        time.sleep(600)  # 메시지를 처리하지 않는다
        return 0
    user32.SetTimer(hwnd, 1, 50, None)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
