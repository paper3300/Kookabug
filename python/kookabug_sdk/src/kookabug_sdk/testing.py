"""게임 없이 노드를 테스트하는 가짜 ctx.

    ctx = fake_context(frames=["tests/fixtures/title.png"])
    result = wait_image(ctx, target=load_target("tests/fixtures/start_button.target.json"))
    assert result.exit == "found"

- 캡처는 `frames`를 순서대로 준다. 다 쓰면 마지막 프레임을 계속 준다 (화면이 그대로인 것처럼)
- 입력은 실행하지 않고 `ctx.input.calls`에 남긴다
- 시간은 `FakeClock`. `ctx.sleep`은 시계만 넘긴다
- `pure=True`면 실행기와 같은 `PureContext`로 감싼다
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, overload

from kookabug_sdk.context import Cancelled, Deadline
from kookabug_sdk.pure import PureContext
from kookabug_sdk.types import Image, Match, Point, Rect, Secret, Target, WindowRef

__all__ = [
    "FakeArtifacts",
    "FakeClock",
    "FakeContext",
    "FakeInput",
    "FakeLog",
    "FakeVars",
    "InputCall",
    "fake_context",
    "load_target",
]


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
    """입력을 실행하지 않고 기록한다."""

    def __init__(self) -> None:
        self.calls: list[InputCall] = []

    def click(self, at: Point | Rect | Match, *, button: str = "left") -> None:
        self.calls.append(InputCall("click", (at,), {"button": button}))

    def key(self, key: str) -> None:
        self.calls.append(InputCall("key", (key,)))

    def type_text(self, text: str | Secret) -> None:
        self.calls.append(InputCall("type_text", (text,)))


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
    ) -> None:
        self.frames = [_frame(f, i) for i, f in enumerate(frames)]
        self.captured = 0
        self._config = dict(config or {})
        self._window = window
        self._vars = FakeVars(vars)
        self._log = FakeLog()
        self._artifacts = FakeArtifacts()
        self._input = FakeInput()
        self.settings = dict(settings or {})
        self.workspace = Path(workspace)
        self.clock = clock or FakeClock()
        self.cancelled = False

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

    def capture(self, region: Rect | None = None) -> Image:
        if not self.frames:
            raise RuntimeError("fake_context에 frames가 없다")
        frame = self.frames[min(self.captured, len(self.frames) - 1)]
        self.captured += 1
        return frame

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
    )
    return PureContext(ctx) if pure else ctx


def load_target(path: str | Path) -> Target:
    """`*.target.json`을 읽는다. 이름은 파일 이름에서 `.target.json`을 뗀 것."""
    p = Path(path)
    spec = json.loads(p.read_text(encoding="utf-8"))
    name = p.name.removesuffix(".json").removesuffix(".target")
    return Target(name=name, path=p, spec=spec)
