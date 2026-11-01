"""testkit M1 노드: runner 연결(공용 입력 서비스·창·관측 RPC) 검사용 (구현 계획 M1 T9).

`testkit.nodes`가 가져와 같은 플러그인으로 등록한다(워커는 `testkit.nodes`만 import한다).
"""

import time
from pathlib import Path
from typing import Any

from kookabug_sdk import Context, Exit, ObservationTimeout, Output, Result, RunnerError, node
from kookabug_sdk.types import Image, Match, Point, ProcessRef, Rect, Target, WindowRef


@node(
    type="testkit.m1.find_click",
    version=1,
    title="찾고 클릭",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Output(Match, nullable=True)},
    effects={"capture", "input"},
)
def find_click(ctx: Context, target: Target, swallow: bool = False) -> Result:
    """캡처 → `ctx.vision.find(target)` → 찾은 `Match`로 클릭. `swallow`면 클릭의 어떤 예외도
    삼키고 정상으로 끝난다 (재검증 실패를 노드가 삼켜도 실행기가 보는지 확인용)."""
    match = ctx.vision.find(ctx.capture(), target)
    if match is None:
        return Result.fail("not_found", "target을 찾지 못했다")
    try:
        ctx.input.click(match)
    except BaseException:
        if not swallow:
            raise
    return Result.ok("done", match=match)


@node(
    type="testkit.m1.find",
    version=1,
    title="찾기",
    exits=[Exit("found", "ok"), Exit("not_found", "fail")],
    outputs={"match": Output(Match, nullable=True)},
    effects={"capture"},
)
def find(ctx: Context, target: Target) -> Result:
    match = ctx.vision.find(ctx.capture(), target)
    if match is None:
        return Result.fail("not_found", "target을 찾지 못했다")
    return Result.ok("found", match=match)


