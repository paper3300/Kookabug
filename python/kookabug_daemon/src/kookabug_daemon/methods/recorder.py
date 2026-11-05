"""`recorder.*` 메서드 (M4 계획 2.9, T8). 모두 `ui_only` + `AGENT_DENIED`(전송이 처리기 앞에서
거부).

세션 소유 연결만 조작·읽기(`not_owner`), 다른 연결은 `recorder.state`로 상태·경과만 본다. 처리는
막히는 일(임대권·캡처·훅·OCR·파일)이라 작업 스레드에서 한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from kookabug_daemon.methods import Call, MethodSpec

if TYPE_CHECKING:
    from kookabug_daemon.recorder import RecorderService, RecorderSession

__all__ = ["METHODS"]


def _service(call: Call) -> RecorderService:
    return call.daemon.recorder  # pyright: ignore[reportAttributeAccessIssue]


def _owned(call: Call) -> RecorderSession:
    return _service(call).require(call.connection)


async def _run[T](fn: Callable[..., T], *args: Any) -> T:
    return await asyncio.to_thread(fn, *args)


async def _start(call: Call) -> dict[str, Any]:
    return await _run(_service(call).start, call.connection, call.params)


async def _state(call: Call) -> dict[str, Any]:
    return _service(call).state(call.connection)


def _then_state(action: Callable[[RecorderSession], object]) -> Callable[[Call], Any]:
    async def handler(call: Call) -> dict[str, Any]:
        session = _owned(call)
        await _run(action, session)
        return session.state_json(owned=True)

    return handler


async def _steps(call: Call) -> dict[str, Any]:
    return await _run(_owned(call).steps)


async def _step_update(call: Call) -> dict[str, Any]:
    session = _owned(call)
    return await _run(session.step_update, str(call.params["step"]), call.params["patch"])


async def _frame(call: Call) -> dict[str, Any]:
    session = _owned(call)
    step = call.params.get("step")
    return await _run(session.frame, str(call.params["which"]), None if step is None else str(step))


async def _insert_check(call: Call) -> dict[str, Any]:
    session = _owned(call)
    p = call.params
    return await _run(session.insert_check, str(p["kind"]), str(p["frame_id"]), list(p["rect"]))


async def _commit_prepare(call: Call) -> dict[str, Any]:
    return await _run(_owned(call).commit_prepare, call.params)


async def _commit_finish(call: Call) -> dict[str, Any]:
    await _run(_owned(call).commit_finish, str(call.params["token"]))
    return {}


async def _commit_abort(call: Call) -> dict[str, Any]:
    await _run(_owned(call).commit_abort, str(call.params["token"]))
    return {}


METHODS: Final[dict[str, MethodSpec]] = {
    "recorder.start": MethodSpec(_start),
    "recorder.state": MethodSpec(_state),
    "recorder.pause": MethodSpec(_then_state(lambda s: s.pause())),
    "recorder.resume": MethodSpec(_then_state(lambda s: s.resume())),
    "recorder.stop": MethodSpec(_then_state(lambda s: s.stop("user"))),
    "recorder.discard": MethodSpec(_then_state(lambda s: s.discard())),
    "recorder.steps": MethodSpec(_steps),
    "recorder.step.update": MethodSpec(_step_update),
    "recorder.frame": MethodSpec(_frame),
    "recorder.insert_check": MethodSpec(_insert_check),
    "recorder.commit_prepare": MethodSpec(_commit_prepare),
    "recorder.commit_finish": MethodSpec(_commit_finish),
    "recorder.commit_abort": MethodSpec(_commit_abort),
}
