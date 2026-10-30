"""게임 없이 노드를 테스트하는 가짜 ctx.

    ctx = fake_context(frames=["tests/fixtures/title.png"])
    result = wait_image(ctx, target=load_target("tests/fixtures/start_button.target.json"))
    assert result.exit == "found"

- 캡처는 `frames`를 순서대로 준다. 다 쓰면 마지막 프레임을 계속 준다 (화면이 그대로인 것처럼)
- 입력은 실행하지 않고 `ctx.input.calls`에 남긴다
- 시간은 `FakeClock`. `ctx.sleep`은 시계만 넘긴다
- `pure=True`면 실행기와 같은 `PureContext`로 감싼다
- `ctx.vision`·`ctx.ocr`은 `vision=`·`ocr=`로 넣은 엔진을 쓴다. 넣지 않으면 `kookabug_platform`이
  설치돼 있을 때 그 실제 엔진(`kookabug_platform.fake_engines`의 `vision()`·`ocr()`)을 처음 쓸 때
  만든다. 둘 다 없으면 `EngineUnavailable`. SDK는 `kookabug_platform`에 의존하지 않는다
- `scenario=`(장면 전이)를 주면 캡처는 그 장면의 지금 화면, 가짜 입력은 장면 전이, 프로세스
  띄우기는 장면의 띄우기 규칙을 따른다. `windows=`는 처음부터 떠 있는 가짜 창들
- `deadline`을 받는 관측 호출(캡처·`vision.find`·`ocr.read`·`process.find_window`)은 그 기한이
  이미 지났으면 엔진을 부르지 않고 `ObservationTimeout`
- `set_window`는 호출 프레임의 창을 바꾸고, 노드 안의 `ctx.window`는 그 노드 호출 동안 그대로다
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal, Protocol, overload

from kookabug_sdk.context import Cancelled, Deadline, OcrApi, VisionApi, Where
from kookabug_sdk.errors import ObservationTimeout
from kookabug_sdk.pure import PureContext
from kookabug_sdk.types import (
    Image,
    Match,
    OcrResult,
    ProcessRef,
    Rect,
    Secret,
    Target,
    WindowInfo,
    WindowRef,
)

__all__ = [
    "EngineUnavailable",
    "FakeArtifacts",
    "FakeClock",
    "FakeContext",
    "FakeInput",
    "FakeLog",
    "FakeProcess",
    "FakeVars",
    "FakeWindow",
    "FakeWindows",
    "InputCall",
    "Scenario",
    "fake_context",
    "load_target",
]

ENGINE_MODULE: Final = "kookabug_platform.fake_engines"
"""`vision()`·`ocr()` 엔진 팩토리를 주는 플랫폼 모듈 (없으면 엔진을 넣어야 한다)."""


class EngineUnavailable(RuntimeError):
    """가짜 ctx에 그 엔진(`vision`·`ocr`)이 없다."""


class FakeClock:
    """손으로 넘기는 시계 (ms)."""

    def __init__(self, start_ms: int = 0) -> None:
        self._now = start_ms

    def now_ms(self) -> int:
        return self._now

    def sleep(self, ms: int) -> None:
        self.advance(ms)

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("시간은 거꾸로 가지 않는다")
        self._now += ms


class FakeVars:
    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self.values: dict[str, Any] = dict(values or {})

    def get(self, name: str, default: Any = ...) -> Any:
        if name in self.values:
            return self.values[name]
        if default is ...:
            raise KeyError(f"변수 '{name}'이(가) 없다")
        return default

    def has(self, name: str) -> bool:
        return name in self.values

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value


class FakeLog:
    """로그를 (수준, 문자열)로 모은다. 비밀값은 `str()`이 가린 채로 남는다."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def debug(self, message: object) -> None:
        self.records.append(("debug", str(message)))

    def info(self, message: object) -> None:
        self.records.append(("info", str(message)))

    def warn(self, message: object) -> None:
        self.records.append(("warn", str(message)))

    def error(self, message: object) -> None:
        self.records.append(("error", str(message)))


class FakeArtifacts:
    """저장한 이미지를 이름으로 모은다. 기록 정책이 없으므로 늘 경로(이름)를 준다."""

    def __init__(self) -> None:
        self.saved: dict[str, Image] = {}

    def save(self, image: Image, name: str) -> str:
        self.saved[name] = image
        return name


@dataclass(frozen=True, slots=True)
class InputCall:
    method: str
    args: tuple[Any, ...]
    kwargs: Mapping[str, Any] = field(default_factory=dict)


