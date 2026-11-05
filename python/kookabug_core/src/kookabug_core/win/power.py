"""프로세스 전력 제한(EcoQoS) 끄기 (M2 사람 확인 S 결함 ②).

Windows 11은 창이 없는 뒤쪽 프로세스(데스크톱 앱·데몬이 띄운 runner)의 실행 속도를 낮출 수 있다
(EcoQoS: 하이브리드 CPU면 효율 코어, 낮은 클럭). 로컬 계측 한 번에서는 같은 그림의 OCR 읽기가
160 ms → 몇 초 뒤 720 ms로 느려졌다가 이것을 끄면 그대로였지만, 독립 재계측에서는 효과가 재현되지
않았다 — Sandbox 증상의 주효 원인 후보는 onnxruntime 스핀이고(`ocr.engine.OnnxSession`), 이것은
보조 조치다. runner는 시작할 때 `keep_full_speed()`로 실행 속도 제한에서 빠진다 — 관측 기한과 영상
칸 간격이 프로세스를 띄운 쪽(콘솔·앱)에 따라 달라지지 않게. 지원하지 않는 Windows(10 1709 이전)면
아무것도 하지 않는다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Final

from kookabug_core.win import _kernel32 as k

__all__ = ["full_speed", "keep_full_speed"]

_PROCESS_POWER_THROTTLING: Final = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling
_VERSION: Final = 1  # PROCESS_POWER_THROTTLING_CURRENT_VERSION
_EXECUTION_SPEED: Final = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED


class _State(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.ULONG),
        ("ControlMask", wintypes.ULONG),
        ("StateMask", wintypes.ULONG),
    ]


_set = k.kernel32.SetProcessInformation
_set.restype = wintypes.BOOL
_set.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
_get = k.kernel32.GetProcessInformation
_get.restype = wintypes.BOOL
_get.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]


def keep_full_speed() -> bool:
    """이 프로세스를 실행 속도 제한(EcoQoS)에서 뺀다 (제어 = 실행 속도, 상태 = 끔). 성공하면 True,
    지원하지 않거나 실패하면 False (그대로 진행한다)."""
    state = _State(_VERSION, _EXECUTION_SPEED, 0)
    size = ctypes.sizeof(state)
    return bool(_set(k.GetCurrentProcess(), _PROCESS_POWER_THROTTLING, ctypes.byref(state), size))


def full_speed() -> bool | None:
    """이 프로세스가 실행 속도 제한에서 빠져 있나: 빠져 있으면 True, 시스템에 맡겼거나 켜져 있으면
    False, 읽을 수 없으면 None (검사용. 다른 프로세스의 값은 이 API로 읽히지 않는다)."""
    state = _State(_VERSION, 0, 0)
    size = ctypes.sizeof(state)
    if not _get(k.GetCurrentProcess(), _PROCESS_POWER_THROTTLING, ctypes.byref(state), size):
        return None
    return bool(state.ControlMask & _EXECUTION_SPEED) and not state.StateMask & _EXECUTION_SPEED
