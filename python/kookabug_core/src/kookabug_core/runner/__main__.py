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
from kookabug_sdk import _faults
from kookabug_sdk.console import utf8_stdio


def main() -> int:
    utf8_stdio()
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
