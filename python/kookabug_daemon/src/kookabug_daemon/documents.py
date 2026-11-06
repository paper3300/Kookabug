"""daemon의 문서 표·경로 검사·검증 풀 (M2 계획 2.4·2.6·2.7, T4).

- **경로**: 요청의 경로는 워크스페이스 루트 기준('/' 구분)이다. 루트 밖(절대 경로·`..`·드라이브)은
  `path_outside_workspace`, `.kookabug/` 안은 `private_path`다. 심볼릭 링크·정션은 해석한 뒤 다시
  본다(링크가 루트 밖이나 `.kookabug/` 안을 가리키면 같은 거부. `.kookabug` 자체가 링크면 그 실제
  대상 폴더도 `.kookabug/`로 본다). 그래프 메서드는 해석 전·후 이름이
  모두 `*.graph.json`이어야 한다 — 그래야 `graph.save`로 `kookabug.json`(팀 권한 정책) 같은 파일을
  고칠 수 없다. 파일 연산(열기·만들기·저장)은 경로 잠금을 잡은 뒤 연산 직전에 경로를 다시
  해석한다. `doc_id`로 하는 검증·저장은 **그 연결이 연 경로**로 다시 해석한다(다른 연결의 별칭
  링크가 사라져도 영향 없음). 폴더가 정션으로 바뀌어 루트 밖·`.kookabug/`·다른 파일을 가리키면
  읽기·쓰기 전에 거부한다
- **문서 표**: 경로 하나에 문서 하나다(연결과 무관). 연결마다 참조 수를 세고, 모든 참조가 풀리면
  (`graph.close`·연결 끊김) 문서를 버린다. 끊긴 연결의 늦게 끝난 열기는 참조를 남기지 않는다.
  `doc_id`는 daemon마다 새로 뽑으므로 다른 daemon의 번호는 `doc_not_open`이다
- **연결별 기준 원문**: 문서는 공유하지만 저장의 기준 원문(사용자가 보고 편집한 원문, 계획 2.6
  저장 3단계)은 연결마다 따로 든다. 다른 연결의 열기·저장은 그 기준을 바꾸지 않는다. 그래서 force
  저장은 그 연결이 본 원문으로 되돌아가고, `graph.changed`도 연결마다 "그 연결이 아는 revision"과
  디스크를 비교해 보낸다(다른 연결의 daemon 저장도 알린다. 자기 저장은 알리지 않는다)
- **직렬화**: 같은 경로의 읽기·저장은 **경로 잠금** 하나로 줄 세운다. 경로 잠금은 문서 항목과 따로
  두고 지우지 않는다 — 연결이 끊겨 항목이 사라져도 진행 중인 저장은 같은 잠금을 쥐고 있으므로 새
  항목의 저장과 갈라지지 않는다. 파일 감시도 그 잠금을 잡을 수 있을 때만 디스크를 읽는다
- **실행 기록**: `runs/` 아래 그래프(실행 스냅샷)는 열 수 있지만 저장·만들기는 `read_only`다 (M3)
- **검증 풀**: `check_graph_value`·노드 모양 계산은 전용 스레드 풀에서 돈다. 이벤트 루프와 다른
  막히는 호출(`asyncio.to_thread`)을 막지 않는다
"""

from __future__ import annotations

import asyncio
import copy
import os
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

from kookabug_core import documents
from kookabug_core.diagnostics import Diagnostic
from kookabug_core.documents import Document, DocumentError
from kookabug_core.loader import Program
from kookabug_core.registry import Registry, default_registry
from kookabug_core.shapes import value_shapes
from kookabug_core.validate import check_graph_value
from kookabug_core.workspace import Workspace, WorkspaceError
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = [
    "GRAPH_SUFFIX",
    "PRIVATE_NAME",
    "RUNS_NAME",
    "Checked",
    "DocumentTable",
    "GraphChecker",
    "OpenDoc",
    "Opened",
    "WsPath",
    "document_failed",
    "in_private_target",
    "is_run_record",
    "read_graph",
    "read_only_failed",
    "recheck_path",
    "resolve_path",
]

