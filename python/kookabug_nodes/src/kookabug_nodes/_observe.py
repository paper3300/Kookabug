"""대기·관측 노드 공용: 폴링, 영역(`region`) 정하기, 민감 target, 증거 저장.

- 기다리는 노드는 `ctx.deadline(timeout_ms)`를 관측 호출(캡처·찾기·OCR)에 넘긴다. 관측이 노드
  기한에 걸리면 `ObservationTimeout`이고 그 노드의 `timeout`(또는 `not_found`·`fail`) 출구다.
  설정 기한(`capture_timeout`)·전체 기한은 노드가 잡지 않는다 (구현 계획 M1 2.6). 예외: 첫 프레임의
  찾기·OCR은 노드 기한 없이 끝까지 한다 (`poll`)
- 화면이 멈춰 있으면 캡처는 같은 프레임을 다시 준다(오류가 아님). 그래서 없는 대상을 기다리는
  노드는 `timeout_ms` 안에 `timeout`으로 끝난다
- `region`은 찾기 대상(`$target` — 지금 화면에서 찾은 상자) 또는 사각형(클라이언트 픽셀
  `[x, y, w, h]`), 없으면 화면 전체다. `sensitive: true` target이면 그 영역에서 읽은 글자는
  `Secret`이다
- 폴링 사이(`ctx.sleep`)에서 디버거로 멈췄다 재개하면 들고 있던 관측(직전 프레임·후보·안정 시간)을
  버리고 재개 뒤 프레임으로 처음부터 다시 본다 (구현 계획 M3 2.4 "폴링 재개"). 받은 입력이 재개 전
  관측이면 `ctx.sleep`이 `StaleObservation`으로 끝낸다
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from kookabug_sdk import Context, ObservationTimeout
from kookabug_sdk.context import Deadline
from kookabug_sdk.types import Image, Match, OcrLine, OcrResult, Rect, Secret, Target

__all__ = [
    "POLL_MS",
    "Area",
    "check_region",
    "line_match",
    "locate",
    "observations_reset",
    "plain",
    "poll",
    "read_area",
    "reset_observations",
    "save_last",
    "sensitive",
    "shown_text",
]

POLL_MS: Final = 100
"""대기 노드가 관측 사이에 쉬는 시간."""


def poll[T](
    ctx: Context,
    timeout_ms: int,
    look: Callable[[Image, Deadline | None], T | None],
    on_reset: Callable[[], None] | None = None,
) -> tuple[T | None, Image | None]:
    """`look(프레임, 노드 기한)`이 값을 줄 때까지 `timeout_ms` 동안 캡처해 본다. `(값, 마지막
    프레임)`이고, 기한 안에 못 얻으면 값이 None이다. `timeout_ms`가 0이면 기다리지 않고 지금 화면을
    한 번만 본다(노드 기한 없이 — 설정 기한·전체 기한만). 0이 아니어도 첫 프레임의 `look`은 노드
    기한 없이 받는다 — 대기는 적어도 한 번은 끝까지 보고(매칭 후보가 남는다) timeout이 된다. 그
    관측이 노드 기한 뒤에 끝났으면 결과는 버리고(`on_reset`도 부른다) timeout이다(캡처는 노드 기한
    그대로). 매칭 후보(진단 증거)는 남는다.

    `look`이 폴링을 넘어 관측을 쥐면(읽은 글자 등) `on_reset`으로 그것을 버린다 — 디버거로 멈췄다
    재개하면 직전 프레임과 함께 부른 뒤 버렸다고 알린다. 첫 관측이 노드 기한 뒤에 끝났을 때도
    부른다. 쥔 관측을 버리지 않고 알리면 재개 전 값이
    재개 뒤 관측으로 세탁된다."""
    if timeout_ms == 0:
        ctx.check_cancel()
        now = ctx.capture()
        return look(now, None), now
    deadline = ctx.deadline(timeout_ms)
    frame: Image | None = None
    looked = False
    try:
        while True:
            ctx.check_cancel()
            frame = ctx.capture(deadline=deadline)
            # 첫 프레임은 노드 기한으로 끊지 않고 끝까지 본다(설정·전체 기한만): 느린 환경에서 찾기
            # 한 번이 `timeout_ms`보다 길면 한 번도 못 보고 timeout이 되어 매칭 후보도 남지 않는다
            first = not looked
            looked = True
            found = look(frame, None if first else deadline)
            if first and deadline.passed:
                # 노드 기한 뒤에 끝난 관측은 버린다 — 반환값도, `look`이 쥔 관측(읽은 글자 등)도.
                # 끊긴 관측과 같은 규칙이다(기한 밖 글자가 실패 출력·메시지로 나가지 않게)
                if on_reset is not None:
                    on_reset()
                break
            if found is not None:
                return found, frame
            if deadline.passed:
                break
            ctx.sleep(min(POLL_MS, deadline.remaining_ms))
            if observations_reset(ctx):
                # 디버거로 멈췄다 재개: 재개 전 프레임·노드가 쥔 관측은 버리고 처음부터 다시 본다
                frame = None
                if on_reset is not None:
                    on_reset()
                reset_observations(ctx)
    except ObservationTimeout:
        pass  # 관측이 노드 기한에 걸렸다 = timeout
    return None, frame


def _runtime(ctx: Context) -> Any:
    """노드가 받은 ctx(SDK 제한 래퍼) 안쪽의 실행 ctx. 관측 무효화를 아는 ctx가 없으면 None."""
    seen: Any = ctx
    while seen is not None:
        if callable(getattr(type(seen), "observations_reset", None)):
            return seen
        seen = getattr(seen, "inner", None)
    return None


def observations_reset(ctx: Context) -> bool:
    """디버거로 폴링 중 멈췄다 재개해 노드 안 관측(이전 프레임·후보·안정 시간)이 무효가 됐나
    (구현 계획 M3 2.4). 그러면 노드는 들고 있던 관측을 버리고 `reset_observations`로 알린다.
    가짜 ctx(노드 단위 테스트)는 늘 False."""
    runtime = _runtime(ctx)
    return runtime is not None and bool(runtime.observations_reset())


def reset_observations(ctx: Context) -> None:
    """들고 있던 관측을 버렸다고 알린다: 출력의 관측 출처가 재개 뒤 관측부터 다시 정해진다.
    알리지 않으면 출력이 재개 전 관측으로 남는다(뒤 분기·검증이 `stale_observation` — 안전한 쪽)."""
    runtime = _runtime(ctx)
    if runtime is not None:
        runtime.reset_observations()


def save_last(ctx: Context, frame: Image | None, name: str) -> None:
    """대기가 실패로 끝날 때 마지막으로 본 프레임을 `steps/<스텝>_<name>`으로 남긴다."""
    if frame is not None:
        ctx.artifacts.save(frame, name)


def sensitive(target: Target) -> bool:
    return target.spec.get("sensitive") is True


@dataclass(frozen=True, slots=True)
class Area:
    """한 프레임에서 정한 영역. `rect`가 None이면 화면 전체, `found`는 target으로 찾은 결과."""

    rect: Rect | None
    sensitive: bool = False
    found: Match | None = None


def check_region(frame: Image, region: Rect | None) -> None:
    """픽셀 영역이 이 프레임(클라이언트 영역)과 하나도 겹치지 않으면 `ValueError`(진단). 크기를
    모르는 이미지(파일 이미지)는 보지 않는다 — 그때 비교는 겹치는 픽셀이 없으면 1(변함)이다.

    픽셀 상수는 창 크기·DPI에 따라 자동으로 바뀌지 않는다. 다른 해상도에서 쓰려면 창 크기를
    고정하거나(`core.window.set_size`) 영역을 target으로 잡는다."""
    if region is None or frame.width <= 0 or frame.height <= 0:
        return
    x0, y0 = max(region.x, 0), max(region.y, 0)
    x1 = min(region.x + region.width, frame.width)
    y1 = min(region.y + region.height, frame.height)
    if x1 <= x0 or y1 <= y0:
        box = [region.x, region.y, region.width, region.height]
        raise ValueError(
            f"영역 {box}이(가) 지금 화면(클라이언트 {frame.width}x{frame.height}) 밖이다 — 픽셀 "
            "영역은 창 크기·DPI에 따라 바뀌지 않는다. core.window.set_size로 창 크기를 맞추거나 "
            "영역을 다시 잡는다(화면 비율에 따르는 영역은 target)"
        )


def locate(
    ctx: Context, frame: Image, region: Target | Rect | None, deadline: Deadline | None = None
) -> Area | None:
    """`region`을 이 프레임에서 정한다. target을 찾지 못하면 None. 사각형이 화면 밖이면
    `ValueError`(`check_region`)."""
    if region is None:
        return Area(None)
    if isinstance(region, Rect):
        check_region(frame, region)
        return Area(region)
    found = ctx.vision.find(frame, region, deadline=deadline)
    if found is None:
        return None
    return Area(found.rect, sensitive(region), found)


def read_area(
    ctx: Context, frame: Image, area: Area, deadline: Deadline | None = None
) -> OcrResult:
    return ctx.ocr.read(frame, region=area.rect, sensitive=area.sensitive, deadline=deadline)


def plain(text: str | Secret) -> str:
    """비교용 원문 (노드 안에서만 쓰고 출력·메시지에는 넣지 않는다)."""
    return text.reveal() if isinstance(text, Secret) else text


def shown_text(text: str | Secret, show: Callable[[Any], str]) -> str:
    """메시지에 넣는 읽은 글자: 평문은 `repr`, 비밀값은 `show`가 가린 값(`***`)이면 그대로, 원문을
    꺼냈으면 `repr`. `message_with_secrets`의 `show`를 받아 기록 정책을 따른다."""
    if not isinstance(text, Secret):
        return repr(text)
    shown = show(text)
    return shown if shown == str(text) else repr(shown)


def line_match(
    ctx: Context, frame: Image, area: Area, result: OcrResult, lines: tuple[OcrLine, ...]
) -> Match:
    """OCR 줄(여럿이면 그 상자들을 덮는 상자)의 `Match`. 클릭 지점은 상자 가운데다.

    읽은 이미지의 캡처 시점 관측(`result.window`·`frame_info` — 영역 종류와 무관)을 실어 입력 직전
    재검증이 창 크기·DPI 변화를 알아보게 한다. 다시 찾을 target은 없으므로 바뀌었으면
    `stale_observation`이다. 관측이 없으면(엔진이 주지 않음) 영역 target의 관측을 쓴다."""
    x0 = min(line.box.x for line in lines)
    y0 = min(line.box.y for line in lines)
    x1 = max(line.box.x + line.box.width for line in lines)
    y1 = max(line.box.y + line.box.height for line in lines)
    score = min(line.score for line in lines)
    found = area.found
    seen = result.frame_info or (found.frame_info if found is not None else None)
    window = result.window or (found.window if found is not None else None) or ctx.window
    return Match(
        Rect(x0, y0, x1 - x0, y1 - y0),
        score,
        window=window,
        frame=frame.frame,
        method="ocr",
        frame_info=seen,
    )
