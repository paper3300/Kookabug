"""pytest 세션 Job과 프로세스 테스트 기반 (구현 계획 M0b 2.3 "테스트 프로세스 정리"·2.12).

세션 시작 때 `KILL_ON_JOB_CLOSE` Job을 만들고 **pytest 자신을 넣는다**. 핸들은 pytest만 쥐고
상속하지 않는다. 이후 테스트가 띄우는 모든 프로세스(손자 포함)는 생성 시점부터 Job 소속이므로,
pytest-timeout이 pytest를 강제로 끝내 fixture 정리가 돌지 않아도 마지막 핸들이 닫히며 OS가
전부 끝낸다.

핸들은 Python이 절대 닫지 않는다(`keep_until_exit`) — 닫으면 pytest 자신도 끝난다. 인터프리터
종료 중 소멸자가 닫으면 그 순간 강제 종료돼 pytest의 종료 코드(실패 1 등)가 0으로 바뀐다.
프로세스가 끝날 때 OS가 닫고, 종료 코드는 그 전에 정해진다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import pytest

from kb_testing.proc import Spawned
from kookabug_core.win import Job

__all__ = ["PROCESS_TIMEOUT_S", "session_job", "spawned"]

PROCESS_TIMEOUT_S: Final = 60

_session_job: Job | None = None


def session_job() -> Job:
    if _session_job is None:
        raise RuntimeError("세션 Job이 없다 (kb_testing.pytest_plugin이 등록되지 않았다)")
    return _session_job


def pytest_configure(config: pytest.Config) -> None:
    global _session_job
    if _session_job is None:
        job = Job.create(kill_on_close=True).keep_until_exit()
        job.assign_current()
        _session_job = job


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # process 검사는 따로 정하지 않았으면 60초 timeout (걸린 검사가 CI를 붙잡지 않게)
    for item in items:
        if item.get_closest_marker("process") and not item.get_closest_marker("timeout"):
            item.add_marker(pytest.mark.timeout(PROCESS_TIMEOUT_S))


@pytest.fixture
def spawned() -> Iterator[Spawned]:
    """테스트별 정리: 테스트가 끝나면 등록한 프로세스 중 남은 것을 끝낸다."""
    procs = Spawned()
    try:
        yield procs
    finally:
        procs.close()
