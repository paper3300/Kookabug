"""pytest 세션 Job과 프로세스 테스트 기반 (구현 계획 M0b 2.3 "테스트 프로세스 정리"·2.12).

세션 시작 때 `KILL_ON_JOB_CLOSE` Job을 만들고 **pytest 자신을 넣는다**. 핸들은 pytest만 쥐고
상속하지 않는다. 이후 테스트가 띄우는 모든 프로세스(손자 포함)는 생성 시점부터 Job 소속이므로,
pytest-timeout이 pytest를 강제로 끝내 fixture 정리가 돌지 않아도 마지막 핸들이 닫히며 OS가
전부 끝낸다.

핸들은 Python이 절대 닫지 않는다(`keep_until_exit`) — 닫으면 pytest 자신도 끝난다. 인터프리터
종료 중 소멸자가 닫으면 그 순간 강제 종료돼 pytest의 종료 코드(실패 1 등)가 0으로 바뀐다.
프로세스가 끝날 때 OS가 닫고, 종료 코드는 그 전에 정해진다.

데스크톱 표시(`desktop`·`desktop_input`·`soak`)의 실행 조건과 `ocr_models` 픽스처도 여기서 건다
(구현 계획 M1 2.13).
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from kb_testing import desktop
from kb_testing.proc import Spawned
from kookabug_core.win import Job

__all__ = ["OCR_MODELS_ENV", "PROCESS_TIMEOUT_S", "ocr_models", "session_job", "spawned"]

PROCESS_TIMEOUT_S: Final = 60
OCR_MODELS_ENV: Final = "KOOKABUG_OCR_MODELS"
REPO_ROOT = Path(__file__).resolve().parents[2]

_session_job: Job | None = None
# 데스크톱 표시 검사의 건너뜀 사유 → 개수 (끝 요약에 쓴다)
_desktop_skips: Counter[str] = Counter()


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
    # 데스크톱 표시 (구현 계획 M1 2.13, 실행 조건은 kb_testing.desktop)
    for line in (
        "desktop: 대화형 데스크톱이 필요한 검사 (창·WGC·예제 게임). "
        f"{desktop.MODE_ENV}=off|auto|require",
        f"desktop_input: 실제 마우스·키보드 입력 검사 (desktop 포함). {desktop.INPUT_ENV}=1일 때만",
        f"soak: 장시간 안정성 검사 (desktop 포함). {desktop.SOAK_ENV}=1일 때만",
    ):
        config.addinivalue_line("markers", line)
    desktop.mode_from_env(os.environ)  # 잘못된 값이면 시작 때 바로 알린다


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # process·데스크톱 검사는 따로 정하지 않았으면 60초 timeout (걸린 검사가 CI를 붙잡지 않게)
    timed = ("process", *desktop.MARKERS)
    for item in items:
        if any(item.get_closest_marker(m) for m in timed) and not item.get_closest_marker(
            "timeout"
        ):
            item.add_marker(pytest.mark.timeout(PROCESS_TIMEOUT_S))


def pytest_runtest_setup(item: pytest.Item) -> None:
    markers = {m.name for m in item.iter_markers()}
    decision = desktop.decide(markers, os.environ, desktop.session_probe)
    if decision.action == "skip":
        _desktop_skips[decision.reason] += 1
        pytest.skip(decision.reason)
    if decision.action == "fail":
        pytest.fail(decision.reason, pytrace=False)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    report = desktop.session_probe_result()
    if report is None and not _desktop_skips:
        return
    tr = terminalreporter
    tr.section("데스크톱 검사")
    tr.write_line(f"{desktop.MODE_ENV}={desktop.mode_from_env(os.environ).value}")
    if report is not None:
        state = "통과" if report.ok else f"실패 — {report.reason}"
        tr.write_line(f"탐지: {state} ({report.elapsed_ms} ms)")
    for reason, count in sorted(_desktop_skips.items()):
        tr.write_line(f"건너뜀 {count}개: {reason}")


@pytest.fixture
def spawned() -> Iterator[Spawned]:
    """테스트별 정리: 테스트가 끝나면 등록한 프로세스 중 남은 것을 끝낸다."""
    procs = Spawned()
    try:
        yield procs
    finally:
        procs.close()


@pytest.fixture(scope="session")
def ocr_models() -> Path:
    """OCR 모델 폴더 (구현 계획 M1 2.13). 없거나 모델 표(`models.toml`)와 크기·SHA256이 다르면
    건너뛰지 않고 **실패**한다. 라이선스 근거 원문도 같이 확인한다.

    찾는 순서: `KOOKABUG_OCR_MODELS` → 레포 `build/ocr-models`.
    """
    from kookabug_platform.ocr.models import load_manifest, verify_file

    env = os.environ.get(OCR_MODELS_ENV, "").strip()
    folder = Path(env) if env else REPO_ROOT / "build" / "ocr-models"
    manifest = load_manifest()
    bad = [
        spec.file
        for spec in (*manifest.models, *manifest.texts)
        if not verify_file(folder / spec.file, spec.sha256, spec.size)
    ]
    if not bad:
        return folder
    pytest.fail(
        f"OCR 모델이 없거나 모델 표와 다르다: {folder} ({', '.join(bad)}). "
        f"`uv run python tools/fetch_ocr_models.py`로 받는다 (다른 폴더면 {OCR_MODELS_ENV})",
        pytrace=False,
    )
