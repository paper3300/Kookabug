"""프로세스 DPI 인식을 Per-Monitor V2로 (구현 계획 M1 2.2).

runner와 좌표를 쓰는 CLI 명령(`target test`·`screen test`·`doctor`)은 진입점 첫 줄에서
`enable_at_startup()`을 부른다. 창 API를 쓰기 전에 정해야 하고, 프로세스 수준 설정은 한 번만 바꿀 수
있다. 감독자는 부르지 않는다 — 좌표 없이 떼기만 하고, CLI·서비스·검사 프로세스 안에서 돌기
때문이다(`supervisor.py`). 플랫폼 패키지(`kookabug_platform`)를 불러오지 않고 여기
두는 이유: 코어는 `platform.kind`가 `windows`일 때만 그 패키지를 불러오지만, 인식 수준은 그보다
먼저(실행 사양을 읽기 전) 정해야 한다.

실패해도 진입점은 계속 간다(`none`·`fake` 실행은 창을 쓰지 않는다). 결과는 `startup_error()`로
남고, 창·캡처·입력을 쓰는 쪽(`kind: windows` 시작, 좌표 CLI)이 그것을 확인해
`dpi_awareness_unavailable`로 끝낸다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

__all__ = [
    "CODE",
    "DpiAwarenessUnavailable",
    "current_awareness",
    "enable_at_startup",
    "ensure_per_monitor_v2",
    "is_per_monitor_v2",
    "startup_error",
]

CODE: Final = "dpi_awareness_unavailable"

# DPI_AWARENESS_CONTEXT 의사 핸들
_CONTEXTS: Final = {
    "unaware": -1,
    "system": -2,
    "per_monitor": -3,
    "per_monitor_v2": -4,
    "unaware_gdiscaled": -5,
}
_PMV2: Final = _CONTEXTS["per_monitor_v2"]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SetProcessDpiAwarenessContext = _user32.SetProcessDpiAwarenessContext
_SetProcessDpiAwarenessContext.restype = wintypes.BOOL
_SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
_GetThreadDpiAwarenessContext = _user32.GetThreadDpiAwarenessContext
_GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
_GetThreadDpiAwarenessContext.argtypes = ()
_AreDpiAwarenessContextsEqual = _user32.AreDpiAwarenessContextsEqual
_AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
_AreDpiAwarenessContextsEqual.argtypes = (ctypes.c_void_p, ctypes.c_void_p)


class DpiAwarenessUnavailable(RuntimeError):
    """이 프로세스를 Per-Monitor V2로 둘 수 없다 (이미 다른 수준으로 정해짐 등)."""

    code: Final = CODE


def current_awareness() -> str:
    """이 스레드의 DPI 인식 수준 이름 (`unaware`·`system`·`per_monitor`·`per_monitor_v2`·
    `unaware_gdiscaled`, 모르면 `unknown`)."""
    context = _GetThreadDpiAwarenessContext()
    for name, value in _CONTEXTS.items():
        if _AreDpiAwarenessContextsEqual(context, ctypes.c_void_p(value)):
            return name
    return "unknown"


def is_per_monitor_v2() -> bool:
    # PMv1과 PMv2는 GetAwarenessFromDpiAwarenessContext가 같은 값을 주므로 문맥끼리 비교한다
    return bool(_AreDpiAwarenessContextsEqual(_GetThreadDpiAwarenessContext(), _PMV2))


def ensure_per_monitor_v2() -> None:
    """프로세스를 Per-Monitor V2로 정하고 확인한다. 이미 PMv2면 그대로 통과(여러 번 불러도 된다).

    프로세스 수준이 이미 다른 값(매니페스트·앞선 호출)이면 바꿀 수 없으므로
    `DpiAwarenessUnavailable`.
    """
    if _SetProcessDpiAwarenessContext(_PMV2):
        if is_per_monitor_v2():
            return
        raise DpiAwarenessUnavailable(
            f"Per-Monitor V2를 설정했는데 이 스레드는 {current_awareness()}다"
        )
    err = ctypes.get_last_error()
    if is_per_monitor_v2():
        return  # 이미 PMv2 (ERROR_ACCESS_DENIED)
    raise DpiAwarenessUnavailable(
        f"DPI 인식을 Per-Monitor V2로 바꿀 수 없다: 이미 {current_awareness()} "
        f"(Win32 오류 {err}: {ctypes.FormatError(err).strip()})"
    )


_startup_error: str | None = None
_startup_done = False


def enable_at_startup() -> str | None:
    """진입점용: PMv2로 정하고 결과를 남긴다. 실패 사유(없으면 None)를 돌려준다."""
    global _startup_error, _startup_done
    try:
        ensure_per_monitor_v2()
        _startup_error = None
    except DpiAwarenessUnavailable as exc:
        _startup_error = str(exc)
    _startup_done = True
    return _startup_error


def startup_error() -> str | None:
    """`enable_at_startup()`의 실패 사유. 부르지 않았으면 그 사실을 사유로 준다."""
    if not _startup_done:
        return "진입점에서 DPI 인식을 정하지 않았다 (enable_at_startup 미호출)"
    return _startup_error