@node(
    type="testkit.m1.click",
    version=1,
    title="클릭",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def click(ctx: Context, at: Match | Rect | Point, count: int = 1) -> Result:
    """받은 위치(`Match`·`Rect`·`Point`)를 클릭한다 (`image.click` 자리)."""
    ctx.input.click(at, count=count)
    return Result.ok("done")


@node(
    type="testkit.m1.key",
    version=1,
    title="키",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def key(ctx: Context, key: str, hold_ms: int = 0) -> Result:
    ctx.input.key(key, hold_ms=hold_ms)
    return Result.ok("done")


@node(
    type="testkit.m1.type",
    version=1,
    title="글자",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def type_text(ctx: Context, text: str) -> Result:
    ctx.input.type_text(text)
    return Result.ok("done")


@node(
    type="testkit.m1.window",
    version=1,
    title="현재 창",
    exits=[Exit("done", "ok")],
    outputs={"handle": Output(int, nullable=True), "title": Output(str, nullable=True)},
)
def window(ctx: Context) -> Result:
    """이 스텝 ctx의 창."""
    win = ctx.window
    return Result.ok(
        "done", handle=None if win is None else win.handle, title=None if win is None else win.title
    )


@node(
    type="testkit.m1.set_window",
    version=1,
    title="창 바꾸기",
    exits=[Exit("done", "ok"), Exit("missing", "fail")],
    outputs={"handle": Output(int, nullable=True), "kept": Output(int, nullable=True)},
)
def set_window(ctx: Context, title: str) -> Result:
    """`ctx.windows.find(title)` → `ctx.set_window`. `kept`는 바꾼 뒤에도 이 노드가 보는 창."""
    found = ctx.windows.find(title)
    if found is None:
        return Result.fail("missing", f"창 {title!r}이(가) 없다")
    ctx.set_window(found)
    kept = ctx.window
    return Result.ok("done", handle=found.handle, kept=None if kept is None else kept.handle)


@node(
    type="testkit.m1.launch",
    version=1,
    title="띄우고 창 정하기",
    exits=[Exit("done", "ok"), Exit("timeout", "fail")],
    outputs={
        "handle": Output(int, nullable=True),
        "pid": int,
        "window": Output(WindowRef, nullable=True),
    },
    effects={"process"},
)
def launch(
    ctx: Context, path: str, args: list[str] | None = None, timeout_ms: int = 5000
) -> Result:
    """`ctx.process.launch` → 그 프로세스 창을 기다려 현재 창으로."""
    process = ctx.process.launch(path, args or [])
    try:
        found = ctx.process.find_window(process, deadline=ctx.deadline(timeout_ms))
    except ObservationTimeout:
        found = None
    if found is None:
        return Result.fail("timeout", "창이 뜨지 않았다")
    ctx.set_window(found)
    ctx.windows.activate(found)
    return Result.ok("done", handle=found.handle, pid=process.pid, window=found)


@node(
    type="testkit.m1.switch_click",
    version=1,
    title="창을 바꾸고 클릭",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def switch_click(ctx: Context, to: WindowRef, x: int, y: int) -> Result:
    """`ctx.set_window(to)` 뒤 클릭. 클릭은 이 스텝의 창으로 가야 한다(요청 창은 만들 때 정해짐)."""
    ctx.set_window(to)
    ctx.input.click(Point(x, y))
    return Result.ok("done")


@node(
    type="testkit.m1.find_window_wait",
    version=1,
    title="창 기다리기",
    exits=[Exit("found", "ok"), Exit("timeout", "fail", outputs=["elapsed_ms"])],
    outputs={"elapsed_ms": int},
    effects={"process"},
)
def find_window_wait(ctx: Context, pid: int, timeout_ms: int = 100) -> Result:
    started = time.monotonic()
    try:
        ctx.process.find_window(
            ProcessRef(pid), "no such window", deadline=ctx.deadline(timeout_ms)
        )
    except ObservationTimeout:
        return Result.fail("timeout", "창이 뜨지 않았다", elapsed_ms=_ms(started))
    return Result.ok("found", elapsed_ms=_ms(started))


@node(
    type="testkit.m1.capture_wait",
    version=1,
    title="기한 있는 캡처",
    exits=[Exit("done", "ok"), Exit("timeout", "fail", outputs=["elapsed_ms"])],
    outputs={"elapsed_ms": int},
    effects={"capture"},
)
def capture_wait(ctx: Context, timeout_ms: int = 100) -> Result:
    """노드 기한 `timeout_ms`로 캡처 한 번. 노드 기한이면 `timeout`."""
    started = time.monotonic()
    try:
        ctx.capture(deadline=ctx.deadline(timeout_ms))
    except ObservationTimeout:
        return Result.fail(
            "timeout", "캡처가 노드 기한 안에 끝나지 않았다", elapsed_ms=_ms(started)
        )
    return Result.ok("done", elapsed_ms=_ms(started))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@node(
    type="testkit.m1.capture_ref",
    version=1,
    title="참조 캡처",
    exits=[Exit("done", "ok")],
    outputs={"image": Image, "has_pixels": bool},
    effects={"capture"},
)
def capture_ref(ctx: Context) -> Result:
    image = ctx.capture()
    return Result.ok(
        "done", image=image, has_pixels=image.data is not None or image.path is not None
    )


@node(
    type="testkit.m1.diff",
    version=1,
    title="두 캡처 비교",
    exits=[Exit("done", "ok")],
    outputs={"value": float, "same_ids": bool},
    effects={"capture", "input"},
)
def diff(ctx: Context, click: list[int] | None = None) -> Result:
    """`a = capture()` → (`click`이면 그 점 클릭) → `b = capture()` → `diff(a, b)`."""
    a = ctx.capture()
    if click is not None:
        ctx.input.click(Point(click[0], click[1]))
    b = ctx.capture()
    return Result.ok("done", value=ctx.vision.diff(a, b), same_ids=a.capture_id == b.capture_id)


@node(
    type="testkit.m1.expired",
    version=1,
    title="버린 프레임 쓰기",
    exits=[Exit("done", "ok")],
    outputs={"code": Output(str, nullable=True)},
    effects={"capture"},
)
def expired(ctx: Context, target: Target, catch: bool = False) -> Result:
    """캡처를 여러 번 한 뒤 세 번째 캡처에서 찾는다 (스텝 최근 두 개에서 밀려났고, 첫 캡처가 아니며,
    증거 표본이 넘쳐 하나 걸러 버릴 때 빠졌다 — M3 2.6). `catch`면 그 오류의 코드를 출력한다."""
    ctx.capture()
    ctx.capture()
    victim = ctx.capture()
    for _ in range(10):
        ctx.capture()
    try:
        ctx.vision.find(victim, target)
    except RunnerError as exc:
        if not catch:
            raise
        return Result.ok("done", code=exc.code)
    return Result.ok("done", code=None)


@node(
    type="testkit.m1.vision_sneak",
    version=1,
    title="선언 없는 찾기",
    exits=[Exit("done", "ok")],
)
def vision_sneak(ctx: Context) -> Result:
    """`capture` 효과 없이 SDK 제한을 건너뛰어(`ctx.inner`) 찾기를 요청한다."""
    inner: Any = getattr(ctx, "inner")  # noqa: B009 - 제한 래퍼를 일부러 건너뛴다
    inner.vision.find(Image(1, 1, capture_id=1), Target("t", Path("targets/t.target.json")))
    return Result.ok("done")


@node(
    type="testkit.m1.tour",
    version=1,
    title="M1 ctx 한 바퀴",
    exits=[Exit("done", "ok")],
    outputs={"closed": bool, "diff": float, "found": bool},
    effects={"capture", "input", "process"},
)
def tour(ctx: Context, target: Target) -> Result:
    """M1의 창·프로세스·관측·입력 ctx를 한 번씩 부른다 (RPC 메시지 스키마 검사용)."""
    process = ctx.process.launch("game.exe", ["--size", "1024x640"])
    win = ctx.process.find_window(process, deadline=ctx.deadline(2000))
    assert win is not None
    ctx.set_window(win)
    found = ctx.windows.find("Sample", None, owned=False)
    assert found is not None
    info = ctx.windows.info(found)
    ctx.windows.set_client_size(found, *info.client_size)
    ctx.windows.activate(found)
    image = ctx.capture(deadline=ctx.deadline(2000))
    match = ctx.vision.find(image, target, deadline=ctx.deadline(2000))
    value = ctx.vision.diff(image, image)
    ctx.ocr.read(image, region=Rect(0, 0, 100, 50), sensitive=True, deadline=ctx.deadline(2000))
    ctx.input.drag(Point(1, 1), Point(5, 5), duration_ms=0)
    ctx.input.scroll(Point(1, 1), 1)
    ctx.input.click(Point(1, 1), count=2)
    ctx.input.key("a", hold_ms=10)
    closed = ctx.process.close(process, 100)
    return Result.ok("done", closed=closed, diff=value, found=match is not None)


M1_NODES = (
    tour,
    find_click,
    find,
    click,
    key,
    type_text,
    window,
    set_window,
    launch,
    switch_click,
    find_window_wait,
    capture_wait,
    capture_ref,
    diff,
    expired,
    vision_sneak,
)
