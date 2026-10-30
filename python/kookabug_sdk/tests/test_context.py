import contextlib
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk import Context, Exit, ObservationTimeout, Result, StaleObservation, node
from kookabug_sdk.context import Cancelled, EffectContext, EffectNotDeclared, GuardedContext
from kookabug_sdk.decorators import guard
from kookabug_sdk.pure import PureContext, PureContextViolation
from kookabug_sdk.testing import FakeClock, FakeContext, FakeWindow, InputCall, fake_context
from kookabug_sdk.types import Image, Match, OcrResult, Point, ProcessRef, Rect, Target, WindowRef
from kookabug_sdk.worker import WorkerContext


def pure_node(body: Callable[[Context], Any]) -> Any:
    @node(type="sample.logic.probe", version=1, title="t", pure=True, outputs={"x": int})
    def probe(ctx: Context) -> dict[str, Any]:
        body(ctx)
        return {"x": 1}

    return probe


def exec_node(body: Callable[[Context], Any], effects: set[str] | None = None) -> Any:
    @node(
        type="sample.act.probe",
        version=1,
        title="t",
        exits=[Exit("done", "ok")],
        effects=effects or set(),
    )
    def probe(ctx: Context) -> Result:
        body(ctx)
        return Result.ok("done")

    return probe


def test_pure_ctx_blocks_capture() -> None:
    with pytest.raises(PureContextViolation, match=r"ctx\.capture"):
        pure_node(lambda ctx: ctx.capture())(fake_context(frames=[Image()]))
    with pytest.raises(PureContextViolation):
        fake_context(pure=True, frames=[Image()]).capture()


@pytest.mark.parametrize("method", ["click", "key", "type_text"])
def test_pure_ctx_blocks_input(method: str) -> None:
    ctx = fake_context()
    with pytest.raises(PureContextViolation, match=rf"ctx\.input\.{method}"):
        pure_node(lambda c: getattr(c.input, method)(Point(1, 1)))(ctx)
    assert ctx.input.calls == []


def test_pure_ctx_blocks_artifacts() -> None:
    ctx = fake_context()
    with pytest.raises(PureContextViolation, match=r"ctx\.artifacts\.save"):
        pure_node(lambda c: c.artifacts.save(Image(), "x"))(ctx)
    assert ctx.artifacts.saved == {}


def test_pure_ctx_blocks_sleep() -> None:
    ctx = fake_context()
    with pytest.raises(PureContextViolation, match=r"ctx\.sleep"):
        pure_node(lambda c: c.sleep(10))(ctx)
    assert ctx.clock.now_ms() == 0


@pytest.mark.parametrize("level", ["debug", "info", "warn", "error"])
def test_pure_ctx_blocks_log(level: str) -> None:
    ctx = fake_context()
    with pytest.raises(PureContextViolation, match=rf"ctx\.log\.{level}"):
        pure_node(lambda c: getattr(c.log, level)("안녕"))(ctx)
    assert ctx.log.records == []


def test_pure_ctx_vars_read_only() -> None:
    ctx = fake_context(vars={"a": 1})
    seen: dict[str, Any] = {}

    def read(c: Context) -> None:
        seen["a"] = c.vars.get("a")
        seen["b"] = c.vars.get("b", 2)
        seen["has"] = c.vars.has("a")
        seen["config"] = c.config
        seen["deadline"] = c.deadline(5).remaining_ms

    pure_node(read)(ctx)
    assert seen == {"a": 1, "b": 2, "has": True, "config": {}, "deadline": 5}
    with pytest.raises(PureContextViolation, match=r"ctx\.vars\.set"):
        pure_node(lambda c: c.vars.set("a", 3))(ctx)
    assert ctx.vars.values == {"a": 1}


