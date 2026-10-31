"""편집기 이미지 캐시 `.kookabug/cache/editor/` (M2 계획 2.4 "이미지는 RPC에 싣지 않는다").

- 정지 화면 PNG를 여기 쓰고 RPC에는 `{cache: "<이름>.png", width, height}`만 보낸다. 주 프로세스의
  `kbimg://cache/<이름>.png`가 이 폴더 안 PNG만 서비스한다
- 이름은 계약(`ImageRef.cache`)의 `^[A-Za-z0-9_-]+\\.png$`만 쓴다 (폴더 밖을 가리킬 수 없다)
- daemon 시작 때 비운다. 합계가 `MAX_BYTES`(200 MiB)를 넘으면 오래된 파일부터 지운다(방금 쓴 파일은
  남긴다)
- 지우는 것은 이 폴더 바로 아래의 **일반 파일**뿐이다. 링크·폴더는 건드리지 않고, 폴더 자체가
  링크·정션이면 비우지도 쓰지도 않는다(`.kookabug/` 밖을 지우지 않게)
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Final

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.session import PRIVATE_DIR

__all__ = ["CACHE_DIR", "MAX_BYTES", "NAME", "EditorCache"]

log = logging.getLogger("kookabug_daemon.image_cache")

CACHE_DIR: Final = ("cache", "editor")
MAX_BYTES: Final = 200 * 1024 * 1024
NAME: Final = re.compile(r"^[A-Za-z0-9_-]+\.png$")


class EditorCache:
    """캐시 폴더 하나. 메서드는 어느 스레드에서 불러도 된다."""

    def __init__(self, root: Path, max_bytes: int = MAX_BYTES) -> None:
        self.root = root
        self.folder = root.joinpath(PRIVATE_DIR, *CACHE_DIR)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def _safe_folder(self) -> bool:
        """폴더가 `.kookabug/` 안의 진짜 폴더인가 (링크·정션이 아니고, 해석해도 그 자리)."""
        path = self.folder
        for part in (path, path.parent, path.parent.parent):
            if part.is_symlink() or (part.exists() and part.is_junction()):
                return False
        try:
            resolved = path.resolve()
        except OSError:
            return False
        return os.path.normcase(resolved) == os.path.normcase(
            self.root.resolve().joinpath(PRIVATE_DIR, *CACHE_DIR)
        )

    def _files(self) -> list[os.DirEntry[str]]:
        try:
            with os.scandir(self.folder) as entries:
                return [e for e in entries if e.is_file(follow_symlinks=False)]
        except FileNotFoundError:
            return []

    def reset(self) -> None:
        """daemon 시작 때: 폴더를 만들고 안의 일반 파일을 지운다."""
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            if not self._safe_folder():
                log.warning("편집기 캐시 폴더가 링크라 비우지 않는다: %s", self.folder)
                return
            for entry in self._files():
                with contextlib.suppress(OSError):
                    os.unlink(entry.path)

    def path_of(self, name: str) -> Path:
        if not NAME.match(name):
            raise ValueError(f"캐시 이름 {name!r}이(가) 규칙에 맞지 않는다")
        return self.folder / name

    def put(self, name: str, data: bytes) -> None:
        """PNG 바이트를 쓰고 용량을 맞춘다. 쓰지 못하면 `io_error`."""
        path = self.path_of(name)
        with self._lock:
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                if not self._safe_folder():
                    raise DocumentError("io_error", f"캐시 폴더 {self.folder}이(가) 링크다")
                write_atomic(path, data)
            except (OSError, DocumentError) as exc:
                text = f"편집기 캐시에 쓸 수 없다: {exc}"
                raise RequestFailed("io_error", text, message=text) from exc
            self._trim(keep=name)

    def _trim(self, *, keep: str) -> None:
        files: list[tuple[int, int, str]] = []
        for entry in self._files():
            with contextlib.suppress(OSError):
                stat = entry.stat(follow_symlinks=False)
                files.append((stat.st_mtime_ns, stat.st_size, entry.name))
        total = sum(size for _, size, _ in files)
        for _, size, name in sorted(files):
            if total <= self.max_bytes:
                break
            if name == keep:
                continue
            with contextlib.suppress(OSError):
                os.unlink(self.folder / name)
                total -= size
