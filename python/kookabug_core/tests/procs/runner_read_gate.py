"""실제 runner의 환경 파일 읽기 직전에 장벽만 더하는 진입점 (테스트 보조, M6 B3 2라운드).

환경 변수 `KB_GATE_ENV`(환경 폴더)의 `Lib/site-packages` 아래 파일을 처음 읽으려 할 때
`<KB_GATE>.ready`를 만들고 `<KB_GATE>.go`가 생길 때까지 기다린 뒤 원래 읽기를 잇는다. 그 사이
검사가 설치 커밋·gc로 그 폴더를 지우는 합법적인 순서를 고정한다. 그 밖은 제품 runner 그대로다.
"""

from __future__ import annotations

import os
import runpy
import time
from pathlib import Path

_ENV = Path(os.environ["KB_GATE_ENV"]) / "Lib" / "site-packages"
_GATE = Path(os.environ["KB_GATE"])
_original = Path.read_bytes
_paused = False


def _read_bytes(self: Path) -> bytes:
    global _paused
    if not _paused and self.is_relative_to(_ENV):
        _paused = True
        Path(f"{_GATE}.ready").write_text("", encoding="utf-8")
        deadline = time.monotonic() + 120
        while not Path(f"{_GATE}.go").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("검사 장벽 시간 초과")
            time.sleep(0.02)
    return _original(self)


Path.read_bytes = _read_bytes
runpy.run_module("kookabug_core.runner", run_name="__main__")
