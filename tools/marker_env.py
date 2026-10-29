"""이 스크립트를 실행한 Python의 PEP 508 마커 환경을 JSON으로 출력한다.

감사 대상 venv의 Python으로 `-I`로 실행한다. 대상 venv에는 packaging이 없을 수 있으므로
표준 라이브러리만 쓴다 (packaging.markers.default_environment와 같은 값).
"""

import json
import os
import platform
import sys


def _implementation_version() -> str:
    info = sys.implementation.version
    version = f"{info.major}.{info.minor}.{info.micro}"
    if info.releaselevel != "final":
        version += info.releaselevel[0] + str(info.serial)
    return version


def marker_environment() -> dict[str, str]:
    return {
        "implementation_name": sys.implementation.name,
        "implementation_version": _implementation_version(),
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_full_version": platform.python_version(),
        "python_version": ".".join(platform.python_version_tuple()[:2]),
        "sys_platform": sys.platform,
    }


if __name__ == "__main__":
    json.dump(marker_environment(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
