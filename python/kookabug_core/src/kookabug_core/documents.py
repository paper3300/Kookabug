"""그래프 문서: 원문 바이트·revision·저장 (M2 계획 2.6).

에디터(JS)는 그래프 파일을 직렬화하지 않는다. 값 전체를 받아 여기서 쓸 바이트를 정한다.

    doc = documents.open(path)
    result = documents.save(doc, value, doc.revision)

- 파일은 **바이트로** 읽는다(줄바꿈 변환 없음). revision은 원문 바이트의 sha256 hex다
- BOM으로 시작하는 파일은 JSON 오류다 (로더도 읽지 못하는 파일이라 실행과 같은 판정)
- 저장은 값이 원문과 같으면 원문 바이트로 되돌리고(`canonical.save_text`), 그 바이트가 **지금 디스크
  바이트**와 같으면 쓰지 않는다. 다르면 같은 폴더 임시 파일 → fsync → `os.replace`로 쓴다
- 형식 검사의 수 규칙(`number_out_of_range`·`number_not_finite`)에 걸리는 값만 저장을 막는다.
  그 밖의 검증 오류는 막지 않는다 (편집 중인 그래프는 틀릴 수 있다)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.canonical import canonical_dumps, is_canonical, loads_strict, save_text
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import check_shape

__all__ = [
    "GRAPH_FORMAT",
    "NUMBER_CODES",
    "Document",
    "DocumentError",
    "SaveResult",
    "create",
    "number_problems",
    "open",
    "revision_of",
    "save",
    "template",
    "write_atomic",
]

GRAPH_FORMAT: Final = "kookabug.graph/0"
NUMBER_CODES: Final = frozenset({"number_out_of_range", "number_not_finite"})
"""저장을 막는 진단 코드 (JSON에 쓸 수 없거나 JavaScript가 정확히 다루지 못하는 수)."""

_BOM: Final = b"\xef\xbb\xbf"
ENTRY_NODE: Final = "n_entry"
EXIT_NODE: Final = "n_exit"
CORE_PLUGIN: Final = "core"

ErrorCode = Literal[
    "not_found", "invalid_json", "revision_conflict", "exists", "validation_failed", "io_error"
]


class DocumentError(Exception):
    """문서를 열거나 저장할 수 없다. `code`는 daemon 오류 `data.code`와 같은 이름이다.

    - `not_found` 파일 없음, `exists` 만들려는 파일이 이미 있음
    - `invalid_json` JSON이 아님(BOM·중복 키·NaN 포함). `line`·`column`은 알 때만
    - `revision_conflict` 디스크가 기준 revision과 다름. `revision`은 지금 디스크(없으면 None)
    - `validation_failed` 수 규칙 위반 (`diagnostics`)
    - `io_error` 읽기·쓰기 실패
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        path: Path | None = None,
        revision: str | None = None,
        line: int | None = None,
        column: int | None = None,
        diagnostics: list[Diagnostic] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.path = path
        self.revision = revision
        self.line = line
        self.column = column
        self.diagnostics = diagnostics or []


@dataclass
class Document:
    """열린 그래프 파일 하나. 저장에 성공하면 원문·값·revision이 새 바이트로 바뀐다."""

    path: Path
    original_bytes: bytes
    original_text: str
    value: Any
    revision: str

    @property
    def canonical(self) -> bool:
        """원문이 canonical 형식인가."""
        return is_canonical(self.original_text)


@dataclass(frozen=True, slots=True)
class SaveResult:
    revision: str
    wrote: bool
    """False면 지금 디스크 바이트와 같아 쓰지 않았다 (mtime 그대로)."""
    canonicalized: bool
    """canonical이 아니던 원문을 처음 편집해 저장해서 파일 전체가 canonical이 됐다."""
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])
    """저장한 값의 형식 검사 진단 (저장을 막지 않은 것)."""


