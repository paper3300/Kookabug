"""플랫폼 의존성과 코어의 분리 (구현 계획 M1 2.1)."""

import json
import subprocess
import sys

HEAVY = ("cv2", "numpy", "onnxruntime", "windows_capture", "pyclipper")


def test_heavy_deps_importable() -> None:
    import cv2
    import numpy
    import onnxruntime
    import pyclipper
    import windows_capture

    import kookabug_platform
    import kookabug_platform.win32

    assert kookabug_platform.__version__
    assert kookabug_platform.win32.__name__ == "kookabug_platform.win32"
    # 주 버전 상한 (pyproject)과 lock이 고른 것
    assert int(numpy.__version__.split(".")[0]) == 2
    assert int(cv2.__version__.split(".")[0]) == 5
    assert int(onnxruntime.__version__.split(".")[0]) == 1
    assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
    assert hasattr(windows_capture, "WindowsCapture")
    assert hasattr(pyclipper, "PyclipperOffset")
    # opencv는 GUI판 하나만 (headless와 같이 깔리면 cv2가 깨진다)
    from importlib.metadata import PackageNotFoundError, distribution

    distribution("opencv-python")
    try:
        distribution("opencv-python-headless")
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError("opencv-python-headless가 함께 설치돼 있다")


# 코어 전체 모듈을 import한 뒤 무엇이 올라왔는지 본다 (새 프로세스)
_PROBE = """
import importlib, json, pkgutil, sys
import kookabug_core
for info in pkgutil.walk_packages(kookabug_core.__path__, "kookabug_core."):
    importlib.import_module(info.name)
import kookabug_sdk, kookabug_nodes, kookabug_cli.main
banned = (*%r, "kookabug_platform")
print(json.dumps(sorted(m for m in sys.modules if m.split(".")[0] in banned)))
"""


def test_core_does_not_import_platform() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE % (HEAVY,)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []
