"""DPI 인식과 좌표 변환 (구현 계획 M1 2.2).

프로세스 수준은 한 번만 바꿀 수 있어 하위 프로세스로 본다.
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys

from kookabug_platform.dpi import (
    client_to_screen,
    normalized_to_pixels,
    offset_point,
    round_half_up,
)

# 하위 프로세스: (먼저 다른 수준으로 정하고) 진입점 함수 → 플랫폼 확인 함수
_PROBE = """
import ctypes, json, sys
pre = json.loads(sys.argv[1])
if pre is not None:
    ctypes.windll.user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    assert ctypes.windll.user32.SetProcessDpiAwarenessContext(pre)
from kookabug_core.win import dpi
startup = dpi.enable_at_startup()
from kookabug_platform.dpi import ensure_per_monitor_v2
from kookabug_platform.errors import PlatformError
try:
    ensure_per_monitor_v2()
    code = None
except PlatformError as exc:
    code = exc.code
print(json.dumps({"startup": startup, "after": dpi.startup_error(), "code": code,
                  "awareness": dpi.current_awareness(), "pmv2": dpi.is_per_monitor_v2()}))
"""


def probe(pre: int | None) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(pre)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_per_monitor_v2_set_and_verified() -> None:
    out = probe(None)
    assert out == {
        "startup": None,
        "after": None,
        "code": None,  # 두 번째 호출(이미 PMv2)도 통과
        "awareness": "per_monitor_v2",
        "pmv2": True,
    }


def test_already_set_other_mode_is_error() -> None:
    for pre, name in ((-2, "system"), (-3, "per_monitor")):  # PMv1도 PMv2가 아니다
        out = probe(pre)
        assert out["code"] == "dpi_awareness_unavailable"
        assert out["awareness"] == name and out["pmv2"] is False
        assert isinstance(out["startup"], str) and name in out["startup"]
        assert out["after"] == out["startup"]


def test_normalized_region_to_pixels_rounding() -> None:
    assert round_half_up(0.5) == 1 and round_half_up(1.5) == 2 and round_half_up(2.5) == 3
    assert normalized_to_pixels((0.0, 0.0, 1.0, 1.0), (1024, 640)) == (0, 0, 1024, 640)
    # 네 변을 각각 반올림: x0 = round(100.1)=100, x1 = round(350.35)=350,
    # y0 = round(1.75)=2, y1 = round(5.25)=5
    assert normalized_to_pixels((0.1, 0.25, 0.25, 0.5), (1001, 7)) == (100, 2, 250, 3)
    # 0.5는 늘 올린다 (파이썬 round의 짝수 반올림과 다름)
    assert normalized_to_pixels((0.25, 0.0, 0.5, 1.0), (10, 2)) == (3, 0, 5, 2)
    # 이웃한 두 사각형은 틈·겹침 없이 맞붙는다
    left = normalized_to_pixels((0.0, 0.0, 1 / 3, 1.0), (1000, 10))
    right = normalized_to_pixels((1 / 3, 0.0, 2 / 3, 1.0), (1000, 10))
    assert left[0] + left[2] == right[0] and right[0] + right[2] == 1000
    # 클라이언트 밖은 잘린다
    assert normalized_to_pixels((0.9, -0.1, 0.5, 0.5), (100, 100)) == (90, 0, 10, 40)
    assert normalized_to_pixels((1.2, 0.0, 0.1, 0.1), (100, 100)) == (100, 0, 0, 10)


def test_client_to_screen_offsets() -> None:
    assert offset_point((100, 50), (10, 20)) == (110, 70)
    assert offset_point((-1920, 0), (5, 5)) == (-1915, 5)  # 왼쪽 보조 모니터
    # 실제 ClientToScreen: 데스크톱 창의 클라이언트 원점은 화면 (0, 0)
    user32 = ctypes.WinDLL("user32")
    user32.GetDesktopWindow.restype = ctypes.c_void_p
    desktop = user32.GetDesktopWindow()
    assert client_to_screen(desktop, (5, 7)) == (5, 7)