def test_undeclared_effect_use_is_error() -> None:
    ctx = fake_context(frames=[Image()])
    with pytest.raises(EffectNotDeclared, match="'capture'"):
        exec_node(lambda c: c.capture())(ctx)
    with pytest.raises(EffectNotDeclared, match="'input'"):
        exec_node(lambda c: c.input.key("enter"), {"capture"})(ctx)
    assert ctx.input.calls == []

    exec_node(lambda c: (c.capture(), c.input.key("enter")), {"capture", "input"})(ctx)
    assert [call.method for call in ctx.input.calls] == ["key"]
    # 기록·시간·변수는 효과가 아니다
    exec_node(lambda c: (c.log.info("x"), c.sleep(5), c.vars.set("v", 1)))(ctx)
    assert ctx.log.records == [("info", "x")]


def test_swallowed_violation_is_still_error() -> None:
    def swallow(c: Context) -> None:
        with contextlib.suppress(Exception):
            c.capture()

    with pytest.raises(PureContextViolation):
        pure_node(swallow)(fake_context(frames=[Image()]))
    with pytest.raises(EffectNotDeclared):
        exec_node(swallow)(fake_context(frames=[Image()]))


def test_fake_context_pure_mode_uses_same_wrapper() -> None:
    ctx = fake_context(pure=True)
    assert type(ctx) is PureContext
    assert isinstance(ctx.inner, FakeContext)

    probe = pure_node(lambda c: None)
    wrapped = guard(fake_context(), probe.spec)
    assert type(wrapped) is PureContext  # 실행기도 guard()로 같은 래퍼를 쓴다
    assert type(guard(fake_context(), exec_node(lambda c: None).spec)) is EffectContext
    assert issubclass(PureContext, GuardedContext)

    with pytest.raises(PureContextViolation):
        ctx.log.info("x")
    assert ctx.inner.log.records == []  # type: ignore[attr-defined]


def test_fake_capture_frames_in_order_then_last() -> None:
    ctx = fake_context(frames=["a.png", "b.png"], workspace="ws")
    got = [ctx.capture() for _ in range(3)]
    assert [(str(f.path), f.frame) for f in got] == [("a.png", 0), ("b.png", 1), ("b.png", 1)]
    assert ctx.path("x/y.png").as_posix() == "ws/x/y.png"


def test_fake_context_artifacts_save_returns_path() -> None:
    # 가짜 ctx에는 기록 정책이 없다: 늘 경로(이름)를 준다. 실행기는 생략하면 None을 준다
    ctx = fake_context(frames=["a.png"])
    frame = ctx.capture()
    assert ctx.artifacts.save(frame, "before") == "before"
    assert ctx.artifacts.saved == {"before": frame}

    @node(
        type="sample.act.shoot",
        version=1,
        title="t",
        exits=[Exit("done", "ok")],
        outputs={"saved": str},
        effects={"capture"},
    )
    def shoot(ctx: Context) -> Result:
        saved = ctx.artifacts.save(ctx.capture(), "shot")
        assert saved is not None
        return Result.ok("done", saved=saved)

    assert shoot(fake_context(frames=["a.png"])).outputs == {"saved": "shot"}


def test_fake_clock_deadline_and_cancel() -> None:
    clock = FakeClock(100)
    ctx = fake_context(clock=clock, settings={"game.exe": "g.exe"})
    deadline = ctx.deadline(50)
    assert not deadline.passed
    ctx.sleep(50)
    assert deadline.passed and deadline.remaining_ms == 0
    assert clock.now_ms() == 150
    assert ctx.setting("game.exe") == "g.exe"
    with pytest.raises(KeyError):
        ctx.setting("missing")
    ctx.check_cancel()
    ctx.cancel()
    with pytest.raises(Cancelled):
        ctx.check_cancel()
    assert not issubclass(Cancelled, Exception)