class FakeInput:
    """입력을 실행하지 않고 기록한다. `on_call`이 있으면 기록한 뒤 부른다 (장면 전이)."""

    def __init__(self, on_call: Callable[[InputCall], None] | None = None) -> None:
        self.calls: list[InputCall] = []
        self._on_call = on_call

    def _record(self, call: InputCall) -> None:
        self.calls.append(call)
        if self._on_call is not None:
            self._on_call(call)

    def click(self, at: Where, *, button: str = "left", count: int = 1) -> None:
        self._record(InputCall("click", (at,), {"button": button, "count": count}))

    def drag(self, start: Where, end: Where, *, duration_ms: int = 0, button: str = "left") -> None:
        self._record(
            InputCall("drag", (start, end), {"duration_ms": duration_ms, "button": button})
        )

    def scroll(self, at: Where, amount: int) -> None:
        self._record(InputCall("scroll", (at, amount)))

    def key(self, key: str, *, hold_ms: int = 0) -> None:
        self._record(InputCall("key", (key,), {"hold_ms": hold_ms}))

    def type_text(self, text: str | Secret) -> None:
        self._record(InputCall("type_text", (text,)))


@dataclass(slots=True)
class FakeWindow:
    """가짜 창 하나. `ctx.windows.set_client_size`가 `client_size`를 바꾼다."""

    ref: WindowRef
    process_name: str = ""
    class_name: str = ""
    client_size: tuple[int, int] = (1280, 720)
    client_origin: tuple[int, int] = (0, 0)
    dpi: int = 96
    owned: bool = False
    """다른 창이 소유한 팝업 (`find(owned=True)`로만 찾는다)."""
    minimized: bool = False

    def info(self) -> WindowInfo:
        return WindowInfo(
            window=self.ref,
            title=self.ref.title,
            process_name=self.process_name,
            class_name=self.class_name,
            client_size=self.client_size,
            client_origin=self.client_origin,
            dpi=self.dpi,
            minimized=self.minimized,
        )


def _title_matches(pattern: str, title: str) -> bool:
    """`/정규식/`이면 정규식 검색, 아니면 대소문자 무시 부분 일치 (플랫폼 찾기와 같다)."""
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.search(pattern[1:-1], title) is not None
    return pattern.casefold() in title.casefold()


class FakeWindows:
    """가짜 창 목록 (앞이 Z 순서 앞). `activated`에 활성화한 창이 남는다."""

    def __init__(self, windows: Iterable[FakeWindow] = ()) -> None:
        self.windows: list[FakeWindow] = list(windows)
        self.activated: list[WindowRef] = []

    def get(self, window: WindowRef) -> FakeWindow:
        """HWND가 같은 창. `window.pid`가 있으면 PID도 같아야 한다 (같은 견본으로 띄운 창들)."""
        for fake in self.windows:
            if fake.ref.handle == window.handle and window.pid in (0, fake.ref.pid):
                return fake
        raise LookupError(f"가짜 창 {window.handle}이(가) 없다")

    def matching(
        self,
        title: str | None = None,
        process_name: str | None = None,
        *,
        owned: bool = False,
        pid: int | None = None,
    ) -> list[FakeWindow]:
        return [
            w
            for w in self.windows
            if (owned or not w.owned)
            and (pid is None or w.ref.pid == pid)
            and (process_name is None or w.process_name.casefold() == process_name.casefold())
            and (title is None or _title_matches(title, w.ref.title))
        ]

    def find(
        self, title: str | None = None, process_name: str | None = None, *, owned: bool = False
    ) -> WindowRef | None:
        found = self.matching(title, process_name, owned=owned)
        return found[0].ref if found else None

    def info(self, window: WindowRef) -> WindowInfo:
        return self.get(window).info()

    def set_client_size(self, window: WindowRef, width: int, height: int) -> bool:
        self.get(window).client_size = (width, height)
        return True

    def activate(self, window: WindowRef) -> None:
        self.activated.append(window)


class Scenario(Protocol):
    """`fake_context(scenario=)`의 장면 전이 (화면·입력·띄우기). 구현은 장면 표를 읽는 쪽이 준다.

    - `capture`: 지금 장면의 화면 (캡처마다 부른다 — 몇 프레임 뒤 전이 같은 셈은 구현이 한다)
    - `on_input`: 가짜 입력 하나 (`FakeInput`이 기록한 뒤 부른다)
    - `launch`: 그 실행 파일·인수로 뜨는 창들. 가짜 ctx가 새 PID를 붙여 창 목록에 넣는다
    """

    def capture(self, region: Rect | None) -> Image: ...
    def on_input(self, call: InputCall) -> None: ...
    def launch(self, path: str, args: Sequence[str]) -> Sequence[FakeWindow]: ...


