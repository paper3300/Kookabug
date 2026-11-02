"""설치본 스모크의 영상 단계 `cli.video` 판정 (M3 T12 검수 1).

"인코더가 없다"는 실행 결과가 아니라 설치 환경에서 따로 탐지한 결과(`probe_media`)로만 판정한다.
인코더가 있는데 실행이 `unavailable`이면(예: 열기 실패 `encoder_open_failed`) 실패다.

설치 트리 대신 예제 사본 모양의 임시 트리와 개발 CLI(`.venv/Scripts`)로 `video_step` 자체를 돌린다.
실제 설치 트리의 기본 탐지(설치본 Python)는 `test_installer_e2e.py`가 본다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import pytest

from installer import build, smoke

pytestmark = pytest.mark.process

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
OPEN_FAILS: Final = json.dumps({"encoder": "msmf", "msmf": {"fourcc": "MJPG"}})
"""인코더는 있는데 MSMF가 열지 못하는 FourCC (`encoder_open_failed`)."""
MF_MISSING: Final = json.dumps({"encoder": "msmf", "msmf": {"mf_dlls": ["kb-missing-mfplat.dll"]}})

PRESENT: Final = smoke.MediaFound(True, None, "H.264 인코더 있음 (검사)")
ABSENT: Final = smoke.MediaFound(False, "h264_encoder_missing", "H.264 인코더 없음 (검사)")


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("tree")
    build.copy_examples(REPO_ROOT / "fixtures" / "sample-game", root / build.EXAMPLES)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def dev_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() != smoke.VIDEO_TEST_ENV}
    env["PATH"] = str(REPO_ROOT / ".venv" / "Scripts") + os.pathsep + env["PATH"]
    env.update(extra)
    return env


def fixed(found: smoke.MediaFound) -> Any:
    return lambda root, env: found


def real_probe(root: Path, env: Mapping[str, str]) -> smoke.MediaFound:
    """개발 venv의 `probe_media()` (설치본 Python 대신)."""
    from kookabug_platform.video import probe_media

    p = probe_media()
    return smoke.MediaFound(p.available, p.reason, p.detail)


@pytest.mark.media
def test_real_encoder_records_h264(tree: Path) -> None:
    ok, detail = smoke.video_step(tree, dev_env(), probe=real_probe)
    assert ok, detail
    assert "'status': 'recorded'" in detail and "b'ftyp'" in detail


@pytest.mark.media
def test_open_failure_with_real_encoder_fails(tree: Path) -> None:
    # 검수 반례: 인코더가 있는 PC에서 열기 실패는 "인코더 없음"으로 넘기지 않는다
    ok, detail = smoke.video_step(
        tree, dev_env(**{smoke.VIDEO_TEST_ENV: OPEN_FAILS}), probe=real_probe
    )
    assert not ok, detail
    assert "encoder_open_failed" in detail


def test_unavailable_run_fails_when_probe_finds_encoder(tree: Path) -> None:
    # 인코더가 있다고 탐지했는데 실행이 영상 없이 끝나면 실패 (MF가 없는 CI에서도 도는 판정 검사)
    ok, detail = smoke.video_step(
        tree, dev_env(**{smoke.VIDEO_TEST_ENV: MF_MISSING}), probe=fixed(PRESENT)
    )
    assert not ok, detail
    assert "'status': 'unavailable'" in detail


def test_unavailable_run_passes_only_when_os_encoder_missing(tree: Path) -> None:
    ok, detail = smoke.video_step(
        tree, dev_env(**{smoke.VIDEO_TEST_ENV: MF_MISSING}), probe=fixed(ABSENT)
    )
    assert ok, detail
    assert "인코더 없음" in detail
    # 설치 트리 결함(OpenCV MSMF 백엔드 없음)은 OS 부재가 아니다
    broken = smoke.MediaFound(False, "backend_missing", "OpenCV에 MSMF 쓰기 백엔드가 없다")
    assert not broken.os_missing and ABSENT.os_missing
    ok, detail = smoke.video_step(
        tree, dev_env(**{smoke.VIDEO_TEST_ENV: MF_MISSING}), probe=fixed(broken)
    )
    assert not ok, detail


def test_probe_failure_is_not_encoder_absence(tree: Path) -> None:
    # 설치본 Python이 없는 트리: 탐지 실패는 "인코더 없음"이 아니다 → 열기 실패 주입은 실패
    found = smoke.probe_installed_media(tree, dev_env())
    assert (found.available, found.reason, found.os_missing) == (False, "probe_failed", False)
    ok, detail = smoke.video_step(tree, dev_env(**{smoke.VIDEO_TEST_ENV: OPEN_FAILS}))
    assert not ok, detail


def test_installed_probe_ignores_video_test_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """기본 탐지는 설치본 Python으로 `probe_media()`를 부르고, 검사 설정은 그 환경에서 뺀다."""
    seen: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.update(cmd=cmd, env=kw["env"])
        out = json.dumps({"available": True, "reason": None, "detail": "ok"})
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    found = smoke.probe_installed_media(tmp_path, {"PATH": "x", smoke.VIDEO_TEST_ENV: MF_MISSING})
    assert found == smoke.MediaFound(True, None, "ok")
    assert Path(seen["cmd"][0]) == tmp_path / "python" / "python.exe"
    assert "probe_media" in seen["cmd"][-1]
    assert smoke.VIDEO_TEST_ENV not in seen["env"] and seen["env"]["PATH"] == "x"