@pytest.mark.parametrize("pure_ctx", [False, True], ids=["node_wraps", "fake_pure"])
def test_pure_vars_get_returns_copy(pure_ctx: bool) -> None:
    # 순수 노드가 읽은 list·dict를 고치거나 출력으로 내보내도 프레임 변수는 그대로 (검수 T3_1)
    ctx = fake_context(pure=pure_ctx, vars={"state": {"items": [1]}})

    @node(type="sample.value.probe", version=1, title="t", pure=True, outputs={"state": Any})
    def probe(c: Context) -> dict[str, Any]:
        state = c.vars.get("state")
        state["items"].append(2)
        c.vars.get("missing", {"d": []})["d"].append(1)
        return {"state": c.vars.get("state")}

    result = probe(ctx)
    result.outputs["state"]["items"].append(3)
    assert ctx.vars.get("state") == {"items": [1]}

    # exec 노드는 PureContext를 거치지 않는다 (변수 쓰기는 vars.set으로)
    plain = fake_context(vars={"state": {"items": [1]}})
    assert plain.vars.get("state") is plain.vars.values["state"]


# ---------------------------------------------------------------- M1 ctx (vision·ocr·창·프로세스)

WIN = WindowRef(10, "Sample Game", pid=4001)
TARGET = Target("start", None, {"image": "start.png"})


class StubVision:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def find(self, image: Image, target: Target, **kw: Any) -> Match | None:
        self.calls.append(("find", (image, target), kw))
        return Match(Rect(1, 2, 3, 4), 0.9)

    def diff(self, a: Image, b: Image, **kw: Any) -> float:
        self.calls.append(("diff", (a, b), kw))
        return 0.0


class StubOcr:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def read(self, image: Image, **kw: Any) -> OcrResult:
        self.calls.append(kw)
        return OcrResult("Gold 12,345")


def m1_ctx() -> FakeContext:
    return fake_context(
        frames=[Image(4, 4, frame=0)],
        vision=StubVision(),
        ocr=StubOcr(),
        windows=[FakeWindow(WIN, "python.exe")],
    )


def engines(ctx: FakeContext) -> tuple[StubVision, StubOcr]:
    """가짜 ctx가 기한 확인으로 감싼 엔진 속의 스텁."""
    vision, ocr = getattr(ctx.vision, "engine", None), getattr(ctx.ocr, "engine", None)
    assert isinstance(vision, StubVision) and isinstance(ocr, StubOcr)
    return vision, ocr


# (설명, 부르는 함수, 필요한 효과 — None이면 효과 없이 됨)
M1_CALLS: list[tuple[str, Callable[[Context], Any], str | None]] = [
    ("vision.find", lambda c: c.vision.find(Image(), TARGET), "capture"),
    ("vision.diff", lambda c: c.vision.diff(Image(), Image()), "capture"),
    ("ocr.read", lambda c: c.ocr.read(Image()), "capture"),
    ("capture", lambda c: c.capture(deadline=c.deadline(100)), "capture"),
    ("windows.set_client_size", lambda c: c.windows.set_client_size(WIN, 800, 600), "process"),
    ("windows.activate", lambda c: c.windows.activate(WIN), "process"),
    ("process.launch", lambda c: c.process.launch("game.exe", ["--x"]), "process"),
    ("process.close", lambda c: c.process.close(ProcessRef(4001), 1000), "process"),
    ("process.find_window", lambda c: c.process.find_window(ProcessRef(4001)), "process"),
    ("input.drag", lambda c: c.input.drag(Point(0, 0), Point(5, 5), duration_ms=10), "input"),
    ("input.scroll", lambda c: c.input.scroll(Point(1, 1), -3), "input"),
    ("input.key", lambda c: c.input.key("w", hold_ms=500), "input"),
    ("windows.find", lambda c: c.windows.find("Sample"), None),
    ("windows.info", lambda c: c.windows.info(WIN), None),
    ("set_window", lambda c: c.set_window(WIN), None),
]
M1_IDS = [name for name, _, _ in M1_CALLS]


