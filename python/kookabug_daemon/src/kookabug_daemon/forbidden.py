"""Agent 제어 입력의 금지 동작 판정 (M8 계획 3.7·9장 R6) — daemon 쪽 화면 공급자.

판정 함수는 `kookabug_core.forbidden.judge` 하나다. 여기는 Agent 연결의 제어 입력(`control.click/
key/type`)을 보내기 **전에** 대상 창 한 장을 잡아 그 판정에 넘기는 일만 한다. 보낸 뒤 runner가 입력
직전에 같은 판정을 다시 한다(제어 실행도 Agent 주체 실행이라 사양에 금지 목록이 실린다 — 그 사이
화면이 바뀌어도 막는다).

- 보호 판정(`frame_guard`)이 `clear`가 아닌 프레임은 글자 항목을 확인하지 않고 거부한다(보호 화면의
  글자는 읽지 않는다). 단 사유가 비밀값 칸(`secret_field`)이고 그 창의 칸 상자를 모두 알면 그 칸을
  가린 사본으로 읽는다. target·화면 항목은 픽셀로만 본다
- 창이 하나로 정해지지 않았거나 캡처가 실패하면 확인 못 함(거부)
- 거부 응답·로그에는 걸린 항목과 고정 사유만. OCR 글자는 메모리에서 판정에만 쓴다
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from kookabug_core import forbidden as rules
from kookabug_core.permissions import Principal
from kookabug_daemon.frames import EditorFrame
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.screen_source import WindowBinding

__all__ = ["MASK_PAD", "check_agent_input", "masked", "refusal_error", "window_sight"]


class _LazyReader:
    """처음 읽을 때 OCR 엔진을 연다 (모델이 없으면 그 예외 — 판정은 확인 못 함으로 거부)."""

    def __init__(self, daemon: Any) -> None:
        self._daemon = daemon

    def read(self, pixels: Any) -> Any:
        from kookabug_platform.ocr.engine import Ocr

        return Ocr(self._daemon.targets.ocr()).read(pixels)


def refusal_error(refusal: rules.Refusal) -> RequestFailed:
    return RequestFailed(refusal.code, refusal.message(), **refusal.fields())


def window_sight(daemon: Any, bindings: Sequence[WindowBinding]) -> rules.PixelSight | None:
    """대상 창 한 장의 `Sight` (창이 하나가 아니거나 캡처가 실패하면 None)."""
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    try:
        grab = daemon.screen_source.capture(binding.hwnd)
    except Exception:
        return None
    if grab.binding is not None and grab.binding != binding:
        return None
    frame = EditorFrame(
        "forbidden-check",
        grab.pixels,
        grab.client_size,
        grab.dpi,
        "",
        window=True,
        binding=binding,
    )
    pixels = grab.pixels
    try:
        verdict = daemon.guard.check(frame)
        protected = None if verdict.clear else str(verdict.reason or "frame_protected")
        if verdict.reason == "secret_field":
            # 비밀값 칸 상자를 모두 알면 그 칸만 가리고 나머지 글자를 읽는다 (비밀번호 입력 뒤
            # 로그인 단추 같은 흐름이 막히지 않게). 하나라도 모르면 읽지 않는다
            boxes = daemon.guard.secret_boxes(frame)
            if boxes:
                pixels = masked(grab.pixels, boxes)
                protected = None
    except Exception:
        protected = "guard_error"
    return rules.PixelSight(
        daemon.root, pixels, reader=_LazyReader(daemon), protected=protected, dpi=grab.dpi
    )


MASK_PAD = 8
"""칸 상자를 가릴 때 둘레 여유 (px)."""


def masked(pixels: Any, boxes: Sequence[tuple[int, int, int, int]]) -> Any:
    """칸 상자(x, y, w, h)를 둘레 여유까지 단색으로 칠한 사본."""
    out = pixels.copy()
    height, width = int(out.shape[0]), int(out.shape[1])
    for x, y, w, h in boxes:
        left, top = max(0, x - MASK_PAD), max(0, y - MASK_PAD)
        right, bottom = min(width, x + w + MASK_PAD), min(height, y + h + MASK_PAD)
        out[top:bottom, left:right] = 128
    return out


def check_agent_input(daemon: Any, principal: Principal, bindings: Sequence[WindowBinding]) -> None:
    """Agent 연결의 제어 입력 전 판정. 사람은 판정하지 않는다. 거부면 `RequestFailed`."""
    if principal.kind != "agent":
        return
    try:
        items = rules.load_items(daemon.root)
    except rules.ForbiddenConfigError as exc:
        raise RequestFailed(
            rules.UNVERIFIABLE,
            "금지 동작 목록을 읽지 못해 입력하지 않았다",
            kind=None,
            value=None,
            reason="config_unreadable",
        ) from exc
    if not items:
        return
    refusal = rules.judge(items, window_sight(daemon, bindings))
    if refusal is not None:
        raise refusal_error(refusal)
