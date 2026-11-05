"""변환기 1: 훅 이벤트 → 동작 (순수, M4 계획 2.7 앞 절·2.4·2.9 상태별 마무리, T5).

받는 것: 사람 입력으로 받은 훅 이벤트(합성은 `HookStream`이 이미 걸렀다)와 그 즉시 관측, IME 표본,
기하 세대 조회. 차례대로 `feed`하고 `finish`로 닫는다. 처리하는 순간의 창·자판 상태를 읽지 않는다.

- 클릭: 같은 버튼 down·up, 거리 ≤ 4 px. 이중 클릭 시간·거리 안 두 번 → `count: 2`. 끌기: > 4 px
  (끝점이 클라이언트 밖이면 가장자리로 자르고 표시). 휠: 16 px·300 ms 안 묶음
- 키: 수정 키 + 키 → `ctrl+a`. 수정 키 없이 300 ms 넘게 누른 키 → `hold_ms`. 자동 반복 down은 합침.
  다른 키 없이 눌렀다 뗀 수정 키 하나 → 그 키
- 녹화 단축키(정지·비밀값 표시): 그 조합 키는 지우고, 그 조합 때문에만 눌린 수정 키는 동작을
  만들지 않는다. 비밀값 표시는 지금 구간(없으면 다음 구간)에 표시
- 글자: 입력 칸 구간(`FieldSpan`)에 쌓인다. 구간 밖 글자는 1초 안 간격 묶음
- 창 떠남 동안 눌려 있던 키, 일시정지 중 뗀 키, 누른 채 끝난 입력은 동작을 만들지 않고 경고
- 일본어·중국어 입력기 자판의 글쇠는 글자가 아니라 키 사슬(`ime_other` 배지)
- 창 전환 조합(Alt+Tab·Alt+Esc·Win+…): 누르는 순간에는 포그라운드가 아직 대상이라 `key`가 남는다.
  다음 이벤트에서 포그라운드가 대상이 아니면 바로 앞의 그 조합을 지운다
- 구간 열림 알림(`on_span_open`): 구간에 첫 편집(글자·지우기·전체 선택)이 들어온 순간 한 번.
  클릭마다 구간 후보가 열리지만 편집이 없는 구간(단추 클릭)은 칸이 아니므로 알리지 않는다 —
  받는 쪽(녹화 세션)이 그때 칸 상자를 정하고 보호 영역·칸 존재·판정을 연다(시각은 `t_start`)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from kookabug_core.recorder.contract import IME_SWITCH_VKS
from kookabug_core.recorder.events import GeometryLookup, clip_to_client
from kookabug_core.recorder.fields import FieldPresence, FieldSpan, SecretText
from kookabug_core.recorder.ime import ime_changes, ime_mode_at
from kookabug_core.recorder.keyboard import (
    CURSOR_KEYS,
    VK_BACK,
    VK_CAPITAL,
    VK_ESCAPE,
    VK_RETURN,
    VK_TAB,
    KeyLayout,
    UsLayout,
    combo_name,
    is_modifier,
    layout_kind,
    vk_name,
)
from kookabug_core.recorder.window_filter import Verdict, WindowFilter

__all__ = [
    "Action",
    "ClickAction",
    "Converter",
    "ConverterOptions",
    "ConverterWarning",
    "DragAction",
    "KeyAction",
    "ScrollAction",
    "TextAction",
]

MS: Final = 1_000_000
_SWITCH_COMBOS: Final = frozenset(
    {"alt+tab", "alt+shift+tab", "ctrl+alt+tab", "alt+esc", "alt+shift+esc"}
)
"""포그라운드를 다른 창으로 옮기는 조합 (그 밖에 `win`이 든 조합 전부)."""


def _is_switch_combo(keys: str) -> bool:
    return keys in _SWITCH_COMBOS or "win" in keys.split("+")


@dataclass(frozen=True, slots=True, kw_only=True)
class Action:
    kind: str
    t_ns: int
    needs_review: tuple[str, ...] = ()
    badges: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        """구조화 데이터 (세션 저장소·로그용). 글자 원문은 넣지 않는다."""
        out: dict[str, Any] = {}
        for name in self.__dataclass_fields__:  # pyright: ignore[reportAttributeAccessIssue]
            value = getattr(self, name)
            if isinstance(value, SecretText):
                out[f"{name}_len"] = len(value)
            elif isinstance(value, tuple):
                out[name] = list(value)  # pyright: ignore[reportUnknownArgumentType]
            else:
                out[name] = value
        return out


@dataclass(frozen=True, slots=True, kw_only=True)
class ClickAction(Action):
    kind: str = "click"
    button: str
    point: tuple[int, int] | None
    """클라이언트 점 (클릭 세대). 세대를 몰랐으면 None (`geometry_unresolved`)."""
    screen: tuple[int, int]
    count: int = 1
    event_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DragAction(Action):
    kind: str = "drag"
    button: str
    start: tuple[int, int] | None
    end: tuple[int, int] | None
    screen_start: tuple[int, int]
    duration_ms: int
    clipped: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ScrollAction(Action):
    kind: str = "scroll"
    point: tuple[int, int] | None
    screen: tuple[int, int]
    delta: int
    horizontal: bool = False

    @property
    def amount(self) -> int:
        """휠 칸 수 (120 단위)."""
        return round(self.delta / 120)


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyAction(Action):
    kind: str = "key"
    keys: str
    hold_ms: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TextAction(Action):
    """입력 칸 구간 하나(또는 구간 밖 글자 묶음) = 재생 `type_text` 하나."""

    kind: str = "text"
    text: SecretText
    clear: bool
    in_field: bool
    span_id: int
    start_kind: str
    anchor: tuple[int, int] | None
    t_end: int
    password_hint: bool | None = None
    marked_secret: bool = False


@dataclass(frozen=True, slots=True)
class ConverterWarning:
    code: Literal[
        "key_held_across_focus_loss", "released_during_pause", "held_at_stop", "unknown_key"
    ]
    t_ns: int


@dataclass(frozen=True, slots=True)
class ConverterOptions:
    click_px: int = 4
    double_click_ns: int = 500 * MS
    """`GetDoubleClickTime` (daemon이 시스템 값을 넣는다)."""
    double_click_px: int = 4
    """`SM_CXDOUBLECLK` (daemon이 시스템 값을 넣는다)."""
    wheel_px: int = 16
    wheel_ns: int = 300 * MS
    hold_ns: int = 300 * MS
    loose_gap_ns: int = 1000 * MS
    hotkeys: tuple[str, ...] = ("ctrl+shift+r", "ctrl+shift+p")
    secret_hotkey: str | None = "ctrl+shift+p"


@dataclass
class _Held:
    t_ns: int
    modifier: bool = False
    used: bool = False
    """수정 키: 그 사이 다른 키가 눌렸다 (혼자 누른 키가 아님)."""
    keys: str | None = None
    """떼면 `key` 동작을 낼 키 이름 (누르고 있기 판정은 뗄 때)."""
    char: _PendingChar | None = None
    review: tuple[str, ...] = ()


@dataclass
class _PendingChar:
    vk: int
    shift: bool
    caps: bool
    t_ns: int
    hkl: str | None
    obs: Mapping[str, Any] | None
    name: str
    """누르고 있기로 바뀌면 낼 키 이름."""

    def __repr__(self) -> str:
        return "_PendingChar(…)"


@dataclass
class _Press:
    button: str
    t_ns: int
    screen: tuple[int, int]
    client: tuple[int, int] | None
    gen_known: bool
    review: tuple[str, ...]
    event_id: int


@dataclass
class _Closed:
    span: FieldSpan
    review: tuple[str, ...] = ()


@dataclass
class _Counts:
    ignored_outside: int = 0
    ignored_popup: int = 0
    undetermined: int = 0
    autorepeat: int = 0
    hotkeys: int = 0


type FieldBox = Callable[[FieldSpan], tuple[int, int, int, int] | None]
type SpanOpened = Callable[[FieldSpan], None]


class Converter:
    """훅 이벤트 → 동작. 스레드 하나에서 차례대로 부른다."""

    def __init__(
        self,
        target_hwnd: int,
        geometry: GeometryLookup,
        *,
        options: ConverterOptions | None = None,
        layout: KeyLayout | None = None,
        presence: FieldPresence | None = None,
        field_box: FieldBox | None = None,
        on_span_open: SpanOpened | None = None,
    ) -> None:
        self.o = options or ConverterOptions()
        self.on_span_open = on_span_open
        self._announced: set[int] = set()
        self.counts_switch = 0
        """지운 창 전환 조합 수."""
        self.filter = WindowFilter(target_hwnd, geometry)
        self.geometry = geometry
        self.layout = layout or UsLayout()
        self.presence = presence
        self.field_box = field_box
        self.counts = _Counts()
        self.warnings: list[ConverterWarning] = []
        self.moves: list[tuple[int, int, int]] = []
        """이동 이력 `(t_ns, 화면 x, 화면 y)` (커서 들어오기 전 프레임·끌기)."""
        self._items: list[Action | _Closed] = []
        self._span: FieldSpan | None = None
        self._next_span = 1
        self._mark_next = False
        self._held: dict[int, _Held] = {}
        self._presses: dict[str, _Press] = {}
        self._pending: _PendingChar | None = None
        self._caps = False
        self._paused = False
        self._finished = False
        self._last_click: ClickAction | None = None
        self._last_wheel_t: int | None = None
        self._ime_events: list[Mapping[str, Any]] = []
        self._obs: list[Mapping[str, Any]] = []
        self._samples: list[Mapping[str, Any]] = []

    # ------------------------------------------------------------ 입력

    def feed_ime(self, samples: Sequence[Mapping[str, Any]]) -> None:
        self._samples.extend(samples)

    def feed(self, event: Mapping[str, Any], obs: Mapping[str, Any] | None = None) -> None:
        if self._finished:
            raise RuntimeError("이미 끝난 변환기다")
        kind = event["kind"]
        t = int(event["t_ns"])
        if obs is not None:
            self._obs.append(obs)
        if kind == "key_up" and event.get("vk") in IME_SWITCH_VKS:
            self._ime_events.append(event)
        if kind == "mouse_move":
            self.moves.append((t, int(event["x"]), int(event["y"])))
            return
        if self._paused:
            self._paused_event(event)
            return
        verdict = self.filter.classify(event, obs)
        if verdict.obs is not None and verdict.obs.get("fg") != self.filter.target:
            self._left_window()
        if (
            self._span is not None
            and self._span.start_kind != "none"  # 구간 밖 글자 묶음에는 칸이 없다
            and self.presence is not None
            and self.presence.gone(self._span, t)
        ):
            self._close_span()
        if self._span is not None and self._span.start_kind == "none" and kind != "key_up":
            last = self._span.t_last if self._span.t_last is not None else self._span.t_start
            if t - last > self.o.loose_gap_ns:
                self._close_span()
        match kind:
            case "mouse_down":
                self._mouse_down(event, verdict)
            case "mouse_up":
                self._mouse_up(event, verdict)
            case "wheel":
                self._wheel(event, verdict)
            case "key_down":
                self._key_down(event, verdict)
            case "key_up":
                self._key_up(event, verdict)
            case _:
                pass
        self._announce()

    def _announce(self) -> None:
        """지금 구간에 첫 편집이 들어왔으면 한 번 알린다."""
        span = self._span
        if span is None or span.empty or span.span_id in self._announced:
            return
        self._announced.add(span.span_id)
        if self.on_span_open is not None:
            self.on_span_open(span)

    # ------------------------------------------------------------ 창 판정

    def _accept(self, verdict: Verdict) -> tuple[bool, tuple[str, ...]]:
        """(녹화하는가, 확인 필요 이유). 창 밖·팝업은 세고 버린다 — 게임 창을 떠난 것이라 구간도
        닫는다."""
        if verdict.where == "target":
            return True, ()
        if verdict.where == "undetermined":
            return True, ("window_undetermined",)
        if verdict.where == "popup":
            self.counts.ignored_popup += 1
        else:
            self.counts.ignored_outside += 1
        self._commit_pending()
        self._close_span()
        return False, ()

    def _left_window(self) -> None:
        """포그라운드가 대상 창이 아님을 관측했다: 눌려 있던 키(수정 키·글자 키·그 밖)는 떼어진
        것으로 보고 동작을 만들지 않는다(돌아온 뒤 뗀 것도). 아직 확정하지 않은 글자도 버린다.
        바로 앞 동작이 창 전환 조합이면 그 조합 때문에 떠난 것이라 지운다."""
        last = self._items[-1] if self._items else None
        if isinstance(last, KeyAction) and _is_switch_combo(last.keys):
            self._items.pop()
            self.counts_switch += 1
        for held in self._held.values():
            if held.modifier or held.keys is not None or held.char is not None:
                self.warnings.append(ConverterWarning("key_held_across_focus_loss", held.t_ns))
        self._held.clear()
        self._pending = None
        self._close_span()

    # ------------------------------------------------------------ 마우스

    def _mouse_down(self, event: Mapping[str, Any], verdict: Verdict) -> None:
        ok, review = self._accept(verdict)
        if not ok:
            return
        if self._outside_by_geometry(verdict):
            return
        self._commit_pending()
        self._use_modifiers()
        if verdict.gen is None:
            review = (*review, "geometry_unresolved")
        button = str(event["button"])
        self._presses[button] = _Press(
            button,
            int(event["t_ns"]),
            (int(event["x"]), int(event["y"])),
            verdict.client,
            verdict.gen is not None,
            review,
            int(event["event_id"]),
        )

    def _outside_by_geometry(self, verdict: Verdict) -> bool:
        """창 판정 불가지만 확정 기하로 클라이언트 밖임이 확인됨 → 제외(센다). 기하도 모르면
        버리지 않는다 — 점 없는 동작 + `window_undetermined`·`geometry_unresolved`로 남긴다."""
        if verdict.where == "undetermined" and verdict.gen is not None and verdict.client is None:
            self.counts.undetermined += 1
            return True
        return False

    def _mouse_up(self, event: Mapping[str, Any], verdict: Verdict) -> None:
        press = self._presses.pop(str(event["button"]), None)
        if press is None:
            return
        t = int(event["t_ns"])
        end_screen = (int(event["x"]), int(event["y"]))
        dx, dy = end_screen[0] - press.screen[0], end_screen[1] - press.screen[1]
        if max(abs(dx), abs(dy)) <= self.o.click_px:
            self._click(press)
            return
        gen = self.geometry.generation_at(t) or self.geometry.generation_at(press.t_ns)
        end, clipped = (None, False) if gen is None else clip_to_client(gen, end_screen)
        badges = ("end_point_pixels", *(("end_clipped",) if clipped else ()))
        self._close_span()
        self._items.append(
            DragAction(
                t_ns=press.t_ns,
                button=press.button,
                start=press.client,
                end=end,
                screen_start=press.screen,
                duration_ms=(t - press.t_ns) // MS,
                clipped=clipped,
                needs_review=press.review,
                badges=badges,
            )
        )

    def _click(self, press: _Press) -> None:
        last = self._last_click
        if (
            last is not None
            and self._items
            and self._items[-1] is last
            and last.button == press.button
            and last.count == 1
            and press.t_ns - last.t_ns <= self.o.double_click_ns
            and abs(press.screen[0] - last.screen[0]) <= self.o.double_click_px
            and abs(press.screen[1] - last.screen[1]) <= self.o.double_click_px
        ):
            double = ClickAction(
                t_ns=last.t_ns,
                button=last.button,
                point=last.point,
                screen=last.screen,
                count=2,
                event_id=last.event_id,
                needs_review=tuple(sorted({*last.needs_review, *press.review})),
            )
            self._items[-1] = double
            self._last_click = double
            return
        if press.button == "left":
            if not self._start_field_by_click(press):
                return  # 칸 안 클릭: 구간이 흡수했다 (커서 이동)
        elif not self._inside_field(press):
            self._close_span()  # 칸 밖 클릭은 버튼과 무관하게 구간을 끝낸다
        click = ClickAction(
            t_ns=press.t_ns,
            button=press.button,
            point=press.client,
            screen=press.screen,
            event_id=press.event_id,
            needs_review=press.review,
        )
        self._items.append(click)
        self._last_click = click

    def _inside_field(self, press: _Press) -> bool:
        """지금 칸 구간의 칸 상자(아는 경우만) 안 클릭인가."""
        span = self._span
        if span is None or span.start_kind != "click" or self.field_box is None:
            return False
        box = self.field_box(span)
        point = press.client
        if box is None or point is None:
            return False
        x, y, w, h = box
        return x <= point[0] < x + w and y <= point[1] < y + h

    def _start_field_by_click(self, press: _Press) -> bool:
        """새 구간을 열면 True. 지금 칸 안 클릭이면 커서 이동으로 흡수하고 False."""
        if self._inside_field(press):
            assert self._span is not None
            self._span.cursor_moved(press.t_ns)
            return False
        self._close_span()
        self._open_span("click", press.t_ns, press.client)
        return True

    def _wheel(self, event: Mapping[str, Any], verdict: Verdict) -> None:
        ok, review = self._accept(verdict)
        if not ok or self._outside_by_geometry(verdict):
            return
        self._commit_pending()
        t = int(event["t_ns"])
        screen = (int(event["x"]), int(event["y"]))
        delta = int(event["delta"])
        horizontal = bool(event.get("horizontal", False))
        last = self._items[-1] if self._items else None
        if (
            isinstance(last, ScrollAction)
            and self._last_wheel_t is not None
            and t - self._last_wheel_t <= self.o.wheel_ns
            and last.horizontal == horizontal
            and abs(screen[0] - last.screen[0]) <= self.o.wheel_px
            and abs(screen[1] - last.screen[1]) <= self.o.wheel_px
        ):
            self._items[-1] = ScrollAction(
                t_ns=last.t_ns,
                point=last.point,
                screen=last.screen,
                delta=last.delta + delta,
                horizontal=horizontal,
                needs_review=last.needs_review,
                badges=last.badges,
            )
        else:
            self._close_span()
            if verdict.gen is None:
                review = (*review, "geometry_unresolved")
            self._items.append(
                ScrollAction(
                    t_ns=t,
                    point=verdict.client,
                    screen=screen,
                    delta=delta,
                    horizontal=horizontal,
                    needs_review=review,
                    badges=("end_point_pixels",),
                )
            )
        self._last_wheel_t = t

    # ------------------------------------------------------------ 키

    def _modifiers(self) -> set[str]:
        return {
            name
            for vk, held in self._held.items()
            if held.modifier and (name := vk_name(vk)) is not None
        }

    def _use_modifiers(self) -> None:
        for held in self._held.values():
            if held.modifier:
                held.used = True

    def _key_down(self, event: Mapping[str, Any], verdict: Verdict) -> None:
        vk = int(event["vk"])
        t = int(event["t_ns"])
        if vk in self._held:
            self.counts.autorepeat += 1  # 자동 반복
            return
        ok, review = self._accept(verdict)
        if not ok:
            return
        if is_modifier(vk):
            self._held[vk] = _Held(t, modifier=True, review=review)
            return
        name = vk_name(vk, bool(event.get("extended", False)))
        mods = self._modifiers()
        if name is not None and combo_name(mods, name) in self.o.hotkeys:
            self._use_modifiers()
            self.counts.hotkeys += 1
            self._held[vk] = _Held(t)
            if combo_name(mods, name) == self.o.secret_hotkey:
                if self._span is not None:
                    self._span.marked_secret = True
                else:
                    self._mark_next = True
            return
        self._use_modifiers()
        self._commit_pending()
        if vk == VK_CAPITAL:
            self._caps = not self._caps
        if name is None:
            self.warnings.append(ConverterWarning("unknown_key", t))
            self._held[vk] = _Held(t)
            return
        obs = verdict.obs
        hkl = None if obs is None else obs.get("hkl")
        shift = "shift" in mods
        if mods - {"shift"}:
            self._combo(vk, combo_name(mods, name), t, review)
            return
        printable = self.layout.char(vk, shift=shift, caps=self._caps, hkl=hkl) is not None
        if printable and layout_kind(hkl) == "cjk_ime":
            # 일본어·중국어 입력기: 글자를 짤 수 없으니 키 사슬로 남긴다
            self._close_span()
            keys = combo_name(mods, name)
            self._items.append(
                KeyAction(t_ns=t, keys=keys, needs_review=review, badges=("ime_other",))
            )
            self._held[vk] = _Held(t)
            return
        if printable:
            self._pending = _PendingChar(vk, shift, self._caps, t, hkl, obs, combo_name(mods, name))
            self._held[vk] = _Held(t, char=self._pending, review=review)
            return
        self._special(vk, combo_name(mods, name), t, review)

    def _combo(self, vk: int, keys: str, t: int, review: tuple[str, ...]) -> None:
        span = self._span
        if span is not None and keys == "ctrl+a":
            span.select_all(t)
            self._held[vk] = _Held(t)
            return
        # 그 밖의 조합(붙여넣기 등)은 칸의 최종 문자열을 알 수 없게 하므로 구간을 닫는다
        self._close_span()
        self._items.append(KeyAction(t_ns=t, keys=keys, needs_review=review))
        self._held[vk] = _Held(t)

    def _special(self, vk: int, keys: str, t: int, review: tuple[str, ...]) -> None:
        span = self._span
        if span is not None and vk == VK_BACK:
            span.backspace(t)
            self._held[vk] = _Held(t)
            return
        if span is not None and vk in CURSOR_KEYS:
            span.cursor_moved(t)
            self._held[vk] = _Held(t)
            return
        if span is not None and vk == VK_CAPITAL:
            self._held[vk] = _Held(t)  # 칸 안 대소문자 전환은 글자에 이미 반영된다
            return
        if vk in (VK_RETURN, VK_ESCAPE, VK_TAB):
            self._close_span()
        self._close_loose()  # 키 동작 앞뒤 글자를 한 묶음으로 합치지 않는다
        self._held[vk] = _Held(t, keys=keys, review=review)
        if vk == VK_TAB:
            self._open_span("tab", t, None)

    def _key_up(self, event: Mapping[str, Any], verdict: Verdict) -> None:
        vk = int(event["vk"])
        t = int(event["t_ns"])
        held = self._held.pop(vk, None)
        if held is None:
            return
        away = verdict.where in ("outside", "popup")
        if held.modifier:
            if not held.used and not away:
                name = vk_name(vk) or "shift"
                hold = t - held.t_ns
                self._emit_key(name, held.t_ns, hold, held.review)
            return
        if held.char is not None:
            pending = held.char
            if away and self._pending is pending:
                # 누른 채 게임 창을 떠났다: 글자로 확정하지 않는다
                self._pending = None
                self.warnings.append(ConverterWarning("key_held_across_focus_loss", held.t_ns))
                return
            if self._pending is pending:
                hold = t - pending.t_ns
                if hold > self.o.hold_ns and not away:
                    self._pending = None
                    self._emit_key(pending.name, pending.t_ns, hold, held.review, force_hold=True)
                else:
                    self._commit_pending()
            return
        if held.keys is not None:
            if away:
                # 누른 채 게임 창을 떠났다: 떼어진 것으로 보고 동작을 만들지 않는다
                self.warnings.append(ConverterWarning("key_held_across_focus_loss", held.t_ns))
                return
            self._emit_key(held.keys, held.t_ns, t - held.t_ns, held.review)

    def _emit_key(
        self,
        keys: str,
        t_down: int,
        hold: int,
        review: tuple[str, ...],
        *,
        force_hold: bool = False,
    ) -> None:
        hold_ms = hold // MS if (force_hold or hold > self.o.hold_ns) else None
        self._close_loose()
        self._items.append(KeyAction(t_ns=t_down, keys=keys, hold_ms=hold_ms, needs_review=review))

    def _close_loose(self) -> None:
        """구간 밖 글자 묶음은 별도 키 동작에서 끝난다 (입력 칸 구간은 그대로)."""
        if self._span is not None and self._span.start_kind == "none":
            self._close_span()

    def _commit_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        if self._span is None:
            self._open_span("none", pending.t_ns, None)
        assert self._span is not None
        self._span.add_key(
            pending.vk,
            shift=pending.shift,
            caps=pending.caps,
            t_ns=pending.t_ns,
            hkl=pending.hkl,
            obs=pending.obs,
        )

    # ------------------------------------------------------------ 구간

    def _open_span(
        self, kind: Literal["click", "tab", "none"], t: int, anchor: tuple[int, int] | None
    ) -> None:
        span = FieldSpan(self._next_span, kind, t, anchor)
        self._next_span += 1
        if self._mark_next:
            span.marked_secret = True
            self._mark_next = False
        self._span = span

    def _close_span(self, *review: str) -> None:
        span = self._span
        if span is None:
            return
        self._announce()  # 같은 입력에서 첫 편집과 닫힘이 함께 올 수 있다
        self._span = None
        if span.empty:
            return
        self._items.append(_Closed(span, review))

    # ------------------------------------------------------------ 일시정지·끝

    def pause(self) -> None:
        """일시정지: 열린 구간은 열어 둔다. 그동안 들어온 입력은 버린다."""
        self._commit_pending()
        self._announce()
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def _paused_event(self, event: Mapping[str, Any]) -> None:
        kind = event["kind"]
        if kind == "key_up":
            held = self._held.pop(int(event["vk"]), None)
            if held is not None and held.keys is not None:
                self.warnings.append(ConverterWarning("released_during_pause", held.t_ns))
        elif kind == "mouse_up":
            press = self._presses.pop(str(event["button"]), None)
            if press is not None:
                self.warnings.append(ConverterWarning("released_during_pause", press.t_ns))

    def finish(self, reason: Literal["stop", "cut"] = "stop") -> list[Action]:
        """녹화를 닫는다. `cut`(훅 끊김·유실)이면 그때 열려 있던 구간·누름은 확인 필요.
        떼지 않은 키·버튼·끌기는 동작을 만들지 않는다."""
        if not self._finished:
            self._commit_pending()
            for held in self._held.values():
                if held.keys is not None:
                    self.warnings.append(ConverterWarning("held_at_stop", held.t_ns))
            for press in self._presses.values():
                self.warnings.append(ConverterWarning("held_at_stop", press.t_ns))
            self._held.clear()
            self._presses.clear()
            self._close_span(*(("cut_by_stop",) if reason == "cut" else ()))
            self._finished = True
        return self.actions()

    @property
    def span(self) -> FieldSpan | None:
        """지금 열린 구간."""
        return self._span

    def settled(self, now_ns: int, settle_ns: int = 400 * MS) -> bool:
        """닫힌 구간이 모두 마지막 편집 뒤 `settle_ns`가 지났는가 — `actions()`가 글자를 짜도 되는가
        (IME 표본이 마지막 키 뒤 300 ms까지 온다)."""
        for item in self._items:
            if isinstance(item, _Closed):
                last = item.span.t_last if item.span.t_last is not None else item.span.t_start
                if now_ns - last < settle_ns:
                    return False
        return True

    def actions(self) -> list[Action]:
        """지금까지의 동작 (시각 차례). 닫힌 구간은 여기서 글자를 짠다 — IME 표본이 모인 뒤에."""
        out: list[Action] = []
        for i, item in enumerate(self._items):
            if isinstance(item, _Closed):
                item = self._items[i] = self._text(item)
            out.append(item)
        return sorted(out, key=lambda a: a.t_ns)

    def _mode_at(self, t: int, obs: Mapping[str, Any] | None) -> Any:
        changes = ime_changes(self._ime_events, self._obs, self._samples)
        return ime_mode_at(t, self._samples, changes, key_obs=obs)

    def _text(self, closed: _Closed) -> TextAction:
        span = closed.span
        result = span.finalize(self._mode_at, self.layout)
        t_first = span.t_first if span.t_first is not None else span.t_start
        return TextAction(
            t_ns=t_first,
            text=result.text,
            clear=result.clear,
            in_field=span.start_kind != "none",
            span_id=span.span_id,
            start_kind=span.start_kind,
            anchor=span.anchor,
            t_end=span.t_last if span.t_last is not None else t_first,
            password_hint=span.password_hint,
            marked_secret=span.marked_secret,
            needs_review=tuple(sorted({*result.review, *closed.review})),
            badges=tuple(sorted(result.badges)),
        )

    def wipe(self) -> None:
        """세션 끝: 메모리의 글자를 지운다."""
        for item in self._items:
            if isinstance(item, TextAction):
                item.text.wipe()
        self._items.clear()
        self._span = None
        self._pending = None