@pytest.mark.parametrize(("name", "call", "effect"), M1_CALLS, ids=M1_IDS)
def test_pure_blocks_vision_ocr_windows_process(
    name: str, call: Callable[[Context], Any], effect: str | None
) -> None:
    # 순수 노드는 창 찾기·정보까지 전부 막는다 (그 순간 화면에 따라 값이 달라진다)
    ctx = m1_ctx()
    with pytest.raises(PureContextViolation, match=rf"ctx\.{name}"):
        pure_node(call)(ctx)
    with pytest.raises(PureContextViolation):
        call(fake_context(pure=True))
    vision, ocr = engines(ctx)
    assert vision.calls == [] and ocr.calls == []
    assert ctx.input.calls == [] and ctx.process.launched == [] and ctx.windows.activated == []
    assert ctx.window is None


@pytest.mark.parametrize(
    ("name", "call", "effect"), [c for c in M1_CALLS if c[2] == "capture"], ids=str
)
def test_vision_find_diff_ocr_need_capture_effect(
    name: str, call: Callable[[Context], Any], effect: str | None
) -> None:
    ctx = m1_ctx()
    for wrong in (set[str](), {"input", "process"}):
        with pytest.raises(EffectNotDeclared, match=rf"ctx\.{name}.*'capture'"):
            exec_node(call, wrong)(ctx)
    vision, ocr = engines(ctx)
    assert vision.calls == [] and ocr.calls == [] and ctx.captured == 0
    exec_node(call, {"capture"})(ctx)
    assert len(vision.calls) + len(ocr.calls) + ctx.captured == 1


def test_vision_ocr_arguments_pass_through_wrappers() -> None:
    ctx = m1_ctx()
    region = Rect(0, 0, 2, 2)

    def body(c: Context) -> None:
        deadline = c.deadline(300)
        frame = c.capture(region, deadline=deadline)
        assert c.vision.find(frame, TARGET, region=region, deadline=deadline) is not None
        assert c.vision.diff(frame, frame, region=region) == 0.0
        assert c.ocr.read(frame, region=region, sensitive=True, deadline=deadline).text == (
            "Gold 12,345"
        )

    exec_node(body, {"capture"})(ctx)
    vision, ocr = engines(ctx)
    (find_kw, diff_kw) = (vision.calls[0][2], vision.calls[1][2])
    assert find_kw["region"] == region and find_kw["deadline"].end_ms == 300
    assert diff_kw == {"region": region}
    assert ocr.calls[0]["sensitive"] is True and ocr.calls[0]["region"] == region


@pytest.mark.parametrize(
    ("name", "call", "effect"), [c for c in M1_CALLS if c[2] != "capture"], ids=str
)
def test_process_api_needs_process_effect(
    name: str, call: Callable[[Context], Any], effect: str | None
) -> None:
    # 프로세스·창 바꾸기는 process, 입력은 input, 창 찾기·정보·set_window는 효과가 필요 없다
    ctx = m1_ctx()
    if effect is not None:
        others = {"capture", "input", "process"} - {effect}
        with pytest.raises(EffectNotDeclared, match=rf"ctx\.{name}.*'{effect}'"):
            exec_node(call, others)(ctx)
        assert ctx.input.calls == [] and ctx.process.launched == [] and ctx.process.closed == []
        assert ctx.windows.activated == [] and ctx.windows.get(WIN).client_size == (1280, 720)
    exec_node(call, set() if effect is None else {effect})(ctx)


