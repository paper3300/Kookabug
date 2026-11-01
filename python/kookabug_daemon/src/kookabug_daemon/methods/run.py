"""`run.start/cancel/status/list/subscribe/unsubscribe` (M2 계획 2.8).

실행 관리는 `runs.RunManager`가 한다.

- `run.start`는 판정을 전송이 아니라 시작 잠금 안의 ② 단계에서 한다 (`MethodSpec.self_authorized`).
  대표 인자는 링크를 해석한 그래프 경로다
- `run.cancel`의 대표 인자는 그 실행의 그래프 경로, `run.status`·`run.subscribe`는 실행 ID다
  (M2 계획 2.5 표)
- dirty 버퍼는 UI 책임이다(먼저 저장한 뒤 실행). daemon은 디스크 파일로 실행한다
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Final

from kookabug_daemon.documents import resolve_path
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.methods.graph import request_int
from kookabug_daemon.runs import StartRequest

__all__ = ["METHODS"]


def _path_arg(call: Call) -> str:
    return resolve_path(call.daemon.root, str(call.params["path"]), graph=True).rel


def _run_id(call: Call) -> str:
    return str(call.params["run_id"])


def _cancel_arg(call: Call) -> str:
    return call.daemon.run_manager.graph_of(_run_id(call))


async def _start(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    profile = params.get("profile")
    key = params.get("idempotency_key")
    deadline = params.get("deadline_ms")
    request = StartRequest(
        principal=call.principal,
        path=str(params["path"]),
        profile=None if profile is None else str(profile),
        settings=dict(params.get("settings") or {}),
        deadline_ms=None if deadline is None else request_int(deadline),
        idempotency_key=None if key is None else str(key),
        # 사람이 UI에서 시작한 실행만 디버그 대상 (주체 kind가 아니라 연결 종류로, M3 2.1)
        ui=call.client_kind == "ui",
    )
    return await asyncio.to_thread(call.daemon.run_manager.start, request)


async def _cancel(call: Call) -> dict[str, Any]:
    await asyncio.to_thread(call.daemon.run_manager.cancel, _run_id(call))
    return {}


async def _status(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(call.daemon.run_manager.status, _run_id(call))


async def _list(call: Call) -> dict[str, Any]:
    limit = call.params.get("limit")
    runs = await asyncio.to_thread(
        call.daemon.run_manager.recent, None if limit is None else request_int(limit)
    )
    return {"runs": runs}


async def _subscribe(call: Call) -> dict[str, Any]:
    # 이벤트 루프 안에서 등록한다 (송신 큐 재개·구독 교체가 이미 넘긴 송신과 섞이지 않게)
    after = request_int(call.params["after_seq"])
    call.daemon.run_manager.subscribe(call.connection, _run_id(call), after)
    return {}


async def _unsubscribe(call: Call) -> dict[str, Any]:
    call.daemon.run_manager.unsubscribe(call.connection, _run_id(call))
    return {}


METHODS: Final = {
    "run.start": MethodSpec(_start, _path_arg, self_authorized=True),
    "run.cancel": MethodSpec(_cancel, _cancel_arg),
    "run.status": MethodSpec(_status, _run_id),
    "run.list": MethodSpec(_list),
    "run.subscribe": MethodSpec(_subscribe, _run_id),
    "run.unsubscribe": MethodSpec(_unsubscribe),
}
