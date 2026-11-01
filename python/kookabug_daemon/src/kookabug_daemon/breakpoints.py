"""브레이크포인트 파일 (M3 계획 2.1·2.3, 워크스페이스 구조 `.kookabug/breakpoints.json`).

개인 파일이다(Git에 올리지 않는 `.kookabug/` 안). daemon만 쓴다: 목록 전체를 정렬·중복 제거한 뒤
같은 폴더 임시 파일 + replace로 바꾼다. 형식은 `breakpoints.schema.json`이고, 읽을 수 없거나
형식이 틀린 파일은 빈 목록으로 보고 경고만 남긴다(실행을 막지 않는다).

`version`은 이 daemon이 목록을 바꿀 때마다 오른다. 실행 관리가 "시작 때 넣은 목록이 그 뒤
바뀌었나"를 가리는 데 쓴다(시작과 변경이 엇갈려도 진행 중인 실행에 최신 목록이 들어가게).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.engine.debug import Breakpoint
from kookabug_core.schema import check_shape
from kookabug_daemon.protocol import RequestFailed

__all__ = ["BREAKPOINTS_FILE", "FORMAT", "BreakpointStore"]

log = logging.getLogger(__name__)

BREAKPOINTS_FILE: Final = ".kookabug/breakpoints.json"
FORMAT: Final = "kookabug.breakpoints/0"


class BreakpointStore:
    """워크스페이스의 브레이크포인트 목록 (스레드 안전)."""

    def __init__(self, root: Path) -> None:
        self.path = root / BREAKPOINTS_FILE
        self._lock = threading.Lock()
        self._version = 0

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def current(self) -> tuple[Breakpoint, ...]:
        """지금 파일의 목록 (정렬·중복 제거)."""
        with self._lock:
            return self._read()

    def snapshot(self) -> tuple[tuple[Breakpoint, ...], int]:
        """(목록, 판) — 같은 잠금 안에서 읽는다."""
        with self._lock:
            return self._read(), self._version

    def replace(self, items: Iterable[Mapping[str, Any]]) -> tuple[Breakpoint, ...]:
        """목록 전체를 바꾼다(원자적 교체). 쓴 목록을 돌려준다. 쓰지 못하면 `io_error`."""
        breakpoints = Breakpoint.many(items)
        data = {"format": FORMAT, "breakpoints": [bp.to_json() for bp in breakpoints]}
        text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(self.path, text.encode("utf-8"))
            except (OSError, DocumentError) as exc:
                message = f"브레이크포인트 파일을 쓸 수 없다: {exc}"
                raise RequestFailed("io_error", message, message=message) from exc
            self._version += 1
        return breakpoints

    def _read(self) -> tuple[Breakpoint, ...]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return ()
        except OSError as exc:
            log.warning("브레이크포인트 파일을 읽을 수 없다 (빈 목록으로 본다): %s", exc)
            return ()
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            log.warning("브레이크포인트 파일이 JSON이 아니다 (빈 목록으로 본다): %s", exc)
            return ()
        if problems := check_shape(data, "breakpoints"):
            log.warning(
                "브레이크포인트 파일 형식이 틀렸다 (빈 목록으로 본다): %s",
                "; ".join(d.message for d in problems[:3]),
            )
            return ()
        return Breakpoint.many(data["breakpoints"])