class FakeProcess:
    """가짜 프로세스. 띄우면 새 PID(4001부터, 처음부터 떠 있던 창의 PID와 이미 준 PID는 건너뜀)를
    주고 장면의 띄우기 규칙에 따라 창을 띄운다. 장면이 준 창은 복사해서 넣는다 (장면의 창 견본은
    바꾸지 않는다 — 같은 견본을 여러 번·여러 ctx에서 띄워도 서로 섞이지 않게)."""

    FIRST_PID: Final = 4001

    def __init__(
        self, windows: FakeWindows, clock: FakeClock, scenario: Scenario | None = None
    ) -> None:
        self._windows = windows
        self._clock = clock
        self._scenario = scenario
        self._taken = {w.ref.pid for w in windows.windows}
        self.launched: list[tuple[str, tuple[str, ...], str | None]] = []
        self.closed: list[ProcessRef] = []

    def _new_pid(self) -> int:
        pid = self.FIRST_PID
        while pid in self._taken:
            pid += 1
        self._taken.add(pid)
        return pid

    def launch(self, path: str, args: Sequence[str] = (), cwd: str | None = None) -> ProcessRef:
        pid = self._new_pid()
        self.launched.append((path, tuple(args), cwd))
        appeared = () if self._scenario is None else self._scenario.launch(path, args)
        for window in appeared:
            self._windows.windows.insert(0, replace(window, ref=replace(window.ref, pid=pid)))
        return ProcessRef(pid, Path(path).name)

    def close(self, process: ProcessRef, force_after_ms: int) -> bool:
        self.closed.append(process)
        self._windows.windows = [w for w in self._windows.windows if w.ref.pid != process.pid]
        return True

    def find_window(
        self, process: ProcessRef, title: str | None = None, *, deadline: Deadline | None = None
    ) -> WindowRef | None:
        _check_deadline(deadline)
        found = self._windows.matching(title, pid=process.pid)
        if found:
            return found[0].ref
        if deadline is None:
            return None
        # 가짜 화면은 기다려도 바뀌지 않는다: 기한까지 시계를 넘기고 끝낸다
        self._clock.advance(deadline.remaining_ms)
        raise ObservationTimeout(f"프로세스 {process.pid}의 창이 기한 안에 뜨지 않았다")


def _check_deadline(deadline: Deadline | None) -> None:
    if deadline is not None and deadline.passed:
        raise ObservationTimeout("노드 기한이 지나 관측을 시작하지 않았다")


class _CheckedVision:
    """넣은 비전 엔진 앞에서 노드 기한을 본다: 이미 지났으면 엔진을 부르지 않고
    `ObservationTimeout` (러너·워커와 같다. 노드의 timeout 처리가 엔진 구현에 달리지 않게)."""

    def __init__(self, engine: VisionApi) -> None:
        self.engine = engine

    def find(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        deadline: Deadline | None = None,
    ) -> Match | None:
        _check_deadline(deadline)
        return self.engine.find(image, target, region=region, deadline=deadline)

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        return self.engine.diff(a, b, region=region)


class _CheckedOcr:
    """`_CheckedVision`과 같은 일을 OCR 엔진 앞에서."""

    def __init__(self, engine: OcrApi) -> None:
        self.engine = engine

    def read(
        self,
        image: Image,
        *,
        region: Rect | None = None,
        sensitive: bool = False,
        deadline: Deadline | None = None,
    ) -> OcrResult:
        _check_deadline(deadline)
        return self.engine.read(image, region=region, sensitive=sensitive, deadline=deadline)


