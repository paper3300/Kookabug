"""고장 주입 지점 (테스트 전용).

환경 변수 `KOOKABUG_FAULTS`가 없으면 `fault_point()`·`check()`는 아무것도 하지 않는다. 있으면 JSON
**규칙 목록**이다:

    [{"point": "journal.partial_line", "role": "runner",
      "when": {"event": "log", "nth": 1}, "action": "wait:C:/tmp/b1", "once": true}]

- `role`: 프로세스가 시작 때 `set_role()`로 정한 역할과 같은 규칙만 쓴다. 역할을 정하지 않은
  프로세스에서는 어떤 규칙도 동작하지 않는다
- `when.event`: 지점이 넘긴 이벤트 종류가 같을 때만 센다. `when.nth`: 조건에 맞은 N번째(기본 1)에서
  동작한다
- `once`(기본 true): 한 번 동작하면 소비된다. false면 N번째부터 매번 동작한다
- 동작: `exit:<코드>`(`os._exit`), `hang`(끊을 수 없는 무한 대기), `wait:<경로>`(`<경로>.ready`를
  만들고 `<경로>.go`가 생길 때까지 10ms 간격으로 기다림), `raise`(`RuntimeError`)

지점·역할 이름은 아래 표로 고정한다. 모르는 이름이나 그 지점에 없는 역할은 규칙을 읽을 때
(`set_role()`) `FaultConfigError`다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

__all__ = [
    "ENV",
    "POINTS",
    "ROLES",
    "Action",
    "FaultConfigError",
    "check",
    "fault_point",
    "perform",
    "reset",
    "set_role",
]

ENV: Final = "KOOKABUG_FAULTS"

type Role = Literal["runner", "worker", "supervisor"]
ROLES: Final[tuple[Role, ...]] = ("runner", "worker", "supervisor")

_ALL: Final[frozenset[Role]] = frozenset(ROLES)
_RUNNER: Final[frozenset[Role]] = frozenset({"runner"})
_WORKER: Final[frozenset[Role]] = frozenset({"worker"})
_SUPERVISOR: Final[frozenset[Role]] = frozenset({"supervisor"})

# 지점 → 그 지점을 지나는 역할 (구현 계획 M0b 2.3 표)
POINTS: Final[dict[str, frozenset[Role]]] = {
    "journal.partial_line": _ALL,
    "runner.after_run_end": _RUNNER,
    "runner.before_run_json_final": _RUNNER,
    "runner.before_worker_shutdown": _RUNNER,
    "runner.before_lease_release": _RUNNER,
    "runner.after_hello": _RUNNER,
    "runner.before_validate": _RUNNER,
    "actor.before_backend": _RUNNER,
    "worker.before_hello_reply": _WORKER,
    "worker.in_import": _WORKER,
    "recovery.runner_exit_observed": _SUPERVISOR,
    "recovery.before_finalize": _SUPERVISOR,
    "recovery.before_input_recovery": _SUPERVISOR,
    "lease.before_recovery": frozenset({"runner", "supervisor"}),
}

_POLL_S: Final = 0.01


class FaultConfigError(ValueError):
    """`KOOKABUG_FAULTS` 규칙이 잘못됐다."""


@dataclass(frozen=True, slots=True)
class Action:
    kind: Literal["exit", "hang", "wait", "raise"]
    arg: str = ""
    point: str = ""


@dataclass(slots=True)
class _Rule:
    point: str
    role: Role
    action: Action
    event: str | None
    nth: int
    once: bool
    seen: int = 0
    spent: bool = False


@dataclass(slots=True)
class _State:
    role: Role | None = None
    rules: list[_Rule] = field(default_factory=list[_Rule])
    lock: threading.Lock = field(default_factory=threading.Lock)


_state: _State | None = None


def set_role(role: Role) -> None:
    """이 프로세스의 역할을 정하고 규칙을 읽는다. 프로세스 시작 때 한 번 부른다."""
    if role not in ROLES:
        raise FaultConfigError(f"모르는 역할 {role!r}. 가능한 값: {', '.join(ROLES)}")
    global _state
    _state = _State(role=role, rules=_parse(os.environ.get(ENV)))


def reset() -> None:
    """역할과 규칙을 지운다 (테스트용)."""
    global _state
    _state = None


def check(point: str, *, event: str | None = None) -> Action | None:
    """`point`에서 동작할 규칙이 있으면 그 동작을 돌려준다 (센 횟수는 소비된다).

    줄 일부를 쓴 뒤 멈추는 것처럼 동작 전에 할 일이 있는 지점이 쓴다. 보통은 `fault_point()`.
    """
    if point not in POINTS:
        raise FaultConfigError(f"모르는 고장 주입 지점 {point!r}")
    state = _state
    if state is None or state.role is None or not state.rules:
        return None
    with state.lock:
        for rule in state.rules:
            if rule.spent or rule.point != point or rule.role != state.role:
                continue
            if rule.event is not None and rule.event != event:
                continue
            rule.seen += 1
            if rule.seen < rule.nth:
                continue
            if rule.once:
                rule.spent = True
            return rule.action
    return None


def perform(action: Action | None) -> None:
    if action is None:
        return
    match action.kind:
        case "exit":
            os._exit(int(action.arg))
        case "hang":
            while True:
                time.sleep(3600)
        case "wait":
            base = action.arg
            Path(base + ".ready").touch()
            go = Path(base + ".go")
            while not go.exists():
                time.sleep(_POLL_S)
        case "raise":
            raise RuntimeError(f"고장 주입: {action.point}")


def fault_point(point: str, *, event: str | None = None) -> None:
    """고장 주입 지점. 규칙이 없으면 아무것도 하지 않는다."""
    perform(check(point, event=event))


def _parse(text: str | None) -> list[_Rule]:
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise FaultConfigError(f"{ENV}가 JSON이 아니다: {exc}") from exc
    if not isinstance(data, list):
        raise FaultConfigError(f"{ENV}는 규칙 목록(JSON 배열)이다")
    items: list[Any] = data
    return [_rule(i, item) for i, item in enumerate(items)]


def _rule(index: int, item: Any) -> _Rule:
    where = f"{ENV}[{index}]"
    if not isinstance(item, dict):
        raise FaultConfigError(f"{where}: 규칙은 객체다")
    rule: dict[str, Any] = item
    unknown = set(rule) - {"point", "role", "when", "action", "once"}
    if unknown:
        raise FaultConfigError(f"{where}: 모르는 필드 {sorted(unknown)}")
    point = rule.get("point")
    if point not in POINTS:
        raise FaultConfigError(f"{where}: 모르는 지점 {point!r}")
    role = rule.get("role")
    if role not in ROLES:
        raise FaultConfigError(f"{where}: 모르는 역할 {role!r}. 가능한 값: {', '.join(ROLES)}")
    if role not in POINTS[point]:
        raise FaultConfigError(f"{where}: 지점 {point!r}는 역할 {role!r}에서 지나지 않는다")
    when = rule.get("when", {})
    if not isinstance(when, dict) or set(when) - {"event", "nth"}:
        raise FaultConfigError(f"{where}: when은 {{event?, nth?}} 객체다")
    when_map: dict[str, Any] = when
    event = when_map.get("event")
    if event is not None and not isinstance(event, str):
        raise FaultConfigError(f"{where}: when.event는 문자열이다")
    nth = when_map.get("nth", 1)
    if isinstance(nth, bool) or not isinstance(nth, int) or nth < 1:
        raise FaultConfigError(f"{where}: when.nth는 1 이상의 정수다")
    once = rule.get("once", True)
    if not isinstance(once, bool):
        raise FaultConfigError(f"{where}: once는 true·false다")
    return _Rule(point, role, _action(where, point, rule.get("action")), event, nth, once)


def _action(where: str, point: str, text: Any) -> Action:
    if not isinstance(text, str):
        raise FaultConfigError(f"{where}: action은 문자열이다")
    kind, _, arg = text.partition(":")
    match kind:
        case "hang" | "raise" if not arg:
            return Action(kind, "", point)
        case "exit":
            try:
                int(arg)
            except ValueError:
                raise FaultConfigError(f"{where}: exit:<정수 코드>여야 한다: {text!r}") from None
            return Action("exit", arg, point)
        case "wait" if arg:
            return Action("wait", arg, point)
        case _:
            raise FaultConfigError(
                f"{where}: 모르는 동작 {text!r} (exit:<코드>, hang, wait:<경로>, raise)"
            )
