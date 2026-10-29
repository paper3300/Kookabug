"""입력 액터: runner 안에서 백엔드를 부르는 유일한 스레드 (구현 계획 M0b 2.4 "입력 액터 계약").

1. 주 스레드(코어 노드·워커 `ctx.input.*` 요청)는 `click`·`key`·`type_text`를 큐에 넣고 완료(또는
   `Cancelled`)를 기다린다. 제어 스레드는 백엔드를 부르지 않는다
2. 요청 하나를 원시 동작으로 나눠 연달아 처리한다. `down` = `input.down` 기록 → 백엔드 → `held`에
   넣음, `up` = 백엔드 → `held`에서 뺌 → `input.up` 기록. 그래서 프로세스가 어디서 죽어도 기록상
   "눌렸을 수 있는" 키(`held_inputs`)에서 실제로 눌린 키가 빠지지 않는다
3. 게이트: 제어 스레드가 `close_gate()`로 플래그를 세우고, 큐에서 기다리던 입력 요청을 그 자리에서
   모두 `Cancelled`로 돌려보내고, 큐 **맨 앞에** `RELEASE_ALL`을 넣는다. 액터는 지금 원시 동작을
   끝낸 뒤 다음 동작 전에 게이트를 보고 `held`를 뗀다. 게이트가 닫힌 뒤 들어오는 요청은 바로
   `Cancelled`. 대기 요청의 취소는 액터의 떼기가 멈춰 있어도 끝난다
4. 수명: 만듦 → `start()` → `stop()`. `stop()`은 게이트를 닫고 `RELEASE_ALL` → `STOP`.
   **quiesced = 멈춘 상태이고(`stop()`을 불렀고) 액터 스레드가 끝났고 `held`가 비었다.** 멈춘
   액터는 다시 시작하지 않으므로 그 뒤 이 액터로는 백엔드 호출이 일어날 수 없다 — 임대권은 이때만
   깨끗하게 놓는다. 시작하지 않은 액터는 `stop()` 전까지 quiesced가 아니다
5. 액터가 백엔드 호출에서 멈추면 그 뒤 항목은 처리되지 않고 quiesced가 되지 않는다(하드 종료 →
   복구 경로 또는 다음 임대권 획득자가 키를 뗀다)
6. 입력 기록 쓰기가 실패하면 액터는 **입력을 막는다**(`journal_error`): 게이트를 닫고 대기 요청을
   취소하고 눌린 키를 뗀다. 그 뒤에는 기록하지 않는다 — 반쯤 쓴 줄 뒤에 이어 쓰면 읽기가 그 줄을
   버려, 실제로 누른 키가 복구 대상에서 빠진다

`type_text`의 비밀값은 백엔드에만 가고 이벤트에는 남지 않는다.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Literal

from kookabug_core.inputs.backends import InputBackend, PlatformUnavailable
from kookabug_core.record.reader import InputKey
from kookabug_sdk import _faults
from kookabug_sdk.context import Cancelled
from kookabug_sdk.types import Match, Point, Rect, Secret

__all__ = ["ACTOR_THREAD_NAME", "Emit", "InputActor"]

ACTOR_THREAD_NAME: Final = "kookabug-input-actor"

# 저널 쓰기 (`Journal.emit`). None이면 이벤트를 남기지 않는다
type Emit = Callable[[Mapping[str, Any]], object]

type _State = Literal["new", "running", "stopped"]

# "ctrl+shift+a" → ctrl, shift, a. 끝의 "+"는 키 이름이다 ("ctrl++" → ctrl, +)
_COMBO_SPLIT: Final = re.compile(r"\+(?=.)")


class _Marker(Enum):
    RELEASE_ALL = "release_all"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class _Primitive:
    op: Literal["down", "up", "text"]
    key: InputKey | None = None
    at: Point | None = None
    text: str | Secret | None = None


@dataclass(slots=True)
class _Request:
    primitives: list[_Primitive]
    step: str | None
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None

    def finish(self, error: BaseException | None = None) -> None:
        self.error = error
        self.done.set()


type _Item = _Request | _Marker


class InputActor:
    """입력 요청 큐와 그것을 처리하는 스레드 하나.

    `gate`를 주면 그 이벤트를 게이트로 쓴다 (가짜 백엔드의 `block` 훅과 같은 게이트를 나눈다).
    """

    def __init__(
        self,
        backend: InputBackend,
        *,
        emit: Emit | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.backend = backend
        self._emit = emit
        self.gate = gate or threading.Event()
        self._queue: deque[_Item] = deque()
        self._cond = threading.Condition(threading.Lock())
        self._state: _State = "new"
        # 누른 순서를 지킨다 (떼기는 거꾸로)
        self._held: dict[InputKey, None] = {}
        self._held_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.errors: list[BaseException] = []
        """`RELEASE_ALL`에서 떼지 못한 키의 오류 (그 키는 `held`에 남는다)."""
        self.journal_error: BaseException | None = None
        """입력 기록 쓰기 실패. 이것이 있으면 액터는 입력을 막았고 더 기록하지 않는다."""

    # ── 시작·멈춤 ─────────────────────────────────────────

    def start(self) -> InputActor:
        with self._cond:
            if self._state != "new":
                raise RuntimeError(
                    "입력 액터는 한 번만 시작한다 (멈춘 액터는 다시 시작하지 않는다)"
                )
            self._state = "running"
            self._thread = threading.Thread(target=self._run, name=ACTOR_THREAD_NAME, daemon=True)
            self._thread.start()
        return self

    def close_gate(self) -> None:
        """취소 순서 1·2: 새 입력을 막고 대기 요청을 취소하고, 지금 원시 동작이 끝나는 대로 눌린
        키를 떼게 한다.

        백엔드를 부르지 않고 곧바로 돌아온다 (액터가 백엔드에서 멈춰 있어도).
        """
        self._close(Cancelled("입력이 막혔다 (실행 취소·마무리 중)"))

    def stop(self, timeout: float | None = None) -> bool:
        """게이트를 닫고 남은 항목을 처리한 뒤 액터를 끝낸다. quiesced인지 돌려준다.

        시작하지 않은 액터도 멈춘 상태가 되어 다시 시작할 수 없다.
        """
        pending: list[_Request]
        with self._cond:
            self.gate.set()
            pending = self._take_requests()
            thread = self._thread
            self._state = "stopped"
            if thread is not None:
                self._queue.appendleft(_Marker.RELEASE_ALL)
                self._queue.append(_Marker.STOP)
                self._cond.notify()
        _cancel(pending, Cancelled("입력 액터를 멈췄다"))
        if thread is not None:
            thread.join(timeout)
        return self.quiesced

    @property
    def gate_closed(self) -> bool:
        return self.gate.is_set()

    @property
    def held(self) -> list[InputKey]:
        with self._held_lock:
            return list(self._held)

    @property
    def quiesced(self) -> bool:
        """멈춘 상태이고, 액터 스레드가 끝났고(또는 시작하지 않았고), 눌린 키가 없다."""
        if self._state != "stopped":
            return False
        thread = self._thread
        if thread is not None and thread.is_alive():
            return False
        with self._held_lock:
            return not self._held

    # ── 생산자 쪽 (주 스레드 등) ───────────────────────────

    def click(
        self, at: Point | Rect | Match, *, button: str = "left", step: str | None = None
    ) -> None:
        if not button:
            raise ValueError("마우스 버튼 이름이 비었다")
        key = InputKey("mouse", button)
        self._submit([_Primitive("down", key, at=_point(at)), _Primitive("up", key)], step)

    def key(self, key: str, *, step: str | None = None) -> None:
        """키 하나 또는 조합(`ctrl+a`)을 누르고 뗀다. 조합은 차례로 누르고 거꾸로 뗀다."""
        names = _COMBO_SPLIT.split(key)
        if not key or any(not n for n in names):
            raise ValueError(f"키 이름이 잘못됐다: {key!r}")
        keys = [InputKey("keyboard", n) for n in names]
        downs = [_Primitive("down", k) for k in keys]
        ups = [_Primitive("up", k) for k in reversed(keys)]
        self._submit(downs + ups, step)

    def type_text(self, text: str | Secret, *, step: str | None = None) -> None:
        self._submit([_Primitive("text", text=text)], step)

    def _submit(self, primitives: list[_Primitive], step: str | None) -> None:
        if not self.backend.available:
            raise PlatformUnavailable
        request = _Request(primitives, step)
        with self._cond:
            if self._state == "new":
                raise RuntimeError("입력 액터를 시작하지 않았다")
            if self.gate.is_set() or self._state == "stopped":
                raise Cancelled("입력이 막혔다 (실행 취소·마무리 중)")
            self._queue.append(request)
            self._cond.notify()
        request.done.wait()
        if request.error is not None:
            raise request.error

    # ── 게이트·큐 ────────────────────────────────────────

    def _close(self, reason: BaseException) -> None:
        with self._cond:
            self.gate.set()
            pending = self._take_requests()
            self._queue.appendleft(_Marker.RELEASE_ALL)
            self._cond.notify()
        _cancel(pending, reason)

    def _take_requests(self) -> list[_Request]:
        """큐의 입력 요청을 모두 꺼낸다 (`_cond` 안에서). 표지는 남긴다."""
        requests = [i for i in self._queue if isinstance(i, _Request)]
        if requests:
            markers = [i for i in self._queue if isinstance(i, _Marker)]
            self._queue.clear()
            self._queue.extend(markers)
        return requests

    # ── 액터 스레드 ──────────────────────────────────────

    def _next(self) -> _Item:
        with self._cond:
            while not self._queue:
                self._cond.wait()
            return self._queue.popleft()

    def _run(self) -> None:
        try:
            while True:
                item = self._next()
                if item is _Marker.STOP:
                    self._release_all()
                    return
                if item is _Marker.RELEASE_ALL:
                    self._release_all()
                elif isinstance(item, _Request):
                    self._execute(item)
        finally:
            with self._cond:
                self._state = "stopped"
                self.gate.set()
                left = self._take_requests()
            _cancel(left, Cancelled("입력 액터가 끝났다"))

    def _execute(self, request: _Request) -> None:
        pressed: list[InputKey] = []
        try:
            for primitive in request.primitives:
                # 원시 동작 사이마다 게이트를 본다: 닫혔으면 이미 누른 키는 RELEASE_ALL이 뗀다
                if self.gate.is_set():
                    raise Cancelled("입력이 막혔다 (실행 취소·마무리 중)")
                self._do(primitive, request.step, pressed)
        except Cancelled as exc:
            request.finish(exc)
        except BaseException as exc:
            # 요청이 실패하면 이 요청이 누른 키를 바로 뗀다 (다음 노드가 눌린 키 위에서 돌지 않게)
            for key in reversed(pressed):
                if self._is_held(key):
                    self._release(key, request.step)
            request.finish(exc)
        else:
            request.finish()

    def _do(self, primitive: _Primitive, step: str | None, pressed: list[InputKey]) -> None:
        match primitive.op:
            case "down":
                key = primitive.key
                assert key is not None
                self._record("input.down", key, step)
                try:
                    _faults.fault_point("actor.before_backend", event="down")
                    if key.device == "keyboard":
                        self.backend.down(key.name)
                    else:
                        self.backend.mouse_down(key.name, primitive.at)
                finally:
                    # 기록은 이미 "눌렸을 수 있음"이다: 백엔드가 실패해도 떼기 대상에 넣는다
                    with self._held_lock:
                        self._held[key] = None
                    pressed.append(key)
            case "up":
                key = primitive.key
                assert key is not None
                self._up(key, step)
            case "text":
                value = primitive.text
                assert value is not None
                _faults.fault_point("actor.before_backend", event="text")
                self.backend.text(value.reveal() if isinstance(value, Secret) else value)

    def _up(self, key: InputKey, step: str | None) -> None:
        _faults.fault_point("actor.before_backend", event="up")
        if key.device == "keyboard":
            self.backend.up(key.name)
        else:
            self.backend.mouse_up(key.name)
        with self._held_lock:
            self._held.pop(key, None)
        self._record("input.up", key, step)

    def _release(self, key: InputKey, step: str | None) -> None:
        try:
            self._up(key, step)
        except Exception as exc:  # 다른 키는 계속 뗀다. 못 뗀 키는 held에 남는다
            self.errors.append(exc)

    def _release_all(self) -> None:
        for key in reversed(self.held):
            self._release(key, None)

    def _is_held(self, key: InputKey) -> bool:
        with self._held_lock:
            return key in self._held

    def _record(self, kind: str, key: InputKey, step: str | None) -> None:
        if self._emit is None or self.journal_error is not None:
            # 기록이 망가진 뒤에는 떼기만 하고 기록하지 않는다 (기록상 눌렸을 수 있음으로 남는다)
            return
        event: dict[str, Any] = {"event": kind, **key.to_event()}
        if step is not None:
            event["step"] = step
        try:
            self._emit(event)
        except BaseException as exc:
            self.journal_error = exc
            self._close(Cancelled("입력 기록 쓰기가 실패해 입력을 막았다"))
            raise


def _cancel(requests: list[_Request], reason: BaseException) -> None:
    for request in requests:
        request.finish(reason)


def _point(at: Point | Rect | Match) -> Point:
    if isinstance(at, Point):
        return at
    if isinstance(at, Rect):
        return at.center
    return at.rect.center
