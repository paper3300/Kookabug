"""testkit 관측 세대 노드: 디버거 재개 뒤 관측 출처 검사용 (구현 계획 M3 T4).

`testkit.nodes`가 가져와 같은 플러그인으로 등록한다(워커는 `testkit.nodes`만 import한다).

- `testkit.epoch.use`: 받은 값을 그대로 내보내는 일반 노드 (예외 목록 밖 소비자)
- `testkit.epoch.hold_poll`: 캡처 → `ctx.sleep` 여러 번 → 캡처, 마지막 장면 이름을 낸다. 폴링 재개
  뒤에도 들고 있던 관측을 버리지 않는다(`reset`을 알리지 않는 노드)
- `testkit.epoch.vars_read`·`vars_write`: SDK `ctx.vars`로 변수를 읽고(가공해) 쓴다
- `testkit.epoch.forge`: 받은 `Match`의 캡처 번호를 새 캡처 번호로 바꿔 클릭한다 ("세대를 위조하는
  워커" 흉내)
- `testkit.epoch.offset_input`: 받은 `Match`에서 뽑은 좌표(`Point`·`Rect`)로 클릭·드래그한다
- `testkit.epoch.unknown_match`: 이 실행이 준 적 없는 캡처 번호를 단 `Match`를 낸다 (출처 없음)
"""

from dataclasses import replace
from typing import Any

from kookabug_sdk import Context, Exit, Result, node
from kookabug_sdk.types import FrameRef, Match, Point, Rect, Target

UNKNOWN_CAPTURE = 999_999


@node(
    type="testkit.epoch.use",
    version=1,
    title="값 쓰기",
    exits=[Exit("done", "ok")],
    outputs={"value": Any},
)
def use(ctx: Context, value: Any) -> Result:
    return Result.ok("done", value=value)


@node(
    type="testkit.epoch.hold_poll",
    version=1,
    title="관측을 버리지 않는 폴링",
    exits=[Exit("done", "ok")],
    outputs={"scene": str},
    effects={"capture"},
)
def hold_poll(ctx: Context, polls: int = 3, poll_ms: int = 100) -> Result:
    first = ctx.capture()
    for _ in range(polls):
        ctx.sleep(poll_ms)
    last = ctx.capture()
    del first  # 첫 캡처를 쥐고 있었다 (폴링 재개 뒤에도 버렸다고 알리지 않는다)
    return Result.ok("done", scene=last.path.stem if last.path is not None else "")


@node(
    type="testkit.epoch.vars_read",
    version=1,
    title="변수 읽기 (SDK)",
    exits=[Exit("done", "ok")],
    outputs={"value": Any},
)
def vars_read(ctx: Context, name: str) -> Result:
    return Result.ok("done", value=ctx.vars.get(name))


@node(
    type="testkit.epoch.vars_write",
    version=1,
    title="변수 가공 (SDK)",
    exits=[Exit("done", "ok")],
)
def vars_write(ctx: Context, src: str, dst: str) -> Result:
    ctx.vars.set(dst, str(ctx.vars.get(src)).upper())
    return Result.ok("done")


@node(
    type="testkit.epoch.forge",
    version=1,
    title="캡처 번호 위조 클릭",
    exits=[Exit("done", "ok")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def forge(ctx: Context, at: Match) -> Result:
    fresh = ctx.capture()
    seen = at.frame_info or FrameRef("fake", (0, 0), 96)
    forged = replace(at, frame_info=replace(seen, capture_id=fresh.capture_id))
    ctx.input.click(forged)
    return Result.ok("done", match=forged)


@node(
    type="testkit.epoch.offset_input",
    version=1,
    title="Match 기준 좌표 입력",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def offset_input(ctx: Context, at: Match, dx: int = 0, mode: str = "click") -> Result:
    """받은 `Match`를 넘기지 않고 거기서 뽑은 좌표로 입력한다 (`click`: 상자 가운데 + `dx` 점,
    `drag`: 상자 → 그 점). 흔한 플러그인 모양 — 재개 전 `Match`면 좌표 입력도 나가면 안 된다."""
    center = at.rect.center
    point = Point(center.x + dx, center.y)
    if mode == "drag":
        ctx.input.drag(at.rect, point)
    else:
        ctx.input.click(point)
    return Result.ok("done")


@node(
    type="testkit.epoch.unknown_match",
    version=1,
    title="출처 없는 Match",
    exits=[Exit("done", "ok")],
    outputs={"match": Match},
)
def unknown_match(ctx: Context, target: Target, rect: list[int]) -> Result:
    x, y, w, h = rect
    match = Match(
        Rect(x, y, w, h),
        0.99,
        window=ctx.window,
        method="stub",
        frame_info=FrameRef("fake", (1024, 640), 96, UNKNOWN_CAPTURE),
        target=target.name,
    )
    return Result.ok("done", match=match)


EPOCH_NODES = (use, hold_poll, vars_read, vars_write, forge, offset_input, unknown_match)
