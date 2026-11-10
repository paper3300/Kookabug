"""`write_atomic`: 다른 프로세스가 대상 파일을 잠깐 읽는 중이어도 교체한다 (M8 B7).

Windows에서 공유 삭제 없이 열린 파일은 `os.replace` 대상이 되지 못한다(`PermissionError`). 보고함이
`jobs.list`로 `job.json`을 읽는 동안 `agent-job`이 같은 파일을 바꾸다 작업이 죽던 경합을 재현한다.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from kookabug_core import documents
from kookabug_core.documents import DocumentError, write_atomic

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 파일 공유 규칙")


def _hold(path: Path, seconds: float, opened: threading.Event) -> None:
    with path.open("rb"):
        opened.set()
        time.sleep(seconds)


def test_replace_waits_for_short_reader(tmp_path: Path) -> None:
    target = tmp_path / "job.json"
    target.write_bytes(b"old")
    opened = threading.Event()
    reader = threading.Thread(target=_hold, args=(target, 0.4, opened))
    reader.start()
    opened.wait(5)
    write_atomic(target, b"new")
    reader.join()
    assert target.read_bytes() == b"new"
    assert [p.name for p in tmp_path.iterdir()] == ["job.json"]  # 임시 파일이 남지 않는다


class _Conflict(Exception):
    pass


def test_review_retry_rechecks_before_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B7 검수 H3: 재시도마다 교체 직전에 호출자 충돌 검사를 다시 부른다. 첫 교체 공유 위반 사이에
    외부 작성자가 바꾸면 충돌 오류로 끝나고 외부 변경은 보존, 임시 파일은 없다."""
    target = tmp_path / "local.json"
    target.write_bytes(b"old")
    real_replace = documents.os.replace
    replaced: list[str] = []
    checks: list[bytes] = []

    def flaky(src: str, dst: str | Path) -> None:
        replaced.append(src)
        if len(replaced) == 1:
            target.write_bytes(b"external-new")  # 그사이 외부 작성자
            raise PermissionError(32, "공유 위반 (검사 주입)")
        real_replace(src, dst)

    def unchanged() -> None:
        now = target.read_bytes()
        checks.append(now)
        if now != b"old":
            raise _Conflict("그사이 바뀌었다")

    monkeypatch.setattr(documents.os, "replace", flaky)
    with pytest.raises(_Conflict):
        write_atomic(target, b"mine", before_replace=unchanged)
    assert checks == [b"old", b"external-new"]  # 재시도 앞에서 다시 봤다
    assert len(replaced) == 1
    assert target.read_bytes() == b"external-new"
    assert [p.name for p in tmp_path.iterdir()] == ["local.json"]
    # 양성 대조: 바뀌지 않았으면 재시도가 교체한다
    replaced.clear()
    checks.clear()
    target.write_bytes(b"old")

    def flaky_once(src: str, dst: str | Path) -> None:
        replaced.append(src)
        if len(replaced) == 1:
            raise PermissionError(32, "공유 위반 (검사 주입)")
        real_replace(src, dst)

    monkeypatch.setattr(documents.os, "replace", flaky_once)
    write_atomic(target, b"mine", before_replace=unchanged)
    assert target.read_bytes() == b"mine" and len(checks) == 2
    assert [p.name for p in tmp_path.iterdir()] == ["local.json"]


def test_replace_gives_up_after_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 양성 대조: 오래 쥐고 있으면 기다리다 실패하고 대상은 그대로
    monkeypatch.setattr(documents, "REPLACE_RETRY_S", 0.2)
    target = tmp_path / "job.json"
    target.write_bytes(b"old")
    opened = threading.Event()
    reader = threading.Thread(target=_hold, args=(target, 1.5, opened))
    reader.start()
    opened.wait(5)
    with pytest.raises(DocumentError):
        write_atomic(target, b"new")
    reader.join()
    assert target.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir()] == ["job.json"]
