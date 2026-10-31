"""`graph.open/validate/save/create/close` (M2 계획 2.4·2.6·2.7).

- 에디터는 그래프 파일을 직렬화하지 않는다. 값 전체를 받아 코어 `documents`가 쓸 바이트를 정한다
  (원문 보존·무수정이면 쓰지 않음·수 규칙만 저장을 막음·원자적 쓰기)
- 진단·노드 모양은 열 때·검증할 때·저장한 뒤 모두 같은 방법(`check_graph_value`)으로 계산한다
- 권한 대표 인자는 링크를 해석한 그래프 경로다. `doc_id` 메서드는 문서 표에서 경로를 찾아 지금
  다시 해석한다(판정 경로 = 실제 대상)
- 저장의 기준 원문은 요청한 연결의 것이다 (`DocumentTable.save`)
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.documents import Opened, WsPath, resolve_path
from kookabug_daemon.methods import Call, MethodSpec

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
    return {
        "doc_id": opened.entry.doc_id,
        "revision": opened.revision,
        "value": opened.value,
        "canonical": opened.canonical,
        "diagnostics": checked.diagnostics,
        "shapes": checked.shapes,
    }


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


async def _create(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    where = graph_path(call)
    title = params.get("title")
    opened = await asyncio.to_thread(
        call.daemon.documents.create,
        where,
        call.connection,
        params["kind"],
        None if title is None else str(title),
    )
    return await _opened_result(call, opened)


async def _close(call: Call) -> dict[str, Any]:
    call.daemon.documents.release(str(call.params["doc_id"]), call.connection)
    return {}


METHODS: Final = {
    "graph.open": MethodSpec(_open, _path_arg),
    "graph.validate": MethodSpec(_validate, _doc_arg),
    "graph.save": MethodSpec(_save, _doc_arg),
    "graph.create": MethodSpec(_create, _path_arg),
    "graph.close": MethodSpec(_close),
}