def revision_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    """지금 디스크 바이트 (파일이 없으면 None)."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise DocumentError("io_error", f"'{path}'을(를) 읽을 수 없다: {exc}", path=path) from exc


def _position(data: bytes, offset: int) -> tuple[int, int]:
    """바이트 위치 → (줄, 열). 열은 그 줄의 글자 수 + 1."""
    before = data[:offset]
    line = before.count(b"\n") + 1
    start = before.rfind(b"\n") + 1
    return line, len(before[start:].decode("utf-8", errors="replace")) + 1


def _parse(path: Path, data: bytes) -> tuple[str, Any]:
    if data.startswith(_BOM):
        raise DocumentError(
            "invalid_json",
            "파일이 BOM으로 시작한다 (BOM 없는 UTF-8로 쓴다)",
            path=path,
            line=1,
            column=1,
        )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        line, column = _position(data, exc.start)
        raise DocumentError(
            "invalid_json", f"UTF-8이 아니다: {exc.reason}", path=path, line=line, column=column
        ) from exc
    try:
        return text, loads_strict(text)
    except json.JSONDecodeError as exc:
        raise DocumentError(
            "invalid_json", exc.msg, path=path, line=exc.lineno, column=exc.colno
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise DocumentError("invalid_json", str(exc), path=path) from exc


def open(path: str | os.PathLike[str]) -> Document:
    """그래프 파일을 바이트로 읽는다. 값을 바꾸지 않는다."""
    path = Path(path)
    data = _read(path)
    if data is None:
        raise DocumentError("not_found", f"'{path}'이(가) 없다", path=path)
    text, value = _parse(path, data)
    return Document(path, data, text, value, revision_of(data))


def number_problems(value: Any, file: str | None = None) -> list[Diagnostic]:
    """형식 검사 진단 중 수 규칙 위반만."""
    return [d for d in check_shape(value, "graph", file=file) if d.code in NUMBER_CODES]


def save(
    doc: Document,
    value: Any,
    base_revision: str | None,
    *,
    force: bool = False,
    file: str | None = None,
) -> SaveResult:
    """값 전체를 저장한다 (M2 계획 2.6 저장 1~5단계). `file`은 진단에 쓸 워크스페이스 기준 경로.

    1. 지금 디스크 revision이 `base_revision`과 다르면 `revision_conflict` (`force`면 덮어쓴다)
    2. 수 규칙 위반이면 `validation_failed` (그 밖의 진단은 결과에 담기만 한다)
    3. 쓸 텍스트 = `save_text(문서 원문, value)`. force여도 기준은 사용자가 보고 편집한 원문이다
    4. 그 바이트가 지금 디스크 바이트와 같으면 쓰지 않는다 (`wrote: False`)
    5. 다르면 같은 폴더 임시 파일 → flush·fsync → `os.replace`
    """
    path = doc.path
    current = _read(path)
    current_revision = None if current is None else revision_of(current)
    if not force and current_revision != base_revision:
        raise DocumentError(
            "revision_conflict",
            "파일이 밖에서 바뀌었다 (디스크가 기준 revision과 다르다)",
            path=path,
            revision=current_revision,
        )

    diagnostics = check_shape(value, "graph", file=file)
    blocking = [d for d in diagnostics if d.code in NUMBER_CODES]
    if blocking:
        raise DocumentError(
            "validation_failed",
            "JSON에 쓸 수 없는 수가 있다 (정수 ±(2^53-1) 밖, NaN·Infinity)",
            path=path,
            diagnostics=blocking,
        )

    text = save_text(doc.original_text, value)
    data = text.encode("utf-8")
    if data == current:
        assert current_revision is not None
        _adopt(doc, data, text)
        return SaveResult(current_revision, False, False, diagnostics)

    canonicalized = text != doc.original_text and not doc.canonical
    write_atomic(path, data)
    _adopt(doc, data, text)
    return SaveResult(doc.revision, True, canonicalized, diagnostics)


def _adopt(doc: Document, data: bytes, text: str) -> None:
    doc.original_bytes = data
    doc.original_text = text
    doc.value = loads_strict(text)
    doc.revision = revision_of(data)


def write_atomic(path: Path, data: bytes) -> None:
    """같은 폴더 임시 파일에 쓰고 fsync한 뒤 `os.replace`. 실패하면 임시 파일을 남기지 않는다.

    임시 파일을 만들지 못한 경우(폴더 쓰기 권한·디스크)도 `io_error`다. 대상 파일은 그대로다.
    """
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    except OSError as exc:
        raise DocumentError(
            "io_error", f"'{path.parent}'에 임시 파일을 만들 수 없다: {exc}", path=path
        ) from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise DocumentError("io_error", f"'{path}'에 쓸 수 없다: {exc}", path=path) from exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _core_version() -> str:
    from kookabug_sdk.schema import load_installed

    return load_installed("kookabug_nodes")["plugin"]["version"]


def template(kind: Literal["test", "subgraph"], title: str | None = None) -> dict[str, Any]:
    """새 그래프의 틀. 테스트는 시작 노드 하나, 서브그래프는 시작 → 출구 `done` 하나."""
    nodes: dict[str, Any] = {ENTRY_NODE: {"type": "core.graph.entry", "version": 1}}
    layout: dict[str, Any] = {ENTRY_NODE: {"x": 0, "y": 0}}
    value: dict[str, Any] = {
        "format": GRAPH_FORMAT,
        "kind": kind,
        "layout": {"nodes": layout},
        "nodes": nodes,
        "plugins": {CORE_PLUGIN: _core_version()},
    }
    if kind == "subgraph":
        nodes[ENTRY_NODE]["next"] = {"start": EXIT_NODE}
        nodes[EXIT_NODE] = {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1}
        layout[EXIT_NODE] = {"x": 280, "y": 0}
        value["interface"] = {"exits": {"done": {"kind": "ok"}}}
    if title is not None:
        value["meta"] = {"title": title}
    return value


def create(
    path: str | os.PathLike[str],
    kind: Literal["test", "subgraph"],
    title: str | None = None,
    *,
    change: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Document:
    """새 그래프 파일을 canonical 틀로 만든다. 파일이 이미 있으면 `exists` (덮어쓰지 않는다).

    `change`는 쓰기 전에 틀을 고친다 (에이전트의 만들기 + 연산, M5). 예외를 내면 파일을 만들지
    않는다."""
    path = Path(path)
    value = template(kind, title)
    if change is not None:
        value = change(value)
    data = canonical_dumps(value).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # 배타적 생성: 확인과 쓰기 사이에 생긴 파일도 덮지 않는다
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
    except FileExistsError as exc:
        current = _read(path)
        raise DocumentError(
            "exists",
            f"'{path}'이(가) 이미 있다",
            path=path,
            revision=None if current is None else revision_of(current),
        ) from exc
    except OSError as exc:
        raise DocumentError("io_error", f"'{path}'을(를) 만들 수 없다: {exc}", path=path) from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        with contextlib.suppress(OSError):
            path.unlink()
        raise DocumentError("io_error", f"'{path}'에 쓸 수 없다: {exc}", path=path) from exc
    return open(path)
