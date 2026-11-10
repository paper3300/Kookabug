"""설치 스모크 `cli.qa`의 판정 (M8 B8): 설치본 없이 개발 환경의 `kookabug`로 같은 단계를 돌린다 —
플레이북 7개가 보이고, `workspace new`가 구조를 만들고, 같은 폴더는 다시 만들지 않는다(1)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from installer import smoke


def test_qa_step_with_dev_cli(tmp_path: Path) -> None:
    scripts = Path(sys.executable).parent
    if shutil.which("kookabug", path=str(scripts)) is None:
        pytest.skip("개발 환경에 kookabug 실행 파일이 없다")
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(scripts), env.get("PATH", "")])
    env.pop("KOOKABUG_AGENT", None)
    ok, detail = smoke.qa_step(tmp_path, env)
    assert ok, detail
    assert "플레이북 7개(빠짐 없음)" in detail and "다시 만들기 종료 코드 1" in detail
