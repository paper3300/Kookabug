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
from typing import Any, Final

from kookabug_daemon.session import PRIVATE_DIR

__all__ = ["MAX_BYTES", "RecorderStore", "recorder_cache_dir"]

MAX_BYTES: Final = 512 * 1024 * 1024


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

    def write_steps(self, steps: Sequence[Mapping[str, Any]], **extra: Any) -> None:
        """`steps.json` (원자적으로 바꿔 쓴다). 글자 원문을 넣지 않는 것은 부르는 쪽 규칙이다."""
        body = {"format": "kookabug.recorder-steps/0", **extra, "steps": list(steps)}
        data = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
        with self._lock:
            if not self.folder.is_dir():
                return
            temp = self.folder / "steps.json.tmp"
            temp.write_bytes(data)
            # Windows: 다른 쪽이 읽는 중이면 바꿔 넣기가 잠깐 거부된다 — 몇 번 다시 해 본다
            for attempt in range(20):
                try:
                    os.replace(temp, self.folder / "steps.json")
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.02)

    def remove(self) -> None:
        with self._lock:
            shutil.rmtree(self.folder, ignore_errors=True)
            self._frames.clear()

    @staticmethod
    def clear_all(root: Path) -> None:
        """daemon 시작: 지난 세션 폴더를 모두 지운다."""
        folder = recorder_cache_dir(root)
        if folder.is_dir():
            with contextlib.suppress(OSError):
                shutil.rmtree(folder, ignore_errors=True)