PRIVATE_NAME: Final = ".kookabug"
RUNS_NAME: Final = "runs"
"""실행 폴더가 모이는 곳 (워크스페이스 루트 기준)."""
GRAPH_SUFFIX: Final = ".graph.json"
VALIDATE_WORKERS: Final = 2


@dataclass(frozen=True, slots=True)
class WsPath:
    """검사를 지난 워크스페이스 경로."""

    given: str
    """요청에 온 그대로 (오류의 `path`)."""
    rel: str
    """링크를 해석한 루트 기준 경로 ('/' 구분). 권한 판정·진단·문서 표가 쓴다."""
    path: Path
    """해석한 절대 경로."""

    @property
    def key(self) -> str:
        """문서 표 열쇠 (Windows는 대소문자 무시)."""
        return os.path.normcase(str(self.path))


def _outside(given: str, why: str) -> RequestFailed:
    return RequestFailed("path_outside_workspace", f"'{given}'은(는) {why}", path=given)


def _private(given: str) -> RequestFailed:
    return RequestFailed(
        "private_path", f"'{given}'은(는) {PRIVATE_NAME}/ 안이라 열 수 없다", path=given
    )


def _is_private(parts: tuple[str, ...] | list[str]) -> bool:
    return bool(parts) and parts[0].casefold() == PRIVATE_NAME


def in_private_target(root: Path, resolved: Path) -> bool:
    """해석한 경로가 `.kookabug/`의 **실제 대상** 안인가. `.kookabug`가 루트 안 다른 폴더를 가리키는
    링크·정션이면 그 폴더도 비공개다 (`tests/alias → 그 폴더`로 돌아 읽지 못하게, 다듬기 P1-B)."""
    try:
        private = os.path.realpath(root / PRIVATE_NAME)
        relative = os.path.relpath(resolved, private)
    except OSError, ValueError:  # 다른 드라이브: 그 안일 수 없다
        return False
    return not os.path.isabs(relative) and Path(relative).parts[:1] != ("..",)


def resolve_path(root: Path, given: str, *, graph: bool = False) -> WsPath:
    """요청 경로 → 검사한 경로. 거부는 `RequestFailed`, 그래프가 아니면 `InvalidParams`."""
    if not given or "\\" in given or given.startswith("/") or ":" in given or "\0" in given:
        raise _outside(given, "워크스페이스 루트 기준 경로('/' 구분)가 아니다")
    parts = given.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise _outside(given, "워크스페이스 루트 기준 경로가 아니다 ('', '.', '..' 조각)")
    if _is_private(parts):
        raise _private(given)
    lexical = root.joinpath(*parts)
    try:
        resolved = Path(os.path.realpath(lexical))
        relative = os.path.relpath(resolved, root)
    except (OSError, ValueError) as exc:  # 다른 드라이브·해석 실패
        raise _outside(given, f"루트 밖을 가리킨다 ({exc})") from exc
    rel_parts = PurePosixPath(Path(relative).as_posix()).parts
    if os.path.isabs(relative) or not rel_parts or rel_parts[0] == "..":
        raise _outside(given, "링크를 따라가면 워크스페이스 루트 밖이다")
    if _is_private(rel_parts) or in_private_target(root, resolved):
        raise _private(given)
    if graph and not (
        given.casefold().endswith(GRAPH_SUFFIX) and resolved.name.casefold().endswith(GRAPH_SUFFIX)
    ):
        raise InvalidParams(f"'{given}'은(는) 그래프 파일(*{GRAPH_SUFFIX})이 아니다", path=given)
    return WsPath(given, "/".join(rel_parts), resolved)


def is_run_record(rel: str) -> bool:
    """실행 폴더(`runs/` 아래)의 파일이다: 스냅샷 그래프는 읽기만 한다 (M3 계획 2.10)."""
    return rel.split("/", 1)[0].casefold() == RUNS_NAME


def read_only_failed(rel: str) -> RequestFailed:
    return RequestFailed("read_only", f"'{rel}'은(는) 실행 기록(runs/)이라 고칠 수 없다", path=rel)


