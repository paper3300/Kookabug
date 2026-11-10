"""`workspace.info`·`workspace.tree` (M2 계획 2.4). 알림 `workspace.changed`는 `watch.Watcher`.

- `workspace.info`: 루트, `kookabug.json` 요약(프로필 이름·설정 파일 진단), 플러그인, 상태 바용 실행
  환경(Python·플랫폼·캡처·OCR)
- `workspace.tree`: 탐색기 항목. 범위는 `watch.walk`와 같다. 그래프는 `graph_kind`를 붙이고, 읽을 수
  없거나 `kind`가 틀리면 `problem`을 단다. `runs/`·`.kookabug/`는 이름만(`name_only`·`git_ignored`)
- `workspace.read`: 탐색기에 보이는 파일 하나의 앞 1 MiB (에디터 보기 탭, 다듬기 P1-B). 범위는
  `workspace.tree`와 같다. 이미지는 싣지 않고 렌더러가 `kbimg://ws/`로 읽는다 (M2 계획 2.4)
"""

from __future__ import annotations

import asyncio
import codecs
import functools
import os
import platform
import sys
from pathlib import Path
from typing import Any, Final

from kookabug_core import documents
from kookabug_core.documents import DocumentError
from kookabug_core.supervisor import DEFAULT_DEADLINE_MS
from kookabug_core.workspace import Workspace, WorkspaceError, agents_md_section
from kookabug_daemon.documents import GRAPH_SUFFIX, resolve_path
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.screens import in_screens
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.watch import NAME_ONLY_DIRS, ROOT_FILES, TREE_DIRS, walk

__all__ = [
    "METHODS",
    "READ_LIMIT",
    "file_kind",
    "graph_entry",
    "read_file",
    "runtime_info",
    "tree_entries",
]

GRAPH_KINDS: Final = ("subgraph", "test")
READ_LIMIT: Final = 1 << 20
"""`workspace.read`가 싣는 최대 바이트 (`run.file`과 같은 1 MiB)."""
BINARY_PROBE: Final = 8192
_ROOT_FILES_FOLDED: Final = frozenset(name.casefold() for name in ROOT_FILES)