def _platform_engine(kind: Literal["vision", "ocr"]) -> Any:
    try:
        module = importlib.import_module(ENGINE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in ("kookabug_platform", ENGINE_MODULE):
            raise  # 플랫폼 모듈 안의 다른 import 실패는 그대로 알린다
        module = None
    factory = getattr(module, kind, None)
    if factory is None:
        raise EngineUnavailable(
            f"fake_context에 ctx.{kind} 엔진이 없다. fake_context({kind}=...)로 넣거나 "
            f"kookabug-platform을 설치한다 ({ENGINE_MODULE}.{kind})"
        )
    return factory()


class FakeContext:
    def __init__(
        self,
        *,
        frames: Iterable[Image | str | Path] = (),
        config: Mapping[str, Any] | None = None,
        vars: Mapping[str, Any] | None = None,
        settings: Mapping[str, Any] | None = None,
        window: WindowRef | None = None,
        workspace: str | Path = ".",
        clock: FakeClock | None = None,
        vision: VisionApi | None = None,
        ocr: OcrApi | None = None,
        scenario: Scenario | None = None,
        windows: Iterable[FakeWindow] = (),
    ) -> None:
        self.frames = [_frame(f, i) for i, f in enumerate(frames)]
        self.captured = 0
        self._config = dict(config or {})
        self._window = window
        self._vars = FakeVars(vars)
        self._log = FakeLog()
        self._artifacts = FakeArtifacts()
        self.scenario = scenario
        self._input = FakeInput(None if scenario is None else scenario.on_input)
        self.settings = dict(settings or {})
        self.workspace = Path(workspace)
        self.clock = clock or FakeClock()
        self.cancelled = False
        self._vision = None if vision is None else _CheckedVision(vision)
        self._ocr = None if ocr is None else _CheckedOcr(ocr)
        self._windows = FakeWindows(windows)
        self._process = FakeProcess(self._windows, self.clock, scenario)

    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    @property
    def window(self) -> WindowRef | None:
        return self._window

    @property
    def vars(self) -> FakeVars:
        return self._vars

    @property
    def log(self) -> FakeLog:
        return self._log

    @property
    def artifacts(self) -> FakeArtifacts:
        return self._artifacts

    @property
    def input(self) -> FakeInput:
        return self._input

    @property
    def vision(self) -> VisionApi:
        """넣은(또는 플랫폼) 엔진을 기한 확인으로 감싼 것. 엔진 자체는 `.engine`."""
        if self._vision is None:
            self._vision = _CheckedVision(_platform_engine("vision"))
        return self._vision

    @property
    def ocr(self) -> OcrApi:
        if self._ocr is None:
            self._ocr = _CheckedOcr(_platform_engine("ocr"))
        return self._ocr

    @property
    def windows(self) -> FakeWindows:
        return self._windows

    @property
    def process(self) -> FakeProcess:
        return self._process

    def capture(self, region: Rect | None = None, *, deadline: Deadline | None = None) -> Image:
        _check_deadline(deadline)
        if self.scenario is not None:
            self.captured += 1
            return self.scenario.capture(region)
        if not self.frames:
            raise RuntimeError("fake_context에 frames가 없다")
        frame = self.frames[min(self.captured, len(self.frames) - 1)]
        self.captured += 1
        return frame

    def set_window(self, window: WindowRef) -> None:
        """호출 프레임의 현재 창을 바꾼다. 노드 안에서 부르면 그 노드의 `ctx.window`(감쌀 때의
        창)는 그대로고, 다음 노드 호출부터 이 창이다."""
        self._window = window

    def deadline(self, ms: int) -> Deadline:
        return Deadline(self.clock, self.clock.now_ms() + ms)

    def sleep(self, ms: int) -> None:
        self.clock.sleep(ms)

    def cancel(self) -> None:
        self.cancelled = True

    def check_cancel(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def setting(self, key: str) -> Any:
        if key not in self.settings:
            raise KeyError(f"설정 '{key}'이(가) 없다")
        return self.settings[key]

    def path(self, rel: str) -> Path:
        return self.workspace / rel


def _frame(value: Image | str | Path, index: int) -> Image:
    if isinstance(value, Image):
        return value
    return Image(path=Path(value), frame=index)


@overload
def fake_context(
    *,
    pure: Literal[False] = False,
    frames: Iterable[Image | str | Path] = (),
    config: Mapping[str, Any] | None = None,
    vars: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    window: WindowRef | None = None,
    workspace: str | Path = ".",
    clock: FakeClock | None = None,
    vision: VisionApi | None = None,
    ocr: OcrApi | None = None,
    scenario: Scenario | None = None,
    windows: Iterable[FakeWindow] = (),
) -> FakeContext: ...
@overload
def fake_context(
    *,
    pure: Literal[True],
    frames: Iterable[Image | str | Path] = (),
    config: Mapping[str, Any] | None = None,
    vars: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    window: WindowRef | None = None,
    workspace: str | Path = ".",
    clock: FakeClock | None = None,
    vision: VisionApi | None = None,
    ocr: OcrApi | None = None,
    scenario: Scenario | None = None,
    windows: Iterable[FakeWindow] = (),
) -> PureContext: ...
def fake_context(
    *,
    pure: bool = False,
    frames: Iterable[Image | str | Path] = (),
    config: Mapping[str, Any] | None = None,
    vars: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    window: WindowRef | None = None,
    workspace: str | Path = ".",
    clock: FakeClock | None = None,
    vision: VisionApi | None = None,
    ocr: OcrApi | None = None,
    scenario: Scenario | None = None,
    windows: Iterable[FakeWindow] = (),
) -> FakeContext | PureContext:
    """가짜 ctx. `pure=True`면 `PureContext`로 감싸고, 기록은 `.inner`(FakeContext)에서 본다."""
    ctx = FakeContext(
        frames=frames,
        config=config,
        vars=vars,
        settings=settings,
        window=window,
        workspace=workspace,
        clock=clock,
        vision=vision,
        ocr=ocr,
        scenario=scenario,
        windows=windows,
    )
    return PureContext(ctx) if pure else ctx


def load_target(path: str | Path) -> Target:
    """`*.target.json`을 읽는다. 이름은 파일 이름에서 `.target.json`을 뗀 것."""
    p = Path(path)
    spec = json.loads(p.read_text(encoding="utf-8"))
    name = p.name.removesuffix(".json").removesuffix(".target")
    return Target(name=name, path=p, spec=spec)
