"""runner 프로세스 (구현 계획 M0b 2.6): 실행 하나를 맡아 스냅샷·워커·검증·실행·기록을 하고, 감독자의
제어(취소·멈춤)를 받는다. 진입점은 `python -m kookabug_core.runner`(stdin에 `RunSpec` JSON).

- `spec`: 실행 사양 `RunSpec`
- `run`: 시작 순서·주 스레드 실행·정상 마무리 (`Runner`)
- `control`: 제어 스레드·취소 순서·경계 멈춤 (`Controller`, `PauseGate`)
- `watchdog`: 자기 종료 감시자 (`Watchdog`)
"""

from kookabug_core.runner.control import Controller, PauseGate
from kookabug_core.runner.run import EXIT_OK, EXIT_RECORD_FAILED, EXIT_START_FAILED, Runner
from kookabug_core.runner.spec import PROTOCOL, PlatformSpec, RunSpec, SpecError
from kookabug_core.runner.watchdog import SELF_KILL_EXIT_CODE, Watchdog

__all__ = [
    "EXIT_OK",
    "EXIT_RECORD_FAILED",
    "EXIT_START_FAILED",
    "PROTOCOL",
    "SELF_KILL_EXIT_CODE",
    "Controller",
    "PauseGate",
    "PlatformSpec",
    "RunSpec",
    "Runner",
    "SpecError",
    "Watchdog",
]
