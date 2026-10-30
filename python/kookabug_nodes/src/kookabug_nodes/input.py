"""입력 노드: 클릭·끌기·휠·키·글자.

노드는 `ctx.input`만 부른다. 대상 창 고정, 입력 직전 확인(창 유효·포그라운드·가림), `Match`의
재검증(창 크기·DPI가 바뀌었으면 다시 찾기)은 runner의 공용 입력 서비스가 한다 (구현 계획 M1 2.4).
확인에 실패하면 그 노드는 `error`, 다시 찾지 못하면 처리되지 않은 fail(`stale_observation`)이다.

그래프에 상수로 쓰는 점은 `[x, y]`(클라이언트 픽셀)다. 실행기가 핀 타입대로 `Point`로 바꿔
주므로(검증기·실행기의 일반 규칙) 노드는 `Match`·`Point`만 받는다.
"""

from typing import Annotated, Final, Literal

from kookabug_sdk import Context, Exit, Input, Result, Secret, node
from kookabug_sdk.types import Match, Point, Target

Button = Literal["left", "right", "middle", "x1", "x2"]

# ctrl+a로 칸 전체를 고른 뒤 지운다. 전체 선택을 모르는 칸은 끝 글자 하나만 지워진다
CLEAR_KEYS: Final = ("ctrl+a", "backspace")


@node(
    type="core.input.click",
    version=1,
    title="클릭",
    category="input",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def click(
    ctx: Context,
    match: Match | None = None,
    point: Point | None = None,
    button: Button = "left",
    count: Annotated[int, Input(minimum=1)] = 1,
) -> Result:
    """매칭 결과(`match`, target의 클릭 지점)나 좌표(`point`, 클라이언트 픽셀 `[x, y]`)를 클릭한다.
    둘 중 하나만 준다. `count` 2면 이중 클릭."""
    if match is not None and point is None:
        ctx.input.click(match, button=button, count=count)
    elif point is not None and match is None:
        ctx.input.click(point, button=button, count=count)
    else:
        raise ValueError("match와 point 중 하나만 준다")
    return Result.ok("done")


@node(
    type="core.input.drag",
    version=1,
    title="끌기",
    category="input",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def drag(
    ctx: Context,
    start: Match | Point,
    end: Match | Point,
    duration_ms: Annotated[int, Input(minimum=0)] = 300,
    button: Button = "left",
) -> Result:
    """`start`에서 눌러 `duration_ms` 동안 `end`까지 옮긴 뒤 뗀다. 매칭 결과는 클릭 지점, 점은
    클라이언트 픽셀 `[x, y]`."""
    ctx.input.drag(start, end, duration_ms=duration_ms, button=button)
    return Result.ok("done")


@node(
    type="core.input.scroll",
    version=1,
    title="휠",
    category="input",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def scroll(ctx: Context, point: Point, amount: int) -> Result:
    """`point`(클라이언트 픽셀 `[x, y]`)에서 휠을 `amount` 칸 굴린다. 양수 = 위."""
    ctx.input.scroll(point, amount)
    return Result.ok("done")


@node(
    type="core.input.key",
    version=1,
    title="키 입력",
    category="input",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def key(ctx: Context, keys: str, hold_ms: Annotated[int, Input(minimum=0)] = 0) -> Result:
    """키 하나나 조합(`ctrl+a`)을 누른다. `hold_ms`만큼 누르고 있다가 뗀다 (기다리는 중 취소돼도
    뗀다). 모르는 키 이름은 `key_unknown`."""
    ctx.input.key(keys, hold_ms=hold_ms)
    return Result.ok("done")


@node(
    type="core.input.type_text",
    version=1,
    title="글자 입력",
    category="input",
    exits=[Exit("done", "ok")],
    effects={"capture", "input"},
)
def type_text(
    ctx: Context, text: str | Secret, target: Target | None = None, clear: bool = False
) -> Result:
    """글자를 입력한다. `target`을 주면 지금 화면에서 그 칸을 찾아 먼저 클릭한다(없으면 `error` —
    칸이 보일 때까지는 대기 노드로 기다린다). `clear`면 입력 전에 칸을 비운다(`ctrl+a` →
    `backspace`, 재시도 때 덧붙여 입력하지 않게). 비밀값은 기록에 남기지 않는다."""
    if target is not None:
        found = ctx.vision.find(ctx.capture(), target)
        if found is None:
            raise LookupError(f"입력 칸 target '{target.name}'이(가) 지금 화면에 없다")
        ctx.input.click(found)
    if clear:
        for name in CLEAR_KEYS:
            ctx.input.key(name)
    ctx.input.type_text(text)
    return Result.ok("done")