def test_fake_windows_and_process_record() -> None:
    ctx = m1_ctx()
    assert ctx.windows.find("sample") == WIN
    assert ctx.windows.find("/^Sample Game$/", "PYTHON.EXE") == WIN
    assert ctx.windows.find("other") is None
    assert ctx.windows.info(WIN).process_name == "python.exe"
    assert ctx.windows.set_client_size(WIN, 1024, 640)
    assert ctx.windows.info(WIN).client_size == (1024, 640)
    ctx.set_window(WIN)
    assert ctx.window == WIN  # 노드 밖에서는 호출 프레임의 창이 곧바로 바뀐다
    # 처음부터 떠 있던 창(pid 4001)의 PID를 피해 새 PID를 준다 (검수 T8_1 지적 4)
    process = ctx.process.launch("C:/games/game.exe", ["--size", "1024x640"], cwd="C:/games")
    assert process == ProcessRef(4002, "game.exe")
    assert ctx.process.launch("C:/games/other.exe") == ProcessRef(4003, "other.exe")
    assert ctx.process.launched[0] == ("C:/games/game.exe", ("--size", "1024x640"), "C:/games")
    assert ctx.process.find_window(process) is None  # 무관한 기존 창을 새 프로세스 창으로 안 줌
    assert ctx.process.find_window(ProcessRef(4001)) == WIN
    assert ctx.process.close(process, 500)
    assert ctx.windows.find("Sample") == WIN  # 새 프로세스를 닫아도 기존 창은 그대로
    # 기다려도 가짜 창은 뜨지 않는다: 기한까지 시계를 넘기고 ObservationTimeout
    with pytest.raises(ObservationTimeout):
        ctx.process.find_window(process, deadline=ctx.deadline(250))
    assert ctx.clock.now_ms() == 250


def test_set_window_keeps_running_node_window_fake_and_worker() -> None:
    # set_window는 다음 스텝부터: 같은 노드 본문을 가짜·워커 ctx에서 돌려 같게 (검수 T8_1 지적 2)
    first, second = WindowRef(1, "first"), WindowRef(2, "second")
    seen: list[tuple[WindowRef | None, WindowRef | None]] = []

    @node(type="sample.window.change", version=1, title="t", exits=[Exit("done", "ok")])
    def change(ctx: Context) -> Result:
        before = ctx.window
        ctx.set_window(second)
        seen.append((before, ctx.window))
        return Result.ok("done")

    worker = WorkerContext(
        request=lambda method, params: {},
        cancel=threading.Event(),
        files_root=Path("."),
        config={},
        window=first,
        deadline_remaining_ms=60_000,
    )
    fake = fake_context(window=first)
    change(worker)
    change(fake)
    assert seen == [(first, first), (first, first)]
    # 가짜 ctx는 호출 프레임: 다음 노드 호출은 바뀐 창을 본다
    change(fake)
    assert seen[-1] == (second, second)
    assert fake.window == second


@pytest.mark.parametrize("kind", ["vision", "ocr"])
def test_expired_fake_observation_never_calls_engine(kind: str) -> None:
    # 넣은 엔진이 기한을 보지 않아도 가짜 ctx가 시작 전에 막는다 (검수 T8_1 지적 3)
    ctx = m1_ctx()
    vision, ocr = engines(ctx)
    passed = ctx.deadline(0)
    with pytest.raises(ObservationTimeout):
        if kind == "vision":
            ctx.vision.find(Image(), TARGET, deadline=passed)
        else:
            ctx.ocr.read(Image(), deadline=passed)
    assert vision.calls == [] and ocr.calls == []

    @node(
        type="sample.image.wait",
        version=1,
        title="t",
        exits=[Exit("found", "ok"), Exit("timeout", "fail")],
        effects={"capture"},
    )
    def wait(c: Context) -> Result:
        deadline = c.deadline(100)
        c.sleep(100)
        try:
            if kind == "vision":
                c.vision.find(Image(), TARGET, deadline=deadline)
            else:
                c.ocr.read(Image(), deadline=deadline)
        except ObservationTimeout:
            return Result.fail("timeout")
        return Result.ok("found")

    assert wait(ctx).exit == "timeout"
    assert vision.calls == [] and ocr.calls == []


class TemplateScenario:
    """띄울 때마다 같은 창 견본 객체를 돌려주는 장면."""

    def __init__(self) -> None:
        self.window = FakeWindow(WindowRef(10, "Sample"), "game.exe")

    def capture(self, region: Rect | None) -> Image:
        return Image()

    def on_input(self, call: InputCall) -> None:
        pass

    def launch(self, path: str, args: Sequence[str]) -> Sequence[FakeWindow]:
        return [self.window]


