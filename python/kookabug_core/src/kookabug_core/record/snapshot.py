"""실행 시작 스냅샷 (스키마 v0 5장 "실행 시작 때 고정", 구현 계획 M0b 2.8).

그래프가 참조하는 파일을 실행 폴더 `snapshot/`에 복사하고, 실행은 그 복사본에서 읽은 프로그램만
쓴다. 참조는 스냅샷에서 다시 읽어야 보이므로(서브그래프가 부르는 서브그래프 등) 고정점까지 돈다.

1. `kookabug.json`을 복사하고 그 복사본으로 스냅샷 워크스페이스를 연다(설정은 복사본 기준,
   `.kookabug/local.json` 설정은 원래 워크스페이스에서 읽은 것). 작업 큐 = [루트 그래프]
2. 큐의 경로를 원본에서 스냅샷으로 **한 번씩** 바이트 그대로 복사한다. 원본에 없으면 `absent`
3. 스냅샷 워크스페이스에서 읽어 `discovered`를 얻는다
4. 아직 처리하지 않은 경로가 있으면 2로. 없으면 고정점이다. 경로를 다시 처리하지 않으므로 반복
   횟수는 참조 파일 수 + 1 이하이고, 호출 깊이와 무관하다
5. 고정점에서 복사한 원본을 다시 `stat`해 복사 때와 다르면(크기·수정 시각) 복사 도중 원본이
   바뀐 것이다. 스냅샷을 비우고 처음부터 다시 (최대 3번, 넘으면 `snapshot_unstable`)

원본에도 없는 참조는 스냅샷 오류가 아니다. 의미 검증이 원래 코드(`call_target_missing`·
`target_missing`)로, 깊이 한도는 `call_depth`로 보고한다. 개인 폴더 `.kookabug/`(local.json·캐시)의
파일은 참조돼도 복사하지 않고 `snapshot_private_file`로 멈춘다. 판정은 경로 기준이다: 대소문자·
짧은 이름·심볼릭 링크·정션은 실제 경로로 풀어 본다. 하드 링크는 대상이 아니다(사용자가 자기
작업 폴더에서 일부러 만드는 것이고, 이것은 보안 경계가 아니다).
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from kookabug_core.loader import Program, load_program
from kookabug_core.record.runfolder import SNAPSHOT_DIR
from kookabug_core.workspace import (
    LOCAL_FILE,
    WORKSPACE_FILE,
    RunOptions,
    SecretProvider,
    Workspace,
    WorkspaceError,
)

__all__ = [
    "DEFAULT_LIMITS",
    "GRAPH_PREFIX",
    "Snapshot",
    "SnapshotError",
    "SnapshotLimits",
    "take_snapshot",
]

GRAPH_PREFIX: Final = f"{SNAPSHOT_DIR}/"
"""실행 폴더 기준 스냅샷 경로 접두 (`step.end.graph`, `ExecOptions.graph_prefix`)."""

PRIVATE_DIR: Final = LOCAL_FILE.split("/", 1)[0]
"""복사하지 않는 개인 폴더 (`.kookabug/`: 개인 설정·캐시·인덱스, Git 제외)."""

SnapshotCode = Literal[
    "snapshot_unstable", "snapshot_too_large", "snapshot_failed", "snapshot_private_file"
]


class SnapshotError(Exception):
    """스냅샷을 만들지 못했다. 실행은 `error`/`code`로 끝난다.

    `snapshot_unstable` 원본이 계속 바뀜, `snapshot_too_large` 자원 한도 초과,
    `snapshot_failed` 원본을 읽거나 스냅샷에 쓰지 못함, `snapshot_private_file` 그래프가
    개인 폴더 `.kookabug/`의 파일을 참조함.
    """

    def __init__(self, code: SnapshotCode, message: str) -> None:
        super().__init__(message)
        self.code: SnapshotCode = code


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    """정상 그래프의 호출 깊이와 무관한 한도. `max_retries`는 원본 변경을 감지했을 때만 센다."""

    max_files: int = 10_000
    max_bytes: int = 1 << 30
    max_retries: int = 3


@dataclass
class Snapshot:
    """`program`은 고정점의 마지막 로드 결과다 (실행은 이것을 다시 읽지 않고 쓴다).

    `files`는 복사한 파일(워크스페이스 기준 경로 → 크기), `absent`는 원본에도 없던 참조,
    `attempts`는 처음부터 다시 한 것을 포함한 시도 횟수.
    """

    root: Path
    workspace: Workspace
    program: Program
    files: dict[str, int] = field(default_factory=dict[str, int])
    absent: set[str] = field(default_factory=set[str])
    attempts: int = 1


DEFAULT_LIMITS: Final = SnapshotLimits()

_Signature = tuple[int, int]


def take_snapshot(
    workspace: Workspace,
    graph: str,
    dest: str | os.PathLike[str],
    *,
    options: RunOptions | None = None,
    secrets: SecretProvider | None = None,
    limits: SnapshotLimits = DEFAULT_LIMITS,
    on_copy: Callable[[str, int], None] | None = None,
) -> Snapshot:
    """`graph`(워크스페이스 기준 경로)와 그것이 참조하는 파일을 `dest`에 복사하고 거기서 읽는다.

    `dest`에 있던 내용은 지운다. `on_copy(경로, 시도 번호)`는 파일 하나를 복사한 직후 불린다
    (테스트에서 복사 도중 원본을 바꿀 때 쓴다).
    """
    root = Path(dest).resolve()
    for attempt in range(1, limits.max_retries + 2):
        _clear(root)
        copier = _Copier(workspace, root, limits, attempt, on_copy)
        copier.copy(WORKSPACE_FILE)
        snap = _open_snapshot(workspace, root)
        queue = {graph}
        while True:
            for rel in sorted(queue):
                copier.copy(rel)
            program = load_program(snap, graph, options=options, secrets=secrets)
            queue = program.references.discovered - copier.done()
            if not queue:
                break
        if copier.changed() is None:
            return Snapshot(
                root,
                snap,
                program,
                {rel: sig[0] for rel, sig in copier.copied.items()},
                copier.absent,
                attempt,
            )
    raise SnapshotError(
        "snapshot_unstable",
        f"스냅샷을 만드는 동안 원본 파일이 계속 바뀌었다 ({limits.max_retries + 1}번 시도)",
    )


def _open_snapshot(source: Workspace, root: Path) -> Workspace:
    """복사한 `kookabug.json`으로 스냅샷 워크스페이스를 연다.

    설정은 복사본에서 다시 읽는다: 원래 워크스페이스를 연 뒤 바뀐 파일이 복사됐을 때 스냅샷 파일과
    실행이 쓰는 설정이 어긋나지 않게 한다. local.json은 복사하지 않으므로 원래 워크스페이스에서
    읽은 값과 그 진단을 그대로 쓴다.
    """
    try:
        opened = Workspace.open(root)
    except WorkspaceError as exc:
        message = f"{WORKSPACE_FILE}을(를) 복사하지 못했다: {exc}"
        raise SnapshotError("snapshot_failed", message) from exc
    local_diags = [d for d in source.diagnostics if d.file == LOCAL_FILE]
    return Workspace(
        root=opened.root,
        config=opened.config,
        local=source.local,
        diagnostics=[*opened.diagnostics, *local_diags],
    )


class _Copier:
    def __init__(
        self,
        source: Workspace,
        root: Path,
        limits: SnapshotLimits,
        attempt: int,
        on_copy: Callable[[str, int], None] | None,
    ) -> None:
        self.source = source
        self.source_root = source.root.resolve()
        self.root = root
        self.limits = limits
        self.attempt = attempt
        self.on_copy = on_copy
        self.copied: dict[str, _Signature] = {}
        self.absent: set[str] = set()
        self.total = 0

    def done(self) -> set[str]:
        return self.copied.keys() | self.absent

    def copy(self, rel: str) -> None:
        src = self.source.resolve(rel)
        if src is None or rel in self.copied or rel in self.absent:
            return  # 워크스페이스 경로가 아님(로더가 graph_missing으로 보고) 또는 이미 처리
        if self._private(rel, src):
            raise SnapshotError(
                "snapshot_private_file",
                f"'{rel}'은(는) 개인 폴더 {PRIVATE_DIR}/의 파일이라 스냅샷에 복사하지 않는다. "
                "그래프·target이 이 파일을 가리키지 않게 고친다",
            )
        dst = self.root.joinpath(*rel.split("/"))
        sig = _signature(src)
        if sig is None:
            self.absent.add(rel)
            return
        if len(self.copied) + 1 > self.limits.max_files:
            raise SnapshotError(
                "snapshot_too_large",
                f"스냅샷 파일이 {self.limits.max_files}개를 넘는다",
            )
        if self.total + sig[0] > self.limits.max_bytes:
            raise SnapshotError(
                "snapshot_too_large",
                f"스냅샷 크기가 {self.limits.max_bytes}바이트를 넘는다 ('{rel}'에서)",
            )
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        except FileNotFoundError:
            # stat과 복사 사이에 지워졌다: 고정점에서 변경으로 잡히도록 복사 전 서명을 남긴다
            pass
        except OSError as exc:
            raise SnapshotError("snapshot_failed", f"'{rel}'을(를) 복사하지 못했다: {exc}") from exc
        self.copied[rel] = sig
        self.total += sig[0]
        if self.on_copy is not None:
            self.on_copy(rel, self.attempt)

    def _private(self, rel: str, src: Path) -> bool:
        """개인 폴더 안을 가리키는 경로인가. 실제 경로(대소문자·짧은 이름·심볼릭 링크·정션
        해석)로 본다. 하드 링크는 다른 경로의 같은 파일이라 가리지 않는다 (모듈 설명)."""
        if rel.split("/", 1)[0].casefold() == PRIVATE_DIR.casefold():
            return True
        try:
            real = src.resolve(strict=True)
        except OSError:
            return False  # 없는 파일: absent로 처리된다
        try:
            first = real.relative_to(self.source_root).parts[0]
        except ValueError, IndexError:
            first = ""
        return first.casefold() == PRIVATE_DIR.casefold()

    def changed(self) -> str | None:
        """복사 때와 서명이 달라진 첫 원본 (없으면 None)."""
        for rel, sig in self.copied.items():
            src = self.source.resolve(rel)
            assert src is not None
            if _signature(src) != sig:
                return rel
        return None


def _signature(path: Path) -> _Signature | None:
    """일반 파일의 (크기, 수정 시각 ns). 없거나 일반 파일이 아니면 None."""
    try:
        st = path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as exc:
        raise SnapshotError("snapshot_failed", f"'{path}'을(를) 확인하지 못했다: {exc}") from exc
    if not stat.S_ISREG(st.st_mode):
        return None
    return st.st_size, st.st_mtime_ns


def _clear(root: Path) -> None:
    """스냅샷 폴더를 비운다 (없으면 만든다). 앞 시도에서 복사한 파일이 남으면 원본에 없는 참조를
    스냅샷에서 읽게 된다."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    except OSError as exc:
        raise SnapshotError(
            "snapshot_failed", f"스냅샷 폴더 {root}을(를) 비우지 못했다: {exc}"
        ) from exc
