"""`graph.open/validate/save/create/close` (M2 계획 2.4·2.6·2.7).

- 에디터는 그래프 파일을 직렬화하지 않는다. 값 전체를 받아 코어 `documents`가 쓸 바이트를 정한다
  (원문 보존·무수정이면 쓰지 않음·수 규칙만 저장을 막음·원자적 쓰기)
- 진단·노드 모양은 열 때·검증할 때·저장한 뒤 모두 같은 방법(`check_graph_value`)으로 계산한다
- 권한 대표 인자는 링크를 해석한 그래프 경로다. `doc_id` 메서드는 문서 표에서 경로를 찾아 지금
  다시 해석한다(판정 경로 = 실제 대상)
- 저장의 기준 원문은 요청한 연결의 것이다 (`DocumentTable.save`)
- 실행 폴더(`runs/` 아래)의 스냅샷 그래프는 읽기 전용으로 열고(`read_only: true`), 저장·만들기는
  `read_only`로 거부한다 (M3 계획 2.10)
- M5: `graph.patch`는 경로·기준 revision·연산으로 고친다(문서 표를 열지 않음, 경로 잠금 안에서
  디스크 비교). agent 연결의 `graph.save force`는 판정 전에 `force_not_allowed`
- M5: MCP 도구마다 그 도구로 판정하는 진입점을 둔다(다른 도구로 판정되는 메서드를 돌아 쓰면 그
  도구의 deny를 우회한다): `graph.list`(kb_graph_list), `graph.check`(kb_graph_validate, 경로·값),
  `graph.create`의 `ops`(kb_graph_create 하나로 판정, 연산이 틀리면 만들지 않음)
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import DocumentError
from kookabug_core.registry import Registry
from kookabug_core.schema import check_shape
from kookabug_daemon.documents import (
    Opened,
    WsPath,
    document_failed,
    is_run_record,
    read_graph,
    resolve_path,
)
from kookabug_daemon.graph_patch import PatchInvalid, PatchResult, apply_ops
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.workspace import file_kind, graph_entry
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.watch import walk

__all__ = ["METHODS", "graph_path", "request_int"]


def request_int(value: Any) -> int:
    """params의 `integer` 칸. Python 클라이언트의 `2.0`도 형식 검사를 지나므로 정수로 바꾼다."""
    return int(value)


def graph_path(call: Call, key: str = "path") -> WsPath:
    """그래프 경로 검사. 거부는 `RequestFailed`, `*.graph.json`이 아니면 `InvalidParams`."""
    return resolve_path(call.daemon.root, str(call.params[key]), graph=True)


def _path_arg(call: Call) -> str:
    return graph_path(call).rel


def _doc_arg(call: Call) -> str:
    """`doc_id` 메서드의 대표 인자 = 그 연결이 연 경로를 지금 다시 해석한 것. 링크가 바뀌어 루트
    밖·`.kookabug/`·다른 파일을 가리키면 판정 전에 거부한다. 검증·저장은 실제 작업 직전에 한 번
    더 본다 (판정과 작업 사이의 대기 동안 바뀔 수 있다)."""
    table = call.daemon.documents
    entry = table.get(str(call.params["doc_id"]))
    return table.path_for(entry, call.connection).rel


async def _opened_result(call: Call, opened: Opened) -> dict[str, Any]:
    checked = await call.daemon.checker.check(opened.entry.rel, opened.value)
    result: dict[str, Any] = {
        "doc_id": opened.entry.doc_id,
        "revision": opened.revision,
        "value": opened.value,
        "canonical": opened.canonical,
        "diagnostics": checked.diagnostics,
        "shapes": checked.shapes,
    }
    if is_run_record(opened.entry.rel):
        # 실행 폴더의 스냅샷 그래프: 읽기만 한다 (graph.save는 read_only, M3 2.10)
        result["read_only"] = True
    return result


async def _open(call: Call) -> dict[str, Any]:
    where = graph_path(call)
    opened = await asyncio.to_thread(call.daemon.documents.open, where, call.connection)
    return await _opened_result(call, opened)


async def _validate(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    table = call.daemon.documents
    entry = table.get(str(params["doc_id"]))
    checked = await call.daemon.checker.check(
        entry.rel, params["value"], guard=lambda: table.path_for(entry, call.connection)
    )
    return {
        "seq": request_int(params["seq"]),
        "diagnostics": checked.diagnostics,
        "shapes": checked.shapes,
    }


async def _save(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    table = call.daemon.documents
    entry = table.get(str(params["doc_id"]))
    result, value = await asyncio.to_thread(
        table.save,
        entry,
        call.connection,
        params["value"],
        str(params["base_revision"]),
        force=bool(params.get("force", False)),
    )
    checked = await call.daemon.checker.check(entry.rel, value)
    return {
        "revision": result.revision,
        "wrote": result.wrote,
        "canonicalized": result.canonicalized,
        "diagnostics": checked.diagnostics,
    }


def _save_arg(call: Call) -> str:
    """agent 연결의 force 저장은 판정 전에 거부한다 (M5 계획 C7: 덮어쓰기는 사람만)."""
    if call.principal.kind == "agent" and bool(call.params.get("force", False)):
        raise RequestFailed(
            "force_not_allowed",
            "에이전트 연결은 force로 덮어쓸 수 없다. 다시 읽어 그 revision으로 고친다",
        )
    return _doc_arg(call)


class _Applier:
    """연산 묶음을 값에 적용하는 바꾸기 함수 (경로 잠금 안에서 불린다). 결과는 `applied`."""

    def __init__(self, rel: str, ops: list[Mapping[str, Any]], registry: Registry) -> None:
        self.rel = rel
        self.ops = ops
        self.registry = registry
        self.applied: PatchResult | None = None

    def __call__(self, value: Any) -> Any:
        try:
            result = apply_ops(value, self.ops, self.registry)
        except PatchInvalid as exc:
            raise RequestFailed("patch_invalid", exc.message, index=exc.index) from exc
        # 형식 오류(스키마)는 쓰지 않는다. 의미 진단(모르는 노드·연결 규칙)은 결과로만 (3.4)
        shape = check_shape(result.value, "graph", file=self.rel)
        problems = [d for d in shape if d.severity == "error"]
        if problems:
            raise RequestFailed(
                "validation_failed",
                "고친 값이 그래프 형식에 맞지 않는다",
                diagnostics=[d.to_dict() for d in problems],
            )
        self.applied = result
        return result.value


async def _applier(call: Call, rel: str, ops: list[Mapping[str, Any]]) -> _Applier:
    registry = await asyncio.to_thread(lambda: call.daemon.checker.registry)
    return _Applier(rel, ops, registry)


async def _patch(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    where = graph_path(call)
    change = await _applier(call, where.rel, list(params["ops"]))
    saved, value = await asyncio.to_thread(
        call.daemon.documents.patch, where, str(params["base_revision"]), change
    )
    checked = await call.daemon.checker.check(where.rel, value)
    assert change.applied is not None
    return {
        "revision": saved.revision,
        "wrote": saved.wrote,
        "created": change.applied.created,
        "removed_refs": change.applied.removed_refs,
        "diagnostics": checked.diagnostics,
    }


async def _create(call: Call) -> dict[str, Any]:
    """새 그래프. `ops`가 있으면 쓰기 전에 틀에 적용한다 — 판정은 `kb_graph_create` 하나, 연산이
    틀리면 파일을 만들지 않는다 (M5 B1 검수)."""
    params: Mapping[str, Any] = call.params
    where = graph_path(call)
    title = params.get("title")
    ops = list(params.get("ops") or [])
    change = await _applier(call, where.rel, ops) if ops else None
    opened = await asyncio.to_thread(
        call.daemon.documents.create,
        where,
        call.connection,
        params["kind"],
        None if title is None else str(title),
        change,
    )
    result = await _opened_result(call, opened)
    if change is not None and change.applied is not None:
        result["created"] = change.applied.created
    return result


def _list_arg(call: Call) -> str:
    return str(call.params.get("under", "")).strip("/")


def _graph_summary(root: Path, rel: str) -> dict[str, Any]:
    entry = graph_entry(root, rel)
    if "problem" in entry:
        return {"path": rel, "problem": entry["problem"]}
    out: dict[str, Any] = {"path": rel, "kind": entry["graph_kind"]}
    try:
        meta = read_graph(resolve_path(root, rel, graph=True).path).value.get("meta")
    except DocumentError, RequestFailed, InvalidParams:
        return out
    title = meta.get("title") if isinstance(meta, dict) else None
    if isinstance(title, str):
        out["title"] = title
    return out


def _list_sync(root: Path, under: str) -> list[dict[str, Any]]:
    prefix = f"{under.casefold()}/" if under else ""
    found: list[dict[str, Any]] = []
    for item in walk(root):
        if item.is_dir or file_kind(item.rel) != "graph":
            continue
        if prefix and not item.rel.casefold().startswith(prefix):
            continue
        found.append(_graph_summary(root, item.rel))
    found.sort(key=lambda g: g["path"])
    return found


async def _list(call: Call) -> dict[str, Any]:
    """그래프 목록 (`kb_graph_list`로 판정, M5 B1 검수 H1). 범위는 `workspace.tree`와 같다."""
    graphs = await asyncio.to_thread(_list_sync, call.daemon.root, _list_arg(call))
    return {"graphs": graphs}


async def _check(call: Call) -> dict[str, Any]:
    """경로로 검증 (`kb_graph_validate`로 판정, M5 B1 검수 H2). value가 없으면 디스크 값."""
    where = graph_path(call)
    if "value" in call.params:
        value = call.params["value"]
    else:
        try:
            value = (await asyncio.to_thread(read_graph, where.path)).value
        except DocumentError as exc:
            raise document_failed(exc, where.given) from exc
    checked = await call.daemon.checker.check(where.rel, value)
    return {"diagnostics": checked.diagnostics}


async def _close(call: Call) -> dict[str, Any]:
    call.daemon.documents.release(str(call.params["doc_id"]), call.connection)
    return {}


METHODS: Final = {
    "graph.open": MethodSpec(_open, _path_arg),
    "graph.validate": MethodSpec(_validate, _doc_arg),
    "graph.save": MethodSpec(_save, _save_arg),
    "graph.patch": MethodSpec(_patch, _path_arg),
    "graph.create": MethodSpec(_create, _path_arg),
    "graph.close": MethodSpec(_close),
    "graph.list": MethodSpec(_list, _list_arg),
    "graph.check": MethodSpec(_check, _path_arg),
}
