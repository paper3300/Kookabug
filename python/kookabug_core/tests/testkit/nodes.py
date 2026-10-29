"""testkit 노드 선언과 구현."""

import copy
from collections import Counter
from typing import Any, Literal

from kookabug_sdk import Config, Context, DynamicExits, Exit, Output, Result, Retry, node
from kookabug_sdk.types import Image, Match, Point, Rect

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
    type="testkit.observe.flaky",
    version=1,
    title="시도마다 다른 결과",
    exits=[Exit("found", "ok"), Exit("timeout", "fail"), Exit("missing", "fail")],
    outputs={"seen": int},
    retry=Retry.observation(on=["timeout", "missing"]),
)
def observe_flaky(ctx: Context, script: list[str], seen: int = 0) -> Result:
    """부를 때마다 `script`의 다음 결과를 낸다 (`COUNTS["flaky"]`번째, 끝나면 마지막 것).

    `"found"`면 `seen`(받은 입력 그대로)을 출력, `"boom"`이면 예외, 그 밖은 그 fail 출구."""
    pick = script[min(COUNTS["flaky"], len(script) - 1)]
    COUNTS["flaky"] += 1
    if pick == "found":
        return Result.ok("found", seen=seen)
    if pick == "boom":
        raise RuntimeError("flaky boom")
    return Result.fail(pick, f"testkit.observe.flaky: {pick}")


SEEN: list[Any] = []
"""`testkit.observe.consume`가 시도마다 받은 입력 (깊은 복사). 테스트마다 비운다."""


@node(
    type="testkit.observe.consume",
    version=1,
    title="받은 입력을 고치는 관측",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    retry=Retry.observation(on=["timeout"]),
)
def observe_consume(ctx: Context, targets: list[list[int]]) -> Result:
    """받은 `targets`를 `SEEN`에 남기고 안쪽 목록 첫 값을 꺼낸다(작업용으로 고침).

    첫 호출은 `timeout`, 그 뒤는 `found`."""
    SEEN.append(copy.deepcopy(targets))
    for inner in targets:
        if inner:
            inner.pop(0)
    return Result.fail("timeout", "다음 시도") if len(SEEN) == 1 else Result.ok("found")


@node(
    type="testkit.observe.wait_any",
    version=1,
    title="가짜 화면 여럿 대기",
    config={"exits": Config(list[str])},
    exits=DynamicExits(from_config="exits", extra=[Exit("timeout", "fail")]),
    outputs={"match": Output(Match)},
    effects={"capture"},
)
def observe_wait_any(
    ctx: Context, targets: dict[str, str], timeout_ms: int = 1000, poll_ms: int = 100
) -> Result:
    """`targets`(출구 → 프레임 이름) 중 먼저 보이는 출구로 나간다.

    동시에 보이면 `config.exits` 앞쪽."""
    deadline = ctx.deadline(timeout_ms)
    while True:
        ctx.check_cancel()
        frame = ctx.capture()
        stem = frame.path.stem if frame.path is not None else None
        for exit in ctx.config["exits"]:
            if targets.get(exit) == stem:
                return Result.ok(exit, match=Match(Rect(0, 0, 1, 1), 1.0, frame=frame.frame))
        if deadline.passed:
            return Result.fail(
                "timeout", f"{sorted(targets)} 중 {timeout_ms}ms 안에 보인 것이 없다"
            )
        ctx.sleep(min(poll_ms, deadline.remaining_ms))


@node(
    type="testkit.read_text",
    version=1,
    title="가짜 글자 읽기",
    exits=[Exit("done", "ok"), Exit("unreadable", "fail")],
    outputs={"text": str},
)
def read_text(ctx: Context, text: str = "text", readable: bool = True) -> Result:
    """`readable`이면 `text`를 출력하고 `done`, 아니면 `unreadable`로 나간다."""
    if readable:
        return Result.ok("done", text=text)
    return Result.fail("unreadable", "testkit.read_text: 읽을 수 없다")


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


