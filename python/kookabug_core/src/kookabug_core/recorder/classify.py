"""입력 칸 구간의 비밀 판정 (M4 계획 2.8, 검수 H2, T7). 순수 — OCR은 부르는 쪽이 한다.

구간마다 상태 `pending → ordinary | secret | needs_review`:

- **secret**: 비밀 근거가 **하나라도** 나오면. 끈적하다 — 그 뒤 근거가 없어도 돌아가지 않는다.
  같은 칸 상자로 다시 들어온 다음 구간도 secret으로 시작한다(`inherit`)
- **ordinary**: 비밀 근거가 없고 **일반 긍정 근거**(구간이 끝난 뒤 칸 OCR에 친 문자열이 그대로
  보임)가 있을 때만
- **needs_review**: 구간이 끝났고 판정 재료를 다 봤는데 둘 다 없음 (`no_evidence`), 칸 상자를 못
  정함(`field_box_unknown`). 증거가 사라졌다고 일반으로 확정하지 않는다
- **pending**: 구간이 열려 있거나 아직 볼 재료(라벨 OCR·끝난 뒤 OCR)가 남음

비밀 근거: Win32 비밀번호 칸(관측 `focus_password`), 라벨 글자(구간 시작 직전 프레임의 칸 왼쪽·위
띠), 가림 글자(키 뒤 프레임의 칸 OCR이 친 글자 없이 가림 글자 x 지금까지 길이 ±1), 사람 표시.
사람이 고치는 것: `confirm_ordinary`(원문을 처음 보이므로 `confirm_reveal` 필수)·`mark_secret`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final, Literal

from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import Box

__all__ = [
    "MASK_CHARS",
    "RevealNotConfirmed",
    "SpanClassifier",
    "SpanState",
    "TextState",
    "is_password_label",
    "mask_evidence",
    "ordinary_evidence",
]

type TextState = Literal["pending", "ordinary", "secret", "needs_review"]
type SecretReason = Literal["win32", "label", "mask", "marked", "inherited"]

_LABEL: Final = re.compile(
    r"비밀\s*번호|암호|패스\s*워드|(?<![a-z])(password|passwd|pwd|pin)(?![a-z])", re.IGNORECASE
)
MASK_CHARS: Final = frozenset("●•*·∙⦁◦○⚫⬤") | {chr(0x2217)}  # 0x2217 = 별표 연산자
"""가림 글자로 보는 글자 (OCR이 ●를 읽는 모양들)."""


class RevealNotConfirmed(Exception):
    """일반 글자로 바꾸려면 원문을 보인다는 확인(`confirm_reveal`)이 있어야 한다."""


def _norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def is_password_label(text: str | None) -> bool:
    """라벨 띠 OCR 글자가 비밀번호 칸 이름인가."""
    return bool(text) and _LABEL.search(unicodedata.normalize("NFKC", text or "")) is not None


def mask_evidence(ocr_text: str | None, typed_len: int, typed: SecretText | None = None) -> bool:
    """칸 OCR이 친 글자 없이 가림 글자를 구간 지금까지의 길이만큼(±1) 보이는가. 글자(`typed`)를
    알면 그것이 보이지 않는지도 본다 (구간 중간에는 길이만 안다)."""
    if not ocr_text or typed_len <= 0:
        return False
    seen = "".join(ocr_text.split()).replace("…", "···")  # OCR이 점 셋을 말줄임표로 읽는다
    if not seen:
        return False
    if typed is not None:
        raw = typed.reveal()
        if len(raw) >= 2 and _norm(raw) in _norm(seen):
            return False  # 친 글자가 보인다
    if not all(ch in MASK_CHARS for ch in seen):
        return False
    return abs(len(seen) - typed_len) <= 1


def ordinary_evidence(ocr_text: str | None, final: SecretText) -> bool:
    """구간이 끝난 뒤 칸 OCR에 친 최종 문자열이 그대로 보이는가 (일반 긍정 근거)."""
    if ocr_text is None or not final:
        return False
    return _norm(final.reveal()) in _norm(ocr_text)


@dataclass
class SpanState:
    """구간 하나의 판정 재료와 상태."""

    span_id: int
    field_box: Box | None
    open: bool = True
    secret_by: set[SecretReason] = field(default_factory=set[SecretReason])
    ordinary_seen: bool = False
    label_checked: bool = False
    final_checked: bool = False
    review: set[str] = field(default_factory=set[str])
    confirmed_ordinary: bool = False
    """사람이 "글자를 보이고 일반 글자로"를 확인했다."""
    empty: bool = False
    """최종 문자열이 비었다 (비울 내용만 있음 — 내보낼 원문이 없다)."""

    @property
    def state(self) -> TextState:
        if self.confirmed_ordinary:
            return "ordinary"
        if self.secret_by:
            return "secret"
        if self.open:
            return "pending"
        if self.empty:
            return "ordinary"
        if self.field_box is None:
            return "needs_review"
        if not (self.label_checked and self.final_checked):
            return "pending"
        return "ordinary" if self.ordinary_seen else "needs_review"

    @property
    def review_reasons(self) -> tuple[str, ...]:
        """text_state의 확인 필요 이유 (`needs_review`일 때)."""
        if self.state != "needs_review":
            return ()
        reasons = set(self.review)
        reasons.add("field_box_unknown" if self.field_box is None else "no_evidence")
        return tuple(sorted(reasons))


class SpanClassifier:
    """녹화 세션의 구간 판정들. 변환기·OCR 작업이 차례로 알려 준다."""

    def __init__(self) -> None:
        self._spans: dict[int, SpanState] = {}
        self._secret_boxes: list[Box] = []
        """이 장면에서 비밀로 판정된 칸 상자 (같은 칸에 다시 들어오면 상속)."""
        self._mark_next = False

    # ------------------------------------------------------------ 구간 열고 닫기

    def open(self, span_id: int, field_box: Box | None) -> SpanState:
        span = SpanState(span_id, field_box)
        if field_box is not None and field_box in self._secret_boxes:
            span.secret_by.add("inherited")
        if self._mark_next:
            span.secret_by.add("marked")
            self._mark_next = False
        self._spans[span_id] = span
        return span

    def scene_changed(self, field_box: Box) -> None:
        """그 칸이 없음으로 확정됐다: 다음에 같은 자리 칸에 들어와도 상속하지 않는다."""
        self._secret_boxes = [b for b in self._secret_boxes if b != field_box]

    def close(
        self,
        span_id: int,
        *,
        final: SecretText,
        review: Iterable[str] = (),
    ) -> SpanState:
        """구간이 끝났다 (재생 동작 하나가 정해짐). 판정 재료가 다 오면 상태가 정해진다."""
        span = self.get(span_id)
        span.open = False
        span.empty = not final
        span.review.update(review)
        self._remember(span)
        return span

    # ------------------------------------------------------------ 근거

    def password_hint(self, span_id: int, hint: bool | None) -> None:
        """Win32 비밀번호 칸 (구간 첫 키의 관측 `focus_password`)."""
        if hint:
            self._secret(span_id, "win32")

    def label(self, span_id: int, ocr_text: str | None) -> None:
        """구간 시작 직전 프레임의 라벨 띠 OCR. None = 읽지 못함(그래도 확인한 것으로 센다)."""
        span = self.get(span_id)
        span.label_checked = True
        if is_password_label(ocr_text):
            self._secret(span_id, "label")

    def mask(self, span_id: int, ocr_text: str | None, typed_len: int) -> None:
        """키 뒤 프레임의 칸 OCR과 구간 지금까지의 글자 수 (편집 키 반영 뒤 최종 길이)."""
        if mask_evidence(ocr_text, typed_len):
            self._secret(span_id, "mask")

    def final(self, span_id: int, ocr_text: str | None, final: SecretText) -> None:
        """구간이 끝난 뒤 칸 OCR (일반 긍정 근거 — 가림 글자면 비밀 근거도 된다)."""
        span = self.get(span_id)
        span.final_checked = True
        if mask_evidence(ocr_text, len(final), final):
            self._secret(span_id, "mask")
        elif ordinary_evidence(ocr_text, final):
            span.ordinary_seen = True

    def no_final_frame(self, span_id: int) -> None:
        """구간 뒤 칸을 볼 프레임이 없다 (칸이 바로 사라짐). 일반 근거 없이 확인 끝."""
        self.get(span_id).final_checked = True

    def mark(self, span_id: int | None) -> None:
        """사람 표시(`Ctrl+Shift+P`·목록 "비밀값으로"). 구간이 없으면 다음 구간."""
        if span_id is None:
            self._mark_next = True
            return
        self.get(span_id).confirmed_ordinary = False  # 사람이 비밀값으로 되돌림
        self._secret(span_id, "marked")

    def confirm_ordinary(self, span_id: int, *, confirm_reveal: bool) -> None:
        """사람이 "일반 글자로"를 골랐다. 원문을 처음 보이는 순간이라 확인이 있어야 한다."""
        if not confirm_reveal:
            raise RevealNotConfirmed("일반 글자로 바꾸려면 글자를 보인다는 확인이 필요하다")
        span = self.get(span_id)
        span.confirmed_ordinary = True
        span.secret_by.clear()
        if span.field_box is not None:
            self.scene_changed(span.field_box)

    # ------------------------------------------------------------ 읽기

    def get(self, span_id: int) -> SpanState:
        return self._spans[span_id]

    def state(self, span_id: int) -> TextState:
        return self._spans[span_id].state

    def spans(self) -> list[SpanState]:
        return list(self._spans.values())

    def _secret(self, span_id: int, reason: SecretReason) -> None:
        span = self.get(span_id)
        if span.confirmed_ordinary:
            return  # 사람이 일반 글자로 확인한 구간은 자동 근거로 되돌리지 않는다
        span.secret_by.add(reason)
        self._remember(span)

    def _remember(self, span: SpanState) -> None:
        if (
            span.secret_by
            and span.field_box is not None
            and span.field_box not in self._secret_boxes
        ):
            self._secret_boxes.append(span.field_box)
