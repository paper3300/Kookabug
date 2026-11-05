"""변환기 검사용 가짜 훅 이벤트 각본 (M4 T5). 훅 프로세스와 같은 번호 규칙으로 이벤트·즉시 관측을
만든다. 좌표는 클라이언트로 주고 화면 좌표로 바꿔 넣는다 (창 원점 `ORIGIN`)."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kookabug_core.recorder.actions import Action, Converter, ConverterOptions
from kookabug_core.recorder.fields import FieldPresence

MS = 1_000_000
TARGET = 0x1000
POPUP = 0x2000
OTHER = 0x3000
APP = 0x4000
US = "4090409"
KO = "4120412"
JA = "4110411"
ORIGIN = (100, 80)
CLIENT = (1024, 640)

VK = {
    "shift": 0xA0, "ctrl": 0xA2, "alt": 0xA4, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23, "delete": 0x2E,
    "space": 0x20, "f5": 0x74, "hangul": 0x15, "capslock": 0x14,
}  # fmt: skip
_SHIFTED = {"!": "1", "@": "2", "#": "3", "_": "-"}
_PUNCT = {"-": 0xBD, ".": 0xBE, " ": 0x20}


def char_vk(ch: str) -> tuple[int, bool]:
    """US 배열 글자 → (vk, shift)."""
    if ch.isalpha():
        return ord(ch.upper()), ch.isupper()
    if ch.isdigit():
        return ord(ch), False
    if ch in _SHIFTED:
        return char_vk(_SHIFTED[ch])[0], True
    return _PUNCT[ch], False


@dataclass(frozen=True)
class FakeGeometry:
    origin: tuple[int, int] = ORIGIN
    size: tuple[int, int] = CLIENT

    @property
    def client_origin(self) -> tuple[int, int]:
        return self.origin

    @property
    def client_size(self) -> tuple[int, int]:
        return self.size


@dataclass(frozen=True)
class FakeGen:
    gen: int
    geometry: FakeGeometry


class FakeTimeline:
    """세대 구간 `(from_ns, to_ns, 원점)` 표. 구간 밖은 불확실 (None)."""

    def __init__(self, spans: list[tuple[int, int, tuple[int, int]]] | None = None) -> None:
        self.spans = spans or [(0, 10**15, ORIGIN)]

    def generation_at(self, t_ns: int) -> FakeGen | None:
        for i, (lo, hi, origin) in enumerate(self.spans):
            if lo <= t_ns <= hi:
                return FakeGen(i + 1, FakeGeometry(origin))
        return None


class Script:
    def __init__(self) -> None:
        self.t = 0
        self.events: list[dict[str, Any]] = []
        self.obs: dict[int, dict[str, Any]] = {}
        self.samples: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self._crit = itertools.count(1)
        self.fg = TARGET
        self.point = TARGET
        self.hkl: str | None = US
        self.obs_delay_ms = 1.0
        self.origin: tuple[int, int] = ORIGIN

    def at(self, ms: float) -> Script:
        self.t = int(ms * MS)
        return self

    def wait(self, ms: float) -> Script:
        self.t += int(ms * MS)
        return self

    def _screen(self, x: int, y: int) -> tuple[int, int]:
        return x + self.origin[0], y + self.origin[1]

    def event(self, kind: str, *, obs: bool = True, **fields: Any) -> dict[str, Any]:
        event = {
            "event_id": next(self._ids),
            "t_ns": self.t,
            "kind": kind,
            "injected": False,
            "injected_lower_il": False,
            "extra_info": 0,
            **fields,
        }
        if kind != "mouse_move":
            event["crit_seq"] = next(self._crit)
        self.events.append(event)
        if kind != "mouse_move" and obs:
            is_mouse = kind.startswith("mouse") or kind == "wheel"
            point_owner = TARGET if self.point == POPUP else None
            self.obs[event["event_id"]] = {
                "cause_event_id": event["event_id"],
                "obs_at_ns": self.t + int(self.obs_delay_ms * MS),
                "fg": self.fg,
                "fg_owner": TARGET if self.fg == POPUP else None,
                "fg_thread": 1,
                "focus": self.fg,
                "focus_password": False,
                "hkl": self.hkl,
                "table_changed_ns": 0,
                "zorder_rev": 1,
                **({"point_window": self.point, "point_owner": point_owner} if is_mouse else {}),
            }
        return event

    # 마우스 (클라이언트 좌표)
    def move(self, x: int, y: int) -> Script:
        sx, sy = self._screen(x, y)
        self.event("mouse_move", x=sx, y=sy)
        return self

    def down(self, x: int, y: int, button: str = "left") -> Script:
        sx, sy = self._screen(x, y)
        self.event("mouse_down", x=sx, y=sy, button=button)
        return self

    def up(self, x: int, y: int, button: str = "left") -> Script:
        sx, sy = self._screen(x, y)
        self.event("mouse_up", x=sx, y=sy, button=button)
        return self

    def click(self, x: int, y: int, button: str = "left", hold_ms: float = 60) -> Script:
        self.down(x, y, button).wait(hold_ms).up(x, y, button)
        return self.wait(40)

    def wheel(self, x: int, y: int, delta: int = 120) -> Script:
        sx, sy = self._screen(x, y)
        self.event("wheel", x=sx, y=sy, delta=delta)
        return self

    # 키
    def key_down(self, vk: int, extended: bool = False) -> Script:
        self.event("key_down", vk=vk, scan=0, extended=extended)
        return self

    def key_up(self, vk: int, extended: bool = False) -> Script:
        self.event("key_up", vk=vk, scan=0, extended=extended)
        return self

    def tap(self, key: str | int, hold_ms: float = 40, gap_ms: float = 40) -> Script:
        vk = VK[key] if isinstance(key, str) else key
        extended = vk in (0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x2E)
        self.key_down(vk, extended).wait(hold_ms).key_up(vk, extended)
        return self.wait(gap_ms)

    def combo(self, *keys: str) -> Script:
        vks = [VK[k] if k in VK else ord(k.upper()) for k in keys]
        for vk in vks:
            self.key_down(vk).wait(10)
        for vk in reversed(vks):
            self.key_up(vk).wait(10)
        return self.wait(30)

    def type(self, text: str, gap_ms: float = 80) -> Script:
        for ch in text:
            vk, shift = char_vk(ch)
            if shift:
                self.key_down(VK["shift"]).wait(5)
            self.tap(vk, hold_ms=30, gap_ms=5)
            if shift:
                self.key_up(VK["shift"])
            self.wait(gap_ms)
        return self

    def ime(self, mode: str, *, status: str = "ok", at_ms: float | None = None) -> Script:
        t = self.t if at_ms is None else int(at_ms * MS)
        sample = {
            "query_started_ns": t,
            "sampled_at_ns": t + MS,
            "fg": self.fg,
            "fg_thread": 1,
            "hkl": self.hkl,
            "status": status,
            "mode": mode if status == "ok" else "unknown",
            "trigger": "periodic",
        }
        if status == "ok":
            sample["conversion"] = 1 if mode == "native" else 0
        self.samples.append(sample)
        return self

    def converter(
        self,
        timeline: FakeTimeline | None = None,
        *,
        options: ConverterOptions | None = None,
        presence: FieldPresence | None = None,
        field_box: Callable[..., Any] | None = None,
    ) -> Converter:
        conv = Converter(
            TARGET,
            timeline or FakeTimeline(),
            options=options,
            presence=presence,
            field_box=field_box,
        )
        conv.feed_ime(self.samples)
        for event in self.events:
            conv.feed(event, self.obs.get(event["event_id"]))
        return conv

    def run(self, timeline: FakeTimeline | None = None, **kwargs: Any) -> list[Action]:
        return self.converter(timeline, **kwargs).finish()


def texts(actions: list[Action]) -> list[str]:
    from kookabug_core.recorder.actions import TextAction

    return [a.text.reveal() for a in actions if isinstance(a, TextAction)]


def kinds(actions: list[Action]) -> list[str]:
    return [a.kind for a in actions]
