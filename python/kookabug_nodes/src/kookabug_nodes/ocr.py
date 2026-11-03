"""OCR 노드: 글자 읽기·문구 대기·문구 클릭.

- `region`: 찾기 대상(`$target`, 지금 화면에서 찾은 상자 안을 읽음) 또는 사각형(클라이언트 픽셀
  `[x, y, w, h]`), 없으면 화면 전체(느리다 — MVP 노드 목록 5장)
- `text`: 줄을 위→아래로 `\\n`으로 이은 것. `confidence`: 상자 점수 평균(글자 없으면 `null`)
- `parse: "number"`: 천 단위 구분(`,`·공백, 세 자리 묶음)을 빼고 처음 나오는 수
- `sensitive: true` target으로 읽은 `text`는 `secret`, `number`는 `null`이다. 비교는 노드 안에서만
  원문으로 하고 출력·메시지에는 가린 값만 낸다. 그 스텝의 OCR 글자 기록은 러너가 생략한다
  (`omitted.reason = "sensitive_target"`)
"""

import re
from typing import Annotated, Final, Literal

from kookabug_nodes._observe import (
    Area,
    line_match,
    locate,
    plain,
    poll,
    read_area,
    save_last,
    shown_text,
)
from kookabug_sdk import (
    Context,
    Exit,
    Input,
    Output,
    Result,
    Retry,
    Secret,
    message_with_secrets,
    node,
)
from kookabug_sdk.context import Deadline
from kookabug_sdk.types import Image, Match, OcrLine, OcrResult, Rect, Target

Button = Literal["left", "right", "middle", "x1", "x2"]

_MINUS: Final = chr(0x2212)  # 유니코드 빼기 기호
_NUMBER: Final = re.compile(rf"[+\-{_MINUS}]?(?:\d{{1,3}}(?:[, ]\d{{3}})+|\d+)(?:\.\d+)?")


def parse_number(text: str) -> int | float | None:
    """처음 나오는 수. 천 단위 구분(`,`·공백, 세 자리 묶음)은 뺀다. 소수점이 있으면 float.
    (플랫폼 OCR 엔진의 `parse_number`와 같은 규칙 — 노드는 플랫폼 패키지에 의존하지 않는다)"""
    m = _NUMBER.search(text)
    if m is None:
        return None
    raw = m.group().replace(",", "").replace(" ", "").replace(_MINUS, "-")
    return float(raw) if "." in raw else int(raw)


def _rows(result: OcrResult) -> list[tuple[str, tuple[OcrLine, ...]]]:
    """`text`의 줄마다 (줄 글자, 그 줄의 글자 상자들). 상자는 줄 순서로 정렬돼 있으므로 줄 글자를
    공백 없이 다 채울 때까지 앞에서부터 가져간다."""
    boxes = result.lines
    rows: list[tuple[str, tuple[OcrLine, ...]]] = []
    i = 0
    for row in plain(result.text).split("\n"):
        want = len(row.replace(" ", ""))
        start, got = i, 0
        while i < len(boxes) and got < want:
            got += len(plain(boxes[i].text).replace(" ", ""))
            i += 1
        rows.append((row, boxes[start:i]))
    return rows


def find_text(
    result: OcrResult, contains: str | None = None, regex: str | None = None
) -> tuple[OcrLine, ...] | None:
    """문구가 있는 글자 상자들. 상자 하나 안에 있으면 그 상자, 한 줄에 걸치면 그 줄의 상자들,
    여러 줄에 걸치면 전부. 없으면 None."""
    if (contains is None) == (regex is None):
        raise ValueError("contains와 regex 중 하나만 준다")
    pattern = re.compile(regex if regex is not None else re.escape(contains or ""))

    def hit(text: str) -> bool:
        return pattern.search(text) is not None

    for line in result.lines:
        if hit(plain(line.text)):
            return (line,)
    for row, boxes in _rows(result):
        if boxes and hit(row):
            return boxes
    if result.lines and hit(plain(result.text)):
        return result.lines
    return None


