"""기록 읽기 (M3 계획 2.7): `run.index`·`run.children`·`run.step`·`run.file`·`run.export`.

- 색인은 코어 `record.index`가 만든다. 끝난 실행은 `.kookabug/cache/runs/<run_id>.index.json`
  캐시(이벤트 파일 크기·수정 시각이 같으면 다시 쓰지 않음)를, 진행 중 실행은 메모리 색인을 쓰고
  읽을 때마다 새로 쓰인 완전한 줄만 더 읽어 늘린다. 실행이 끝나면 메모리 색인을 캐시로 옮긴다
- 실행이 끝났는지는 실행 관리(`RunManager.locate`)가 정한다: 이 daemon이 띄운 실행은 감독자 마무리,
  아니면 `run.json`이 `finished`이거나 runner가 없음
- 실행 폴더 기준 파일 경로는 `kbimg://ws/<run_dir>/<경로>`로 연다 (`run_dir` = `runs/<폴더>`)
- `run.export`는 진행 중 실행을 거부한다(`run_active`). zip은 `dest` 옆 임시 파일에 쓰고 끝나면
  replace한다. 에이전트 연결은 전송이 판정 전에 거부하므로(`AGENT_DENIED`) 여기까지 오지 않는다
"""

from __future__ import annotations

import os
import tempfile
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.record import read_run_json
from kookabug_core.record.index import (
    MAX_PAGE,
    RunIndex,
    RunState,
    cached_index,
    index_cache_file,
    thumbnails,
    video_view,
    write_cache,
)
from kookabug_core.record.runfolder import EVENTS_FILE, RUN_JSON_FILE
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = ["FILE_LIMIT", "Located", "RunRecords"]

FILE_LIMIT: Final = 1024 * 1024
"""`run.file`이 돌려주는 글자의 최대 바이트."""
KEEP_INDEXES: Final = 4
"""메모리에 남기는 끝난 실행 색인 수 (쪽 넘김이 캐시 파일을 매번 다시 읽지 않게)."""
_STORED: Final = frozenset({".mp4", ".jpg", ".jpeg", ".png", ".zip"})
"""이미 압축된 파일은 zip에 그대로 넣는다."""


@dataclass(frozen=True, slots=True)
class Located:
    """실행 폴더와 지금 상태."""

    run_id: str
    folder: Path
    state: RunState


@dataclass(eq=False, slots=True)
class _Entry:
    index: RunIndex
    lock: threading.Lock
    state: RunState


