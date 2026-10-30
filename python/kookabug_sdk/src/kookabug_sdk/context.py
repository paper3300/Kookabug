"""노드가 외부와 만나는 `ctx`.

노드는 `Context` 프로토콜로만 창·캡처·입력·기록·시간·변수를 다룬다. 실행기(core)와
`kookabug_sdk.testing.fake_context`가 구현을 준다. 제한(선언 안 한 효과, 순수 노드)은
`GuardedContext` 래퍼로 걸고, 실행기와 가짜 ctx가 같은 래퍼를 쓴다.

효과와 ctx 기능 (구현 계획 M1 2.8)

| 효과 | 기능 |
|---|---|
| `capture` | `ctx.capture`, `ctx.vision.*`, `ctx.ocr.*` |
| `input` | `ctx.input.*` |
| `process` | `ctx.process.*`, `ctx.windows.set_client_size`·`activate` |
| (없음) | `ctx.windows.find`·`info`, `ctx.set_window` |

관측 호출(`capture`·`vision.find`·`ocr.read`·`process.find_window`)은 `deadline`을 받는다. 노드가
넘긴 기한 안에 끝나지 않으면 `ObservationTimeout`(노드의 `timeout` 출구)이고, 남은 시간이 0이면
관측을 시작하지 않는다. 설정 기한(`run.capture_timeout_ms`)과 전체 기한은 실행기가 따로 건다.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, NoReturn, Protocol, cast

from kookabug_sdk.types import (
    Image,
    Match,
    OcrResult,
    Point,
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = [
    "EFFECTS",
    "ArtifactsApi",
    "BlockedApi",
    "Cancelled",
    "Clock",
    "Context",
    "ContextViolation",
    "Deadline",
    "Effect",
    "EffectContext",
    "EffectNotDeclared",
    "GuardedContext",
    "InputApi",
    "LogApi",
    "OcrApi",
    "ProcessApi",
    "VarsApi",
    "VisionApi",
    "Where",
    "WindowsApi",
]

type Effect = Literal["capture", "input", "process"]
EFFECTS: Final[frozenset[str]] = frozenset({"capture", "input", "process"})


class Cancelled(BaseException):
    """실행 취소. `except Exception`에 잡히지 않도록 BaseException이다."""


class ContextViolation(RuntimeError):
    """노드가 쓸 수 없는 ctx 기능을 불렀다. 실행기는 `error`로 본다."""


class EffectNotDeclared(ContextViolation):
    """`@node(effects=...)`에 선언하지 않은 효과를 ctx로 썼다."""


class Clock(Protocol):
    def now_ms(self) -> int: ...
    def sleep(self, ms: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Deadline:
    clock: Clock
    end_ms: int

    @property
    def passed(self) -> bool:
        return self.clock.now_ms() >= self.end_ms

    @property
    def remaining_ms(self) -> int:
        return max(0, self.end_ms - self.clock.now_ms())


class VarsApi(Protocol):
    """호출 프레임 변수. 없는 이름을 기본값 없이 읽으면 KeyError."""

    def get(self, name: str, default: Any = ...) -> Any: ...
    def has(self, name: str) -> bool: ...
    def set(self, name: str, value: Any) -> None: ...


class LogApi(Protocol):
    def debug(self, message: object) -> None: ...
    def info(self, message: object) -> None: ...
    def warn(self, message: object) -> None: ...
    def error(self, message: object) -> None: ...


class ArtifactsApi(Protocol):
    def save(self, image: Image, name: str) -> str | None:
        """저장하고 실행 폴더 기준 경로를 준다. 기록 정책(구간 끄기·비밀값 입력)으로 남기지 않으면
        None (실행 기록에는 생략 이유가 남는다)."""
        ...


type Where = Point | Rect | Match
"""입력 위치. `Match`는 클릭 지점(`Match.click_point`), `Rect`는 중심, `Point`는 그대로."""


class InputApi(Protocol):
    """입력. 요청마다 그 스텝의 대상 창(`in.window` 또는 현재 대상 창)으로 간다. 입력 직전에 창
    유효성·포그라운드·가림을 확인하고, `Match`는 그 관측 뒤 창 크기·DPI가 바뀌었으면 다시 찾는다
    (못 찾으면 `StaleObservation`)."""

    def click(self, at: Where, *, button: str = "left", count: int = 1) -> None: ...
    def drag(
        self, start: Where, end: Where, *, duration_ms: int = 0, button: str = "left"
    ) -> None: ...
    def scroll(self, at: Where, amount: int) -> None:
        """휠 `amount` 칸 (양수 = 위)."""
        ...

    def key(self, key: str, *, hold_ms: int = 0) -> None:
        """키 하나나 조합(`ctrl+a`). `hold_ms`만큼 누르고 있다가 뗀다(기다리다 취소되면 뗀다)."""
        ...

    def type_text(self, text: str | Secret) -> None: ...


class VisionApi(Protocol):
    """이미지 찾기·비교. 픽셀은 러너가 가진다 (참조 이미지면 프레임 저장소)."""

    def find(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        deadline: Deadline | None = None,
    ) -> Match | None:
        """`target`을 찾는다. `region`(클라이언트 좌표)을 주면 target의 검색 범위 대신 그 안에서."""
        ...

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        """두 프레임의 채널 평균 절대 차이 / 255 (0 = 같음, 1 = 완전히 다름). 크기가 다르면 1.

        `region`(클라이언트 좌표)을 주면 두 프레임의 같은 클라이언트 영역끼리 비교한다 (영역 캡처는
        자기 원점 기준으로 옮긴다, 둘 다 덮는 부분만)."""
        ...


class OcrApi(Protocol):
    def read(
        self,
        image: Image,
        *,
        region: Rect | None = None,
        sensitive: bool = False,
        deadline: Deadline | None = None,
    ) -> OcrResult:
        """글자를 읽는다. `sensitive=True`(비밀 target 영역)면 글자가 `Secret`으로 온다."""
        ...


class WindowsApi(Protocol):
    def find(
        self, title: str | None = None, process_name: str | None = None, *, owned: bool = False
    ) -> WindowRef | None:
        """보이는 최상위 창을 찾는다. `title`은 부분 일치(대소문자 무시) 또는 `/정규식/`. 기본은
        소유자 없는 창만, `owned=True`면 소유 팝업도. 여러 개면 Z 순서 앞."""
        ...

    def info(self, window: WindowRef) -> WindowInfo: ...
    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        """클라이언트 영역을 그 크기로 맞춘다. 다시 읽어 다르면 False."""
        ...

    def activate(self, window: WindowRef) -> None:
        """앞으로 가져온다 (최선 노력, 실패해도 예외 없음)."""
        ...


class ProcessApi(Protocol):
    def launch(self, path: str, args: Sequence[str] = (), cwd: str | None = None) -> ProcessRef: ...
    def close(self, process: ProcessRef, force_after_ms: int) -> bool:
        """창에 닫기를 보내고 기다리다 `force_after_ms`가 지나면 강제로 끝낸다. 정상 종료면 True."""
        ...

    def find_window(
        self, process: ProcessRef, title: str | None = None, *, deadline: Deadline | None = None
    ) -> WindowRef | None:
        """그 프로세스(띄운 프로세스가 런처면 그 아래 프로세스까지)의 창. `deadline`이 있으면 뜰
        때까지 기다린다 (지나면 `ObservationTimeout`). 없으면 지금 있는 창만 본다."""
        ...


class Context(Protocol):
    @property
    def config(self) -> Mapping[str, Any]:
        """그래프 노드의 `config` 값."""
        ...

    @property
    def window(self) -> WindowRef | None:
        """현재 대상 창."""
        ...

    @property
    def vars(self) -> VarsApi: ...
    @property
    def log(self) -> LogApi: ...
    @property
    def artifacts(self) -> ArtifactsApi: ...
    @property
    def input(self) -> InputApi: ...
    @property
    def vision(self) -> VisionApi: ...
    @property
    def ocr(self) -> OcrApi: ...
    @property
    def windows(self) -> WindowsApi: ...
    @property
    def process(self) -> ProcessApi: ...
    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image: ...
    def set_window(self, window: WindowRef) -> None:
        """호출 프레임의 현재 대상 창을 다음 스텝부터 바꾼다. 서브그래프는 부른 쪽의 창을 이어받고,
        서브그래프 안에서 바꾼 것은 밖으로 나오지 않는다."""
        ...

    def deadline(self, ms: int) -> Deadline: ...
    def sleep(self, ms: int) -> None: ...
    def check_cancel(self) -> None: ...
    def setting(self, key: str) -> Any: ...
    def path(self, rel: str) -> Path: ...


class GuardedContext:
    """다른 ctx를 감싸 일부 기능을 막는 래퍼의 바탕. 막힌 호출은 `violations`에도 남긴다
    (노드 코드가 예외를 삼켜도 실행기가 `error`로 볼 수 있게).

    노드 호출 하나마다 감싸므로 `window`는 감쌀 때의 창이다: 노드가 `set_window`로 호출 프레임의
    창을 바꿔도 그 노드의 `ctx.window`는 그대로고, 다음 스텝부터 바뀐다 (러너·워커·가짜 ctx가 같다).
    """

    def __init__(self, inner: Context) -> None:
        self._inner = inner
        self._window = inner.window
        self.violations: list[ContextViolation] = []

    @property
    def inner(self) -> Context:
        return self._inner

    def _violate(self, exc: ContextViolation) -> NoReturn:
        self.violations.append(exc)
        raise exc

    @property
    def config(self) -> Mapping[str, Any]:
        return self._inner.config

    @property
    def window(self) -> WindowRef | None:
        return self._window

    @property
    def vars(self) -> VarsApi:
        return self._inner.vars

    @property
    def log(self) -> LogApi:
        return self._inner.log

    @property
    def artifacts(self) -> ArtifactsApi:
        return self._inner.artifacts

    @property
    def input(self) -> InputApi:
        return self._inner.input

    @property
    def vision(self) -> VisionApi:
        return self._inner.vision

    @property
    def ocr(self) -> OcrApi:
        return self._inner.ocr

    @property
    def windows(self) -> WindowsApi:
        return self._inner.windows

    @property
    def process(self) -> ProcessApi:
        return self._inner.process

    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image:
        return self._inner.capture(region, deadline=deadline)

    def set_window(self, window: WindowRef) -> None:
        self._inner.set_window(window)

    def deadline(self, ms: int) -> Deadline:
        return self._inner.deadline(ms)

    def sleep(self, ms: int) -> None:
        self._inner.sleep(ms)

    def check_cancel(self) -> None:
        self._inner.check_cancel()

    def setting(self, key: str) -> Any:
        return self._inner.setting(key)

    def path(self, rel: str) -> Path:
        return self._inner.path(rel)


class BlockedApi:
    """어떤 속성에 접근해도 막는 객체 (`ctx.input`, `ctx.log` 등의 대역)."""

    def __init__(self, guard: GuardedContext, make: Callable[[str], ContextViolation]) -> None:
        self._guard = guard
        self._make = make

    def __getattr__(self, name: str) -> NoReturn:
        if name.startswith("__"):
            raise AttributeError(name)
        self._guard._violate(self._make(name))


class _GuardedWindows:
    """`ctx.windows`: 찾기·정보는 효과 없이, 크기 맞춤·활성화는 `process` 효과로."""

    def __init__(self, guard: EffectContext) -> None:
        self._guard = guard

    def _inner(self, what: str | None = None) -> WindowsApi:
        if what is not None and "process" not in self._guard.effects:
            self._guard._violate(self._guard._missing("process", f"windows.{what}"))
        return self._guard.inner.windows

    def find(
        self, title: str | None = None, process_name: str | None = None, *, owned: bool = False
    ) -> WindowRef | None:
        return self._inner().find(title, process_name, owned=owned)

    def info(self, window: WindowRef) -> WindowInfo:
        return self._inner().info(window)

    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        return self._inner("set_client_size").set_client_size(window, width, height)

    def activate(self, window: WindowRef) -> None:
        self._inner("activate").activate(window)


class EffectContext(GuardedContext):
    """선언한 효과만 쓰게 한다 (효과별 기능은 모듈 설명의 표)."""

    def __init__(self, inner: Context, effects: Collection[str]) -> None:
        super().__init__(inner)
        self.effects = frozenset(effects)

    def _missing(self, effect: str, what: str) -> EffectNotDeclared:
        return EffectNotDeclared(
            f"ctx.{what}을(를) 쓰려면 @node(effects=...)에 '{effect}'을(를) 선언해야 한다"
        )

    def _blocked(self, effect: str, api: str) -> BlockedApi:
        return BlockedApi(self, lambda name: self._missing(effect, f"{api}.{name}"))

    @property
    def input(self) -> InputApi:
        if "input" not in self.effects:
            return cast(InputApi, self._blocked("input", "input"))
        return self._inner.input

    @property
    def vision(self) -> VisionApi:
        if "capture" not in self.effects:
            return cast(VisionApi, self._blocked("capture", "vision"))
        return self._inner.vision

    @property
    def ocr(self) -> OcrApi:
        if "capture" not in self.effects:
            return cast(OcrApi, self._blocked("capture", "ocr"))
        return self._inner.ocr

    @property
    def windows(self) -> WindowsApi:
        return _GuardedWindows(self)

    @property
    def process(self) -> ProcessApi:
        if "process" not in self.effects:
            return cast(ProcessApi, self._blocked("process", "process"))
        return self._inner.process

    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image:
        if "capture" not in self.effects:
            self._violate(self._missing("capture", "capture"))
        return self._inner.capture(region, deadline=deadline)
