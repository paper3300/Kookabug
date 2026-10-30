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

**M1 (2.4)**: 액터는 좌표로 대상 창 클라이언트 물리 픽셀 점(`ClientPoint`)만 받는다 — `Match`·
`Rect`·SDK `Point`를 점으로 줄이는 것(재검증 포함)은 공용 입력 서비스의 일이다. 요청마다 대상
창(`target`, 플랫폼의 바인딩)을 싣는다. 원시 동작은 `down`·`up`·`text`·`move`·`wheel`이고, `move`·
`wheel`은 누르기 기록 대상이 아니다. **입력 직전 확인**(`InputGuard`)은 액터 스레드에서
`down`·`text`·`move`·`wheel` 직전마다 돌고(대상 창·포그라운드·점 아래 창 등, 마우스면 화면 좌표를
돌려줌) `up`·`RELEASE_ALL`·복구에는 돌지 않는다. 확인 실패는 그 요청의 오류이고 그 요청이 새로 누른
키는 바로 뗀다(요청 단위 원자성). 앞 요청(`press`)이 쥐고 있던 키는 실패한 요청이 다시 눌렀어도
남긴다.
같은 키를 떼지 않고 다시 누르면 눌린 차례의 맨 뒤로 간다(떼기는 거꾸로) — 기록 읽기의
`held_inputs`와 같은 규칙이라 정상 마무리와 복구의 떼는 차례가 같다.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Literal, Protocol

from kookabug_core.inputs.backends import InputBackend, PlatformUnavailable
from kookabug_core.inputs.keys import canonical_button, canonical_key, split_combo
from kookabug_core.record.reader import InputKey
from kookabug_sdk import _faults
from kookabug_sdk.context import Cancelled
from kookabug_sdk.types import Point, Secret

__all__ = [
    "ACTOR_THREAD_NAME",
    "DRAG_INTERVAL_MS",
    "ClientPoint",
    "Emit",
    "GuardedOp",
    "InputActor",
    "InputGuard",
]

ACTOR_THREAD_NAME: Final = "kookabug-input-actor"
DRAG_INTERVAL_MS: Final = 16
"""드래그 중 보간 이동 사이 간격."""

# 저널 쓰기 (`Journal.emit`). None이면 이벤트를 남기지 않는다
type Emit = Callable[[Mapping[str, Any]], object]

type _State = Literal["new", "running", "stopped"]

_NOT_HELD: Final = object()
type GuardedOp = Literal["down", "text", "move", "wheel"]


@dataclass(frozen=True, slots=True)
class ClientPoint:
    """대상 창 클라이언트 영역의 물리 픽셀 점 (좌표의 단일 기준, M1 2.2)."""

    x: int
    y: int


class InputGuard(Protocol):
    """입력 직전 확인. 액터 스레드가 `down`·`text`·`move`·`wheel` 직전마다 부른다.

    `at`이 None이면 키보드·글자, 있으면 마우스다. 통과하면 마우스는 그 점의 화면 좌표를,
    키보드·글자는 None을 돌려준다. 통과하지 못하면 그 사유의 오류를 던진다.
    """

    def check(
        self, op: GuardedOp, target: object | None, at: ClientPoint | None
    ) -> Point | None: ...


class _Marker(Enum):
    RELEASE_ALL = "release_all"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class _Primitive:
    op: Literal["down", "up", "text", "move", "wheel"]
    key: InputKey | None = None
    at: ClientPoint | None = None
    text: str | Secret | None = None
    amount: int = 0
    wait_ms: float = 0
    """이 동작 전에 기다리는 시간 (드래그 보간). 게이트가 닫히면 바로 깬다."""


@dataclass(slots=True)
class _Request:
    primitives: list[_Primitive]
    step: str | None
    target: object | None = None
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None

    def finish(self, error: BaseException | None = None) -> None:
        self.error = error
        self.done.set()


type _Item = _Request | _Marker


