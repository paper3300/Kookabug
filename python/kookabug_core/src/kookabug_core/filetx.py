"""일반 파일 집합 거래 `filetx` (M8 계획 3.8 끝, E7) — 엄격: 사용자 파일 손상.

M7 화면 지도 승격 거래(`screen_promote._Tx`)의 규칙을 파일 집합용으로 새로 쓴 것이다(그 모듈은
그대로 둔다 — 통합은 BACKLOG). 지식 연산·위키 쓰기(B1), 자동 채택·되돌리기·묶음 수락(B3)이 쓴다.

    with locked(root) as warnings:          # 잠금 → 남은 거래 복구 → 남으면 recovery_pending
        tx = Tx(root)
        tx.create("knowledge/a.json", data)
        tx.replace("knowledge/b.json", data, expect_sha=before)
        tx.delete("knowledge/c.json", expect_sha=sha)
        result = tx.commit()

**원칙: 사용자 파일은 덮어쓰지도, 확인 뒤 지우지도 않는다.** 바꾸거나 지우거나 되돌릴 파일은
먼저 거래별 보존 영역(`.kookabug/filetx/trash/<txid>/<칸>`)으로 **옮기고**(이름 바꾸기 — 그 뒤
사람이 열린 핸들로 써도 바이트는 보존 영역 파일에 남는다) 옮긴 바이트를 확인한다. 기대와 다르면
제자리로 돌려놓는다. 새 바이트는 **배타** 이름 바꾸기로만 놓는다(그사이 같은 이름이 생기면 실패 →
사람 파일이 남는다). 보존 영역은 지우지 않고 나이·개수 기준으로만 가지치기한다(`TRASH_KEEP_DAYS`
지난 것 중 최근 `TRASH_KEEP_MIN` 거래 밖).

1. 확인: 만들 파일은 없어야(`exists`), 바꿀·지울 파일은 지금 sha가 기대값이어야
   (`revision_conflict`). 하나라도 어긋나면 아무것도 쓰지 않는다
2. 저널 `.kookabug/knowledge-tx/<txid>/`: 바꿀 파일의 원래 바이트 사본(`backup/<n>`) fsync, 그다음
   `journal.json`(`kookabug.filetx/0`, `phase: prepare`, 항목마다 보존 영역 칸 `slot`)을 임시 이름에
   쓰고 fsync → 이름 바꾸기
3. 게시: 새 파일은 같은 폴더 임시 이름 → fsync → 배타 이름 바꾸기. 바꿀 파일은 새 바이트를 임시
   이름(`.<이름>.<txid>.tmp`)에 쓰고 fsync → 원래 파일을 보존 영역 `old-<칸>`으로 옮겨 확인 → 새
   바이트를 배타로 놓음 → 저널 항목에 **놓음 표시**(`placed: true`)를 fsync로 남긴다
4. 커밋 표시: 저널을 `phase: committed`로 원자 교체. 이 뒤로 거래는 성공이다
5. 마무리(멱등): 지울 파일은 보존 영역 `del-<칸>`으로 옮겨 확인(다르면 제자리로) → 저널 폴더 지움

복구(`recover`, 잠금을 얻으면 먼저): 저널 파일이 없는 거래 폴더는 게시 전이라 지운다. `committed`면
5를 다시. `prepare`면 롤백 — 이 거래가 쓴 바이트일 때만 되돌린다(바꾼 파일이 `after_sha256`이면
`rb-<칸>`으로 옮겨 확인한 뒤 원래 바이트를 배타로 놓고, 만든 파일이 저널 sha면 `rm-<칸>`으로 옮겨
확인). 롤백이 중간에 멈춰도 다음 복구가 보존 영역 칸을 보고 이어 간다(저널 항목은 끝까지
처리한 뒤에만 빠진다). 원래 바이트를 제자리에 놓으면 **복원함 표시**(`restored: true`)를 fsync로
남긴다. 바꿀 파일이 없을 때 원래 자리로 되돌리는 것은 복원함 표시가 없고, 원래 파일이 보존 영역
`old-<칸>`에 그대로 있고(복원에 쓰면 사라진다), "놓기 전" 또는 "rb로 옮긴 뒤"가 디스크로 확실할
때뿐이다(놓음 표시가 없고 새 바이트 임시 파일이 남음 / `rb-<칸>`이 거래 바이트). 그 밖에는 사람의
삭제로 보고 되살리지 않는다(원래 바이트는 `.kookabug/knowledge-tx-kept/`에 남기고 알림). kept는
배타 게시만 한다 — 같은 이름에 다른 바이트(사람이 고친 것)가 있으면 그대로 두고 `<이름>-2`, `-3`…
비어 있는 이름에 놓고, 재시도는 같은 바이트의 이름을 찾는다. 사용자가 그사이 고친 파일은 손대지
않고 저널을 남긴다(그동안 새 거래는 `recovery_pending`).

쓰는 경로는 경로 조각마다 링크·정션이 아니고 실경로가 워크스페이스 안이어야 한다
(`path_outside_workspace`). 실패 주입 지점 `filetx.stage`(이벤트 = `STAGES`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import msvcrt
import os
import secrets
import shutil
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from kookabug_sdk import _faults

__all__ = [
    "FAULT_POINT",
    "KNOWLEDGE_LOCK",
    "RECOVERY_STAGES",
    "STAGES",
    "TRASH_DIR",
    "TRASH_KEEP_DAYS",
    "TRASH_KEEP_MIN",
    "TX_DIR",
    "Tx",
    "TxError",
    "file_lock",
    "journals",
    "locked",
    "pending",
    "plain",
    "read",
    "recover",
    "sha256_of",
]

log = logging.getLogger(__name__)

TX_DIR: Final = (".kookabug", "knowledge-tx")
KEPT_DIR: Final = (".kookabug", "knowledge-tx-kept")
TRASH_DIR: Final = (".kookabug", "filetx", "trash")
TRASH_KEEP_DAYS: Final = 7
TRASH_KEEP_MIN: Final = 20
"""보존 영역 가지치기: `TRASH_KEEP_DAYS`일 지났고 최근 `TRASH_KEEP_MIN` 거래 밖인 것만 지운다."""
JOURNAL: Final = "journal.json"
FORMAT: Final = "kookabug.filetx/0"
KNOWLEDGE_LOCK: Final = ".kookabug/knowledge.lock"
LOCK_WAIT_S: Final = 5.0
FAULT_POINT: Final = "filetx.stage"
STAGES: Final = (
    "journal_write",  # 저널 쓰기 중 (임시 파일 반쯤)
    "created",  # 새 파일 하나 게시 뒤
    "publish_fsync",  # 게시 파일 fsync 자리
    "taken",  # 바꿀 파일을 보존 영역으로 옮긴 뒤 (새 바이트를 놓기 전)
    "replaced",  # 바꿀 파일 하나 놓고 놓음 표시를 쓴 뒤
    "before_commit",  # 커밋 표시 직전
    "commit_fsync",  # 커밋 표시 fsync 자리 (교체 전)
    "after_commit",  # 커밋 표시 직후
    "deleted",  # 지울 파일 하나 보존 영역으로 옮긴 뒤
    "before_journal_remove",  # 저널 폴더 지우기 직전
    "rollback_rb",  # 롤백: 바꾼 파일을 보존 영역으로 옮긴 직후 (원래 바이트를 놓기 전)
    "rollback_rm",  # 롤백: 만든 파일을 보존 영역으로 옮긴 직후 (확인 전)
    "rollback_restored",  # 롤백: 원래 바이트를 제자리에 놓은 직후 (복원함 표시 전)
)
"""실패 주입 이벤트 이름 (`KOOKABUG_FAULTS` 지점 `filetx.stage`)."""
RECOVERY_STAGES: Final = frozenset({"rollback_rb", "rollback_rm", "rollback_restored"})
"""롤백·복구에서만 지나는 단계."""


class TxError(Exception):
    """거래를 하지 않았다 (또는 커밋 표시 중 실패). `code`는 daemon 오류 코드와 같다."""

    def __init__(self, code: str, message: str, **fields: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields


def _stage(name: str) -> None:
    _faults.fault_point(FAULT_POINT, event=name)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- 경로


def _parts(rel: str) -> list[str]:
    return [p for p in rel.replace("\\", "/").split("/") if p]


def plain(root: Path, rel: str) -> Path:
    """`root` 아래 `rel`: `.`·`..`·드라이브 없음, 있는 조각마다 링크·정션이 아니고 실경로가
    워크스페이스 실경로 안. 아니면 `path_outside_workspace`. 쓰기·지우기·읽기 전에 부른다."""
    parts = _parts(rel)
    if not parts or any(p in (".", "..") or ":" in p for p in parts) or rel.startswith("/"):
        raise TxError("path_outside_workspace", f"'{rel}'은(는) 쓸 수 없는 경로다", path=rel)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (current.exists() and current.is_junction()):
            raise TxError(
                "path_outside_workspace", f"'{rel}' 경로에 링크·정션이 있어 쓰지 않는다", path=rel
            )
    if not Path(os.path.realpath(current)).is_relative_to(Path(os.path.realpath(root))):
        raise TxError("path_outside_workspace", f"'{rel}'의 실경로가 워크스페이스 밖이다", path=rel)
    return current


def read(root: Path, rel: str) -> bytes | None:
    """`plain` 경로의 바이트. 없으면 None."""
    path = plain(root, rel)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TxError("io_error", f"'{rel}'을(를) 읽을 수 없다: {exc}", path=rel) from exc


def _sha(root: Path, rel: str) -> str | None:
    data = read(root, rel)
    return None if data is None else sha256_of(data)


def _file_sha(path: Path) -> str | None:
    try:
        return sha256_of(path.read_bytes())
    except FileNotFoundError:
        return None


def _flush(folder: Path) -> None:
    """폴더 항목을 디스크에 내린다. 못 하면 기록만 (파일 fsync·원자 이름 바꾸기에 기댄다)."""
    try:
        from kookabug_core.win.files import flush_dir

        flush_dir(folder)
    except (OSError, ImportError) as exc:
        log.warning("폴더 flush 실패 %s: %s", folder, exc)


def _write_journal(folder: Path, journal: Mapping[str, Any]) -> None:
    body = json.dumps(journal, ensure_ascii=False, indent=1).encode("utf-8")
    tmp = folder / f"{JOURNAL}.tmp"
    for path in (folder, tmp, folder / JOURNAL):
        if path.is_symlink() or path.is_junction():
            raise TxError("path_outside_workspace", "거래 저널 경로에 링크·정션이 있어 쓰지 않는다")
    with open(tmp, "wb") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, folder / JOURNAL)
    _flush(folder)


def _write_file(path: Path, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        _stage("publish_fsync")
        os.fsync(f.fileno())


def _tmp(path: Path, txid: str, tag: str = "tmp") -> Path:
    """새 바이트 임시 파일 (같은 폴더 — 배타 이름 바꾸기로 놓는다)."""
    return path.with_name(f".{path.name}.{txid}.{tag}")


# ---------------------------------------------------------------- 보존 영역


def _inside(root: Path, *parts: str) -> Path:
    """복구가 읽거나 옮기는 경로(원본·목적지 모두): `plain`과 같은 쓰기 경계 — 경로 조각마다
    링크·정션이 아니고 실경로가 워크스페이스 안. 아니면 `path_outside_workspace`(바깥 파일에는
    손대지 않고, 복구는 그 거래를 경고와 함께 남긴다 → `recovery_pending`)."""
    return plain(root, "/".join(parts))


def _slot(root: Path, txid: str, name: str) -> Path:
    """보존 영역 칸 (읽기·원본용 — 폴더를 만들지 않는다)."""
    return _inside(root, *TRASH_DIR, txid, name)


def _backup_bytes(root: Path, folder: Path, item: Mapping[str, Any]) -> bytes:
    return _inside(root, *TX_DIR, folder.name, *_parts(str(item["backup"]))).read_bytes()


def _trash(root: Path, txid: str, name: str) -> Path:
    rel = "/".join((*TRASH_DIR, txid, name))
    path = plain(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    return plain(root, rel)


def _move(src: Path, dst: Path) -> bool:
    """배타 이름 바꾸기. `dst`가 이미 있으면 False(아무것도 안 함)."""
    try:
        os.rename(src, dst)
    except FileExistsError:
        return False
    _flush(dst.parent)
    return True


def _kept_names(txid: str, rel: str) -> Iterator[str]:
    """kept 후보 이름: `<rel>`, `<rel>-2`, `<rel>-3`, … (재시도에서 같은 순서로 찾는다)."""
    base = "/".join((*KEPT_DIR, txid, *_parts(rel)))
    yield base
    for n in range(2, 10_000):
        yield f"{base}-{n}"


def _keep_path(root: Path, txid: str, rel: str, src: Path) -> str:
    """사용자 바이트일 수 있는 `src`를 `.kookabug/knowledge-tx-kept/<txid>/<rel>`(또는 비어 있는
    `-n` 이름)으로 **배타** 이름 바꾸기로 옮긴다. 있는 kept 파일은 절대 바꾸지 않는다(가지치기
    대상도 아니다)."""
    for target_rel in _kept_names(txid, rel):
        target = plain(root, target_rel)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if _move(src, plain(root, target_rel)):
            return target_rel
    raise TxError("io_error", f"'{rel}'의 보존 이름을 찾지 못했다", path=rel)


def _take(
    root: Path,
    txid: str,
    rel: str,
    path: Path,
    name: str,
    expect: str,
    *,
    stage: str | None = None,
) -> tuple[str, str | None]:
    """`path`를 보존 영역 칸 `name`으로 옮기고 그 바이트가 `expect`인지 본다. `(상태, 알림)`:
    `ok`(옮긴 파일 = 기대 바이트, 보존 영역에 있다), `missing`(없었다), `changed`(다른 바이트 —
    제자리로 돌려놓았다. 그새 같은 이름이 생겨 못 돌려놓으면 kept 폴더로 옮기고 알림)."""
    dst = _trash(root, txid, name)
    if dst.exists():  # 지난번 쓰고 남은 칸 (끝난 처리): 사람 바이트일 수 있어 kept로
        _keep_path(root, txid, rel, dst)
    try:
        os.rename(path, dst)
    except FileNotFoundError:
        return "missing", None
    if stage is not None:
        _stage(stage)
    if _file_sha(dst) == expect:
        return "ok", None
    if _move(dst, path):
        return "changed", None
    kept = _keep_path(root, txid, rel, dst)
    return "changed", f"'{rel}'의 사용자 바이트를 {kept}에 남겼다"


def _prune_trash(root: Path, live: set[str]) -> None:
    """보존 영역 가지치기 (나이·개수 기준만). `live`(남은 저널) 거래는 건드리지 않는다."""
    try:
        base = _inside(root, *TRASH_DIR)
    except TxError:
        log.warning("보존 영역 경로에 링크·정션이 있어 가지치기하지 않았다")
        return
    if not base.is_dir():
        return
    folders = sorted(
        (p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and not p.is_junction()),
        key=lambda p: p.name,
        reverse=True,
    )
    limit = time.time() - TRASH_KEEP_DAYS * 86400
    for folder in folders[TRASH_KEEP_MIN:]:
        if folder.name in live:
            continue
        try:
            if folder.stat().st_mtime < limit:
                shutil.rmtree(folder)
        except OSError as exc:
            log.warning("보존 영역 가지치기 실패 %s: %s", folder.name, exc)


# ---------------------------------------------------------------- 잠금


@contextlib.contextmanager
def file_lock(
    root: Path, rel: str = KNOWLEDGE_LOCK, *, wait_s: float = LOCK_WAIT_S
) -> Iterator[None]:
    """프로세스 공통 바이트 잠금 (`screen_lock`과 같은 방식). 못 얻으면 `knowledge_busy`."""
    path = plain(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TxError(
                        "knowledge_busy", f"다른 작업이 지식 저장소를 바꾸는 중이다 ({rel})"
                    ) from None
                time.sleep(0.02)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            with contextlib.suppress(OSError):
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(root: Path, rel: str = KNOWLEDGE_LOCK) -> Iterator[list[str]]:
    """잠금 → 복구 → 끝나지 않은 저널이 남으면 `recovery_pending`. 복구 경고 목록을 준다."""
    with file_lock(root, rel):
        warnings = recover(root)
        left = pending(root)
        if left:
            raise TxError(
                "recovery_pending",
                "끝나지 않은 파일 거래가 있어 바꾸지 않는다 — "
                + " / ".join(e["guide"] for e in left),
                paths=sorted({p for e in left for p in e["paths"]}),
                journals=[e["txid"] for e in left],
            )
        yield warnings


# ---------------------------------------------------------------- 거래


class Tx:
    """파일 집합 거래 하나. 잠금(`locked`)을 쥔 채 만들고 `commit()`한다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.creates: list[tuple[str, bytes]] = []
        self.replaces: list[tuple[str, str, bytes]] = []
        self.deletes: list[tuple[str, str]] = []
        self.txid = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        self.folder = root.joinpath(*TX_DIR, self.txid)
        self.journal: dict[str, Any] = {}
        self.placed: set[str] = set()
        """이 거래가 실제로 새 바이트를 놓은 바꿀 파일 (같은 프로세스 롤백이 놓지 않은 파일을
        사용자 수정으로 오해하지 않게)."""

    # ------------------------------------------------------------ 계획

    def _taken(self, rel: str) -> None:
        key = "/".join(_parts(rel)).casefold()
        used = [r for r, _ in self.creates] + [r for r, _, _ in self.replaces]
        used += [r for r, _ in self.deletes]
        if any("/".join(_parts(r)).casefold() == key for r in used):
            raise TxError("tx_invalid", f"'{rel}'을(를) 한 거래에서 두 번 바꾼다", path=rel)

    def create(self, rel: str, data: bytes) -> None:
        self._taken(rel)
        plain(self.root, rel)
        self.creates.append((rel, data))

    def replace(self, rel: str, data: bytes, *, expect_sha: str) -> None:
        self._taken(rel)
        plain(self.root, rel)
        self.replaces.append((rel, expect_sha, data))

    def delete(self, rel: str, *, expect_sha: str) -> None:
        self._taken(rel)
        plain(self.root, rel)
        self.deletes.append((rel, expect_sha))

    def write(self, rel: str, data: bytes, *, expect_sha: str | None) -> None:
        """`expect_sha`가 None이면 새 파일, 아니면 바꾸기. 바이트가 같으면 아무것도 안 한다."""
        if expect_sha is None:
            self.create(rel, data)
        elif sha256_of(data) != expect_sha:
            self.replace(rel, data, expect_sha=expect_sha)

    @property
    def empty(self) -> bool:
        return not (self.creates or self.replaces or self.deletes)

    # ------------------------------------------------------------ 실행

    def commit(self) -> dict[str, Any]:
        """거래 한 번. `{txid, paths, cleanup_pending, warnings}`. 커밋 전 실패는 되돌리고 예외."""
        paths = sorted(
            {r for r, _ in self.creates}
            | {r for r, _, _ in self.replaces}
            | {r for r, _ in self.deletes}
        )
        if self.empty:
            return {"txid": None, "paths": [], "cleanup_pending": False, "warnings": []}
        self._check()
        try:
            self._prepare()
            self._publish()
            _stage("before_commit")
        except BaseException:
            self.rollback_now()
            raise
        self._commit_mark()
        warnings: list[str] = []
        try:
            _stage("after_commit")
            warnings += _finish(self.root, self.folder, self.journal)
            cleanup = self.folder.exists()
        except Exception as exc:  # 커밋 뒤: 성공이다. 마무리는 다음 잠금에서
            log.warning("파일 거래 마무리가 남았다 (%s): %s", self.txid, exc)
            cleanup = True
        return {"txid": self.txid, "paths": paths, "cleanup_pending": cleanup, "warnings": warnings}

    def _check(self) -> None:
        for rel, _ in self.creates:
            if plain(self.root, rel).exists():
                raise TxError("exists", f"'{rel}'이(가) 이미 있다", path=rel)
        for rel, before, _ in self.replaces:
            if _sha(self.root, rel) != before:
                raise TxError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
        for rel, before in self.deletes:
            if _sha(self.root, rel) != before:
                raise TxError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])

    def _prepare(self) -> None:
        base = plain(self.root, "/".join(TX_DIR))
        base.mkdir(parents=True, exist_ok=True)
        plain(self.root, "/".join((*TX_DIR, self.txid)))
        self.folder.mkdir()
        backup = self.folder / "backup"
        backup.mkdir()
        replaces: list[dict[str, Any]] = []
        for n, (rel, before, after) in enumerate(self.replaces):
            data = read(self.root, rel)
            if data is None or sha256_of(data) != before:
                raise TxError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
            with open(backup / str(n), "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            replaces.append(
                {
                    "path": rel,
                    "slot": n,
                    "before_sha256": before,
                    "after_sha256": sha256_of(after),
                    "backup": f"backup/{n}",
                    "placed": False,
                }
            )
        dirs: list[str] = []
        for rel, _ in self.creates:
            parts = _parts(rel)[:-1]
            for n in range(len(parts), 0, -1):
                folder_rel = "/".join(parts[:n])
                if plain(self.root, folder_rel).exists():
                    break
                if folder_rel not in dirs:
                    dirs.append(folder_rel)
        self.journal = {
            "format": FORMAT,
            "txid": self.txid,
            "phase": "prepare",
            "created_at": _now(),
            "creates": [
                {"path": rel, "slot": n, "sha256": sha256_of(data)}
                for n, (rel, data) in enumerate(self.creates)
            ],
            "replaces": replaces,
            "deletes": [
                {"path": rel, "slot": n, "sha256": sha} for n, (rel, sha) in enumerate(self.deletes)
            ],
            "dirs": dirs,
        }
        body = json.dumps(self.journal, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = self.folder / f"{JOURNAL}.tmp"
        with open(tmp, "wb") as f:
            half = len(body) // 2
            f.write(body[:half])
            f.flush()
            _stage("journal_write")
            f.write(body[half:])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.folder / JOURNAL)
        _flush(self.folder)
        _flush(self.folder.parent)

    def _publish(self) -> None:
        touched: set[Path] = set()
        for rel, data in self.creates:
            path = plain(self.root, rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path = plain(self.root, rel)  # 만든 폴더도 다시 본다
            tmp = _tmp(path, self.txid)
            try:
                _write_file(tmp, data)
                os.rename(tmp, path)  # 배타: 있으면 실패
            except FileExistsError as exc:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise TxError("exists", f"'{rel}'이(가) 이미 있다", path=rel) from exc
            except BaseException:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            touched.add(path.parent)
            _stage("created")
        for n, (rel, before, data) in enumerate(self.replaces):
            path = plain(self.root, rel)
            # 새 바이트 임시 파일은 실패해도 지우지 않는다 — 롤백이 "놓기 전에 멈춤"을 가르는 표시다
            tmp = _tmp(path, self.txid)
            _write_file(tmp, data)
            state, note = _take(self.root, self.txid, rel, path, f"old-{n}", before)
            if note:
                log.warning("파일 거래 게시: %s", note)
            if state != "ok":
                raise TxError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
            _stage("taken")
            if not _move(tmp, path):  # 옮긴 사이 사람이 같은 이름을 만들었다
                raise TxError("revision_conflict", f"'{rel}'이(가) 바뀌었다", paths=[rel])
            self.placed.add(rel)
            self._mark_placed(n)
            touched.add(path.parent)
            _stage("replaced")
        for folder in sorted(touched):
            _flush(folder)

    def _mark_placed(self, slot: int) -> None:
        """놓음 표시를 저널에 fsync로 남긴다 (복구가 "옮긴 뒤 멈춤"과 "놓은 뒤 사람이 지움"을
        가른다)."""
        replaces = [
            {**item, "placed": True} if item["slot"] == slot else item
            for item in self.journal["replaces"]
        ]
        journal = {**self.journal, "replaces": replaces}
        _write_journal(self.folder, journal)
        self.journal = journal

    def _commit_mark(self) -> None:
        committed = {**self.journal, "phase": "committed"}
        body = json.dumps(committed, ensure_ascii=False, indent=1).encode("utf-8")
        tmp = self.folder / f"{JOURNAL}.tmp"
        swapped = False
        try:
            with open(tmp, "wb") as f:
                f.write(body)
                f.flush()
                _stage("commit_fsync")
                os.fsync(f.fileno())
            os.replace(tmp, self.folder / JOURNAL)
            swapped = True
            self.journal = committed
            _flush(self.folder)
        except Exception as exc:
            if not swapped:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                self.rollback_now()
            raise TxError(
                "tx_failed", f"거래 커밋 표시를 쓰지 못했다 — 저널대로 복구한다: {exc}"
            ) from exc

    def rollback_now(self) -> None:
        """게시 중 실패: 저널이 있으면 그대로 되돌리고, 없으면 거래 폴더만 지운다."""
        try:
            if (self.folder / JOURNAL).is_file():
                untouched = {
                    str(i["path"])
                    for i in self.journal.get("replaces", [])
                    if str(i["path"]) not in self.placed
                }
                _rollback(self.root, self.folder, self.journal, untouched=untouched)
            else:
                shutil.rmtree(self.folder, ignore_errors=True)
        except Exception:
            log.exception("파일 거래 롤백 실패 (%s) — 다음 복구가 다시 한다", self.txid)


# ---------------------------------------------------------------- 마무리·롤백·복구


def _finish(root: Path, folder: Path, journal: Mapping[str, Any]) -> list[str]:
    """커밋된 거래의 마무리 (멱등). 끝나면 거래 폴더를 지운다."""
    warnings: list[str] = []
    txid = str(journal.get("txid", folder.name))
    for item in journal.get("replaces", []):
        # 옮긴 원래 파일이 그사이(열린 핸들로) 바뀌었으면 가지치기되지 않는 kept로
        old = _slot(root, txid, f"old-{item['slot']}")
        sha = _file_sha(old)
        if sha is not None and sha != item["before_sha256"]:
            kept = _keep_path(root, txid, str(item["path"]), old)
            warnings.append(f"'{item['path']}'의 옮긴 원래 파일이 거래 중에 바뀌어 {kept}에 남겼다")
    for item in journal.get("deletes", []):
        rel = str(item["path"])
        path = plain(root, rel)
        name = f"del-{item['slot']}"
        gone = _slot(root, txid, name)
        if not path.exists() and gone.is_file():
            # 지난번 옮긴 뒤 확인 전에 멈췄다: 기대 바이트가 아니면 사람 것 → 제자리로
            if _file_sha(gone) != item["sha256"]:
                if not _move(gone, path):
                    kept = _keep_path(root, txid, rel, gone)
                    warnings.append(f"'{rel}'의 사용자 바이트를 {kept}에 남겼다")
                warnings.append(f"'{rel}'이(가) 거래 뒤 바뀌어 지우지 않았다")
            continue
        state, note = _take(root, txid, rel, path, name, str(item["sha256"]))
        if note:
            warnings.append(note)
        if state == "changed":
            warnings.append(f"'{rel}'이(가) 거래 뒤 바뀌어 지우지 않았다")
            continue
        if state == "ok":
            _stage("deleted")
    _stage("before_journal_remove")
    shutil.rmtree(folder)
    return warnings


def _keep_backup(root: Path, folder: Path, txid: str, item: Mapping[str, Any]) -> str:
    """원래 바이트(백업)를 kept에 남긴다. 같은 바이트의 kept가 이미 있으면 그 이름(재시도), 다른
    바이트가 있으면(사람이 고침) 그대로 두고 비어 있는 `-n` 이름에 **배타** 게시한다."""
    data = _backup_bytes(root, folder, item)
    for target_rel in _kept_names(txid, str(item["path"])):
        target = plain(root, target_rel)
        if target.exists():
            if target.is_file() and target.read_bytes() == data:
                return target_rel
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if _move(tmp, plain(root, target_rel)):
            return target_rel
        with contextlib.suppress(OSError):
            tmp.unlink()  # 그새 같은 이름이 생겼다 — 우리 사본만 버리고 다음 이름
    raise TxError("io_error", f"'{item['path']}'의 보존 이름을 찾지 못했다", path=item["path"])


def _restore_original(
    root: Path, folder: Path, txid: str, item: Mapping[str, Any], *, from_backup: bool
) -> str | None:
    """빈 자리(`path` 없음)에 원래 바이트를 배타로 놓는다: 보존 영역 `old-<칸>`이 원래 바이트면
    그것을, 아니면(`from_backup`일 때만) 백업 사본을. 경고 글(놓지 못함) 또는 None."""
    rel = str(item["path"])
    path = plain(root, rel)
    before = str(item["before_sha256"])
    old = _slot(root, txid, f"old-{item['slot']}")
    if _file_sha(old) == before:
        src = old
    elif not from_backup:
        return f"'{rel}'의 원래 파일이 보존 영역에 없어 되돌리지 않았다"
    else:
        backup = _backup_bytes(root, folder, item)
        if sha256_of(backup) != before:
            return f"'{rel}'의 백업이 손상돼 되돌리지 않았다"
        src = _tmp(path, txid, "rb.tmp")
        with open(src, "wb") as f:
            f.write(backup)
            f.flush()
            os.fsync(f.fileno())
    if not _move(src, path):
        if src != old:
            with contextlib.suppress(OSError):
                src.unlink()  # 백업에서 만든 우리 사본
        return f"'{rel}'이(가) 되돌리는 중에 새로 생겨 손대지 않았다 (사용자 바이트 보존)"
    return None


def _drop_tmps(path: Path, txid: str) -> None:
    """이 거래가 그 파일 옆에 쓴 임시 파일들 (처리가 끝난 항목만)."""
    for tag in ("tmp", "rb.tmp"):
        with contextlib.suppress(OSError):
            _tmp(path, txid, tag).unlink()


def _rollback_replace(
    root: Path,
    folder: Path,
    txid: str,
    item: dict[str, Any],
    untouched: set[str] | frozenset[str],
    warnings: list[str],
    notes: list[str],
    mark_restored: Callable[[dict[str, Any]], None],
) -> bool:
    """바꿀 파일 하나 되돌리기. 끝났으면 True, 사람 확인이 필요해 저널에 남기면 False.

    원래 바이트를 제자리에 놓으면 저널 항목에 **복원함 표시**(`restored`)를 fsync로 남긴다
    (`mark_restored`). 다음 복구는 이 표시로 "복원 전에 멈춤"과 "복원 뒤 사람이 지움"을 가른다.
    표시가 없을 때는 보존 영역 `old-<칸>`(복원에 쓰면 사라진다)이 원래 바이트로 남아 있을 때만
    복원 전이 확실하다고 보고, 그 밖에는 되살리지 않고 원래 바이트를 kept에 남긴다."""
    rel = str(item["path"])
    path = plain(root, rel)
    before = str(item["before_sha256"])
    after = str(item["after_sha256"])
    rb = _slot(root, txid, f"rb-{item['slot']}")
    if item.get("restored") is True:
        return True  # 복원까지 끝났다: 그 뒤 사람이 지우거나 고친 것은 그대로 둔다
    marked = item.get("placed") is True
    # 놓지 않은 것이 확실: 놓음 표시가 없고, 같은 프로세스가 놓지 않았다고 알거나 새 바이트 임시
    # 파일이 아직 있다(배타 이름 바꾸기로 놓으면 임시 파일은 사라진다)
    unplaced = not marked and (rel in untouched or _tmp(path, txid).is_file())
    current = _sha(root, rel)

    def undecidable(why: str) -> bool:
        kept = _keep_backup(root, folder, txid, item)
        notes.append(f"'{rel}'이(가) {why} 되살리지 않았다 — 원래 바이트는 {kept}에 남겼다")
        return True

    def restore(*, from_backup: bool) -> bool:
        problem = _restore_original(root, folder, txid, item, from_backup=from_backup)
        if problem:
            warnings.append(problem)
            return False
        _stage("rollback_restored")
        mark_restored(item)
        return True

    old_ok = _file_sha(_slot(root, txid, f"old-{item['slot']}")) == before
    if current is None and rb.is_file():
        if _file_sha(rb) == after:
            # 지난 롤백이 우리 바이트를 rb로 옮겼다. 원래 파일이 보존 영역에 그대로면 복원 전에
            # 멈춘 것 → 이어서 복원. 아니면 복원 뒤 사람이 지웠을 수 있어 가를 수 없다
            if old_ok:
                return restore(from_backup=False)
            return undecidable("복원 뒤 지워졌는지 가를 수 없어")
        if not _move(rb, path):  # rb에 사람 바이트(열린 핸들로 씀) → 제자리로
            kept = _keep_path(root, txid, rel, rb)
            notes.append(f"'{rel}'의 사용자 바이트를 {kept}에 남겼다")
        warnings.append(f"'{rel}'이(가) 거래 중에 바뀌어 되돌리지 않았다 (사용자 바이트 보존)")
        return False
    if current is None:
        if unplaced and old_ok:
            # 원래 파일을 옮긴 뒤 새 바이트를 놓기 전에 멈췄다 → 원래 자리로
            return restore(from_backup=False)
        # 놓은 뒤 사람이 지웠거나 가를 수 없다: 되살리지 않는다
        return undecidable("지워졌거나 가를 수 없어")
    if current == before or unplaced:
        return True  # 원래 그대로이거나, 이 거래가 놓지 않은 사람 바이트
    if current == after:
        state, note = _take(root, txid, rel, path, rb.name, after, stage="rollback_rb")
        if note:
            notes.append(note)
        if state == "ok":
            if restore(from_backup=True):
                return True
            if not _move(rb, path):
                notes.append(f"'{rel}'의 거래 바이트는 보존 영역 {rb.name}에 남겼다")
            return False
        if state == "missing":
            return undecidable("지워져")
    warnings.append(
        f"'{rel}'이(가) 거래 중에 바뀌어 되돌리지 않았다 (사용자 바이트 보존 — 원래 바이트는 "
        f"{'/'.join((*TX_DIR, folder.name, str(item['backup'])))})"
    )
    return False


def _rollback_create(
    root: Path, txid: str, item: Mapping[str, Any], warnings: list[str], notes: list[str]
) -> bool:
    """만든 파일 하나 되돌리기 (보존 영역 `rm-<칸>`으로 옮김). 끝났으면 True."""
    rel = str(item["path"])
    path = plain(root, rel)
    rm = _slot(root, txid, f"rm-{item['slot']}")
    current = _sha(root, rel)
    if current is None:
        if rm.is_file() and _file_sha(rm) != item["sha256"]:
            # 지난 롤백이 옮긴 뒤 확인 전에 멈췄고, 그사이 사람이 썼다 → 제자리로
            if not _move(rm, path):
                kept = _keep_path(root, txid, rel, rm)
                notes.append(f"'{rel}'의 사용자 바이트를 {kept}에 남겼다")
            warnings.append(f"'{rel}'이(가) 거래 중에 바뀌어 지우지 않았다 (사용자 바이트 보존)")
            return False
        return True
    if current != item["sha256"]:
        warnings.append(f"'{rel}'이(가) 거래 중에 바뀌어 지우지 않았다 (사용자 바이트 보존)")
        return False
    state, note = _take(root, txid, rel, path, rm.name, str(item["sha256"]), stage="rollback_rm")
    if note:
        notes.append(note)
    if state == "changed":
        warnings.append(f"'{rel}'이(가) 거래 중에 바뀌어 지우지 않았다 (사용자 바이트 보존)")
        return False
    return True


def _rollback(
    root: Path,
    folder: Path,
    journal: Mapping[str, Any],
    *,
    untouched: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """커밋 안 된 거래를 되돌린다. 이 거래가 쓴 바이트일 때만 손댄다(손대기 전에 보존 영역으로 옮겨
    확인한다). 저널은 모든 항목을 처리한 뒤에만 고친다 — 중간에 멈추면 다음 복구가 보존 영역 칸을
    보고 이어 간다. 경고 항목(사람이 고친 파일·백업 손상)만 남으면 저널을 남긴다. `untouched`: 같은
    프로세스 롤백에서 새 바이트를 놓지 않은 바꿀 파일."""
    warnings: list[str] = []
    notes: list[str] = []
    txid = str(journal.get("txid", folder.name))
    left_replaces: list[Any] = []
    left_creates: list[Any] = []
    # 복원함 표시를 항목마다 남기려고 저널을 고쳐 쓸 사본 (처리 끝 항목을 빼는 것은 맨 끝에만)
    state: dict[str, Any] = {**journal, "replaces": [dict(i) for i in journal.get("replaces", [])]}

    def mark_restored(item: dict[str, Any]) -> None:
        item["restored"] = True
        _write_journal(folder, state)

    for item in cast(list[dict[str, Any]], state["replaces"]):
        done = _rollback_replace(
            root, folder, txid, item, untouched, warnings, notes, mark_restored
        )
        if done:
            _drop_tmps(plain(root, str(item["path"])), txid)
            # 보존 영역의 원래 파일이 그사이(열린 핸들로) 바뀌었으면 가지치기되지 않는 kept로
            old = _slot(root, txid, f"old-{item['slot']}")
            sha = _file_sha(old)
            if sha is not None and sha != item["before_sha256"]:
                kept = _keep_path(root, txid, str(item["path"]), old)
                notes.append(f"'{item['path']}'의 옮긴 원래 파일이 바뀌어 {kept}에 남겼다")
        else:
            left_replaces.append(item)
    for item in reversed(journal.get("creates", [])):
        path = plain(root, str(item["path"]))
        _drop_tmps(path, txid)  # 만든 파일의 임시 파일은 판정에 쓰지 않는다
        if not _rollback_create(root, txid, item, warnings, notes):
            left_creates.insert(0, item)
    left_dirs: list[str] = []
    for folder_rel in sorted(journal.get("dirs", []), key=lambda r: r.count("/"), reverse=True):
        path = plain(root, str(folder_rel))
        if not path.is_dir():
            continue
        try:
            path.rmdir()
        except OSError:
            left_dirs.append(str(folder_rel))
    for note in notes:
        log.warning("파일 거래 롤백: %s", note)
    if warnings:
        for w in warnings:
            log.warning("파일 거래 롤백: %s", w)
        _write_journal(
            folder,
            {
                **journal,
                "creates": left_creates,
                "replaces": left_replaces,
                "deletes": [],
                "dirs": left_dirs,
                "warnings": warnings,
                "updated_at": _now(),
            },
        )
        return [*warnings, *notes]
    shutil.rmtree(folder, ignore_errors=True)
    return notes


def _readable_dir(path: Path) -> bool:
    try:
        with os.scandir(path) as it:
            next(it, None)
    except OSError:
        return False
    return True


def _tx_entries(root: Path) -> tuple[list[Path], list[str]]:
    """(안전한 거래 폴더들, 안전하지 않은 항목 이름들). 거래 폴더 자리의 링크·정션·파일·읽을 수
    없는 폴더는 **존재하는 안전하지 않은 거래**다 — 따라 읽지 않고 이름만 돌려준다(빼먹으면
    복구 대기·가지치기 보호가 함께 풀린다). 상위 폴더 경계 위반은 `path_outside_workspace`."""
    base = _inside(root, *TX_DIR)
    if not base.is_dir():
        return [], []
    safe: list[Path] = []
    unsafe: list[str] = []
    for p in sorted(base.iterdir()):
        if p.is_symlink() or p.is_junction() or not p.is_dir() or not _readable_dir(p):
            unsafe.append(p.name)
        else:
            safe.append(p)
    return safe, unsafe


def _unsafe_entry(name: str) -> dict[str, Any]:
    folder = "/".join((*TX_DIR, name))
    return {
        "txid": name,
        "folder": folder,
        "phase": "unsafe",
        "paths": [],
        "backups": {},
        "warnings": [f"거래 저널 자리 {folder}가 링크·정션이거나 폴더가 아니어서 읽지 않았다"],
        "guide": f"거래 저널 자리 {folder}가 링크·정션이거나 폴더가 아니다 — 직접 확인한다",
    }


def recover(root: Path) -> list[str]:
    """남은 거래를 끝낸다 (잠금을 쥔 채 부른다). 경고 목록. 끝에 보존 영역을 가지치기한다.

    복구가 읽거나 옮기는 경로(저널·백업·보존 영역 칸·kept·대상)는 모두 쓰기 경계(`_inside`)를
    지난다. 경계를 벗어나는 경로가 있으면 그 거래는 손대지 않고(바깥 파일 그대로) 경고와 함께
    남긴다 — 다음 거래는 `recovery_pending`."""
    warnings: list[str] = []
    try:
        folders, unsafe = _tx_entries(root)
    except TxError as exc:
        return [f"거래 저널 폴더: {exc.message}"]
    for name in unsafe:
        warnings.append(_unsafe_entry(name)["warnings"][0])
    for folder in folders:
        try:
            journal_path = _inside(root, *TX_DIR, folder.name, JOURNAL)
        except TxError as exc:
            warnings.append(f"거래 저널 {folder.name}: {exc.message}")
            continue
        if not journal_path.exists():
            shutil.rmtree(folder, ignore_errors=True)
            warnings.append(f"끝나지 않은 거래 준비 {folder.name}을(를) 지웠다 (바뀐 파일 없음)")
            continue
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(journal, dict) or journal.get("format") != FORMAT:
                raise ValueError("형식이 다르다")
            phase = journal["phase"]
        except (OSError, ValueError, KeyError) as exc:
            text = f"거래 저널 {folder.name}이(가) 깨져 손대지 않았다: {exc}"
            log.warning("%s", text)
            warnings.append(text)
            continue
        try:
            if phase == "committed":
                warnings += _finish(root, folder, journal)
            elif phase == "prepare":
                warnings += _rollback(root, folder, journal)
            else:
                warnings.append(f"거래 저널 {folder.name}의 단계 {phase!r}를 몰라 손대지 않았다")
        except TxError as exc:
            warnings.append(f"거래 저널 {folder.name}: {exc.message}")
        except Exception as exc:  # 파일이 잠겨 있는 등: 저널을 남기고 다음에 다시
            log.exception("거래 저널 %s 복구 실패", folder.name)
            warnings.append(f"거래 저널 {folder.name}을(를) 복구하지 못했다 (다음에 다시): {exc}")
    try:
        live, unsafe = _tx_entries(root)
    except TxError:
        return warnings
    if unsafe:  # 안전하지 않은 거래가 있으면 어느 보존 폴더가 그 거래 것인지 믿을 수 없다
        log.warning("안전하지 않은 거래 저널이 있어 보존 영역 가지치기를 미뤘다")
    else:
        _prune_trash(root, {p.name for p in live})
    return warnings


def pending(root: Path) -> list[dict[str, Any]]:
    """남은 거래 저널 (사람 확인용): `{txid, phase, paths, warnings, backups, guide}`."""
    out: list[dict[str, Any]] = []
    try:
        folders, unsafe = _tx_entries(root)
    except TxError as exc:
        folder = "/".join(TX_DIR)
        return [
            {
                "txid": "-",
                "folder": folder,
                "phase": "unsafe",
                "paths": [],
                "backups": {},
                "warnings": [exc.message],
                "guide": f"거래 저널 폴더 {folder}에 링크·정션이 있다 — 직접 확인한다",
            }
        ]
    out.extend(_unsafe_entry(name) for name in unsafe)
    for folder in folders:
        entry: dict[str, Any] = {"txid": folder.name, "folder": "/".join((*TX_DIR, folder.name))}
        try:
            journal = json.loads(
                _inside(root, *TX_DIR, folder.name, JOURNAL).read_text(encoding="utf-8")
            )
            if not isinstance(journal, dict) or journal.get("format") != FORMAT:
                raise ValueError("형식이 다르다")
        except (OSError, ValueError, TxError) as exc:
            entry.update(
                phase="corrupt", paths=[], backups={}, warnings=[f"저널을 읽을 수 없다: {exc}"]
            )
            entry["guide"] = f"거래 저널 {entry['folder']}이(가) 손상됐다 — 직접 확인한다"
            out.append(entry)
            continue
        creates = sorted(str(i["path"]) for i in journal.get("creates", []))
        replaces = sorted(str(i["path"]) for i in journal.get("replaces", []))
        entry["phase"] = journal.get("phase")
        entry["warnings"] = list(journal.get("warnings", []))
        entry["paths"] = sorted(
            {*creates, *replaces, *(str(i["path"]) for i in journal.get("deletes", []))}
        )
        entry["backups"] = {
            str(i["path"]): "/".join((*TX_DIR, folder.name, str(i["backup"])))
            for i in journal.get("replaces", [])
        }
        parts: list[str] = []
        if replaces:
            parts.append("바뀐 파일(" + ", ".join(replaces) + ")은 원래 바이트(백업)로 되돌린다")
        if creates:
            parts.append(
                "거래가 만든 파일(" + ", ".join(creates) + ")은 필요하면 다른 곳으로 옮긴다"
            )
        entry["guide"] = "; ".join(parts) or "남은 항목이 없다 (다음 복구가 끝낸다)"
        out.append(entry)
    return out


def journals(root: Path) -> list[str]:
    """남아 있는 거래 이름들 (진단·검사용 — 안전하지 않은 항목 포함)."""
    folders, unsafe = _tx_entries(root)
    return sorted([p.name for p in folders] + unsafe)
