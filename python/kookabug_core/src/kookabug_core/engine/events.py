"""실행 이벤트 (스키마 v0 5장).

- `step.start`: `run`, `step`, `parent`, `node`, `path`, `attempt` (반복 안이면 `iteration`)
- `step.end`: `run`, `step`, `attempt`, `status`(`success`·`fail`·`error`·`cancelled`), `exit`,
  `outputs`, `duration_ms`, 상황에 따라 `error`·`message`·`graph`·`artifacts`·`omitted`·`iteration`
- `log`: `run`, `step`, `node`, `level`, `message` (`ctx.log`)

M0a는 메모리에만 남긴다. M0b가 같은 dict를 `events.jsonl`에 쓴다 (시각 `t`는 쓰는 쪽이 붙인다).
값은 `event_value()`로 JSON 값으로 바꾸고, 비밀값 가림(`record.redact_secrets`)이 켜진 실행만
비밀값을 가린다.

**에이전트용 분류 (M5 3.8)**: 가림이 꺼진 실행도 "켜져 있었다면 가렸을 필드"를 이벤트의
`secret_paths`(이벤트 기준 JSON pointer 목록)로 남긴다(`classified_value`). daemon이 에이전트에게
줄 때 그 필드를 `***`로 바꾼다. 비밀값 목록은 어디에도 저장하지 않는다 — 비밀 형식이 살아 있는 이
자리에서만 판정한다.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any, Protocol

from kookabug_sdk import Secret, SecretMessage

__all__ = ["EventSink", "MemoryEventSink", "classified_value", "event_value", "mark_secret"]


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


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def classified_value(value: Any, *, redact: bool, pointer: str) -> tuple[Any, list[str]]:
    """`event_value`와 같은 값 + 비밀값(`Secret`·`SecretMessage`)이 있던 자리의 pointer 목록.
    `pointer`는 이벤트 안에서 이 값의 위치(예: `/outputs`)."""
    found: list[str] = []

    def walk(item: Any, at: str) -> Any:
        if isinstance(item, Secret | SecretMessage):
            found.append(at)
            return event_value(item, redact=redact)
        if isinstance(item, Mapping):
            items: Mapping[Any, Any] = item
            return {str(k): walk(v, f"{at}/{_escape(str(k))}") for k, v in items.items()}
        if isinstance(item, list | tuple):
            seq: list[Any] | tuple[Any, ...] = item
            return [walk(v, f"{at}/{i}") for i, v in enumerate(seq)]
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return {
                f.name: walk(getattr(item, f.name), f"{at}/{_escape(f.name)}")
                for f in dataclasses.fields(item)
            }
        return event_value(item, redact=redact)

    return walk(value, pointer), found


def mark_secret(event: dict[str, Any], paths: list[str]) -> None:
    """이벤트에 비밀 필드 위치를 더한다 (같은 위치는 한 번)."""
    if not paths:
        return
    held: list[str] = event.setdefault("secret_paths", [])
    for path in paths:
        if path not in held:
            held.append(path)
