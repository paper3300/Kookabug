"""녹화 세션의 글자 보관과 노출 규칙 (M4 계획 2.8 "판정이 끝나기 전에는 원문을 내보내지 않는다",
"글자를 어디에도 남기지 않는다", T7).

- 글자(`SecretText`)는 이 보관소(daemon 녹화 세션 메모리)에만 있다. 세션 저장소·로그·알림에는
  `text_state`와 길이만 간다
- 원문을 주는 곳은 `view()`(→ `recorder.steps`) 하나이고 `ordinary`(근거로 판정 또는 사람 확인)일
  때만이다. `pending`·`secret`·`needs_review`는 길이만
- 그래프 값(`type_text.text`)은 일반이면 문자열, 비밀이면 `{"$secret": 키}` — 원문이 아니다
- 커밋 검사: `pending` → `classification_pending`, `needs_review` → `text_review_required`, 키 없는
  `secret` → `secret_unresolved` (이 순서로 먼저 걸린 것)
- 세션이 끝나면(커밋·버리기·연결 끊김) `wipe()`로 메모리의 글자를 0으로 덮는다(최선 노력)
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final, Literal

from kookabug_core.recorder.actions import TextAction
from kookabug_core.recorder.classify import SpanClassifier, SpanState, TextState
from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import Box

__all__ = [
    "SECRET_KEY",
    "CommitBlocked",
    "RecorderTexts",
    "TextNotAvailable",
]

SECRET_KEY: Final = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")

type BlockCode = Literal["classification_pending", "text_review_required", "secret_unresolved"]


@dataclass(frozen=True, slots=True)
class CommitBlocked:
    """커밋을 막는 이유와 걸린 구간."""

    code: BlockCode
    spans: tuple[int, ...]


class TextNotAvailable(Exception):
    """원문을 줄 수 없는 상태 (판정 중·비밀값·확인 필요, 또는 지운 뒤)."""


@dataclass
class _Entry:
    text: SecretText
    secret_key: str | None = None


class RecorderTexts:
    """구간 ID → 글자 + 판정. 여러 스레드(변환기·OCR 작업·RPC)에서 불러도 된다."""

    def __init__(self, classifier: SpanClassifier | None = None) -> None:
        self.classifier = classifier or SpanClassifier()
        self._lock = threading.Lock()
        self._texts: dict[int, _Entry] = {}
        self._wiped = False

    # ------------------------------------------------------------ 넣기·바꾸기

    def put(self, span_id: int, text: SecretText) -> None:
        """닫힌 구간의 최종 글자 (변환기 `TextAction.text`). 보관소가 소유한다."""
        with self._lock:
            if self._wiped:
                text.wipe()
                raise TextNotAvailable("세션이 끝나 글자를 받지 않는다")
            old = self._texts.get(span_id)
            if old is not None and old.text is not text:
                old.text.wipe()
            self._texts[span_id] = _Entry(text, None if old is None else old.secret_key)

    def open_span(self, span_id: int, field_box: Box | None) -> None:
        """구간이 열렸다 (판정 중). 이미 열려 있으면 그대로."""
        with self._lock:
            try:
                self.classifier.get(span_id)
            except KeyError:
                self.classifier.open(span_id, field_box)

    def add_text_action(self, action: TextAction, field_box: Box | None) -> None:
        """닫힌 구간(변환기 `TextAction`)을 받는다: 글자를 맡고 Win32·사람 표시 근거를 적는다.
        라벨·가림 글자·끝난 뒤 OCR 근거는 판정 작업이 따로 알려 준다."""
        self.open_span(action.span_id, field_box)
        with self._lock:
            self.classifier.password_hint(action.span_id, action.password_hint)
            if action.marked_secret:
                self.classifier.mark(action.span_id)
            self.classifier.close(action.span_id, final=action.text, review=action.needs_review)
        self.put(action.span_id, action.text)

    def set_secret_key(self, span_id: int, key: str | None) -> None:
        """비밀값 키를 고른다 (비밀 구간만)."""
        if key is not None and not SECRET_KEY.fullmatch(key):
            raise ValueError("비밀값 키 형식이 틀렸다")
        with self._lock:
            if self.classifier.state(span_id) != "secret":
                raise TextNotAvailable("비밀값 구간이 아니다")
            self._entry(span_id).secret_key = key

    def confirm_ordinary(self, span_id: int, *, confirm_reveal: bool) -> None:
        with self._lock:
            self.classifier.confirm_ordinary(span_id, confirm_reveal=confirm_reveal)
            self._entry(span_id).secret_key = None

    def mark_secret(self, span_id: int) -> None:
        with self._lock:
            self.classifier.mark(span_id)

    def replace_ordinary(self, span_id: int, text: str) -> None:
        """일반 글자 고치기 (`ordinary` 구간만)."""
        with self._lock:
            if self.classifier.state(span_id) != "ordinary":
                raise TextNotAvailable("일반 글자 구간만 고칠 수 있다")
            entry = self._entry(span_id)
            entry.text.wipe()
            entry.text = SecretText(text)

    def drop(self, span_id: int) -> None:
        """스텝을 지웠다: 그 글자도 지운다."""
        with self._lock:
            entry = self._texts.pop(span_id, None)
            if entry is not None:
                entry.text.wipe()

    # ------------------------------------------------------------ 읽기

    def state(self, span_id: int) -> TextState:
        with self._lock:
            return self.classifier.state(span_id)

    def view(self, span_id: int) -> dict[str, Any]:
        """`recorder.steps` 스텝의 글자 필드: `text_state`·`text_len`, 일반이면 `text`, 사람이
        확인했으면 `reveal_confirmed`, 비밀이면 `secret_key`."""
        with self._lock:
            entry = self._entry(span_id)
            span = self.classifier.get(span_id)
            state = span.state
            out: dict[str, Any] = {"text_state": state, "text_len": len(entry.text)}
            if state == "ordinary":
                out["text"] = entry.text.reveal()
                if span.confirmed_ordinary:
                    out["reveal_confirmed"] = True
            elif state == "secret":
                out["secret_key"] = entry.secret_key
            return out

    def raw_for_secret(self, span_id: int) -> SecretText:
        """`secrets.create`: 비밀값·확인 필요 구간의 원문 (자격 증명 관리자에 쓸 때만)."""
        with self._lock:
            state = self.classifier.state(span_id)
            if state not in ("secret", "needs_review"):
                raise TextNotAvailable("비밀값·확인 필요 구간만 새 비밀값으로 만들 수 있다")
            return self._entry(span_id).text

    def typed_so_far(self, span_id: int) -> SecretText:
        """판정 재료(가림 글자 길이·OCR 대조)에만 쓴다."""
        with self._lock:
            return self._entry(span_id).text

    def protected_texts(self) -> Iterator[SecretText]:
        """이름·제목 짓기에서 피할 원문: 일반으로 확정되지 않은 모든 구간."""
        with self._lock:
            items = [
                e.text
                for span_id, e in self._texts.items()
                if self.classifier.state(span_id) != "ordinary"
            ]
        yield from items

    def graph_text(self, span_id: int) -> str | dict[str, str]:
        """`type_text.text`에 넣을 값: 일반이면 문자열, 비밀이면 `{"$secret": 키}`."""
        with self._lock:
            state = self.classifier.state(span_id)
            entry = self._entry(span_id)
            if state == "ordinary":
                return entry.text.reveal()
            if state == "secret" and entry.secret_key is not None:
                return {"$secret": entry.secret_key}
            raise TextNotAvailable("판정이 끝나지 않았거나 비밀값 키를 고르지 않았다")

    def commit_blocked(self, spans: list[int] | None = None) -> CommitBlocked | None:
        """커밋을 막는 첫 이유 (`spans`가 있으면 그 구간만 본다 — 지운 스텝 제외)."""
        with self._lock:
            ids = list(self._texts) if spans is None else [s for s in spans if s in self._texts]
            states: dict[int, SpanState] = {s: self.classifier.get(s) for s in ids}
            for code, test in (
                ("classification_pending", lambda s: s.state == "pending"),
                ("text_review_required", lambda s: s.state == "needs_review"),
                (
                    "secret_unresolved",
                    lambda s: s.state == "secret" and self._texts[s.span_id].secret_key is None,
                ),
            ):
                hit = tuple(sorted(i for i, s in states.items() if test(s)))
                if hit:
                    return CommitBlocked(code, hit)  # pyright: ignore[reportArgumentType]
            return None

    # ------------------------------------------------------------ 끝

    def wipe(self) -> None:
        """세션 끝 (커밋·버리기·연결 끊김): 모든 글자를 0으로 덮고 버린다."""
        with self._lock:
            for entry in self._texts.values():
                entry.text.wipe()
            self._texts.clear()
            self._wiped = True

    @property
    def wiped(self) -> bool:
        return self._wiped

    def _entry(self, span_id: int) -> _Entry:
        if self._wiped:
            raise TextNotAvailable("세션이 끝나 글자를 지웠다")
        entry = self._texts.get(span_id)
        if entry is None:
            raise TextNotAvailable("그 구간의 글자가 없다")
        return entry

    def __repr__(self) -> str:
        return f"RecorderTexts(spans={len(self._texts)})"
