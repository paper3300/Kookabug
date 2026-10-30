"""이미지 노드: 대상 대기·여러 대상 중 먼저 보이는 것·사라질 때까지 대기·대기 후 클릭.

기다리는 노드는 `timeout_ms` 동안 캡처해 찾고, 못 찾고 끝나면 마지막 프레임을
`steps/<스텝>_timeout`(클릭은 `_not_found`)으로 남긴다. 정지 화면은 같은 프레임의 반복이라
오류가 아니고 그대로 기다리다 `timeout`이다 (`_observe` 설명).
"""

from typing import Annotated, Literal

from kookabug_nodes._observe import poll, save_last
from kookabug_sdk import Config, Context, DynamicExits, Exit, Input, Result, Retry, node
from kookabug_sdk.context import Deadline
from kookabug_sdk.types import Image, Match, Target

Button = Literal["left", "right", "middle", "x1", "x2"]


@node(
    type="core.image.wait",
    version=1,
    title="이미지 대기",
    category="image",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait(
    ctx: Context, target: Target, timeout_ms: Annotated[int, Input(minimum=0)] = 10000
) -> Result:
    """대상이 나타날 때까지 기다린다."""
    found, frame = poll(ctx, timeout_ms, lambda f, d: ctx.vision.find(f, target, deadline=d))
    if found is not None:
        return Result.ok("found", match=found)
    save_last(ctx, frame, "timeout")
    return Result.fail("timeout", f"'{target.name}'이(가) {timeout_ms}ms 안에 보이지 않았다")


@node(
    type="core.image.wait_any",
    version=1,
    title="여러 대상 중 먼저 보이는 것",
    category="image",
    config={"exits": Config(list[str], min_items=2)},
    exits=DynamicExits(from_config="exits", kind="ok", extra=[Exit("timeout", "fail")]),
    outputs={"match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait_any(
    ctx: Context,
    targets: dict[str, Target],
    timeout_ms: Annotated[int, Input(minimum=0)] = 10000,
) -> Result:
    """`targets`(출구 이름 → 대상) 중 먼저 보이는 것의 출구로 나간다. 같은 프레임에 여럿이
    보이면 `config.exits`의 앞쪽이다."""
    order: list[str] = list(ctx.config["exits"])
    missing = [name for name in order if name not in targets]
    extra = sorted(set(targets) - set(order))
    if missing or extra:
        raise ValueError(
            f"targets의 이름은 config.exits와 같아야 한다 (없음: {missing}, 남음: {extra})"
        )

    def look(frame: Image, deadline: Deadline | None) -> tuple[str, Match] | None:
        for name in order:
            found = ctx.vision.find(frame, targets[name], deadline=deadline)
            if found is not None:
                return name, found
        return None

    hit, frame = poll(ctx, timeout_ms, look)
    if hit is not None:
        return Result.ok(hit[0], match=hit[1])
    save_last(ctx, frame, "timeout")
    return Result.fail(
        "timeout", f"{', '.join(order)} 중 아무것도 {timeout_ms}ms 안에 보이지 않았다"
    )


@node(
    type="core.image.wait_gone",
    version=1,
    title="이미지 사라질 때까지 대기",
    category="image",
    exits=[Exit("gone", "ok"), Exit("timeout", "fail")],
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait_gone(
    ctx: Context, target: Target, timeout_ms: Annotated[int, Input(minimum=0)] = 10000
) -> Result:
    """대상이 사라질 때까지 기다린다 (로딩 표시 등). 처음부터 없으면 바로 `gone`."""
    gone, frame = poll(
        ctx,
        timeout_ms,
        lambda f, d: True if ctx.vision.find(f, target, deadline=d) is None else None,
    )
    if gone:
        return Result.ok("gone")
    save_last(ctx, frame, "timeout")
    return Result.fail("timeout", f"'{target.name}'이(가) {timeout_ms}ms 안에 사라지지 않았다")


@node(
    type="core.image.click",
    version=1,
    title="이미지 클릭",
    category="image",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def click(
    ctx: Context,
    target: Target,
    button: Button = "left",
    count: Annotated[int, Input(minimum=1)] = 1,
    timeout_ms: Annotated[int, Input(minimum=0)] = 10000,
) -> Result:
    """대상이 보일 때까지 기다렸다가 그 클릭 지점을 클릭한다. 못 찾으면 입력하지 않고
    `not_found`. 입력 직전 재검증은 공용 입력 서비스가 한다."""
    found, frame = poll(ctx, timeout_ms, lambda f, d: ctx.vision.find(f, target, deadline=d))
    if found is None:
        save_last(ctx, frame, "not_found")
        return Result.fail("not_found", f"'{target.name}'이(가) {timeout_ms}ms 안에 보이지 않았다")
    ctx.input.click(found, button=button, count=count)
    return Result.ok("done", match=found)