def file_kind(rel: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if "/" not in rel and name in ROOT_FILES:
        return ROOT_FILES[name]
    lowered = name.casefold()
    if lowered.endswith(GRAPH_SUFFIX):
        return "graph"
    if lowered.endswith(".target.json"):
        return "target"
    if lowered.endswith(".screen.json"):
        return "screen"
    return "other"


def graph_entry(root: Path, rel: str) -> dict[str, Any]:
    """그래프 파일의 `graph_kind` 또는 `problem`. 읽기 직전에 경로를 다시 해석한다 (목록을 만든 뒤
    폴더가 링크로 바뀌었으면 루트 밖·`.kookabug/` 파일을 읽지 않는다)."""
    try:
        path = resolve_path(root, rel).path
    except RequestFailed as exc:
        return {"problem": exc.message}
    try:
        doc = documents.open(path)
    except DocumentError as exc:
        where = f" ({exc.line}:{exc.column})" if exc.line is not None else ""
        return {"problem": f"{exc.message}{where}"}
    kind: Any = doc.value.get("kind") if isinstance(doc.value, dict) else None
    if kind not in GRAPH_KINDS:
        return {"problem": f"kind가 {' 또는 '.join(GRAPH_KINDS)}가 아니다: {kind!r}"}
    return {"graph_kind": kind}


def tree_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in walk(root):
        if item.is_dir:
            entries.append({"path": item.rel, "type": "dir"})
            continue
        kind = file_kind(item.rel)
        entry: dict[str, Any] = {"path": item.rel, "type": "file", "kind": kind}
        if kind == "graph":
            entry.update(graph_entry(root, item.rel))
        entries.append(entry)
    for name in NAME_ONLY_DIRS:
        if (root / name).is_dir():
            entries.append({"path": name, "type": "dir", "name_only": True, "git_ignored": True})
    entries.sort(key=lambda e: e["path"])
    return entries


def in_tree_scope(rel: str) -> bool:
    """`workspace.tree`가 보이는 범위의 파일 경로인가 (루트 설정 파일 또는 감시 폴더 아래).
    대소문자는 가리지 않는다 (Windows에서 링크를 해석한 경로는 디스크의 글자 그대로다)."""
    parts = rel.casefold().split("/")
    if len(parts) == 1:
        return parts[0] in _ROOT_FILES_FOLDED
    return parts[0] in TREE_DIRS or parts[0] in READ_ONLY_DIRS


READ_ONLY_DIRS: Final = ("knowledge", "wiki")
"""탐색기 목록에는 없지만 보기 탭으로 읽을 수 있는 폴더 (M8 B7 보고함: 증거 묶음·렌더된
보고서·위키). `.kookabug/`·`runs/`는 여전히 막는다."""


def _through_folder_link(root: Path, given: str) -> bool:
    """요청 경로의 중간 폴더에 링크·정션이 있는가. `watch.walk`는 폴더 링크 안으로 들어가지 않으므로
    (항목으로만 둔다) 그 아래 파일은 탐색기에 없다. 마지막 조각(파일 링크)은 walk처럼 허용한다."""
    folder = root
    for part in given.split("/")[:-1]:
        folder = folder / part
        try:
            if folder.is_symlink() or folder.is_junction():
                return True
        except OSError:
            return True
    return False


def read_file(root: Path, given: str) -> dict[str, Any]:
    """탐색기 파일 하나의 앞부분. 범위는 `workspace.tree`(`watch.walk`)와 같다.

    루트 밖·`.kookabug/`(그 실제 대상 포함)는 `resolve_path`가 거부한다. 그 위에 요청 경로와 링크를
    해석한 경로가 **둘 다** 탐색기 범위여야 하고, 중간 폴더가 링크면 안 된다 — `tests/alias → runs`
    같은 정션으로 `runs/`·비공개 파일을 읽지 못한다 (다듬기 P1-B 검수)."""
    where = resolve_path(root, given)
    if (
        not in_tree_scope(where.given)
        or not in_tree_scope(where.rel)
        or _through_folder_link(root, where.given)
    ):
        raise InvalidParams(f"'{given}'은(는) 탐색기에 보이는 파일이 아니다", path=given)
    if where.path.is_dir():
        raise InvalidParams(f"'{given}'은(는) 폴더다", path=given)
    try:
        with where.path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            data = f.read(READ_LIMIT)
    except FileNotFoundError:
        raise RequestFailed("not_found", f"'{given}'이(가) 없다", path=given) from None
    except OSError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    truncated = size > len(data)
    if b"\0" in data[:BINARY_PROBE]:
        return {"text": "", "bytes": size, "binary": True, "truncated": truncated}
    # 잘렸으면 끝의 덜 읽은 UTF-8 글자는 버린다 (U+FFFD로 남기지 않는다)
    text = codecs.getincrementaldecoder("utf-8")("replace").decode(data, final=not truncated)
    return {"text": text, "bytes": size, "binary": False, "truncated": truncated}


@functools.cache
def _ocr_info() -> str | None:
    """OCR 모델 (설치·해시 확인). 플랫폼 패키지가 없거나 모델이 없으면 None."""
    try:
        from kookabug_platform.ocr.models import find_models
    except ImportError:
        return None
    try:
        models = find_models()
    except Exception:
        return None
    return f"{models.det.name} · {models.rec.name}"


def runtime_info(platform_fake: Path | None) -> dict[str, Any]:
    windows = sys.platform == "win32"
    if platform_fake is not None:
        name, capture = "fake", "fake"
    else:
        name, capture = ("windows", "wgc") if windows else (sys.platform, None)
    return {
        "python": platform.python_version(),
        "platform": name,
        "capture": capture,
        "ocr": _ocr_info(),
    }


def _info_sync(call: Call) -> dict[str, Any]:
    root = call.daemon.root
    try:
        workspace = Workspace.open(root)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    registry = call.daemon.checker.registry
    return {
        "root": str(root),
        "profiles": workspace.profile_names(),
        "deadline_ms": workspace.run_conditions().deadline_ms or DEFAULT_DEADLINE_MS,
        "retention": workspace.retention(),
        "diagnostics": [d.to_dict() for d in workspace.diagnostics],
        # 요약만 (M6에서 스키마 머리에 modules·permissions 등이 늘었다. 자세한 것은 plugins.list)
        "plugins": [
            {k: v for k, v in registry.plugin_info(p).items() if k in ("id", "title", "version")}
            for p in sorted(registry.plugins)
        ],
        "runtime": runtime_info(call.daemon.platform_fake),
        "agents_md": agents_md_section(root),
    }


async def _info(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_info_sync, call)


async def _tree(call: Call) -> dict[str, Any]:
    entries = await asyncio.to_thread(tree_entries, call.daemon.root)
    if call.principal.kind == "agent":
        # 화면 지도는 screens 툴셋 도구(`screens.*`)로만 (M5 3.5 H4)
        entries = [e for e in entries if not in_screens(e["path"])]
    return {"entries": entries}


def _read_arg(call: Call) -> str:
    return resolve_path(call.daemon.root, str(call.params["path"])).rel


async def _read(call: Call) -> dict[str, Any]:
    given = str(call.params["path"])
    if call.principal.kind == "agent":
        where = resolve_path(call.daemon.root, given)
        if in_screens(where.given) or in_screens(where.rel):
            raise RequestFailed(
                "permission_denied",
                "에이전트 연결은 화면 지도(screens/)를 kb_screen_list·kb_screen_get으로만 읽는다",
                path=given,
            )
    return await asyncio.to_thread(read_file, call.daemon.root, given)


METHODS: Final = {
    "workspace.info": MethodSpec(_info),
    "workspace.tree": MethodSpec(_tree),
    "workspace.read": MethodSpec(_read, _read_arg),
}
