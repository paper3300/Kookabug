"""흐름 노드. 반복(`repeat`·`while`)은 실행기가 처리한다 (`engine=`)."""

from typing import Annotated

from kookabug_sdk import Context, Exit, Input, Result, node


@node(
    type="core.flow.branch",
    version=1,
    title="참·거짓 분기",
    category="flow",
    exits=[Exit("true", "ok"), Exit("false", "ok")],
)
def branch(ctx: Context, condition: bool) -> Result:
    """`condition`이 참이면 `true`, 거짓이면 `false`로 나간다."""
    if not isinstance(condition, bool):
        raise TypeError(f"condition은 bool이어야 한다: {type(condition).__name__}")
    return Result.ok("true" if condition else "false")


@node(
    type="core.flow.repeat",
    version=1,
    title="정해진 횟수 반복",
    category="flow",
    outputs={"index": int},
    exits=[Exit("body", "ok", outputs=["index"]), Exit("done", "ok", outputs=[])],
    engine="repeat",
)
def repeat(ctx: Context, times: Annotated[int, Input(minimum=0)]) -> Result:
    """`body`를 `times`번 실행한 뒤 `done`으로 나간다. `index`(0부터)는 본문 안에서만 읽는다."""
    raise NotImplementedError


@node(
    type="core.flow.while",
    version=1,
    title="조건 반복",
    category="flow",
    outputs={"index": int},
    exits=[
        Exit("body", "ok", outputs=["index"]),
        Exit("done", "ok", outputs=[]),
        Exit("limit", "fail"),
    ],
    engine="while",
)
def while_(
    ctx: Context, condition: bool, max_iterations: Annotated[int, Input(minimum=1)]
) -> Result:
    """조건이 참인 동안 `body`를 실행한다. 조건은 검사할 때마다 새로 계산한다.

    조건이 거짓 → `done`, 참인데 이미 `max_iterations`번 실행함 → `limit`(fail).
    """
    raise NotImplementedError


@node(
    type="core.flow.delay",
    version=1,
    title="고정 지연",
    category="flow",
    exits=[Exit("done", "ok")],
)
def delay(ctx: Context, ms: Annotated[int, Input(minimum=0)]) -> Result:
    """`ms`만큼 기다린다. 화면을 기다릴 때는 대기 노드를 쓴다."""
    ctx.sleep(ms)
    return Result.ok("done")
