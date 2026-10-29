"""입력 백엔드 (구현 계획 M0b 2.4).

runner 안에서 백엔드를 부르는 스레드는 입력 액터 하나다(`InputActor`). 실제 SendInput 백엔드는 M1.

- `none`: 입력 장치가 없는 플랫폼. 모든 입력이 `platform_unavailable`
- `fake`: 호출을 JSONL 파일에 덧붙인다(`{op, device, key|button, by, run, pid, thread}`). 여러
  프로세스가 같은 파일에 써도 줄이 섞이지 않는다(`FILE_APPEND_DATA` 핸들, 줄마다 쓰기 한 번).
  키별 훅 `before_down`·`after_down`·`before_up`으로 "누른 채 멈춘 runner"를 만든다

훅 동작: `block`(게이트가 닫힐 때까지 기다렸다 돌아옴), `hang`(끊을 수 없는 무한 대기),
`wait:<경로>`(파일 장벽 — `<경로>.ready`를 만들고 `<경로>.go`를 기다림). 단위 테스트는 같은 자리에
호출 가능한 값(스레드 장벽)을 넣는다. 훅 이름은 키보드 키 이름, 마우스는 `mouse:<버튼>`.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from kookabug_core.engine.errors import EngineError
from kookabug_core.win.files import append_bytes
from kookabug_sdk import _faults
from kookabug_sdk.types import Point

__all__ = [
    "HOOKS",
    "BackendKind",
    "FakeBackend",
    "HookAction",
    "InputBackend",
    "NoneBackend",
    "PlatformUnavailable",
    "create_backend",
]

type BackendKind = Literal["none", "fake"]
type Hook = Literal["before_down", "after_down", "before_up"]
type HookAction = str | Callable[[], None]

HOOKS: Final[tuple[Hook, ...]] = ("before_down", "after_down", "before_up")


class PlatformUnavailable(EngineError):
    """이 플랫폼에는 입력 장치가 없다 (`none`)."""

    def __init__(self, message: str = "이 플랫폼에서는 입력을 보낼 수 없다") -> None:
        super().__init__("platform_unavailable", message)


class InputBackend(Protocol):
    """원시 입력 동작. 입력 액터 스레드만 부른다."""

    @property
    def available(self) -> bool: ...
    def down(self, key: str) -> None: ...
    def up(self, key: str) -> None: ...
    def mouse_down(self, button: str, at: Point | None = None) -> None: ...
    def mouse_up(self, button: str) -> None: ...
    def text(self, text: str) -> None: ...


class NoneBackend:
    @property
    def available(self) -> bool:
        return False

    def down(self, key: str) -> None:
        raise PlatformUnavailable

    def up(self, key: str) -> None:
        raise PlatformUnavailable

    def mouse_down(self, button: str, at: Point | None = None) -> None:
        raise PlatformUnavailable

    def mouse_up(self, button: str) -> None:
        raise PlatformUnavailable

    def text(self, text: str) -> None:
        raise PlatformUnavailable


class FakeBackend:
    """입력을 실행하지 않고 JSONL 파일에 남긴다. `by`는 누가 보냈는지(로그 구분용)."""

    def __init__(
        self,
        log: str | os.PathLike[str],
        *,
        run: str | None = None,
        by: str = "runner",
        hooks: Mapping[str, Mapping[str, HookAction]] | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.log = Path(log)
        self.run = run
        self.by = by
        self._gate = gate
        self._hooks = _check_hooks(hooks or {}, gate)

    @property
    def available(self) -> bool:
        return True

    def down(self, key: str) -> None:
        self._press("down", "keyboard", key)

    def up(self, key: str) -> None:
        self._hook("before_up", key)
        self._write("up", "keyboard", key)

    def mouse_down(self, button: str, at: Point | None = None) -> None:
        self._press("down", "mouse", button, at)

    def mouse_up(self, button: str) -> None:
        self._hook("before_up", f"mouse:{button}")
        self._write("up", "mouse", button)

    def text(self, text: str) -> None:
        # 글자 수만 남긴다: 비밀값 원문은 가짜 기록에도 남기지 않는다
        self._append({"op": "text", "length": len(text)})

    def _press(self, op: str, device: str, name: str, at: Point | None = None) -> None:
        hook_name = name if device == "keyboard" else f"mouse:{name}"
        self._hook("before_down", hook_name)
        self._write(op, device, name, at)
        self._hook("after_down", hook_name)

    def _write(self, op: str, device: str, name: str, at: Point | None = None) -> None:
        line: dict[str, Any] = {
            "op": op,
            "device": device,
            "key" if device == "keyboard" else "button": name,
        }
        if at is not None:
            line["at"] = [at.x, at.y]
        self._append(line)

    def _append(self, line: dict[str, Any]) -> None:
        record = {
            **line,
            "by": self.by,
            "run": self.run,
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
        }
        data = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        append_bytes(self.log, data)

    def _hook(self, hook: Hook, name: str) -> None:
        action = self._hooks.get(hook, {}).get(name)
        if action is None:
            return
        if callable(action):
            action()
        elif action == "block":
            assert self._gate is not None
            self._gate.wait()
        elif action == "hang":
            _faults.perform(_faults.Action("hang"))
        else:
            _faults.perform(_faults.Action("wait", action.removeprefix("wait:")))


def _check_hooks(
    hooks: Mapping[str, Mapping[str, HookAction]], gate: threading.Event | None
) -> dict[str, dict[str, HookAction]]:
    checked: dict[str, dict[str, HookAction]] = {}
    for hook, actions in hooks.items():
        if hook not in HOOKS:
            raise ValueError(f"모르는 훅 {hook!r}. 가능한 값: {', '.join(HOOKS)}")
        for name, action in actions.items():
            if callable(action):
                continue
            if action == "block" and gate is None:
                raise ValueError("block 훅에는 액터 게이트(gate)가 필요하다")
            if action not in ("block", "hang") and not (
                action.startswith("wait:") and len(action) > len("wait:")
            ):
                raise ValueError(f"모르는 훅 동작 {action!r} ({hook}.{name})")
        checked[hook] = dict(actions)
    return checked


def create_backend(
    kind: BackendKind,
    *,
    input_log: str | os.PathLike[str] | None = None,
    hooks: Mapping[str, Mapping[str, HookAction]] | None = None,
    run: str | None = None,
    by: str = "runner",
    gate: threading.Event | None = None,
) -> InputBackend:
    """실행 사양의 `platform`(`kind`·`input_log`·`hooks`)으로 백엔드를 만든다."""
    if kind == "none":
        return NoneBackend()
    if kind == "fake":
        if input_log is None:
            raise ValueError("fake 백엔드에는 input_log가 필요하다")
        return FakeBackend(input_log, run=run, by=by, hooks=hooks, gate=gate)
    raise ValueError(f"모르는 입력 백엔드 {kind!r}")
