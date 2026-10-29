import contextlib
from collections.abc import Callable
from typing import Any

import pytest

from kookabug_sdk import Context, Exit, Result, node
from kookabug_sdk.context import Cancelled, EffectContext, EffectNotDeclared, GuardedContext
from kookabug_sdk.decorators import guard
from kookabug_sdk.pure import PureContext, PureContextViolation
from kookabug_sdk.testing import FakeClock, FakeContext, fake_context
from kookabug_sdk.types import Image, Point


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
