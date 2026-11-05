"""입력 칸 구간과 원문을 감싼 글자 (M4 계획 2.7 "입력 칸 구간", 2.8, 검수 H2).

- **구간**은 게임 안 클릭·Tab으로 시작해 칸 밖 클릭·Tab·Enter·Esc·게임 창 떠남·칸 없음 확정·정지로
  끝난다. 쉼으로는 끝나지 않는다 — `abc` → 3초 → `def`는 한 구간이고 재생 동작 하나다
- 구간 안 편집 키는 구간이 흡수한다: Backspace(구간 시작 전 내용까지 지우면 "기존 내용 있었음" →
  `clear`), Ctrl+A 뒤 글자(전체 바꿈), Ctrl+A → Backspace(비움). 커서를 옮기면 최종 문자열을
  확정할 수 없어 `cursor_moved_in_field`
- 구간은 키 입력 기록만 든다. 글자는 닫을 때(IME 표본이 모인 뒤) 자판·IME 모드로 짠다
- 글자는 `SecretText`로만 든다: `repr`·`str`·로그·JSON에는 길이만 나온다. 원문은 `reveal()`로만
- 칸 존재 판정(`FieldPresence`, T6)은 인터페이스로 받는다 — 값·포커스만 바뀐 것은 끝이 아니다
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, Protocol

from kookabug_core.recorder.hangul import TextBuffer, jamo_for_key
from kookabug_core.recorder.ime import ImeMode
from kookabug_core.recorder.keyboard import KeyLayout, UsLayout, layout_kind

__all__ = ["FieldPresence", "FieldSpan", "SecretText", "SpanResult"]


class SecretText:
    """원문 글자. 바이트(`bytearray`)로 들고 `wipe()`가 0으로 덮는다(최선 노력 — 원문을 `reveal()`한
    파이썬 문자열은 덮을 수 없다). `repr`·`str`·`format`·직렬화에 원문이 나오지 않는다."""

    __slots__ = ("_buf", "_len")

    def __init__(self, text: str = "") -> None:
        self._buf = bytearray(text.encode("utf-8"))
        self._len = len(text)

    def reveal(self) -> str:
        return self._buf.decode("utf-8")

    def wipe(self) -> None:
        for i in range(len(self._buf)):
            self._buf[i] = 0
        self._buf.clear()
        self._len = 0

    def __len__(self) -> int:
        return self._len

    def __bool__(self) -> bool:
        return self._len > 0

    def __repr__(self) -> str:
        return f"SecretText(len={self._len})"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def __reduce__(self) -> NoReturn:
        raise TypeError("SecretText는 직렬화하지 않는다")

    def __copy__(self) -> NoReturn:
        raise TypeError("SecretText는 복사하지 않는다 (원문이 여러 곳에 남는다)")


type StartKind = Literal["click", "tab", "none"]
type ModeAt = Callable[[int, Mapping[str, Any] | None], ImeMode | None]
"""키 시각·그 키의 쓸 수 있는 즉시 관측 → IME 모드 (판정 불가면 None)."""


@dataclass(frozen=True, slots=True)
class _Stroke:
    vk: int
    shift: bool
    caps: bool
    t_ns: int
    hkl: str | None
    obs: Mapping[str, Any] | None
    """쓸 수 있는 즉시 관측 (없으면 None — 자판·창 판정 불가)."""

    def __repr__(self) -> str:  # 키 코드도 원문이다
        return "_Stroke(…)"


@dataclass(frozen=True, slots=True)
class SpanResult:
    text: SecretText
    clear: bool
    review: frozenset[str]
    badges: frozenset[str]


@dataclass(eq=False)
class FieldSpan:
    """입력 칸 구간 하나 (구간 밖 글자 묶음은 `start_kind="none"`)."""

    span_id: int
    start_kind: StartKind
    t_start: int
    anchor: tuple[int, int] | None = None
    """시작 클릭의 클라이언트 점 (칸 상자 후보 — T6·T7이 상자를 정한다)."""
    password_hint: bool | None = None
    """첫 키의 관측 `focus_password` (Win32 비밀번호 칸, 비밀 근거 1)."""
    marked_secret: bool = False
    review: set[str] = field(default_factory=set[str])
    badges: set[str] = field(default_factory=set[str])
    t_first: int | None = None
    t_last: int | None = None
    keys: int = 0
    _ops: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]], repr=False)
    _strokes: list[_Stroke] = field(default_factory=list[_Stroke], repr=False)

    def _touch(self, t_ns: int) -> None:
        if self.t_first is None:
            self.t_first = t_ns
        self.t_last = t_ns

    @property
    def empty(self) -> bool:
        """편집이 하나도 없었다 (재생 동작을 만들지 않음)."""
        return not self._ops

    def add_key(
        self,
        vk: int,
        *,
        shift: bool,
        caps: bool,
        t_ns: int,
        hkl: str | None,
        obs: Mapping[str, Any] | None,
    ) -> None:
        if self.keys == 0 and obs is not None:
            password = obs.get("focus_password")
            self.password_hint = password if isinstance(password, bool) else None
        self._touch(t_ns)
        self.keys += 1
        self._strokes.append(_Stroke(vk, shift, caps, t_ns, hkl, obs))
        self._ops.append(("k", len(self._strokes) - 1))

    def backspace(self, t_ns: int) -> None:
        self._touch(t_ns)
        self._ops.append(("b", 0))

    def select_all(self, t_ns: int) -> None:
        self._touch(t_ns)
        self._ops.append(("a", 0))

    def cursor_moved(self, t_ns: int) -> None:
        self._touch(t_ns)
        self.review.add("cursor_moved_in_field")
        self._ops.append(("c", 0))

    def finalize(self, mode_at: ModeAt, layout: KeyLayout | None = None) -> SpanResult:
        """키 기록 → 최종 문자열. 기록은 지운다 (같은 구간을 두 번 짜지 않는다)."""
        layout = layout or UsLayout()
        review = set(self.review)
        badges = set(self.badges)
        buffer = TextBuffer()
        selected = clear = False
        for op, index in self._ops:
            if op == "a":
                buffer.commit()
                selected = True
            elif op == "c":
                buffer.commit()
            elif op == "b":
                if selected:
                    buffer.clear()
                    clear, selected = True, False
                elif not buffer.backspace():
                    clear = True  # 구간 시작 전 내용을 지웠다
            else:
                if selected:
                    buffer.clear()
                    clear, selected = True, False
                self._type(buffer, self._strokes[index], mode_at, layout, review, badges)
        text = SecretText(buffer.text())
        buffer.clear()
        self._ops.clear()
        self._strokes.clear()
        return SpanResult(text, clear, frozenset(review), frozenset(badges))

    @staticmethod
    def _type(
        buffer: TextBuffer,
        stroke: _Stroke,
        mode_at: ModeAt,
        layout: KeyLayout,
        review: set[str],
        badges: set[str],
    ) -> None:
        latin = UsLayout().char(stroke.vk, shift=stroke.shift, caps=stroke.caps, hkl=stroke.hkl)
        if stroke.obs is None:
            review.add("window_undetermined")
        if layout_kind(stroke.hkl) == "korean":
            mode = mode_at(stroke.t_ns, stroke.obs)
            if mode is None:
                review.add("ime_unknown")  # 영문으로 해석하되 확인 필요
            elif mode == "native" and latin is not None and latin.isalpha():
                jamo = jamo_for_key(latin, stroke.shift)
                if jamo is not None:
                    badges.add("hangul_guess")
                    buffer.type_jamo(jamo)
                    return
            if latin is not None:
                buffer.type_char(latin)
            return
        ch = layout.char(stroke.vk, shift=stroke.shift, caps=stroke.caps, hkl=stroke.hkl)
        if ch is not None:
            buffer.type_char(ch)


class FieldPresence(Protocol):
    """칸 존재 판정 (T6 구현). 구간의 칸이 `t_ns` 전에 **없음으로 확정**됐으면 True — 장면이
    바뀌었을 때만. 값·가림 글자·커서·포커스 테두리가 바뀐 것, 확정하지 못한 것은 False."""

    def gone(self, span: FieldSpan, t_ns: int) -> bool: ...