class RunRecords:
    """실행 기록 읽기. 메서드는 막히는 호출이다 (스레드에서 부른다)."""

    def __init__(self, root: Path, locate: Callable[[str], Located]) -> None:
        self.root = root
        self.locate = locate
        self._lock = threading.Lock()
        self._live: dict[str, _Entry] = {}
        """진행 중 실행의 메모리 색인."""
        self._ended: OrderedDict[str, _Entry] = OrderedDict()
        """최근에 읽은 끝난 실행 색인 (`KEEP_INDEXES`개)."""

    # ---------------------------------------------------------------- 색인

    def _index(self, run_id: str) -> tuple[Located, _Entry]:
        where = self.locate(run_id)
        with self._lock:
            entry = self._live.get(run_id) if where.state == "running" else None
            if where.state == "running" and entry is None:
                entry = self._live[run_id] = _Entry(
                    RunIndex(where.folder), threading.Lock(), "running"
                )
            if entry is not None:
                with entry.lock:
                    entry.index.update()
                return where, entry
            live = self._live.pop(run_id, None)
            cached = self._ended.get(run_id)
        if live is not None:
            # 끝났다: 메모리 색인을 마저 읽어 캐시로 옮긴다
            with live.lock:
                live.index.update()
                write_cache(live.index, index_cache_file(self.root, run_id))
                entry = _Entry(live.index, live.lock, "ended")
        elif cached is not None and _same_file(cached.index):
            entry = cached
        else:
            index = cached_index(where.folder, index_cache_file(self.root, run_id))
            entry = _Entry(index, threading.Lock(), "ended")
        with self._lock:
            self._ended[run_id] = entry
            self._ended.move_to_end(run_id)
            while len(self._ended) > KEEP_INDEXES:
                self._ended.popitem(last=False)
        return where, entry

    def forget(self, run_id: str) -> None:
        """메모리 색인을 버린다 (다음 읽기가 파일·캐시에서 다시 만든다)."""
        with self._lock:
            self._live.pop(run_id, None)
            self._ended.pop(run_id, None)

    def run_dir(self, folder: Path) -> str:
        """실행 폴더의 워크스페이스 기준 경로 ('/' 구분)."""
        try:
            return folder.relative_to(self.root).as_posix()
        except ValueError:
            return Path(os.path.relpath(folder, self.root)).as_posix()

    def index(self, run_id: str) -> dict[str, Any]:
        where, entry = self._index(run_id)
        run_json = read_run_json(where.folder / RUN_JSON_FILE)
        video = video_view(where.folder)
        thumbs = thumbnails(where.folder)
        with entry.lock:
            return entry.index.result(
                run_dir=self.run_dir(where.folder),
                state=entry.state,
                run_json=run_json,
                video=video,
                thumbs=thumbs,
            )

    def children(
        self, run_id: str, parent: str, iteration: int | None, offset: int, limit: int
    ) -> dict[str, Any]:
        where, entry = self._index(run_id)
        thumbs = thumbnails(where.folder)
        with entry.lock:
            try:
                total, steps = entry.index.children(
                    parent,
                    iteration,
                    offset,
                    min(limit, MAX_PAGE),
                    state=entry.state,
                    thumbs=thumbs,
                )
            except KeyError as exc:
                raise InvalidParams(f"실행 {run_id}에 스텝 {parent}이(가) 없다") from exc
        return {"offset": offset, "total": total, "steps": steps}

    def step(self, run_id: str, step: str) -> dict[str, Any]:
        where, entry = self._index(run_id)
        thumbs = thumbnails(where.folder)
        with entry.lock:
            row = entry.index.rows.get(step)
            if row is None:
                raise InvalidParams(f"실행 {run_id}에 스텝 {step}이(가) 없다")
            node = entry.index.node_json(row, entry.state, thumbs)
            events = entry.index.step_events(step)
        return {
            "run_dir": self.run_dir(where.folder),
            "step": node,
            "events": events,
            "ocr_text": _read_text(where.folder / "steps" / f"{step}_ocr.txt"),
            "thumbnail": f"thumbs/{step}.jpg" if step in thumbs else None,
        }

    # ---------------------------------------------------------------- 파일

    def file(self, run_id: str, name: str) -> dict[str, Any]:
        where = self.locate(run_id)
        path = where.folder / (RUN_JSON_FILE if name == "run.json" else EVENTS_FILE)
        try:
            with path.open("rb") as f:
                size = os.fstat(f.fileno()).st_size
                if name == "run.json":
                    data = f.read(FILE_LIMIT)
                else:
                    f.seek(max(0, size - FILE_LIMIT))
                    data = f.read(FILE_LIMIT)
        except FileNotFoundError:
            raise RequestFailed("not_found", f"{path.name}이(가) 없다", path=path.name) from None
        except OSError as exc:
            raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
        truncated = size > len(data)
        if truncated and name != "run.json":
            # 잘린 앞 줄은 버린다 (완전한 줄만)
            cut = data.find(b"\n")
            data = data[cut + 1 :] if cut >= 0 else b""
        return {
            "text": data.decode("utf-8", errors="replace"),
            "bytes": size,
            "truncated": truncated,
        }

    def export(self, run_id: str, dest: str) -> dict[str, Any]:
        """실행 폴더를 zip으로 `dest`에 쓴다 (같은 폴더 임시 파일 + replace)."""
        where = self.locate(run_id)
        if where.state == "running":
            raise RequestFailed(
                "run_active", f"진행 중인 실행 {run_id}은(는) 내보낼 수 없다", run_id=run_id
            )
        target = Path(dest)
        if not target.is_absolute() or target.name == "":
            raise InvalidParams(f"dest는 절대 경로 파일이어야 한다: {dest}")
        if not target.parent.is_dir():
            text = f"저장할 폴더가 없다: {target.parent}"
            raise RequestFailed("io_error", text, message=text)
        try:
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".kb-export-", suffix=".tmp")
        except OSError as exc:
            raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
        try:
            with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w") as archive:
                _zip_folder(archive, where.folder)
            os.replace(temp, target)
        except BaseException as exc:
            Path(temp).unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
            raise
        return {"path": str(target), "bytes": target.stat().st_size}


def _zip_folder(archive: zipfile.ZipFile, folder: Path) -> None:
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        name = f"{folder.name}/{path.relative_to(folder).as_posix()}"
        method = zipfile.ZIP_STORED if path.suffix.lower() in _STORED else zipfile.ZIP_DEFLATED
        archive.write(path, name, compress_type=method)


def _same_file(index: RunIndex) -> bool:
    try:
        stat = (index.folder / EVENTS_FILE).stat()
    except OSError:
        return False
    return stat.st_size == index.size and stat.st_mtime_ns == index.mtime_ns


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
