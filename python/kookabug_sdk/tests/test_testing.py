"""가짜 ctx의 엔진 주입·장면 전이 (구현 계획 M1 2.8 `fake_context`)."""

from __future__ import annotations

import sys
import types
from collections.abc import Sequence
from typing import Any

import pytest

from kookabug_sdk import Context, Exit, ObservationTimeout, Result, node
from kookabug_sdk.testing import (
    ENGINE_MODULE,
    EngineUnavailable,
    FakeWindow,
    InputCall,
    fake_context,
)
from kookabug_sdk.types import Image, Match, OcrResult, Point, Rect, Target, WindowRef


class Vision:
    def __init__(self, found: Match | None) -> None:
        self.found = found
        self.seen: list[Image] = []

    def find(self, image: Image, target: Target, **kw: Any) -> Match | None:
        self.seen.append(image)
        return self.found

    def diff(self, a: Image, b: Image, **kw: Any) -> float:
        return 0.0 if a == b else 1.0


class Ocr:
    def read(self, image: Image, **kw: Any) -> OcrResult:
        return OcrResult("인벤토리", confidence=0.9)


@node(
    type="sample.image.click",
    version=1,
    title="찾아서 클릭",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def click_image(ctx: Context, target: Target) -> Result:
    match = ctx.vision.find(ctx.capture(), target)
    if match is None:
        return Result.fail("not_found")
    ctx.input.click(match)
    return Result.ok("done", match=match)


TARGET = Target("start", None, {})


def test_fake_context_injected_engines() -> None:
    found = Match(Rect(10, 10, 20, 10), 0.95, click=Point(12, 15))
    vision = Vision(found)
    ctx = fake_context(frames=[Image(64, 64, frame=0)], vision=vision, ocr=Ocr())
    result = click_image(ctx, target=TARGET)
    assert (result.exit, result.outputs["match"]) == ("done", found)
    assert vision.seen == [Image(64, 64, frame=0)]
    assert [(c.method, c.args) for c in ctx.input.calls] == [("click", (found,))]
    assert ctx.ocr.read(Image()).text == "인벤토리"
    assert ctx.vision.diff(Image(1, 1), Image(2, 2)) == 1.0

    missing = fake_context(frames=[Image()], vision=Vision(None))
    assert click_image(missing, target=TARGET).exit == "not_found"
    assert missing.input.calls == []


def _block_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """`kookabug_platform`이 없는 환경 (SDK만 설치한 플러그인 venv). `sys.modules`의 None은
    그 모듈 import를 `ModuleNotFoundError`로 막는다 (이미 import됐어도)."""
    for name in [m for m in sys.modules if m.startswith("kookabug_platform.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, "kookabug_platform", None)


@pytest.mark.parametrize("engine", ["vision", "ocr"])
def test_fake_context_without_platform_clear_error(
    monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    _block_platform(monkeypatch)
    ctx = fake_context(frames=[Image()])
    with pytest.raises(EngineUnavailable, match=rf"ctx\.{engine}.*fake_context\({engine}=") as info:
        getattr(ctx, engine)
    assert ENGINE_MODULE in str(info.value)
    # 노드 안에서 쓰면 그 노드의 예외(error)다 — 엔진 없이 조용히 None을 주지 않는다
    with pytest.raises(EngineUnavailable):
        click_image(ctx, target=TARGET)
    # 넣은 엔진은 플랫폼 없이도 쓴다
    assert fake_context(vision=Vision(None)).vision.find(Image(), TARGET) is None


def test_fake_context_platform_module_without_factory_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 플랫폼은 있지만 엔진 팩토리가 없는 판 (모듈만 있고 vision()이 없음)
    module = types.ModuleType(ENGINE_MODULE)
    monkeypatch.setitem(sys.modules, ENGINE_MODULE, module)
    with pytest.raises(EngineUnavailable, match=r"ctx\.vision"):
        _ = fake_context().vision

    module.vision = lambda: Vision(None)  # type: ignore[attr-defined]
    ctx = fake_context()
    engine = getattr(ctx.vision, "engine", None)
    assert isinstance(engine, Vision)
    # 플랫폼 엔진도 기한 확인으로 감싼다
    with pytest.raises(ObservationTimeout):
        ctx.vision.find(Image(), TARGET, deadline=ctx.deadline(0))
    assert engine.seen == []


class TwoScenes:
    """타이틀에서 시작 버튼을 누르면 2프레임 뒤 로비, 로비에서 `esc`면 타이틀."""

    START = Rect(100, 100, 50, 20)
    WINDOW = FakeWindow(WindowRef(77, "Sample Game"), "python.exe", client_size=(320, 200))

    def __init__(self) -> None:
        self.scene = "title"
        self.pending: tuple[str, int] | None = None
        self.inputs: list[InputCall] = []

    def capture(self, region: Rect | None) -> Image:
        if self.pending is not None:
            scene, frames = self.pending
            self.pending = None if frames <= 0 else (scene, frames - 1)
            if self.pending is None:
                self.scene = scene
        return Image(320, 200, path=None, frame=len(self.inputs), data=self.scene.encode())

    def on_input(self, call: InputCall) -> None:
        self.inputs.append(call)
        if call.method == "click" and self.scene == "title":
            at = call.args[0]
            point = at if isinstance(at, Point) else at.click_point
            r = self.START
            if r.x <= point.x < r.x + r.width and r.y <= point.y < r.y + r.height:
                self.pending = ("lobby", 1)
        if call.method == "key" and call.args == ("esc",) and self.scene == "lobby":
            self.scene = "title"

    def launch(self, path: str, args: Sequence[str]) -> Sequence[FakeWindow]:
        return [self.WINDOW] if path.endswith("sample_game.exe") else []


def test_fake_context_scenario_transitions() -> None:
    scenario = TwoScenes()
    ctx = fake_context(scenario=scenario)

    def scene() -> bytes | None:
        return ctx.capture().data

    process = ctx.process.launch("C:/game/sample_game.exe", ["--size", "320x200"])
    window = ctx.process.find_window(process)
    assert window == WindowRef(77, "Sample Game", pid=process.pid)
    assert ctx.windows.find("sample game") == window
    assert ctx.process.find_window(ctx.process.launch("other.exe")) is None

    assert scene() == b"title"
    ctx.input.click(Point(10, 10))  # 버튼 밖: 전이 없음
    assert scene() == b"title"
    ctx.input.click(Match(Rect(100, 100, 50, 20), 0.9))  # 클릭 지점 = 중심
    assert scene() == b"title"  # after_frames: 다음 한 프레임은 그대로
    assert scene() == b"lobby"
    ctx.input.key("esc")
    assert scene() == b"title"
    # 입력은 장면에도 가고 기록에도 남는다
    assert [c.method for c in ctx.input.calls] == ["click", "click", "key"]
    assert scenario.inputs == ctx.input.calls
    assert ctx.captured == 5
