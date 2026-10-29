"""testkit 노드 선언과 구현."""

import copy
import ctypes
import os
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from kookabug_sdk import Config, Context, DynamicExits, Exit, Output, Result, Retry, node
from kookabug_sdk.types import Image, Match, Point, Rect, Secret

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


# ---------------------------------------------------------------- 프로세스 시나리오 (M0b)
# 워커·runner 검사에서 `--plugin-module testkit.nodes`로 워커가 실행한다. 같은 프로세스 실행기에서는
# 쓰지 않는다 (block·hang·crash는 끝나지 않거나 프로세스를 끝낸다).


@node(type="testkit.block", version=1, title="취소될 때까지 대기", exits=[Exit("done", "ok")])
def block(ctx: Context) -> Result:
    """`blocking`을 기록한 뒤 `ctx.check_cancel()`·`ctx.sleep(10)`을 반복한다 (취소로만 끝난다)."""
    ctx.log.info("blocking")
    while True:
        ctx.check_cancel()
        ctx.sleep(10)


@node(type="testkit.gate", version=1, title="신호 파일 대기", exits=[Exit("done", "ok")])
def gate(ctx: Context, signal: str) -> Result:
    """`gate`를 기록하고 `signal`(절대 경로) 파일이 생길 때까지 협력해 기다린 뒤 정상으로 끝난다."""
    ctx.log.info("gate")
    while not Path(signal).exists():
        ctx.check_cancel()
        ctx.sleep(10)
    return Result.ok("done")


@node(type="testkit.hang", version=1, title="응답 없는 노드", exits=[Exit("done", "ok")])
def hang(ctx: Context, hold_gil: bool = False, label: str | None = None) -> Result:
    """`ctx` 없이 끝나지 않는다(`label`을 주면 그것만 먼저 기록). `hold_gil`이면 GIL을 쥔 채 멈춰
    같은 프로세스의 다른 스레드(RPC 읽기 포함)도 돌지 못한다 (`ctypes.PyDLL` 호출은 GIL을 놓지
    않는다)."""
    if label is not None:
        ctx.log.info(label)
    if hold_gil:
        ctypes.PyDLL("kernel32").Sleep(0xFFFFFFFF)
    while True:
        pass


@node(
    type="testkit.input.hold",
    version=1,
    title="키 누르기",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def input_hold(ctx: Context, key: str = "ctrl", text: str | Secret | None = None) -> Result:
    """`ctx.input.key(key)` (가짜 백엔드 `after_down` 훅과 함께 쓰면 키를 누른 채 멈춘다).
    `text`를 주면 그 뒤 `ctx.input.type_text(text)`."""
    ctx.input.key(key)
    if text is not None:
        ctx.input.type_text(text)
    return Result.ok("done")


@node(
    type="testkit.ctx_roundtrip",
    version=1,
    title="ctx 왕복",
    exits=[Exit("done", "ok")],
    outputs={
        "image": Image,
        "value": Output(Any, nullable=True),
        "value_type": str,
        "has_missing": bool,
        "saved": Output(str, nullable=True),
        "setting": Output(Any, nullable=True),
        "window": Output(str, nullable=True),
    },
    effects={"capture"},
)
def ctx_roundtrip(
    ctx: Context,
    value: Any | None = None,
    message: str = "roundtrip",
    setting_key: str | None = None,
) -> Result:
    """캡처·변수 쓰기/읽기·기록·저장·설정을 한 번씩 하고 받은 값을 돌려준다. `message`는
    `print()`로도 내보낸다(워커 stdout 로그 확인용)."""
    print(f"print: {message}", flush=True)
    image = ctx.capture()
    ctx.vars.set("roundtrip", value)
    got = ctx.vars.get("roundtrip")
    ctx.log.info(f"{message}: {value}")
    saved = ctx.artifacts.save(image, "roundtrip")
    window = ctx.window
    return Result.ok(
        "done",
        image=image,
        value=got,
        value_type="secret" if isinstance(got, Secret) else type(got).__name__,
        has_missing=ctx.vars.has("no_such_var"),
        saved=saved,
        setting=None if setting_key is None else ctx.setting(setting_key),
        window=None if window is None else window.title,
    )


@node(
    type="testkit.read_file",
    version=1,
    title="파일 읽기",
    exits=[Exit("done", "ok")],
    outputs={"text": str},
)
def read_file(ctx: Context, rel: str) -> Result:
    """`ctx.path(rel)`의 파일을 읽어 출력한다."""
    return Result.ok("done", text=ctx.path(rel).read_text(encoding="utf-8"))


@node(type="testkit.crash", version=1, title="프로세스 종료", exits=[Exit("done", "ok")])
def crash(ctx: Context, code: int = 3) -> Result:
    """프로세스를 곧바로 끝낸다 (`os._exit(code)`)."""
    os._exit(code)


@node(type="testkit.ctx_sneak", version=1, title="선언 없는 캡처", exits=[Exit("done", "ok")])
def ctx_sneak(ctx: Context, swallow: bool = False) -> Result:
    """`capture` 효과를 선언하지 않고, SDK 제한을 건너뛰어(`ctx.inner`) 캡처를 요청한다.
    `swallow`면 그 오류를 삼키고 정상으로 끝난다 (runner가 다시 검사하는지 확인용)."""
    try:
        getattr(ctx, "inner").capture()  # noqa: B009 - 제한 래퍼를 일부러 건너뛴다
    except Exception:
        if not swallow:
            raise
    return Result.ok("done")


@node(
    type="testkit.ctx_replay",
    version=1,
    title="다른 실행 번호로 ctx 요청",
    exits=[Exit("done", "ok")],
    outputs={"rejected": Output(str, nullable=True)},
    effects={"capture"},
)
def ctx_replay(ctx: Context, offset: int = -1) -> Result:
    """워커 ctx를 건너뛰어 지금 실행 번호 + `offset`을 실은 캡처 요청을 runner에 직접 보낸다
    ("끝난 실행의 요청을 다시 보내는 워커" 흉내). runner가 거부한 오류 메시지를 출력한다."""
    inner = getattr(ctx, "inner")  # noqa: B009 - 제한 래퍼를 일부러 건너뛴다
    request = getattr(inner, "_request")  # noqa: B009
    try:
        request("ctx.capture", {"invoke": inner.invoke + offset, "region": None})
    except Exception as exc:
        return Result.ok("done", rejected=str(exc))
    return Result.ok("done", rejected=None)


@node(type="testkit.liar", version=1, title="선언과 다른 결과", exits=[Exit("done", "ok")])
def liar(ctx: Context) -> Result:
    """선언하지 않은 출구로 나간다. 워커 쪽 대조를 꺼 두었으므로 runner의 재대조만 잡는다."""
    return Result.ok("other")


# 워커 쪽 SDK 대조를 건너뛰는 "믿을 수 없는 워커" 흉내
setattr(liar, "check_result", lambda returned, config: returned)  # noqa: B010


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
    block,
    gate,
    hang,
    input_hold,
    ctx_roundtrip,
    read_file,
    crash,
    ctx_sneak,
    ctx_replay,
    liar,
)
