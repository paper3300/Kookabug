"""실행 이벤트 (스키마 v0 5장).

- `step.start`: `run`, `step`, `parent`, `node`, `path`, `attempt` (반복 안이면 `iteration`)
- `step.end`: `run`, `step`, `attempt`, `status`(`success`·`fail`·`error`·`cancelled`), `exit`,
  `outputs`, `duration_ms`, 상황에 따라 `error`·`message`·`graph`·`artifacts`·`omitted`·`iteration`
- `log`: `run`, `step`, `node`, `level`, `message` (`ctx.log`)

M0a는 메모리에만 남긴다. M0b가 같은 dict를 `events.jsonl`에 쓴다 (시각 `t`는 쓰는 쪽이 붙인다).
값은 `event_value()`로 JSON 값으로 바꾸고, 비밀값 가림(`record.redact_secrets`)이 켜진 실행만
비밀값을 가린다.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any, Protocol

from kookabug_sdk import Secret, SecretMessage

__all__ = ["EventSink", "MemoryEventSink", "event_value"]


class EventSink(Protocol):
    def emit(self, event: Mapping[str, Any]) -> None: ...


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


def event_value(value: Any, *, redact: bool = True) -> Any:
    """이벤트에 남길 값: JSON 값으로 바꾸고 비밀값은 가린 값(`***`)으로. `redact=False`(워크스페이스
    `record.redact_secrets`가 꺼진 실행, D3)면 비밀값 원문을 그대로 남긴다."""
    if isinstance(value, Secret):
        return Secret.MASK if redact else value.reveal()
    if isinstance(value, SecretMessage):
        # 코어 노드가 출력 등 값 안에 비밀값 메시지를 넣어도 둘 중 하나만 남긴다 (원문을 같이
        # 풀지 않게)
        return value.masked if redact else value.raw
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Mapping):
        items: Mapping[Any, Any] = value
        return {str(k): event_value(v, redact=redact) for k, v in items.items()}
    if isinstance(value, list | tuple):
        seq: list[Any] | tuple[Any, ...] = value
        return [event_value(v, redact=redact) for v in seq]
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: event_value(getattr(value, f.name), redact=redact)
            for f in dataclasses.fields(value)
        }
    return str(value)
