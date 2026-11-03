"""워크스페이스 파일 목록과 1초 폴링 감시 (M2 계획 2.4 `workspace.tree`·`workspace.changed`, Q10).

- **보는 범위**: `tests/`·`subgraphs/`·`targets/`·`screens/` 아래 전부와 루트의 `kookabug.json`·
  `kookabug.lock`·`AGENTS.md`. `runs/`·`.kookabug/`는 안을 보지 않는다(이름만). 열린 문서는 그 밖에
  있어도 본다
- **링크**: 심볼릭 링크·정션이 루트 밖이나 `.kookabug/`(그 실제 대상) 안을 가리키면 건너뛴다.
  루트 안을 가리키는 폴더 링크는 항목으로만 두고 안으로 들어가지 않는다(순환 방지)
- **감시**: 주기마다 (mtime_ns, 크기)를 비교해 바뀐(생김·없어짐 포함) 경로를 `workspace.changed`로
  알린다. 열린 문서는 디스크 revision을 **그 문서를 연 연결마다** 그 연결이 아는 revision(그 연결이
  열거나 저장한 바이트)과 비교해 다르면 그 연결에 `graph.changed {doc_id, revision}`을 보낸다.
  다른 연결의 daemon 저장도 알리고, 자기 저장은 알리지 않는다. 같은 revision은 연결마다 한 번만
  알린다. 경로 잠금을 잡지 못하면(저장·읽기 중) 그 주기는 건너뛴다
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kookabug_daemon.documents import (
    PRIVATE_NAME,
    DocumentTable,
    OpenDoc,
    in_private_target,
    recheck_path,
)
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = [
    "NAME_ONLY_DIRS",
    "ROOT_FILES",
    "TREE_DIRS",
    "DocChange",
    "Item",
    "Watcher",
    "scan",
    "walk",
]

log = logging.getLogger(__name__)

TREE_DIRS: Final = ("tests", "subgraphs", "targets", "screens")
ROOT_FILES: Final = {"kookabug.json": "workspace", "kookabug.lock": "lock", "AGENTS.md": "agents"}
NAME_ONLY_DIRS: Final = ("runs", PRIVATE_NAME)
"""이름만 보이는 폴더 (Git 제외)."""
MISSING: Final = "missing"
"""`OpenDoc.notified`: 파일이 없어졌다고 알렸다 (revision 자리에 오지 않는 값)."""

type Signature = tuple[int, int]
"""(mtime_ns, 크기). 폴더는 (0, 0) — 있음·없음만 본다."""


@dataclass(frozen=True, slots=True)
class Item:
    rel: str
    path: Path
    is_dir: bool


def _inside(root: Path, path: Path) -> bool:
    """링크를 해석한 경로가 루트 안이고 `.kookabug/`(링크면 그 실제 대상 포함) 밖인가."""
    try:
        resolved = os.path.realpath(path)
        relative = os.path.relpath(resolved, root)
    except OSError, ValueError:
        return False
    parts = Path(relative).parts
    if os.path.isabs(relative) or not parts or parts[0] == "..":
        return False
    return parts[0].casefold() != PRIVATE_NAME and not in_private_target(root, Path(resolved))


def _is_link(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_symlink() or entry.is_junction()
    except OSError:
        return True


def _walk_dir(root: Path, folder: Path, rel: str) -> Iterator[Item]:
    try:
        with os.scandir(folder) as it:
            children = sorted(it, key=lambda e: e.name)
    except OSError:
        return
    for entry in children:
        child_rel = f"{rel}/{entry.name}"
        path = Path(entry.path)
        link = _is_link(entry)
        if link and not _inside(root, path):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        yield Item(child_rel, path, is_dir)
        if is_dir and not link:
            yield from _walk_dir(root, path, child_rel)


def walk(root: Path) -> Iterator[Item]:
    """보는 범위의 파일·폴더 (경로 순이 아니라 폴더별 이름 순)."""
    for name in TREE_DIRS:
        path = root / name
        if not path.is_dir():
            continue
        link = path.is_symlink() or path.is_junction()
        if link and not _inside(root, path):
            continue
        yield Item(name, path, True)
        if not link:
            yield from _walk_dir(root, path, name)
    for name in ROOT_FILES:
        path = root / name
        if path.is_file() and _inside(root, path):
            yield Item(name, path, False)


def _signature(path: Path, is_dir: bool) -> Signature | None:
    if is_dir:
        return (0, 0)
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def scan(root: Path, extra: dict[str, Path] | None = None) -> dict[str, Signature]:
    """경로 → 서명. `extra`(열린 문서 등)는 보는 범위 밖이어도 넣는다."""
    found: dict[str, Signature] = {}
    for item in walk(root):
        if (sig := _signature(item.path, item.is_dir)) is not None:
            found[item.rel] = sig
    for rel, path in (extra or {}).items():
        if rel not in found and (sig := _signature(path, False)) is not None:
            found[rel] = sig
    return found


def changed_paths(before: dict[str, Signature], after: dict[str, Signature]) -> list[str]:
    return sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel))


# ---------------------------------------------------------------- 감시


@dataclass(frozen=True, slots=True)
class DocChange:
    entry: OpenDoc
    connection: int
    """알릴 연결 (그 문서를 연 연결 하나)."""
    revision: str | None
    """지금 디스크 revision (파일이 없어졌거나 경로가 루트 밖·다른 파일로 바뀌었으면 None)."""


_GONE: Final = (-1, -1)


def _disk_revision(root: Path, entry: OpenDoc) -> bool:
    """`entry.disk`를 지금 디스크로 맞춘다 (경로 잠금 안). 읽지 못하면 False (다음 주기에 본다)."""
    # 실제 파일 경로(링크 없는 경로)로 다시 해석한다. 부모 폴더가 링크로 바뀌었으면 밖을 읽지 않는다
    try:
        recheck_path(root, entry.target)
    except RequestFailed, InvalidParams:
        entry.seen, entry.disk = _GONE, None  # 연 뒤에 경로가 바뀜: 그 파일은 없다
        return True
    path = entry.target.path
    try:
        st = path.stat()
        seen = (st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        seen = _GONE
    except OSError:
        return False
    if seen == entry.seen:
        return True
    if seen == _GONE:
        entry.disk = None
    else:
        try:
            entry.disk = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            entry.disk = None
        except OSError:
            return False
    entry.seen = seen
    return True


def check_document(root: Path, entry: OpenDoc, holders: list[int]) -> list[DocChange]:
    """열린 문서 하나의 디스크 revision을 **연결마다** 그 연결이 아는 revision과 비교한다.

    다른 연결의 daemon 저장도 그 연결에는 변경이다. 같은 디스크 revision은 연결마다 한 번만
    알리고, 디스크가 그 연결이 아는 revision과 같아지면 다시 알릴 수 있게 된다."""
    if not entry.lock.acquire(blocking=False):
        return []  # 저장·다시 읽기 중: 다음 주기에 본다
    try:
        if not _disk_revision(root, entry):
            return []
        marker = MISSING if entry.disk is None else entry.disk
        changes: list[DocChange] = []
        for connection in holders:
            if entry.disk == entry.known_revision(connection):
                entry.notified.pop(connection, None)
                continue
            if entry.notified.get(connection) == marker:
                continue
            entry.notified[connection] = marker
            changes.append(DocChange(entry, connection, entry.disk))
        return changes
    finally:
        entry.lock.release()


type Publish = Callable[[list[str], list[DocChange]], None]


class Watcher:
    """주기 폴링. `run()`은 이벤트 루프의 작업이고, 디스크 읽기는 스레드에서 한다."""

    def __init__(
        self, root: Path, documents: DocumentTable, publish: Publish, interval_s: float = 1.0
    ) -> None:
        self.root = root
        self.documents = documents
        self.publish = publish
        self.interval_s = interval_s
        self._last: dict[str, Signature] | None = None

    def _tick(self) -> tuple[list[str], list[DocChange]]:
        entries = self.documents.entries()
        current = scan(self.root, {e.rel: e.target.path for e in entries})
        paths = [] if self._last is None else changed_paths(self._last, current)
        self._last = current
        changes = [
            c for e in entries for c in check_document(self.root, e, self.documents.holders(e))
        ]
        return paths, changes

    async def run(self) -> None:
        while True:
            try:
                paths, changes = await asyncio.to_thread(self._tick)
            except Exception:
                log.exception("파일 감시 중 오류")
            else:
                if paths or changes:
                    try:
                        self.publish(paths, changes)
                    except Exception:
                        log.exception("변경 알림을 보내지 못했다")
            await asyncio.sleep(self.interval_s)