class InputActor:
    """입력 요청 큐와 그것을 처리하는 스레드 하나.

    `gate`를 주면 그 이벤트를 게이트로 쓴다 (훅 래퍼의 `block` 훅과 같은 게이트를 나눈다).
    `guard`가 없으면 확인 없이 클라이언트 좌표를 그대로 화면 좌표로 넘긴다(가짜·없음 플랫폼).
    """

    def __init__(
        self,
        backend: InputBackend,
        *,
        emit: Emit | None = None,
        gate: threading.Event | None = None,
        guard: InputGuard | None = None,
    ) -> None:
        self.backend = backend
        self.guard = guard
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
        self,
        at: ClientPoint,
        *,
        button: str = "left",
        count: int = 1,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        """`move` → (`down` → `up`)을 `count`번. 이중 클릭은 `count=2`."""
        point = _client(at)
        if count < 1:
            raise ValueError(f"클릭 횟수는 1 이상이다: {count}")
        key = _button(button)
        presses = [_Primitive("down", key, at=point), _Primitive("up", key)] * count
        self._submit([_Primitive("move", at=point), *presses], step, target)

    def drag(
        self,
        start: ClientPoint,
        end: ClientPoint,
        *,
        button: str = "left",
        duration_ms: int = 0,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        """`move(start)` → `down` → `DRAG_INTERVAL_MS` 간격 보간 `move`(각각 확인) → `up`."""
        a, b = _client(start), _client(end)
        key = _button(button)
        steps = max(1, math.ceil(max(0, duration_ms) / DRAG_INTERVAL_MS))
        wait = max(0, duration_ms) / steps
        moves = [
            _Primitive(
                "move",
                at=ClientPoint(
                    round(a.x + (b.x - a.x) * i / steps), round(a.y + (b.y - a.y) * i / steps)
                ),
                wait_ms=wait,
            )
            for i in range(1, steps + 1)
        ]
        primitives = [_Primitive("move", at=a), _Primitive("down", key, at=a), *moves]
        self._submit([*primitives, _Primitive("up", key)], step, target)

    def scroll(
        self,
        at: ClientPoint,
        amount: int,
        *,
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        """`move` → 휠 `amount` 칸 (양수 = 위·앞으로)."""
        point = _client(at)
        if not amount:
            raise ValueError("휠 칸 수가 0이다")
        wheel = _Primitive("wheel", at=point, amount=amount)
        self._submit([_Primitive("move", at=point), wheel], step, target)

    def key(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        """키 하나 또는 조합(`ctrl+a`)을 누르고 뗀다. 조합은 차례로 누르고 거꾸로 뗀다."""
        keys = _keys(key)
        downs = [_Primitive("down", k) for k in keys]
        ups = [_Primitive("up", k) for k in reversed(keys)]
        self._submit(downs + ups, step, target)

    def press(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        """키(조합)를 눌러 둔다 — 누르고 있기의 앞 요청. 떼기는 `release` 또는 `RELEASE_ALL`."""
        self._submit([_Primitive("down", k) for k in _keys(key)], step, target)

    def release(self, key: str, *, target: object | None = None, step: str | None = None) -> None:
        """`press`로 누른 키(조합)를 거꾸로 뗀다 — 누르고 있기의 뒤 요청 (확인 없음)."""
        self._submit([_Primitive("up", k) for k in reversed(_keys(key))], step, target)

    def press_button(
        self,
        at: ClientPoint,
        *,
        button: str = "left",
        target: object | None = None,
        step: str | None = None,
    ) -> None:
        """`move` → 마우스 버튼 `down` (뗄 때까지 눌러 둔다)."""
        point = _client(at)
        key = _button(button)
        self._submit(
            [_Primitive("move", at=point), _Primitive("down", key, at=point)], step, target
        )

    def release_button(
        self, button: str = "left", *, target: object | None = None, step: str | None = None
    ) -> None:
        self._submit([_Primitive("up", _button(button))], step, target)

    def type_text(
        self, text: str | Secret, *, target: object | None = None, step: str | None = None
    ) -> None:
        """글자(코드 포인트)마다 원시 동작 하나 — 입력 직전 확인이 글자마다 돈다. 보내는 도중
        포커스를 잃으면 남은 글자는 다른 창에 가지 않고 그 요청이 오류로 끝난다."""
        secret = isinstance(text, Secret)
        raw = text.reveal() if isinstance(text, Secret) else text
        chars = [Secret(ch) if secret else ch for ch in raw]
        self._submit([_Primitive("text", text=ch) for ch in chars], step, target)

    def _submit(
        self, primitives: list[_Primitive], step: str | None, target: object | None
    ) -> None:
        if not self.backend.available:
            raise PlatformUnavailable
        request = _Request(primitives, step, target)
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
                if primitive.wait_ms and self.gate.wait(primitive.wait_ms / 1000):
                    raise Cancelled("입력이 막혔다 (실행 취소·마무리 중)")
                self._do(primitive, request, pressed)
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

    def _do(self, primitive: _Primitive, request: _Request, pressed: list[InputKey]) -> None:
        step = request.step
        match primitive.op:
            case "down":
                key = primitive.key
                assert key is not None
                screen = self._check("down", request, primitive.at)
                self._record("input.down", key, step)
                try:
                    _faults.fault_point("actor.before_backend", event="down")
                    if key.device == "keyboard":
                        self.backend.down(key.name)
                    else:
                        self.backend.mouse_down(key.name, screen)
                finally:
                    # 기록은 이미 "눌렸을 수 있음"이다: 백엔드가 실패해도 떼기 대상에 넣는다.
                    # 다시 누른 키는 맨 뒤로 옮긴다 — 기록 읽기(`held_inputs`)의 차례와 같게
                    with self._held_lock:
                        before = self._held.pop(key, _NOT_HELD)
                        self._held[key] = None
                    # 실패 정리는 이 요청이 새로 누른 키만 뗀다. 앞 요청(누르고 있기)이 이미
                    # 쥐고 있던 키는 그 요청의 것이다. 이 요청이 누른 키를 다시 누르면 정리
                    # 목록에서도 맨 뒤로 — 실패 정리·정상 마무리·기록 복구가 같은 차례로 뗀다
                    if key in pressed:
                        pressed.remove(key)
                        pressed.append(key)
                    elif before is _NOT_HELD:
                        pressed.append(key)
            case "up":
                key = primitive.key
                assert key is not None
                self._up(key, step)
            case "text":
                value = primitive.text
                assert value is not None
                self._check("text", request, None)
                _faults.fault_point("actor.before_backend", event="text")
                self.backend.text(value.reveal() if isinstance(value, Secret) else value)
            case "move":
                screen = self._check("move", request, primitive.at)
                assert screen is not None
                self.backend.move(screen)
            case "wheel":
                screen = self._check("wheel", request, primitive.at)
                self.backend.wheel(primitive.amount, screen)

    def _check(self, op: GuardedOp, request: _Request, at: ClientPoint | None) -> Point | None:
        """입력 직전 확인 (이 스레드). 확인이 없으면 클라이언트 좌표를 그대로 넘긴다."""
        if self.guard is not None:
            return self.guard.check(op, request.target, at)
        return None if at is None else Point(at.x, at.y)

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


def _client(at: object) -> ClientPoint:
    if not isinstance(at, ClientPoint):
        # Match·Rect·SDK Point는 공용 입력 서비스가 재검증한 뒤 클라이언트 점으로 바꿔 넣는다
        raise TypeError(f"입력 액터는 ClientPoint만 받는다 ({type(at).__name__})")
    return at


def _button(button: str) -> InputKey:
    return InputKey("mouse", canonical_button(button))


def _keys(combo: str) -> list[InputKey]:
    return [InputKey("keyboard", canonical_key(n)) for n in split_combo(combo)]
