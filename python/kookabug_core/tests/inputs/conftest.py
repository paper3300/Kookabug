from pathlib import Path

import pytest
from helpers.lease import LeaseEnv


@pytest.fixture
def env(tmp_path: Path) -> LeaseEnv:
    """테스트마다 다른 임대권 이름·상태 폴더·가짜 입력 기록."""
    return LeaseEnv.make(tmp_path)
