"""testkit 노드 선언과 구현."""

from typing import Literal

from kookabug_sdk import Config, Context, DynamicExits, Exit, Output, Result, Retry, node
from kookabug_sdk.types import Match, Point, Rect

PLUGIN_ID = "testkit"
PLUGIN_VERSION = "0"


@node(
    type="testkit.observe.wait",
    version=1,
    title="가짜 화면 대기",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"match": Output(Match)},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def observe_wait(ctx: Context, expect: str, timeout_ms: int = 1000, poll_ms: int = 100) -> Result:
    """캡처 프레임 이름(파일 이름 줄기)이 `expect`인 프레임이 나올 때까지 기다린다."""
    deadline = ctx.deadline(timeout_ms)
    while True:
        ctx.check_cancel()
        frame = ctx.capture()
        if frame.path is not None and frame.path.stem == expect:
            return Result.ok("found", match=Match(Rect(0, 0, 1, 1), 1.0, frame=frame.frame))
        if deadline.passed:
            return Result.fail("timeout", f"'{expect}' 프레임이 {timeout_ms}ms 안에 없다")
        ctx.sleep(min(poll_ms, deadline.remaining_ms))


@node(
    type="testkit.input.tap",
    version=1,
    title="가짜 탭",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def input_tap(ctx: Context, x: int, y: int) -> Result:
    """(x, y)를 누른다 (가짜 입력에 기록만 된다)."""
    ctx.input.click(Point(x, y))
    return Result.ok("done")


@node(type="testkit.boom", version=1, title="예외", exits=[Exit("done", "ok")])
def boom(ctx: Context, message: str = "boom") -> Result:
    """늘 예외를 던진다 (error 전파 시나리오용)."""
    raise RuntimeError(message)


@node(
    type="testkit.fail_once",
    version=1,
    title="출구 고르기",
    exits=[
        Exit("ok", "ok"),
        Exit("fail", "fail"),
        Exit("timeout", "fail"),
    ],
    outputs={"value": int},
)
def fail_once(
    ctx: Context, exit: Literal["ok", "fail", "timeout"] = "fail", value: int = 1
) -> Result:
    """`exit`로 정한 출구로 나간다. `ok`면 `value`를 출력한다."""
    if exit == "ok":
        return Result.ok("ok", value=value)
    return Result.fail(exit, f"testkit.fail_once: {exit}")


@node(
    type="testkit.flow.choose",
    version=1,
    title="동적 출구",
    config={"exits": Config(list[str], default=["done"])},
    exits=DynamicExits(from_config="exits", extra=[Exit("failed", "fail")]),
)
def choose(ctx: Context, pick: str = "done") -> Result:
    """`config.exits`(기본 `["done"]`)로 출구를 만들고 `pick` 출구로 나간다."""
    return Result.ok(pick)


NODES = (observe_wait, input_tap, boom, fail_once, choose)
