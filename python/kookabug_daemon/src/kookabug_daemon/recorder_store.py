"""녹화 세션 저장소 (M4 계획 2.9 "세션 저장소"·"정리"): `.kookabug/cache/recorder/<세션 ID>/`.

- 붙잡은 프레임 PNG(`f<seq>.png`)와 `steps.json`(동작·노드 초안·배지·target 초안 상자 — **글자는
  길이와 `text_state`만**). 전체 화면 PNG에는 칸이 가려지지 않는 게임이면 비밀번호가 찍힐 수 있다
  (녹화 임시 화면의 D3 예외) — 세션이 끝나면 폴더째 지운다
- 크기 상한 512 MiB. 넘으면 `put_frame`이 False — 세션이 녹화를 오류로 멈춘다(`storage_full`)
- daemon 시작 때 `cache/recorder/`를 비운다(지난 daemon이 남긴 세션)
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_daemon.session import PRIVATE_DIR

__all__ = ["MAX_BYTES", "RecorderStore", "StepsWrite", "StoreUnclean", "recorder_cache_dir"]

MAX_BYTES: Final = 512 * 1024 * 1024
_REPLACE_TRIES: Final = 20
"""`steps.json` 바꿔 넣기 시도 수 (10ms부터 100ms까지 늘려 기다림, 합 1.5초 남짓)."""

type StepsWrite = Literal["replaced", "overwritten", "deleted", "skipped"]
"""`write_steps`가 끝난 방식: 바꿔 넣음 · 제자리 덮어씀 · 지움(새 내용은 못 씀) · 폴더 없음."""


class StoreUnclean(OSError):
    """`steps.json`을 바꿔 넣지도, 덮어쓰지도, 지우지도 못했다 — 지난 내용이 남아 있을 수 있다."""


def recorder_cache_dir(root: Path) -> Path:
    return root / PRIVATE_DIR / "cache" / "recorder"


class RecorderStore:
    def __init__(self, root: Path, session_id: str, *, max_bytes: int = MAX_BYTES) -> None:
        self.folder = recorder_cache_dir(root) / session_id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.bytes = 0
        self._lock = threading.Lock()
        self._frames: set[int] = set()

    def put_frame(self, seq: int, png: bytes) -> bool:
        """프레임 하나 (같은 seq는 한 번만). 상한을 넘으면 쓰지 않고 False."""
        with self._lock:
            if seq in self._frames:
                return True
            if self.bytes + len(png) > self.max_bytes:
                return False
            (self.folder / f"f{seq}.png").write_bytes(png)
            self._frames.add(seq)
            self.bytes += len(png)
            return True

    def write_steps(self, steps: Sequence[Mapping[str, Any]], **extra: Any) -> StepsWrite:
        """`steps.json`을 새 내용으로. 글자 원문을 넣지 않는 것은 부르는 쪽 규칙이다.

        지난 내용(비밀값으로 바뀌기 전 이름·제목이 있을 수 있다)을 남기지 않게 단계적으로 한다:
        (a) 임시 파일 → 바꿔 넣기 재시도 → (b) 기존 파일 제자리 덮어쓰기(다른 쪽이 쓰기 공유로
        읽는 중일 때) → (c) 지우기. 셋 다 안 되면 `StoreUnclean`."""
        body = {"format": "kookabug.recorder-steps/0", **extra, "steps": list(steps)}
        data = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        with self._lock:
            if not self.folder.is_dir():
                return "skipped"
            path, temp = self.folder / "steps.json", self.folder / "steps.json.tmp"
            temp_current = False  # 임시 파일이 지금 내용인가 (못 지워도 남겨도 된다)
            try:
                temp.write_bytes(data)
                temp_current = True
            except OSError:
                pass
            if temp_current:
                # Windows: 다른 쪽(검사 도구·백신 검사 포함)이 읽는 중이면 바꿔 넣기가 잠깐
                # 거부된다 — 부하 때도 버티게 잠깐 다시 해 본다
                for attempt in range(_REPLACE_TRIES):
                    try:
                        os.replace(temp, path)
                        return "replaced"
                    except PermissionError:
                        if attempt < _REPLACE_TRIES - 1:
                            time.sleep(min(0.1, 0.01 * (attempt + 1)))
                    except OSError:
                        break
            outcome: StepsWrite | None = None
            if path.exists():
                try:
                    with path.open("r+b") as f:
                        f.write(data)
                        f.truncate()
                        f.flush()
                        os.fsync(f.fileno())
                    outcome = "overwritten"
                except OSError:
                    pass
            if outcome is None:
                try:
                    path.unlink(missing_ok=True)
                    outcome = "deleted"
                except OSError as exc:
                    raise StoreUnclean(exc.errno, "녹화 steps.json을 정리하지 못했다") from exc
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                if not temp_current:
                    raise StoreUnclean("녹화 steps.json.tmp를 정리하지 못했다") from None
            return outcome

    def remove(self) -> bool:
        """폴더째 지운다. 남은 것이 없으면 True (잠긴 파일이 남으면 False — 부르는 쪽이 다시
        한다)."""
        with self._lock:
            shutil.rmtree(self.folder, ignore_errors=True)
            self._frames.clear()
            return not self.folder.exists()

    @staticmethod
    def clear_all(root: Path) -> None:
        """daemon 시작: 지난 세션 폴더를 모두 지운다."""
        folder = recorder_cache_dir(root)
        if folder.is_dir():
            with contextlib.suppress(OSError):
                shutil.rmtree(folder, ignore_errors=True)
