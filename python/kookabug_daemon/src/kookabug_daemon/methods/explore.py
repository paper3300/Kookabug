"""`explore.start/end/list` (M7 계획 3.4): 에이전트 탐색 세션.

`explore.start`·`explore.end`는 에이전트 전용(`kb_explore_start`·`kb_explore_end`, 사람 연결은
`agent_only`). `explore.list`는 사람만(UI). 세션 제목·목표·창 이름은 3.5b 글자 검사를 지난다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from kookabug_core.workspace import Workspace
from kookabug_daemon.explore import DEFAULT_MAX_STEPS, check_texts, job_secrets
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = ["METHODS"]

_LIMITS: Final = {"title": 200, "goal": 1000, "window": 200}
_ID_MAX: Final = 200
"""`explore.json` `agent.id`·`agent.client` 최대 길이 (explore 형식)."""


def _agent_only(call: Call) -> None:
    if call.principal.kind != "agent":
        raise RequestFailed("agent_only", "탐색 세션은 에이전트 연결만 연다 (사람은 화면 지도 탭)")


def _text(call: Call, name: str, *, required: bool = False) -> str | None:
    value = call.params.get(name)
    if value is None:
        if required:
            raise InvalidParams(f"{name}이(가) 없다")
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > _LIMITS[name]:
        raise InvalidParams(f"{name}은(는) 1~{_LIMITS[name]}자 글자다")
    return value


def _start(call: Call) -> dict[str, Any]:
    _agent_only(call)
    title = _text(call, "title", required=True)
    assert title is not None
    goal, window = _text(call, "goal"), _text(call, "window")
    max_steps = call.params.get("max_steps", DEFAULT_MAX_STEPS)
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 1000:
        raise InvalidParams("max_steps는 1~1000이다")
    agent_id = call.principal.id
    # explore.json에 남는 에이전트 식별자 (B2b Low 6): ID는 형식 검사(바꾸지 않음), 표시 이름은 제어
    # 문자를 빼고 자른다. 둘 다 비밀값 글자 검사도 지난다
    if len(agent_id) > _ID_MAX or not agent_id.isprintable():
        raise RequestFailed(
            "validation_failed",
            f"에이전트 ID가 {_ID_MAX}자를 넘거나 제어 문자가 있어 탐색 세션을 열지 않는다",
        )
    client = "".join(ch for ch in call.daemon.connection_name(call.connection) if ch.isprintable())
    client = client[:_ID_MAX]
    texts = [
        (n, v)
        for n, v in (
            ("title", title),
            ("goal", goal),
            ("window", window),
            ("agent.id", agent_id),
            ("agent.client", client),
        )
        if v
    ]
    check_texts(texts, call.daemon.guard, call.daemon.root, job_secrets(call.daemon))
    session = call.daemon.explore.start(
        call.connection,
        agent_id,
        client,
        title,
        goal,
        window,
        max_steps,
    )
    return {"session": session.id, "folder": session.rel, "max_steps": session.max_steps}


def _end(call: Call) -> dict[str, Any]:
    _agent_only(call)
    session = call.daemon.explore.end(call.connection)
    if session is None:
        raise RequestFailed("explore_not_active", "탐색 세션이 없다")
    listed = call.daemon.explore.listing(Workspace.open(call.daemon.root))
    counts = next(
        (s["counts"] for s in listed if s["id"] == session.id),
        {"screens": 0, "moves": 0, "untried": 0},
    )
    return {"session": session.id, "counts": counts}


def _list(call: Call) -> dict[str, Any]:
    return {"sessions": call.daemon.explore.listing(Workspace.open(call.daemon.root))}


async def _start_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_start, call)


async def _end_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_end, call)


async def _list_handler(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(_list, call)


METHODS: Final = {
    "explore.start": MethodSpec(_start_handler),
    "explore.end": MethodSpec(_end_handler),
    "explore.list": MethodSpec(_list_handler),
}