def recheck_path(root: Path, where: WsPath) -> WsPath:
    """검사했던 경로를 지금 다시 해석한다. 루트 밖·`.kookabug/`면 그 거부, 그 사이 링크가 바뀌어
    다른 파일을 가리키면 `not_found` (그 문서는 더는 그 경로에 없다).

    파일 연산은 경로 잠금을 잡은 뒤 **연산 직전에** 부른다 (검사 → 대기 → 사용 틈을 없앤다)."""
    current = resolve_path(root, where.given, graph=True)
    if current.key != where.key:
        raise RequestFailed(
            "not_found",
            f"'{where.given}'이(가) 검사한 뒤에 다른 파일({current.rel})을 가리킨다. 다시 연다",
            path=where.given,
        )
    return current


def document_failed(exc: DocumentError, given: str) -> RequestFailed:
    """코어 문서 오류 → daemon 오류 (`data`의 종류별 필드를 채운다)."""
    match exc.code:
        case "not_found":
            return RequestFailed("not_found", exc.message, path=given)
        case "invalid_json":
            return RequestFailed(
                "invalid_json",
                exc.message,
                message=exc.message,
                line=exc.line,
                column=exc.column,
            )
        case "revision_conflict" | "exists":
            return RequestFailed(exc.code, exc.message, revision=exc.revision)
        case "validation_failed":
            return RequestFailed(
                "validation_failed",
                exc.message,
                diagnostics=[d.to_dict() for d in exc.diagnostics],
            )
        case "io_error":
            return RequestFailed("io_error", exc.message, message=exc.message)


def _doc_not_open(doc_id: str) -> RequestFailed:
    return RequestFailed(
        "doc_not_open", f"열린 문서 {doc_id!r}이(가) 없다 (graph.open으로 다시 연다)", revision=None
    )


# ---------------------------------------------------------------- 문서 표


@dataclass(eq=False)
class OpenDoc:
    """열린 문서 하나.

    `latest`·`bases`·`disk`·`seen`·`notified`는 경로 잠금(`lock`)을 쥐고 바꾼다. `refs`·`bases`의
    키 추가·삭제는 표 잠금도 함께 쥔다."""

    doc_id: str
    target: WsPath
    """실제 파일 (링크를 해석한 경로. `given`도 루트 기준 경로라 링크 없이 그 파일을 가리킨다)."""
    lock: threading.Lock
    """경로 잠금 (같은 경로의 항목이 바뀌어도 같은 객체)."""
    latest: Document
    """daemon이 마지막으로 읽거나 쓴 문서. 기준이 없는 연결의 저장이 이 사본을 기준으로 쓴다."""
    bases: dict[int, Document] = field(default_factory=dict[int, Document])
    """연결 번호 → 그 연결의 기준 원문(그 연결이 열거나 저장한 바이트)."""
    paths: dict[int, WsPath] = field(default_factory=dict[int, WsPath])
    """연결 번호 → 그 연결이 연 경로 (별칭 링크일 수 있다). 그 연결의 경로 재검사에 쓴다."""
    refs: dict[int, int] = field(default_factory=dict[int, int])
    """연결 번호 → 참조 수."""
    notified: dict[int, str] = field(default_factory=dict[int, str])
    """연결 번호 → `graph.changed`로 마지막에 알린 디스크 revision 표시."""
    disk: str | None = None
    """감시가 마지막에 읽은 디스크 revision (없는 파일이면 None, `seen`이 None이면 모름)."""
    seen: tuple[int, int] | None = None
    """감시가 마지막에 본 (mtime_ns, 크기). 없는 파일이면 (-1, -1). None이면 다시 읽는다."""

    @property
    def rel(self) -> str:
        return self.target.rel

    def known_revision(self, connection: int) -> str:
        """그 연결이 아는 revision (기준이 없으면 daemon이 마지막에 본 것)."""
        base = self.bases.get(connection)
        return (base or self.latest).revision


