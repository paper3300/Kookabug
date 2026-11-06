"""`run.start/cancel/status/list/subscribe/unsubscribe` (M2 계획 2.8), 기록 읽기
`run.index/children/step/file`과 `run.export` (M3 계획 2.7), 지난 성공과 비교 `run.compare` (2.8).

실행 관리는 `runs.RunManager`가, 기록 읽기는 `run_index.RunRecords`가 한다. 기록 읽기의 대표 인자는
실행 ID다. `run.export`는 `ui_only`이고 `AGENT_DENIED`라 에이전트 연결은 전송이 판정 전에 거부한다.
M5: 기록 원문 읽기(`run.index/children/step/file/compare/subscribe`)는 에이전트 연결이면 판정 전에
`agent_use_safe_api`(에이전트는 `methods.run_agent`의 가린 결과로만). `run.list`의 판정 사유는
에이전트에게 분류대로 가린다(3.8).

- `run.start`는 판정을 전송이 아니라 시작 잠금 안의 ② 단계에서 한다 (`MethodSpec.self_authorized`).
  대표 인자는 링크를 해석한 그래프 경로다
- `run.cancel`의 대표 인자는 그 실행의 그래프 경로, `run.status`·`run.subscribe`는 실행 ID다
  (M2 계획 2.5 표)
- dirty 버퍼는 UI 책임이다(먼저 저장한 뒤 실행). daemon은 디스크 파일로 실행한다
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_daemon.agent_view import mask_run_summary
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
    # 개발 모듈 daemon의 에이전트 실행은 사람 확인을 묻기 전에 거부 (M6 3.7)
    call.daemon.run_manager.refuse_dev_modules(call.principal)
    # ask면 시작 잠금 밖에서 사람 확인을 받는다 (M5 3.6). 판정 자체는 ② 단계에서 다시 한다
    approved = await call.daemon.approvals.approve(call, _path_arg(call))
    request = StartRequest(
        principal=call.principal,
        path=str(params["path"]),
        profile=None if profile is None else str(profile),
        settings=dict(params.get("settings") or {}),
        deadline_ms=None if deadline is None else request_int(deadline),
        idempotency_key=None if key is None else str(key),
        # 사람이 UI에서 시작한 실행만 디버그 대상 (주체 kind가 아니라 연결 종류로, M3 2.1)
        ui=call.client_kind == "ui",
        approved=approved,
    )
    return await asyncio.to_thread(call.daemon.run_manager.start, request)


async def _cancel(call: Call) -> dict[str, Any]:
    await asyncio.to_thread(call.daemon.run_manager.cancel, _run_id(call))
    return {}


async def _status(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(call.daemon.run_manager.status, _run_id(call))


def _list_sync(call: Call) -> dict[str, Any]:
    params = call.params
    limit = params.get("limit")
    before, graph, verdict = params.get("before"), params.get("graph"), params.get("verdict")
    result = call.daemon.run_manager.list_runs(
        None if limit is None else request_int(limit),
        before=None if before is None else str(before),
        graph=None if graph is None else str(graph),
        verdict=None if verdict is None else str(verdict),
    )
    if call.principal.kind == "agent":
        # 판정 사유는 비밀값을 담을 수 있다: 에이전트에게는 분류대로 가린다 (M5 3.8)
        result["runs"] = [
            mask_run_summary(s, Path(str(s["run_dir"]))) for s in result.get("runs", [])
        ]
    return result


async def _list(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_list_sync, call)


# ---------------------------------------------------------------- 기록 읽기 (M3 2.7)


async def _index(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(call.daemon.run_manager.records.index, _run_id(call))


async def _children(call: Call) -> dict[str, Any]:
    params = call.params
    iteration = params.get("iteration")
    return await asyncio.to_thread(
        call.daemon.run_manager.records.children,
        _run_id(call),
        str(params["parent"]),
        None if iteration is None else request_int(iteration),
        request_int(params["offset"]),
        request_int(params["limit"]),
    )


async def _step(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(
        call.daemon.run_manager.records.step, _run_id(call), str(call.params["step"])
    )


async def _file(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(
        call.daemon.run_manager.records.file, _run_id(call), str(call.params["name"])
    )


async def _compare(call: Call) -> dict[str, Any]:
    params = call.params
    baseline, step = params.get("baseline"), params.get("step")
    return await asyncio.to_thread(
        call.daemon.run_manager.records.compare,
        _run_id(call),
        None if baseline is None else str(baseline),
        None if step is None else str(step),
    )


async def _export(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(
        call.daemon.run_manager.records.export, _run_id(call), str(call.params["dest"])
    )


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
    "run.index": MethodSpec(_index, _run_id),
    "run.children": MethodSpec(_children, _run_id),
    "run.step": MethodSpec(_step, _run_id),
    "run.file": MethodSpec(_file, _run_id),
    "run.compare": MethodSpec(_compare, _run_id),
    "run.export": MethodSpec(_export, _run_id),
}