def test_launch_copies_scenario_window_template() -> None:
    # 장면의 창 견본을 바꾸지 않고 복사해 넣는다: 여러 번·여러 ctx가 섞이지 않게 (검수 T8_1 지적 5)
    scenario = TemplateScenario()
    one, two = fake_context(scenario=scenario), fake_context(scenario=scenario)
    a = one.process.launch("game.exe")
    first = one.process.find_window(a)
    assert first == WindowRef(10, "Sample", pid=a.pid)
    b = one.process.launch("game.exe")
    two.process.launch("game.exe")
    two.process.launch("game.exe")
    assert one.process.find_window(a) == first  # 같은 견본으로 다시 띄워도 앞 창의 PID는 그대로
    assert one.process.find_window(b) == WindowRef(10, "Sample", pid=b.pid)
    assert scenario.window.ref == WindowRef(10, "Sample")  # 견본은 그대로
    assert first is not None
    one.windows.set_client_size(first, 640, 480)
    assert one.windows.info(first).client_size == (640, 480)
    assert one.windows.info(WindowRef(10, pid=b.pid)).client_size == (1280, 720)
    assert scenario.window.client_size == (1280, 720)
    assert [w.client_size for w in two.windows.windows] == [(1280, 720), (1280, 720)]


def test_fake_input_records_new_methods() -> None:
    ctx = fake_context()
    ctx.input.click(Point(1, 2), count=2)
    ctx.input.drag(Point(0, 0), Rect(0, 0, 4, 4), duration_ms=100, button="right")
    ctx.input.scroll(Point(3, 3), -2)
    ctx.input.key("shift+w", hold_ms=250)
    assert [(c.method, c.args, dict(c.kwargs)) for c in ctx.input.calls] == [
        ("click", (Point(1, 2),), {"button": "left", "count": 2}),
        ("drag", (Point(0, 0), Rect(0, 0, 4, 4)), {"duration_ms": 100, "button": "right"}),
        ("scroll", (Point(3, 3), -2), {}),
        ("key", ("shift+w",), {"hold_ms": 250}),
    ]


def test_passed_deadline_does_not_start_observation() -> None:
    ctx = m1_ctx()
    deadline = ctx.deadline(0)
    with pytest.raises(ObservationTimeout):
        ctx.capture(deadline=deadline)
    assert ctx.captured == 0


def test_stale_observation_not_caught_by_except_exception() -> None:
    # 재검증 실패는 노드가 삼키지 못하고 실행기까지 올라간다 (처리되지 않은 fail)
    assert not issubclass(StaleObservation, Exception)

    @node(
        type="sample.act.click",
        version=1,
        title="t",
        exits=[Exit("done", "ok"), Exit("broken", "fail")],
        effects={"input"},
    )
    def click(ctx: Context) -> Result:
        try:
            raise StaleObservation("창 크기가 바뀌었고 다시 찾지 못했다")
        except Exception:
            return Result.fail("broken")

    with pytest.raises(StaleObservation):
        click(fake_context())


def test_observation_timeout_is_exception() -> None:
    # 노드 기한 소진은 노드가 잡아 timeout 출구로 간다
    assert issubclass(ObservationTimeout, Exception)

    @node(
        type="sample.image.wait",
        version=1,
        title="t",
        exits=[Exit("found", "ok"), Exit("timeout", "fail")],
        effects={"capture"},
    )
    def wait(ctx: Context) -> Result:
        deadline = ctx.deadline(100)
        ctx.sleep(100)
        try:
            ctx.capture(deadline=deadline)
        except ObservationTimeout:
            return Result.fail("timeout")
        return Result.ok("found")

    assert wait(fake_context(frames=[Image()])).exit == "timeout"
