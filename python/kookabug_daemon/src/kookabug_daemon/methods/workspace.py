"""`workspace.info`·`workspace.tree` (M2 계획 2.4). 알림 `workspace.changed`는 `watch.Watcher`.

- `workspace.info`: 루트, `kookabug.json` 요약(프로필 이름·설정 파일 진단), 플러그인, 상태 바용 실행
  환경(Python·플랫폼·캡처·OCR)
- `workspace.tree`: 탐색기 항목. 범위는 `watch.walk`와 같다. 그래프는 `graph_kind`를 붙이고, 읽을 수
  없거나 `kind`가 틀리면 `problem`을 단다. `runs/`·`.kookabug/`는 이름만(`name_only`·`git_ignored`)
"""

from __future__ import annotations

import asyncio
import functools
import platform
import sys
from pathlib import Path
from typing import Any, Final

from kookabug_core import documents
from kookabug_core.documents import DocumentError
from kookabug_core.workspace import Workspace, WorkspaceError
from kookabug_daemon.documents import GRAPH_SUFFIX, resolve_path
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.watch import NAME_ONLY_DIRS, ROOT_FILES, walk

__all__ = ["METHODS", "file_kind", "graph_entry", "runtime_info", "tree_entries"]

GRAPH_KINDS: Final = ("subgraph", "test")


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
        "retention": workspace.retention(),
        "diagnostics": [d.to_dict() for d in workspace.diagnostics],
        "plugins": [registry.plugin_info(p) for p in sorted(registry.plugins)],
        "runtime": runtime_info(call.daemon.platform_fake),
    }


async def _info(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_info_sync, call)


async def _tree(call: Call) -> dict[str, Any]:
    return {"entries": await asyncio.to_thread(tree_entries, call.daemon.root)}


METHODS: Final = {
    "workspace.info": MethodSpec(_info),
    "workspace.tree": MethodSpec(_tree),
}
