"""화면 검증 노드: 보이는지·안 보이는지·OCR 문구.

검증 노드(`assertion`)라 `ok`로 끝나면 판정의 "검증 하나 이상 성공"에 든다. 화면은 바로 바뀌지
않을 수 있으므로 `timeout_ms`(기본 5초) 동안 다시 보고, 그래도 아니면 `fail`이다. 바로 판정하려면
`timeout_ms: 0`(관측 한 번). 민감 target 영역에서 읽은 글자는 실패 메시지·출력에서 가린다.
"""

import re
from typing import Annotated

from kookabug_nodes._observe import locate, plain, poll, read_area, shown_text
from kookabug_sdk import Context, Exit, Input, Result, Retry, Secret, message_with_secrets, node
from kookabug_sdk.context import Deadline
from kookabug_sdk.types import Image, Match, OcrResult, Rect, Target


@node(
    type="core.assert.visible",
    version=1,
    title="보이는지 검증",
    category="test",
    exits=[Exit("ok", "ok"), Exit("fail", "fail")],
    outputs={"match": Match},
    effects={"capture"},
    assertion=True,
    retry=Retry.observation(on=["fail"]),
)
def visible(
    ctx: Context, target: Target, timeout_ms: Annotated[int, Input(minimum=0)] = 5000
) -> Result:
    """대상이 보이는지 검증한다 (`timeout_ms` 안에 한 번이라도 보이면 `ok`)."""
    found, _ = poll(ctx, timeout_ms, lambda f, d: ctx.vision.find(f, target, deadline=d))
    if found is not None:
        return Result.ok("ok", match=found)
    return Result.fail("fail", f"'{target.name}'이(가) 보이지 않는다 ({timeout_ms}ms)")


@node(
    type="core.assert.not_visible",
    version=1,
    title="안 보이는지 검증",
    category="test",
    exits=[Exit("ok", "ok"), Exit("fail", "fail")],
    effects={"capture"},
    assertion=True,
    retry=Retry.observation(on=["fail"]),
)
def not_visible(
    ctx: Context, target: Target, timeout_ms: Annotated[int, Input(minimum=0)] = 5000
) -> Result:
    """대상이 안 보이는지 검증한다 (`timeout_ms` 안에 한 번이라도 안 보이면 `ok`)."""
    gone, _ = poll(
        ctx,
        timeout_ms,
        lambda f, d: True if ctx.vision.find(f, target, deadline=d) is None else None,
    )
    if gone:
        return Result.ok("ok")
    return Result.fail("fail", f"'{target.name}'이(가) 계속 보인다 ({timeout_ms}ms)")


def _matches(text: str, equals: str | None, contains: str | None, regex: str | None) -> bool:
    if equals is not None:
        return text.strip() == equals.strip()
    if contains is not None:
        return contains in text
    assert regex is not None
    return re.search(regex, text) is not None


@node(
    type="core.assert.text",
    version=1,
    title="문구 검증",
    category="test",
    exits=[Exit("ok", "ok"), Exit("fail", "fail", outputs=["text"])],
    outputs={"text": str | Secret},
    effects={"capture"},
    assertion=True,
    retry=Retry.observation(on=["fail"]),
)
def text(
    ctx: Context,
    region: Target | Rect | None = None,
    equals: str | None = None,
    contains: str | None = None,
    regex: str | None = None,
    timeout_ms: Annotated[int, Input(minimum=0)] = 5000,
) -> Result:
    """영역에서 읽은 글자를 검증한다: `equals`(앞뒤 공백 무시 같음)·`contains`(부분 일치)·
    `regex`(검색) 중 하나. `timeout_ms` 안에 한 번이라도 맞으면 `ok`. `text`는 마지막으로 읽은
    글자(민감 target이면 비밀값)."""
    given = [v for v in (equals, contains, regex) if v is not None]
    if len(given) != 1:
        raise ValueError("equals·contains·regex 중 하나만 준다")
    if regex is not None:
        re.compile(regex)
    last: list[OcrResult] = []

    def look(frame: Image, deadline: Deadline | None) -> OcrResult | None:
        area = locate(ctx, frame, region, deadline)
        if area is None:
            return None
        result = read_area(ctx, frame, area, deadline)
        last[:] = [result]
        return result if _matches(plain(result.text), equals, contains, regex) else None

    # 디버거 재개 전 읽은 글자는 fail 출력(`text`)으로 내지 않는다 (재개 뒤 관측으로 세탁됨)
    found, _ = poll(ctx, timeout_ms, look, on_reset=last.clear)
    if found is not None:
        return Result.ok("ok", text=found.text)
    if not last:
        name = region.name if isinstance(region, Target) else "?"
        return Result.fail("fail", f"영역 target '{name}'이(가) 보이지 않는다", text="")
    read = last[0].text
    wanted = (
        f"{equals!r}와(과) 같지"
        if equals is not None
        else f"{contains!r}을(를) 포함하지"
        if contains is not None
        else f"/{regex}/에 맞지"
    )
    # 민감 target의 글자는 기록 정책(record.redact_secrets)대로 가리거나 원문으로 남는다
    message = message_with_secrets(
        lambda s: f"읽은 글자 {shown_text(read, s)}이(가) {wanted} 않는다"
    )
    return Result.fail("fail", message, text=read)
