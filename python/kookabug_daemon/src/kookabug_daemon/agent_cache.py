"""에이전트용 축소 이미지 캐시 `.kookabug/cache/agent/<연결>/` (M5 계획 3.2·3.5).

- daemon이 긴 변 1568px·1 MiB 이하 PNG로 줄여 여기에 쓰고, MCP shim이 읽어 base64로 실은 뒤
  지운다. 편집기 캐시(`cache/editor/`, 사람 화면)와 나눈다 — UI 원문 결과와 에이전트 결과가 캐시를
  공유하지 않는다
- 이름은 `c<연결>/<무작위>.png`만 쓴다. daemon 시작 때 비우고, 연결마다 `MAX_FILES`장이 넘으면
  오래된 것부터 지운다
- 지우는 것은 이 폴더 아래 **일반 파일**뿐이다. 폴더가 링크·정션이면 쓰지 않는다
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import shutil
import threading
from pathlib import Path
from typing import Final

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.session import PRIVATE_DIR

__all__ = ["AGENT_CACHE_DIR", "MAX_IMAGE_BYTES", "MAX_SIDE", "NAME", "AgentCache", "shrink_png"]

log = logging.getLogger("kookabug_daemon.agent_cache")

AGENT_CACHE_DIR: Final = ("cache", "agent")
MAX_SIDE: Final = 1568
MAX_IMAGE_BYTES: Final = 1024 * 1024
MAX_FILES: Final = 64
NAME: Final = re.compile(r"^c\d+/[0-9a-f]{16}\.png$")


def shrink_png(data: bytes, max_side: int = MAX_SIDE) -> tuple[bytes, int, int]:
    """이미지 바이트 → 긴 변 `max_side` 이하·1 MiB 이하 PNG와 크기. 읽을 수 없으면 ValueError."""
    import cv2
    import numpy as np

    from kookabug_platform.frames import decode_image, encode_png

    pixels = decode_image(data)
    height, width = int(pixels.shape[0]), int(pixels.shape[1])
    side = min(max_side, max(width, height))
    while True:
        scale = side / max(width, height)
        if scale < 1:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            shown = np.asarray(cv2.resize(pixels, size, interpolation=cv2.INTER_AREA), np.uint8)
        else:
            shown = pixels
        png = encode_png(shown)
        if len(png) <= MAX_IMAGE_BYTES or side <= 64:
            return png, int(shown.shape[1]), int(shown.shape[0])
        side = int(side * 0.75)


class AgentCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.folder = root.joinpath(PRIVATE_DIR, *AGENT_CACHE_DIR)
        self._lock = threading.Lock()

    def _safe(self, path: Path) -> bool:
        current = path
        stop = self.root / PRIVATE_DIR
        while True:
            if current.is_symlink() or (current.exists() and current.is_junction()):
                return False
            if current == stop or current.parent == current:
                break
            current = current.parent
        try:
            resolved = path.resolve()
        except OSError:
            return False
        expected = self.root.resolve().joinpath(PRIVATE_DIR, *AGENT_CACHE_DIR)
        return os.path.normcase(str(resolved)).startswith(os.path.normcase(str(expected)))

    def reset(self) -> None:
        """daemon 시작 때 비운다 (링크면 건드리지 않는다)."""
        with self._lock:
            if not self.folder.exists():
                return
            if not self._safe(self.folder):
                log.warning("에이전트 캐시 폴더가 링크라 비우지 않는다: %s", self.folder)
                return
            for entry in self.folder.iterdir():
                if entry.is_dir() and not entry.is_symlink() and not entry.is_junction():
                    shutil.rmtree(entry, ignore_errors=True)
                elif entry.is_file() and not entry.is_symlink():
                    with contextlib.suppress(OSError):
                        entry.unlink()

    def path_of(self, name: str) -> Path:
        if not NAME.match(name):
            raise ValueError(f"에이전트 캐시 이름 {name!r}이(가) 규칙에 맞지 않는다")
        return self.folder.joinpath(*name.split("/"))

    def put(self, connection: int, data: bytes) -> str:
        """PNG를 쓰고 이름(`c<연결>/<무작위>.png`)을 돌려준다."""
        name = f"c{connection}/{secrets.token_hex(8)}.png"
        path = self.path_of(name)
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if not self._safe(path.parent):
                    raise DocumentError(
                        "io_error", f"에이전트 캐시 폴더 {path.parent}이(가) 링크다"
                    )
                write_atomic(path, data)
            except (OSError, DocumentError) as exc:
                text = f"에이전트 캐시에 쓸 수 없다: {exc}"
                raise RequestFailed("io_error", text, message=text) from exc
            self._trim(path.parent, keep=path.name)
        return name

    def _trim(self, folder: Path, *, keep: str) -> None:
        files: list[tuple[int, Path]] = []
        with contextlib.suppress(OSError):
            for entry in folder.iterdir():
                if entry.is_file() and not entry.is_symlink() and entry.name != keep:
                    files.append((entry.stat().st_mtime_ns, entry))
        files.sort()
        for _, entry in files[: max(0, len(files) - (MAX_FILES - 1))]:
            with contextlib.suppress(OSError):
                entry.unlink()