@dataclass(frozen=True, slots=True)
class Opened:
    """열기 직후의 문서 상태 (잠금 밖에서 응답을 만들 때 쓴다)."""

    entry: OpenDoc
    revision: str
    value: Any
    canonical: bool


type Reader = Callable[[Path], Document]


def read_graph(path: Path) -> Document:
    """그래프 파일을 연다. 최상위가 객체가 아니면(`[]` 등) 그래프로 다룰 수 없어 `invalid_json`."""
    doc = documents.open(path)
    if not isinstance(doc.value, dict):
        raise DocumentError("invalid_json", "그래프 파일의 최상위가 JSON 객체가 아니다", path=path)
    return doc


class DocumentTable:
    """경로당 문서 하나. 메서드는 어느 스레드에서 불러도 된다 (막히는 파일 읽기·쓰기를 한다)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._by_id: dict[str, OpenDoc] = {}
        self._by_key: dict[str, OpenDoc] = {}
        self._path_locks: dict[str, threading.Lock] = {}
        self._closed: set[int] = set()
        """끝난 연결 번호 (번호는 다시 쓰지 않는다)."""

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_id)

    def entries(self) -> list[OpenDoc]:
        with self._lock:
            return list(self._by_id.values())

    def get(self, doc_id: str) -> OpenDoc:
        with self._lock:
            entry = self._by_id.get(doc_id)
        if entry is None:
            raise _doc_not_open(doc_id)
        return entry

    def path_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._path_locks.setdefault(key, threading.Lock())

    def open(self, where: WsPath, connection: int, reader: Reader = read_graph) -> Opened:
        """디스크에서 읽어 연다. 이미 열린 경로면 같은 `doc_id`로 다시 읽어 **그 연결의** 기준을
        바꾼다 (clean 탭 다시 열기). 다른 연결의 기준은 그대로다.

        읽기에 실패하면 표를 바꾸지 않는다. 연결이 이미 끝났으면 참조를 남기지 않는다.
        경로 잠금을 기다리는 동안 링크가 바뀔 수 있어 잠금을 잡은 뒤 읽기 직전에 다시 검사한다."""
        with self.path_lock(where.key):
            where = recheck_path(self.root, where)
            try:
                doc = reader(where.path)
            except DocumentError as exc:
                raise document_failed(exc, where.given) from exc
            return self._register(where, connection, doc)

    def create(
        self,
        where: WsPath,
        connection: int,
        kind: Any,
        title: str | None,
        change: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> Opened:
        """새 그래프 파일을 만들고 연다 (있으면 `exists`). 잠금 안에서 만들기 직전에 경로를 다시
        검사한다. `change`는 쓰기 전에 틀을 고친다(예외면 만들지 않음)."""
        with self.path_lock(where.key):
            where = recheck_path(self.root, where)
            if is_run_record(where.rel):
                raise read_only_failed(where.rel)
            try:
                doc = documents.create(where.path, kind, title, change=change)
                if not isinstance(doc.value, dict):  # 틀은 항상 객체다 (read_graph와 같은 규칙)
                    raise DocumentError(
                        "invalid_json", "새 그래프가 객체가 아니다", path=where.path
                    )
            except DocumentError as exc:
                raise document_failed(exc, where.given) from exc
            return self._register(where, connection, doc)

    def _register(self, where: WsPath, connection: int, doc: Document) -> Opened:
        """읽은 문서를 표에 넣는다 (경로 잠금 안). 그 연결의 기준·경로만 바꾼다."""
        with self._lock:
            entry = self._by_key.get(where.key)
            if entry is None:
                target = WsPath(where.rel, where.rel, where.path)
                entry = OpenDoc(self._new_id(), target, self._path_locks[where.key], doc)
                if connection in self._closed:
                    # 끊긴 연결의 늦은 열기: 응답을 받을 곳이 없다. 표에 넣지 않는다
                    return Opened(entry, doc.revision, doc.value, doc.canonical)
                self._by_id[entry.doc_id] = entry
                self._by_key[where.key] = entry
            entry.latest = doc
            entry.seen = None
            if connection not in self._closed:
                entry.bases[connection] = doc
                entry.paths[connection] = where
                entry.refs[connection] = entry.refs.get(connection, 0) + 1
                entry.notified.pop(connection, None)
        return Opened(entry, doc.revision, doc.value, doc.canonical)

    def path_for(self, entry: OpenDoc, connection: int) -> WsPath:
        """그 연결의 경로를 지금 다시 검사한다. 연 연결은 **자기가 연 경로**로만 본다(다른 연결의
        별칭이 사라져도 영향 없음). 열지 않은 연결은 지금 문서를 연 경로들과 실제 파일 경로 중
        하나라도 그 파일을 가리키면 된다. 후보 하나의 실패(루트 밖·`.kookabug/`·다른 파일·그래프가
        아닌 대상)는 그 후보만 버리고 다음 후보를 본다. 모두 실패하면 마지막 후보의 오류를 낸다 —
        열지 않은 연결이면 실제 파일 경로(`target`)의 오류다."""
        with self._lock:
            mine = entry.paths.get(connection)
            others = list(entry.paths.values())
        candidates = [mine] if mine is not None else [*others, entry.target]
        failure: RequestFailed | InvalidParams | None = None
        for where in candidates:
            try:
                return recheck_path(self.root, where)
            except (RequestFailed, InvalidParams) as exc:
                failure = exc
        assert failure is not None
        raise failure

    def save(
        self, entry: OpenDoc, connection: int, value: Any, base_revision: str, *, force: bool
    ) -> tuple[documents.SaveResult, Any]:
        """같은 경로의 저장은 줄 세운다. 기준 원문은 그 연결의 것이다. (결과, 저장한 뒤 값).

        경로 잠금을 잡은 뒤 쓰기 직전에 그 연결의 경로를 다시 해석한다(연 뒤에 바뀐 링크로 다른
        파일을 쓰지 않는다)."""
        with entry.lock:
            where = self.path_for(entry, connection)
            if is_run_record(where.rel) or is_run_record(entry.rel):
                raise read_only_failed(where.rel)
            with self._lock:
                base = entry.bases.get(connection)
            doc = base if base is not None else copy.copy(entry.latest)
            try:
                result = documents.save(doc, value, base_revision, force=force, file=entry.rel)
            except DocumentError as exc:
                raise document_failed(exc, where.given) from exc
            with self._lock:
                entry.latest = doc
                entry.seen = None
                if connection in entry.refs:
                    entry.bases[connection] = doc
                    entry.notified.pop(connection, None)
            return result, doc.value

    def patch(
        self, where: WsPath, base_revision: str, change: Callable[[Any], Any]
    ) -> tuple[documents.SaveResult, Any]:
        """경로로 고친다 (`graph.patch`, M5 계획 3.4). 경로 잠금 안에서 디스크를 읽고 revision을
        기준과 비교한 뒤 `change(값)`이 돌려준 값을 저장한다(force 없음). `change`가 예외를 내면
        아무것도 쓰지 않는다. 그 경로를 연 연결이 있으면 감시가 다음 주기에 `graph.changed`를
        보낸다(이 연결의 기준 원문은 바꾸지 않는다)."""
        with self.path_lock(where.key):
            where = recheck_path(self.root, where)
            if is_run_record(where.rel):
                raise read_only_failed(where.rel)
            try:
                doc = read_graph(where.path)
            except DocumentError as exc:
                raise document_failed(exc, where.given) from exc
            if doc.revision != base_revision:
                raise RequestFailed(
                    "revision_conflict",
                    "파일이 밖에서 바뀌었다 (디스크가 기준 revision과 다르다)",
                    revision=doc.revision,
                )
            value = change(copy.deepcopy(doc.value))
            try:
                result = documents.save(doc, value, base_revision, file=where.rel)
            except DocumentError as exc:
                raise document_failed(exc, where.given) from exc
            with self._lock:
                entry = self._by_key.get(where.key)
                if entry is not None:
                    entry.latest = doc
                    entry.seen = None
            return result, doc.value

    def release(self, doc_id: str, connection: int) -> None:
        """`graph.close`: 그 연결의 참조 하나를 푼다. 그 연결이 열지 않은 문서면 `doc_not_open`."""
        with self._lock:
            entry = self._by_id.get(doc_id)
            if entry is None or connection not in entry.refs:
                raise _doc_not_open(doc_id)
            entry.refs[connection] -= 1
            if entry.refs[connection] <= 0:
                self._forget(entry, connection)
            self._drop_if_unused(entry)

    def release_connection(self, connection: int) -> None:
        """연결이 끝났다: 그 연결의 참조·기준을 모두 푼다. 그 뒤에 끝나는 열기는 참조를 남기지
        않는다."""
        with self._lock:
            self._closed.add(connection)
            for entry in list(self._by_id.values()):
                if connection in entry.refs:
                    self._forget(entry, connection)
                    self._drop_if_unused(entry)

    def holders(self, entry: OpenDoc) -> list[int]:
        with self._lock:
            return sorted(entry.refs)

    def _forget(self, entry: OpenDoc, connection: int) -> None:
        entry.refs.pop(connection, None)
        entry.bases.pop(connection, None)
        entry.paths.pop(connection, None)
        entry.notified.pop(connection, None)

    def _drop_if_unused(self, entry: OpenDoc) -> None:
        if not entry.refs:
            self._by_id.pop(entry.doc_id, None)
            if self._by_key.get(entry.target.key) is entry:
                del self._by_key[entry.target.key]

    def _new_id(self) -> str:
        while True:
            doc_id = f"d_{secrets.token_hex(8)}"
            if doc_id not in self._by_id:
                return doc_id


# ---------------------------------------------------------------- 검증


@dataclass(frozen=True, slots=True)
class Checked:
    diagnostics: list[dict[str, Any]]
    shapes: dict[str, Any]


class GraphChecker:
    """편집 버퍼 검증과 노드 모양 (M2 계획 2.7). 전용 스레드 풀에서 돈다.

    워크스페이스 설정(`kookabug.json`·`local.json`)은 검증할 때마다 다시 읽는다. 비밀값은 실행과
    같이 환경 변수에서 찾는다 (없으면 오류. 편집 중이라고 경고로 낮추지 않는다)."""

    def __init__(
        self,
        root: Path,
        registry: Callable[[], Registry] | None = None,
        plugin_check: Callable[[Program, Registry], list[Diagnostic]] | None = None,
    ) -> None:
        """`plugin_check(프로그램, 레지스트리)`: 설치 플러그인 진단 (M6 `plugin_env_*` — 읽기만)."""
        self.root = root
        self._make_registry = registry or default_registry
        self._plugin_check = plugin_check
        self._registry: Registry | None = None
        self._registry_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(VALIDATE_WORKERS, thread_name_prefix="kb-validate")

    @property
    def registry(self) -> Registry:
        with self._registry_lock:
            if self._registry is None:
                self._registry = self._make_registry()
            return self._registry

    def invalidate(self) -> None:
        """레지스트리를 다음에 다시 만든다 (플러그인 잠금이 바뀌었다, M6 `plugins.changed`)."""
        with self._registry_lock:
            self._registry = None

    def check_sync(
        self, rel: str, value: Any, guard: Callable[[], object] | None = None
    ) -> Checked:
        if guard is not None:
            guard()  # 풀에서 차례를 기다린 뒤, 검증 직전의 경로 재검사
        try:
            workspace = Workspace.open(self.root)
        except WorkspaceError as exc:
            raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
        registry = self.registry
        program, diagnostics = check_graph_value(workspace, rel, value, registry=registry)
        if self._plugin_check is not None:
            diagnostics = [*diagnostics, *self._plugin_check(program, registry)]
        shapes = value_shapes(program, rel, value, registry)
        return Checked(
            [d.to_dict() for d in diagnostics],
            {node_id: shape.to_json() for node_id, shape in shapes.items()},
        )

    async def check(
        self, rel: str, value: Any, *, guard: Callable[[], object] | None = None
    ) -> Checked:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self.check_sync, rel, value, guard)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
