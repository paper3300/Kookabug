"""공용 입력 서비스: 모든 입력 요청이 지나는 한 곳 (구현 계획 M1 2.4, 계획 검수 4).

코어 노드의 `ctx.input.*`, 워커 노드의 `ctx.input.*` RPC(`CtxServer`), `image.click`·
`ocr.click_text` 안의 입력이 모두 스텝 ctx의 `input` → 이 서비스 → 입력 싱크(액터 큐 또는 가짜
장면)로 간다. 액터는 클라이언트 물리 픽셀 점(`ClientPoint`)만 받는다 — `Match`·`Rect`·`Point`를
점으로 줄이는 곳은 여기 하나다.

- **요청의 대상 창은 불변 값**: 스텝 ctx가 만들 때 정한 그 스텝의 창(`in.window`, 없으면 그 스텝
  시작 때의 호출 프레임 현재 창)을 요청마다 바인딩으로 바꿔 싣는다. 뒤에 `set_window`나 다른
  스텝이 창을 바꿔도 이미 만든 요청의 창은 그대로다
- **`Match` 재검증** (점으로 줄이기 전에):
  1. `Match.window`가 있으면 그것과 요청 창을 플랫폼이 이 실행의 바인딩으로 확정해(`identify`)
     비교한다. 관측한 창이 닫혔으면 `window_gone`, 다른 창(같은 HWND에 새로 뜬 창 포함)이면
     `window_mismatch`(다른 창의 관측 좌표로 입력하지 않는다)
  2. `Match.frame_info`의 클라이언트 크기·DPI·캡처 방식이 지금 창과 다르면 `Match.target`으로 새
     캡처에서 한 번 다시 찾고 그 클릭 지점으로 입력한다(원래 출력은 그대로, `log` 이벤트에 남김)
  3. 다시 찾지 못했거나 `target`이 없으면 `StaleObservation` — 처리되지 않은 fail
     (`stale_observation`, 출구 없음)
  4. 클릭 지점은 `Match.click_point`. `Rect`는 중심, `Point`는 그대로(출처가 없어 재검증 없음).
     창이 움직이기만 한 것은 다시 찾지 않는다(좌표가 클라이언트 기준이다)
- 대상 창이 없는 요청(창을 정하지 않은 가짜·없음 플랫폼)은 창 확인 없이 싱크로 간다. Windows
  싱크는 입력 직전 확인에서 "대상 창이 정해지지 않았다"로 거부한다
- **누르고 있기** `key(hold_ms>0)` = 누르기 요청 → 취소로 깨는 기다림 → 떼기 요청. 기다리다 취소되면
  떼기 요청도 막히므로 키는 액터의 `RELEASE_ALL`이 뗀다(게이트). 이 기다림은 런타임 `wait_hold`라
  멈춤 요청을 보지 않는다 — 키를 누른 채 멈추지 않고, 그 사이 온 일시정지는 떼기 뒤 다음 확인
  지점에서 확정된다 (M3 2.2)
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Final, Protocol

from kookabug_core.engine.errors import EngineError
from kookabug_core.inputs.actor import ClientPoint
from kookabug_sdk.context import Cancelled, Where
from kookabug_sdk.errors import StaleObservation
from kookabug_sdk.types import FrameRef, Match, Point, Rect, Secret, WindowRef

__all__ = [
    "WINDOW_MISMATCH",
    "InputService",
    "InputSink",
    "Observer",
    "ServiceInput",
    "WindowState",
    "WindowTargets",
    "same_window",
]

WINDOW_MISMATCH: Final = "window_mismatch"


class InputSink(Protocol):
    """입력을 실제로 넣는 곳 (`InputActor`와 같은 모양). `target`은 플랫폼의 창 바인딩."""

    def click(
        self,
        at: ClientPoint,
        *,
        button: str = "left",
        count: int = 1,
        target: object | None = None,
        step: str | None = None,
    ) -> None: ...
    def drag(
        self,
        start: ClientPoint,
        end: ClientPoint,
        *,
        button: str = "left",
        duration_ms: int = 0,
        target: object | None = None,
        step: str | None = None,
    ) -> None: ...
    def scroll(
        self,
        at: ClientPoint,
        amount: int,
        *,
        target: object | None = None,
        step: str | None = None,
    ) -> None: ...
    def key(self, key: str, *, target: object | None = None, step: str | None = None) -> None: ...
    def press(self, key: str, *, target: object | None = None, step: str | None = None) -> None: ...
    def release(
        self, key: str, *, target: object | None = None, step: str | None = None
    ) -> None: ...
    def type_text(
        self, text: str | Secret, *, target: object | None = None, step: str | None = None
    ) -> None: ...


class WindowState(Protocol):
    """지금 창의 관측 조건 (재검증 비교용)."""

    @property
    def backend(self) -> str: ...
    @property
    def client_size(self) -> tuple[int, int]: ...
    @property
    def dpi(self) -> int: ...


class WindowTargets(Protocol):
    """플랫폼의 창: SDK 창 참조 → 싱크에 싣는 바인딩, 지금 관측 조건."""

    def bind(self, window: WindowRef) -> object:
        """그 창의 바인딩 (닫혔으면 `window_gone`)."""
        ...

    def identify(self, window: WindowRef) -> WindowRef:
        """그 참조가 가리키는 이 실행의 창을 완전한 참조(HWND·PID·생성 시각·바인딩)로. 부분 참조도
        바인딩을 확정한 값이다. 참조의 창(바인딩)이 닫혔으면 `window_gone`."""
        ...

    def state(self, window: WindowRef) -> WindowState:
        """지금 그 창의 캡처 방식·클라이언트 크기·DPI."""
        ...


class Observer(Protocol):
    """요청을 만든 스텝의 관측: 다시 찾기와 기록 (스텝 ctx가 준다)."""

    def rematch(self, match: Match) -> Match | None:
        """`match.target`을 그 스텝의 창 새 캡처에서 다시 찾는다."""
        ...

    def note(self, message: str) -> None:
        """그 스텝의 `log` 이벤트로 남긴다."""
        ...


def same_window(a: WindowRef, b: WindowRef) -> bool:
    """같은 창인가: HWND가 같고, 둘 다 가진 PID·생성 시각·바인딩이 같다."""
    if a.handle != b.handle:
        return False
    pairs = ((a.pid, b.pid), (a.process_created, b.process_created), (a.binding, b.binding))
    return all(not x or not y or x == y for x, y in pairs)


class InputService:
    """한 실행의 공용 입력 서비스. `windows`가 없으면 창 확인·재검증을 하지 않는다(창 없는 가짜)."""

    def __init__(
        self,
        sink: InputSink,
        windows: WindowTargets | None = None,
        *,
        sleep: Callable[[int], None] | None = None,
    ) -> None:
        self.sink = sink
        self.windows = windows
        self._sleep = sleep

    def for_step(
        self,
        step: str,
        window: WindowRef | None,
        observer: Observer,
        *,
        sleep: Callable[[int], None] | None = None,
    ) -> ServiceInput:
        """그 스텝의 `ctx.input`. `window`는 그 스텝의 대상 창(불변), `sleep`은 누르고 있기의
        기다림(취소로만 깨고 멈춤 요청은 보지 않는 것 — 런타임 `wait_hold`)."""
        wait = sleep or self._sleep
        if wait is None:
            raise ValueError("누르고 있기에 쓸 기다림(sleep)이 없다")
        return ServiceInput(self, step, window, observer, wait)

    # ------------------------------------------------------------ 위치

    def target_of(self, window: WindowRef | None) -> object | None:
        if window is None or self.windows is None:
            return None
        return self.windows.bind(window)

    def point(self, at: Where, window: WindowRef | None, observer: Observer) -> ClientPoint:
        """입력 위치 → 클라이언트 점. `Match`는 재검증한다 (모듈 설명)."""
        if isinstance(at, Point):
            return ClientPoint(at.x, at.y)
        if isinstance(at, Rect):
            center = at.center
            return ClientPoint(center.x, center.y)
        point = self._revalidated(at, window, observer).click_point
        return ClientPoint(point.x, point.y)

    def _revalidated(self, match: Match, window: WindowRef | None, observer: Observer) -> Match:
        if window is None or self.windows is None:
            return match
        if match.window is not None:
            # 두 참조를 모두 이 실행의 바인딩으로 확정해 비교한다 (빈 필드를 와일드카드로 두지
            # 않는다): 관측한 창이 닫혔으면 window_gone, 같은 HWND의 다른 창이면 window_mismatch
            request = self.windows.identify(window)
            observed = self.windows.identify(match.window)
            if not same_window(observed, request):
                raise EngineError(
                    WINDOW_MISMATCH,
                    f"찾은 창(hwnd {observed.handle:#x} {observed.title!r}, {observed.binding})과 "
                    f"입력할 창(hwnd {request.handle:#x} {request.title!r}, {request.binding})이 "
                    "다르다 — in.window로 맞추거나 그 창으로 대상 창을 바꾼다",
                )
        seen = match.frame_info
        if seen is None:
            return match
        now = self.windows.state(window)
        if _same_view(seen, now):
            return match
        change = (
            f"찾은 뒤 창이 바뀌었다 (크기 {seen.client_size} → {now.client_size}, "
            f"DPI {seen.dpi} → {now.dpi}, 캡처 {seen.backend} → {now.backend})"
        )
        if match.target is None:
            raise StaleObservation(f"{change}. 다시 찾을 target이 없어 입력하지 않았다")
        found = observer.rematch(match)
        if found is None:
            raise StaleObservation(f"{change}. target '{match.target}'을(를) 다시 찾지 못했다")
        observer.note(
            f"{change}: target '{match.target}'을(를) 다시 찾아 {found.click_point}에 입력한다 "
            f"(원래 {match.click_point})"
        )
        return found


def _same_view(seen: FrameRef, now: WindowState) -> bool:
    return (
        tuple(seen.client_size) == tuple(now.client_size)
        and seen.dpi == now.dpi
        and seen.backend == now.backend
    )


class ServiceInput:
    """스텝 하나의 `ctx.input` (SDK `InputApi`). 대상 창은 만들 때 정해진다."""

    def __init__(
        self,
        service: InputService,
        step: str,
        window: WindowRef | None,
        observer: Observer,
        sleep: Callable[[int], None],
    ) -> None:
        self._service = service
        self._step = step
        self.window = window
        self._observer = observer
        self._sleep = sleep

    def _target(self) -> object | None:
        return self._service.target_of(self.window)

    def _point(self, at: Where) -> ClientPoint:
        return self._service.point(at, self.window, self._observer)

    def click(self, at: Where, *, button: str = "left", count: int = 1) -> None:
        point = self._point(at)
        self._service.sink.click(
            point, button=button, count=count, target=self._target(), step=self._step
        )

    def drag(self, start: Where, end: Where, *, duration_ms: int = 0, button: str = "left") -> None:
        a, b = self._point(start), self._point(end)
        self._service.sink.drag(
            a, b, button=button, duration_ms=duration_ms, target=self._target(), step=self._step
        )

    def scroll(self, at: Where, amount: int) -> None:
        point = self._point(at)
        self._service.sink.scroll(point, amount, target=self._target(), step=self._step)

    def key(self, key: str, *, hold_ms: int = 0) -> None:
        if hold_ms < 0:
            raise ValueError(f"누르고 있는 시간은 0 이상이다: {hold_ms}")
        target = self._target()
        if not hold_ms:
            self._service.sink.key(key, target=target, step=self._step)
            return
        self._service.sink.press(key, target=target, step=self._step)
        try:
            self._sleep(hold_ms)
        finally:
            # 취소로 깼으면 게이트가 닫혀 이 요청은 막히고, 키는 액터의 RELEASE_ALL이 뗀다
            with contextlib.suppress(Cancelled):
                self._service.sink.release(key, target=target, step=self._step)

    def type_text(self, text: str | Secret) -> None:
        self._service.sink.type_text(text, target=self._target(), step=self._step)
