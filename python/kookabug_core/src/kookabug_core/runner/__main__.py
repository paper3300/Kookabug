"""runner 진입점: `python -m kookabug_core.runner` (감독자가 띄운다).

실행 사양(`RunSpec`)은 stdin의 JSON 하나다. 끝날 때는 stdio만 비우고 `os._exit`로 끝낸다 —
멈춘 데몬 스레드(백엔드에서 멈춘 입력 액터 등)가 인터프리터 종료를 붙잡지 않게.
"""

from __future__ import annotations

import contextlib
import os
import sys
import traceback

from kookabug_core.runner.run import EXIT_START_FAILED, Runner
from kookabug_core.runner.spec import RunSpec
from kookabug_core.win import dpi, power
from kookabug_sdk import _faults
from kookabug_sdk.console import utf8_stdio


def main() -> int:
    # 어떤 창 API보다 먼저 (구현 계획 M1 2.2). 실패는 창을 쓰는 플랫폼이 시작 때 오류로 낸다
    dpi_error = dpi.enable_at_startup()
    utf8_stdio()
    if dpi_error is not None:
        print(f"runner: {dpi.CODE}: {dpi_error}", file=sys.stderr)
    # 앱·데몬이 띄운 창 없는 runner도 콘솔에서 띄운 것과 같은 속도로 관측한다 (EcoQoS, win.power)
    if not power.keep_full_speed():
        print("runner: 실행 속도 제한(EcoQoS)을 끄지 못했다 (그대로 진행)", file=sys.stderr)
    try:
        _faults.set_role("runner")
        spec = RunSpec.loads(sys.stdin.buffer.read())
    except Exception:
        traceback.print_exc()
        return EXIT_START_FAILED
    return Runner(spec).run()


def _exit(code: int) -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(code)


if __name__ == "__main__":
    _exit(main())