@node(
    type="core.ocr.read",
    version=1,
    title="글자 읽기",
    category="ocr",
    exits=[Exit("done", "ok"), Exit("unreadable", "fail")],
    outputs={
        "text": str | Secret,
        "number": Output(float, nullable=True),
        "confidence": Output(float, nullable=True),
    },
    effects={"capture"},
    retry=Retry.observation(on=["unreadable"]),
)
def read(
    ctx: Context, region: Target | Rect | None = None, parse: Literal["text", "number"] = "text"
) -> Result:
    """영역의 글자를 읽는다. 글자가 없거나(`parse: "number"`면 수가 없거나) 영역 target이 지금
    화면에 없으면 `unreadable`."""
    frame = ctx.capture()
    area = locate(ctx, frame, region)
    if area is None:
        assert isinstance(region, Target)
        return Result.fail("unreadable", f"영역 target '{region.name}'이(가) 지금 화면에 없다")
    result = read_area(ctx, frame, area)
    raw = plain(result.text)
    if not raw.strip():
        return Result.fail("unreadable", "글자를 읽지 못했다")
    number = parse_number(raw) if parse == "number" else None
    if parse == "number" and number is None:
        text = result.text
        message = message_with_secrets(lambda s: f"읽은 글자 {shown_text(text, s)}에 수가 없다")
        return Result.fail("unreadable", message)
    return Result.ok(
        "done",
        text=result.text,
        number=None if area.sensitive else number,
        confidence=result.confidence,
    )


@node(
    type="core.ocr.wait_text",
    version=1,
    title="문구 대기",
    category="ocr",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"text": str | Secret, "match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait_text(
    ctx: Context,
    region: Target | Rect | None = None,
    contains: str | None = None,
    regex: str | None = None,
    timeout_ms: Annotated[int, Input(minimum=0)] = 10000,
) -> Result:
    """영역에 문구(`contains` 부분 일치 또는 `regex` 검색, 하나만)가 나타날 때까지 기다린다.
    `match`는 그 문구가 있는 줄 상자다. 되풀이해 읽으므로 영역을 주는 것이 기본이다."""
    find_text(OcrResult(""), contains, regex)  # 인자 확인 (기다리기 전에)

    def look(frame: Image, deadline: Deadline | None) -> tuple[OcrResult, Match] | None:
        area = locate(ctx, frame, region, deadline)
        if area is None:
            return None
        result = read_area(ctx, frame, area, deadline)
        lines = find_text(result, contains, regex)
        return None if lines is None else (result, line_match(ctx, frame, area, result, lines))

    found, frame = poll(ctx, timeout_ms, look)
    if found is not None:
        return Result.ok("found", text=found[0].text, match=found[1])
    save_last(ctx, frame, "timeout")
    wanted = f"/{regex}/" if regex is not None else repr(contains)
    return Result.fail("timeout", f"문구 {wanted}이(가) {timeout_ms}ms 안에 보이지 않았다")


@node(
    type="core.ocr.click_text",
    version=1,
    title="문구 클릭",
    category="ocr",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def click_text(
    ctx: Context,
    text: str,
    region: Target | Rect | None = None,
    button: Button = "left",
    timeout_ms: Annotated[int, Input(minimum=0)] = 10000,
) -> Result:
    """영역에서 `text`가 들어 있는 줄을 찾아(보일 때까지 기다림) 그 줄 가운데를 클릭한다. 못 찾으면
    입력하지 않고 `not_found`."""
    if not text:
        raise ValueError("text가 비어 있다")

    def look(frame: Image, deadline: Deadline | None) -> Match | None:
        area: Area | None = locate(ctx, frame, region, deadline)
        if area is None:
            return None
        result = read_area(ctx, frame, area, deadline)
        lines = find_text(result, contains=text)
        return None if lines is None else line_match(ctx, frame, area, result, lines)

    found, frame = poll(ctx, timeout_ms, look)
    if found is None:
        save_last(ctx, frame, "not_found")
        return Result.fail("not_found", f"문구 {text!r}이(가) {timeout_ms}ms 안에 보이지 않았다")
    ctx.input.click(found, button=button)
    return Result.ok("done", match=found)
