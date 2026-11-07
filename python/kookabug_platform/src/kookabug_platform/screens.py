"""화면 판정 (구현 계획 M1 2.10, M7 계획 3.1): `*.screen.json`의 `detect` 조건을 프레임 한 장에서.

`all`의 조건이 전부 맞고 `none`의 조건이 하나도 맞지 않으면 그 화면이다. 조건은 target(이미지
매칭, `vision`)과 OCR 조건(정규화 영역에서 읽은 글자에 `text`가 들어 있음, 공백·대소문자 무시).
파일 찾기·형식은 `kookabug_core.screens`. `kookabug screen test`가 쓴다(실행 중 화면 판정으로
실행을 바꾸지 않는다).

OCR 조건은 비밀값을 추측하는 통로가 되면 안 된다(M7 3.5a "OCR 조건 오라클 차단"):
- 글자 읽기(`ocr`)를 넘기지 않으면 OCR 조건은 보지 않고 `unknown`이다. 보호된 프레임(민감 target·
  비밀값 입력 창)에서는 호출자가 넘기지 않는다
- 읽은 글자는 결과에 남기지 않는다. 사람 CLI만 `reveal_text`로 앞 40자를 받는다
- 일치 여부도 값에 대한 정보다. 보호 판정을 거치지 않는 경로(에이전트가 부른 CLI)는 글자 읽기를
  넘기지 않는다 — 에이전트의 OCR 조건 판정은 daemon `screens.identify`(보호 판정 통과)만
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

if TYPE_CHECKING:
    from kookabug_core.screens import Condition, OcrCondition, ScreenDef
    from kookabug_platform.ocr.engine import OcrResult
    from kookabug_platform.vision import FindResult, FrameMeta, Pixels, Vision
    from kookabug_sdk.types import Target

__all__ = [
    "REVEAL_CHARS",
    "ConditionResult",
    "ScreenResult",
    "TextReader",
    "evaluate_screen",
    "normalize_text",
    "ocr_region",
]

REVEAL_CHARS: Final = 40
"""사람 CLI에 보이는 읽은 글자 길이 (M7 3.1)."""


class TextReader(Protocol):
    """글자 읽기 (`kookabug_platform.ocr.engine.Ocr`). `region`·결과는 이미지 좌표."""

    def read(self, pixels: Pixels, *, region: Sequence[int] | None = None) -> OcrResult: ...


@dataclass(frozen=True, slots=True)
class ConditionResult:
    """조건 하나.

    - `found`: target이 보였는지 / OCR 영역에 글자가 들어 있는지. `None`은 확인하지 않음
    - `ok`: 조건이 맞는지(`none`이면 안 보여야 맞음). `None`은 확인하지 않음(`unknown`)
    - `result`: target 매칭 결과(OCR 조건은 None), `region`: OCR 영역(프레임 픽셀 x, y, w, h)
    - `read`: 읽은 글자 앞 40자 — `reveal_text`일 때만
    """

    kind: Literal["all", "none"]
    target: str | None
    found: bool | None
    ok: bool | None
    result: FindResult | None
    ocr: OcrCondition | None = None
    region: tuple[int, int, int, int] | None = None
    read: str | None = None


@dataclass(frozen=True, slots=True)
class ScreenResult:
    screen: ScreenDef
    conditions: tuple[ConditionResult, ...]

    @property
    def matched(self) -> bool:
        """조건이 하나 이상 있고 모두 확인됐고 맞다 (조건 없는 후보는 어느 화면에도 맞지 않는다)."""
        return bool(self.conditions) and all(c.ok is True for c in self.conditions)

    @property
    def state(self) -> Literal["matched", "not_matched", "unknown"]:
        """틀린 조건이 하나라도 있으면 `not_matched`, 아니고 확인 못 한 조건이 있거나 조건이
        없으면 `unknown`(판정 불가)."""
        if any(c.ok is False for c in self.conditions):
            return "not_matched"
        return "matched" if self.matched else "unknown"


def normalize_text(text: str) -> str:
    """비교용 글자: NFKC, 공백 제거, 대소문자 무시."""
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def ocr_region(
    rect: tuple[float, float, float, float], pixels: Pixels, meta: FrameMeta
) -> tuple[int, int, int, int]:
    """정규화 사각형(클라이언트 기준) → 프레임 픽셀 영역 (x, y, w, h). 프레임 밖은 잘라낸다."""
    cw, ch = meta.client_size
    ox, oy = meta.origin
    x, y, w, h = rect
    left = math.floor(x * cw) - ox
    top = math.floor(y * ch) - oy
    right = math.ceil((x + w) * cw) - ox
    bottom = math.ceil((y + h) * ch) - oy
    width, height = int(pixels.shape[1]), int(pixels.shape[0])
    left, top = max(0, min(left, width)), max(0, min(top, height))
    right, bottom = max(left, min(right, width)), max(top, min(bottom, height))
    return (left, top, right - left, bottom - top)


def evaluate_screen(
    screen: ScreenDef,
    load: Callable[[str], Target],
    pixels: Pixels,
    meta: FrameMeta,
    vision: Vision,
    *,
    ocr: TextReader | None = None,
    reveal_text: bool = False,
) -> ScreenResult:
    """모든 조건을 본다 (맞지 않는 조건이 있어도 끝까지 — 어느 조건이 틀렸는지 보이게).

    `load`는 target 경로(워크스페이스 기준)를 `Target`으로 읽는다. `ocr`이 없으면 OCR 조건은
    확인하지 않는다(`unknown`). `reveal_text`는 사람 CLI만 켠다.
    """
    results: list[ConditionResult] = []
    for cond in screen.detect():
        results.append(_evaluate(cond, load, pixels, meta, vision, ocr, reveal_text))
    return ScreenResult(screen, tuple(results))


def _evaluate(
    cond: Condition,
    load: Callable[[str], Target],
    pixels: Pixels,
    meta: FrameMeta,
    vision: Vision,
    ocr: TextReader | None,
    reveal_text: bool,
) -> ConditionResult:
    if cond.target is not None:
        found = vision.find(pixels, meta, load(cond.target))
        visible = found.found
        ok = visible if cond.group == "all" else not visible
        return ConditionResult(cond.group, cond.target, visible, ok, found)
    spec = cond.ocr
    assert spec is not None
    region = ocr_region(spec.rect, pixels, meta)
    if ocr is None:
        return ConditionResult(cond.group, None, None, None, None, spec, region)
    text = ocr.read(pixels, region=region).text if region[2] and region[3] else ""
    present = normalize_text(spec.text) in normalize_text(text)
    ok = present if cond.group == "all" else not present
    shown = text.replace("\n", " ")[:REVEAL_CHARS] if reveal_text else None
    return ConditionResult(cond.group, None, present, ok, None, spec, region, shown)