@node(type="testkit.input.sneak", version=1, title="선언 없는 입력", exits=[Exit("done", "ok")])
def input_sneak(ctx: Context) -> Result:
    """`effects`에 `input`을 선언하지 않고 누른다 (→ error)."""
    ctx.input.click(Point(0, 0))
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


@node(
    type="testkit.config_value",
    version=1,
    title="config 읽기",
    config={"n": Config(int, default=3)},
    exits=[Exit("done", "ok")],
    outputs={"n": int},
)
def config_value(ctx: Context) -> Result:
    """`ctx.config["n"]`(기본 3)을 출력한다."""
    return Result.ok("done", n=ctx.config["n"])


@node(
    type="testkit.mutate",
    version=1,
    title="받은 목록 고치기",
    exits=[Exit("done", "ok")],
    outputs={"items": list[Any]},
)
def mutate(ctx: Context, items: list[Any]) -> Result:
    """받은 목록 안쪽까지 고치고(`"x"` 덧붙임, 안쪽 목록에도) 그 목록을 출력한다."""
    items.append("x")
    for item in items:
        if isinstance(item, list):
            inner: list[Any] = item
            inner.append("x")
    return Result.ok("done", items=items)


@node(
    type="testkit.shot",
    version=1,
    title="캡처와 저장",
    exits=[Exit("done", "ok")],
    outputs={
        "image": Output(Image, nullable=True),
        "saved": Output(str, nullable=True),
    },
    effects={"capture"},
)
def shot(
    ctx: Context,
    name: str = "shot",
    captures: int = 1,
    save: bool = False,
    image: Image | None = None,
    boom: bool = False,
    value: Any | None = None,
) -> Result:
    """기록 정책 시나리오용. `captures`번 캡처(마지막 것을 출력), `save`면 저장(`image`를 주면
    그것을), `boom`이면 그 뒤 예외. `value`는 받기만 한다(비밀값 입력 스텝 만들기). 출력 `saved`는
    `ctx.artifacts.save`의 반환값(생략이면 null)."""
    frame: Image | None = None
    for _ in range(captures):
        frame = ctx.capture()
    saved: str | None = None
    target = image if image is not None else frame
    if save and target is not None:
        saved = ctx.artifacts.save(target, name)
    if boom:
        raise RuntimeError("testkit.shot boom")
    return Result.ok("done", image=frame, saved=saved)


COUNTS: Counter[str] = Counter()
"""`testkit.pure.count`가 계산된 횟수 (키별). 테스트마다 비운다."""


@node(
    type="testkit.pure.count",
    version=1,
    title="계산 횟수",
    pure=True,
    outputs={"n": int},
)
def pure_count(ctx: Context, key: str = "c") -> dict[str, Any]:
    """계산될 때마다 `COUNTS[key]`를 1 올리고 그 값을 준다 (순수 노드 계산 횟수 확인용)."""
    COUNTS[key] += 1
    return {"n": COUNTS[key]}


@node(
    type="testkit.pure.capture",
    version=1,
    title="캡처하는 순수 노드",
    pure=True,
    outputs={"ok": bool},
)
def pure_capture(ctx: Context) -> dict[str, Any]:
    """순수 노드인데 캡처한다 (금지 → error)."""
    ctx.capture()
    return {"ok": True}


@node(
    type="testkit.pure.log", version=1, title="기록하는 순수 노드", pure=True, outputs={"ok": bool}
)
def pure_log(ctx: Context) -> dict[str, Any]:
    """순수 노드인데 기록한다 (금지 → error)."""
    ctx.log.info("순수 노드 기록")
    return {"ok": True}


NODES = (
    observe_wait,
    observe_flaky,
    observe_consume,
    observe_wait_any,
    read_text,
    input_tap,
    input_sneak,
    boom,
    fail_once,
    choose,
    config_value,
    mutate,
    shot,
    pure_count,
    pure_capture,
    pure_log,
)
