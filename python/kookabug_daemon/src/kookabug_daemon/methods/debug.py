"""디버거 메서드 (M3 계획 2.1·2.3): `debug.breakpoints.get/set`, `run.pause/resume/restart`.

다섯 메서드 모두 `ui_only`이고 `AGENT_DENIED`에도 든다(에이전트 연결은 판정 전에 거부). 실행 제어는
이 daemon이 사람의 UI 연결에서 시작한 실행에만 먹는다(`run_not_debuggable`). 집행은 runner가 하고
daemon은 중계·저장만 한다 — 멈춤 상태는 이벤트(`debug.pause`·`debug.resume`)로 알린다.

- `debug.breakpoints.set`은 `.kookabug/breakpoints.json`에 원자적으로 쓰고, 진행 중인 UI 실행에
  밀어 넣고(다음 경계부터), 다른 UI 연결에 `debug.breakpoints.changed`를 보낸다
- `run.restart`는 원래 실행의 인자(경로·프로필·설정·기한, 시작한 주체·연결 종류)로 새 실행을
  시작한다. 중복 방지 키는 넘기지 않고, 브레이크포인트는 그 순간의 파일 값이다
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_daemon.methods import Call, MethodSpec

__all__ = ["METHODS"]


def _run_id(call: Call) -> str:
    return str(call.params["run_id"])


async def _breakpoints_get(call: Call) -> dict[str, Any]:
    found = await asyncio.to_thread(call.daemon.run_manager.breakpoints.current)
    return {"breakpoints": [bp.to_json() for bp in found]}


async def _breakpoints_set(call: Call) -> dict[str, Any]:
    items = [dict(item) for item in call.params["breakpoints"]]
    written = await asyncio.to_thread(call.daemon.run_manager.set_breakpoints, items)
    call.daemon.breakpoints_changed(call.connection, written)
    return {"breakpoints": written}


async def _pause(call: Call) -> dict[str, Any]:
    state = await asyncio.to_thread(call.daemon.run_manager.pause, _run_id(call))
    return {"state": state}


async def _resume(call: Call) -> dict[str, Any]:
    mode = call.params.get("mode", "continue")
    state = await asyncio.to_thread(call.daemon.run_manager.resume, _run_id(call), mode)
    return {"state": state}


async def _restart(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(call.daemon.run_manager.restart, _run_id(call))


METHODS: Final = {
    "debug.breakpoints.get": MethodSpec(_breakpoints_get),
    "debug.breakpoints.set": MethodSpec(_breakpoints_set),
    "run.pause": MethodSpec(_pause, _run_id),
    "run.resume": MethodSpec(_resume, _run_id),
    "run.restart": MethodSpec(_restart, _run_id),
}
