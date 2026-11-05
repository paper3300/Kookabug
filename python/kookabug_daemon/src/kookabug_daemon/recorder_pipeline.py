"""녹화 파이프라인 (M4 계획 2.5~2.9, T8): 훅 이벤트 → 동작 → 프레임 붙잡기 → target·대기 → 비밀 판정
→ 스텝. 녹화 세션 하나가 하나를 쓴다.

- **붙잡기**(`hold`, 훅 스레드에서 받는 즉시): 버튼·휠·키 down마다 그 시각 앞 프레임을 링에서
  붙잡는다(링에서 밀려나기 전에). 클릭 직전·키 직전·구간 시작 직전 프레임이 이것이다
- **먹이기**(`feed`, 처리 스레드): 이벤트는 그 즉시 관측이 오고 그 시각의 기하가 확인된 뒤 변환기에
  넣는다(관측 200 ms·기하 500 ms를 넘게 기다리면 없는 채로 — 판정 불가로 남는다)
- **구간 열림**(변환기 `on_span_open`): 칸 상자(클릭 구간 = 클릭 직전 프레임의 경계 추정, Tab 구간 =
  Tab 직전·첫 키 직전 프레임의 포커스 테두리)를 정하고 판정·보호 영역·칸 존재를 연다
- **프레임 훑기**: 새 링 프레임마다 칸 존재(`FieldPresenceTracker.observe`)와 바뀐 시각(대기 추론의
  전이)을 적는다. 칸 없음이 확정되면 보호를 끝내고 같은 칸 상속을 끊는다
- **만들기**(`refresh`): 닫힌 구간이 마지막 키 뒤 400 ms 지나면 변환기 동작을 스텝으로 만든다 —
  클릭은 같은 확정 세대 프레임에서만 자르고(보호 영역을 피함), 재사용·이름(보호 규칙), 앞 동작과의
  대기 추론, 글자 구간은 판정 재료(라벨·끝난 뒤 칸 OCR)를 다음 동작 직전 프레임으로 본다

글자 원문은 `RecorderTexts`(메모리)에만 있다. 스텝 JSON(`step_json`)은 `ordinary`일 때만 `text`를
싣고 세션 저장소용(`reveal=False`)은 싣지 않는다. 로그에는 개수만 쓴다.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import numpy as np

from kookabug_core.recorder.actions import (
    Action,
    ClickAction,
    Converter,
    ConverterOptions,
    DragAction,
    KeyAction,
    ScrollAction,
    TextAction,
)
from kookabug_core.recorder.fields import FieldSpan, SecretText
from kookabug_core.recorder.protect import Box, ProtectionSet, sanitize_name
from kookabug_core.recorder.secrets import RecorderTexts
from kookabug_core.recorder.waits import NextKind
from kookabug_platform.dpi import normalized_to_pixels
from kookabug_platform.recorder.crop import crop_click, estimate_bounds
from kookabug_platform.recorder.evidence import ReadText, field_text, label_text, tab_field_box
from kookabug_platform.recorder.frames import (
    ClickFrame,
    FrameHolds,
    FrameSource,
    RingEntry,
    Unresolved,
    click_frame,
    pre_hover,
)
from kookabug_platform.recorder.geometry import Generation
from kookabug_platform.recorder.presence import FieldPresenceTracker
from kookabug_platform.recorder.targets import Candidate, SessionTargets, name_for_box
from kookabug_platform.recorder.waits import infer_wait
from kookabug_platform.vision import FrameMeta, Pixels, Vision

__all__ = ["FrameRef", "Pipeline", "Step"]

log = logging.getLogger(__name__)

MS: Final = 1_000_000
OBS_WAIT_NS: Final = 200 * MS
GEOMETRY_WAIT_NS: Final = 500 * MS
SETTLE_NS: Final = 400 * MS
_CHANGE_LEVEL: Final = 24
_HOLD_KINDS: Final = frozenset({"mouse_down", "key_down", "wheel"})

type StepKind = Literal[
    "check_text", "check_visible", "click", "delay", "drag", "key", "scroll", "text", "wait"
]
type FrameWhich = Literal["pre_click", "pre_hover", "pre_next"]

_NEXT_KIND: Final[dict[str, NextKind]] = {
    "click": "click",
    "drag": "drag",
    "scroll": "scroll",
    "key": "key",
    "text": "text",
    "check_visible": "check",
    "check_text": "check",
}

BADGE_TEXT: Final[dict[str, tuple[str, str]]] = {
    "same_shape": ("review", "같은 모양이 여러 곳 — 검색 범위를 좁히세요"),
    "hover_maybe": ("info", "마우스를 올린 모양일 수 있어요"),
    "end_point_pixels": ("info", "끝점은 픽셀 좌표"),
    "end_clipped": ("info", "끝점을 게임 화면 가장자리로 잘랐어요"),
    "reused": ("info", "기존 대상 재사용"),
    "hangul_guess": ("review", "한글 조합 추정 — 확인하세요"),
    "ime_other": ("review", "입력기 글자는 키 사슬로 남겼어요"),
    "secret_required": ("warning", "비밀값 선택 필요"),
}


@dataclass(frozen=True, slots=True, eq=False)
class FrameRef:
    """같은 확정 세대로 검증된 프레임 (클라이언트로 자를 수 있다)."""

    entry: RingEntry
    generation: Generation

    @property
    def arrival_ns(self) -> int:
        return self.entry.arrival_ns

    @property
    def client_size(self) -> tuple[int, int]:
        return self.generation.geometry.client_size

    @property
    def dpi(self) -> int:
        return self.generation.geometry.dpi

    def client(self) -> Pixels:
        return np.ascontiguousarray(self.generation.geometry.crop_client(self.entry.buffer))


@dataclass
class _Field:
    box: Box | None
    start: FrameRef | None
    t_start: int


@dataclass
class _Prev:
    t_ns: int
    ref: FrameRef | Pixels | None
    field_box: Box | None


@dataclass
class Step:
    """녹화 스텝 하나 (= 재생 동작 하나, 노드는 하나 이상)."""

    step_id: str
    kind: StepKind
    t_ns: int
    node_type: str
    title: str
    input: dict[str, Any] = field(default_factory=dict[str, Any])
    needs_review: list[str] = field(default_factory=list[str])
    badges: list[str] = field(default_factory=list[str])
    target: str | None = None
    """초안 ID(`d1`) 또는 워크스페이스 target 경로."""
    reused: bool = False
    name: str = ""
    frames: dict[str, FrameRef | Pixels] = field(default_factory=lambda: {})
    span_id: int | None = None
    clear: bool = False
    timeout_ms: int | None = None
    ms: int | None = None
    equals: str | None = None
    deleted: bool = False
    kept: bool = False
    peaks: int | None = None
    classified: bool = False
    invalidated: bool = False
    """만든 뒤 보호 상태가 바뀌어(일반 → 비밀값) 초안·이름·문구를 버렸다 — 사람이 고치기 전에는
    커밋하지 않는다 (`secret_region_overlap`)."""

    @property
    def needs_target(self) -> bool:
        return self.kind in ("click", "drag", "wait", "check_visible", "check_text")


class Pipeline:
    """녹화 세션 하나의 변환 상태. `lock` 아래에서 부른다 (붙잡기만 잠금 없이 — 따로 잠금)."""

    def __init__(
        self,
        *,
        target_hwnd: int,
        source: FrameSource,
        options: ConverterOptions,
        read_text: ReadText | None,
        vision: Vision,
        workspace_targets: list[Candidate],
        on_store_frame: Callable[[FrameRef], None] | None = None,
    ) -> None:
        self.lock = threading.RLock()
        self.source = source
        self.timeline = source.geometry
        self.read_text = read_text
        self.vision = vision
        self.holds = FrameHolds()
        self._held_lock = threading.Lock()
        self._held_at: dict[int, RingEntry | None] = {}
        self.tracker = FieldPresenceTracker()
        self.protect = ProtectionSet(absent_in=self.tracker.absent_in)
        self.texts = RecorderTexts()
        self.converter = Converter(
            target_hwnd,
            self.timeline,
            options=options,
            presence=self.tracker,
            field_box=self._field_box_of,
            on_span_open=self._span_opened,
        )
        self.targets = SessionTargets(vision, workspace_targets)
        self.draft_frames: dict[str, FrameRef | Pixels] = {}
        """초안 ID → 자른 프레임 (커밋 때 target 파일을 쓴다)."""
        self.steps: list[Step] = []
        self._ids = itertools.count(1)
        self._built: set[tuple[Any, ...]] = set()
        self._pending: deque[dict[str, Any]] = deque()
        self._obs: dict[int, dict[str, Any]] = {}
        self.latest_ns = 0
        self.last_fg: int | None = None
        """마지막 즉시 관측의 포그라운드 ("게임 창이 앞에 없어요")."""
        self._last_seq = 0
        self._prev_buffer: Pixels | None = None
        self._changes: list[int] = []
        self._fields: dict[int, _Field] = {}
        self._prev: _Prev | None = None
        self._last_text_box: Box | None = None
        self.final_frame: FrameRef | None = None
        self.finished = False
        self.rev = 0
        self._on_store_frame = on_store_frame

    # ------------------------------------------------------------ 붙잡기 (훅 스레드)

    def hold(self, events: list[dict[str, Any]]) -> None:
        """버튼·휠·키 down의 그 시각 앞 프레임을 붙잡는다 (받는 즉시, 변환보다 먼저)."""
        ring = self.source.ring
        with self._held_lock:
            for event in events:
                if event.get("kind") in _HOLD_KINDS:
                    t = int(event["t_ns"])
                    if t not in self._held_at:
                        self._held_at[t] = self.holds.hold_before(ring, t)

    def held(self, t_ns: int) -> RingEntry | None:
        with self._held_lock:
            return self._held_at.get(t_ns)

    def _held_after(self, t_ns: int) -> RingEntry | None:
        """`t_ns` 뒤 첫 down 이벤트 앞에 붙잡은 프레임 (구간 뒤 칸을 볼 프레임)."""
        with self._held_lock:
            later = sorted(t for t in self._held_at if t > t_ns)
            return self._held_at[later[0]] if later else None

    # ------------------------------------------------------------ 먹이기 (처리 스레드)

    def feed(self, update: Any, now_ns: int) -> None:
        """`HookUpdate` 하나 (이벤트·즉시 관측·IME 표본)."""
        self.latest_ns = max(self.latest_ns, now_ns)
        self.scan_frames()
        for obs in update.obs:
            self._obs[int(obs["cause_event_id"])] = obs
            self.last_fg = obs.get("fg")
        if update.ime:
            self.converter.feed_ime(update.ime)
        self._pending.extend(update.events)
        self.flush(force=False)

    def flush(self, *, force: bool) -> None:
        """관측·기하가 준비된 이벤트를 차례대로 변환기에 넣는다 (`force`면 모두)."""
        while self._pending:
            event = self._pending[0]
            t = int(event["t_ns"])
            if not force:
                waited = self.latest_ns - t
                critical = "crit_seq" in event
                if critical and int(event["event_id"]) not in self._obs and waited < OBS_WAIT_NS:
                    break
                if not self.timeline.settled(t) and waited < GEOMETRY_WAIT_NS:
                    break
            self._pending.popleft()
            self.converter.feed(event, self._obs.pop(int(event["event_id"]), None))

    def pause(self) -> None:
        self.flush(force=True)
        self.converter.pause()

    def resume(self) -> None:
        self.converter.resume()

    def finish(self, reason: Literal["stop", "cut"]) -> None:
        """녹화를 닫는다: 남은 이벤트를 넣고 변환기를 끝낸 뒤 마지막 프레임을 붙잡는다."""
        if self.finished:
            return
        self.scan_frames()
        self.flush(force=True)
        self.converter.finish(reason)
        latest = self.source.ring.latest()
        if latest is not None:
            self.holds.hold(latest)
            self.final_frame = self._ref(latest)
        self.finished = True

    # ------------------------------------------------------------ 프레임

    def _ref(self, entry: RingEntry | None) -> FrameRef | None:
        if entry is None:
            return None
        gen = self.timeline.frame_generation(entry.arrival_ns, entry.buffer_size)
        return None if gen is None else FrameRef(entry, gen)

    def scan_frames(self) -> None:
        """새 링 프레임: 칸 존재·바뀐 시각."""
        for entry in self.source.ring.entries():
            if entry.seq <= self._last_seq:
                continue
            self._last_seq = entry.seq
            ref = self._ref(entry)
            client = None if ref is None else ref.client()
            for span_id in self.tracker.observe(entry.arrival_ns, client):
                gone = self.tracker.gone_at(span_id)
                self.protect.end(span_id, entry.arrival_ns if gone is None else gone)
                info = self._fields.get(span_id)
                if info is not None and info.box is not None:
                    self.texts.classifier.scene_changed(info.box)
            previous = self._prev_buffer
            buffer = entry.buffer
            if previous is None or previous.shape != buffer.shape:
                changed = previous is not None
            else:
                diff = np.abs(previous.astype(np.int16) - buffer.astype(np.int16)).max(axis=2)
                changed = bool((diff > _CHANGE_LEVEL).any())
            if changed:
                self._changes.append(entry.arrival_ns)
            self._prev_buffer = buffer

    # ------------------------------------------------------------ 구간

    def _field_box_of(self, span: FieldSpan) -> Box | None:
        info = self._fields.get(span.span_id)
        return None if info is None else info.box

    def _span_opened(self, span: FieldSpan) -> None:
        start = self._ref(self.held(span.t_start))
        box: Box | None = None
        if span.start_kind == "click" and start is not None and span.anchor is not None:
            box = estimate_bounds(start.client(), span.anchor)
        elif span.start_kind == "tab" and start is not None and span.t_first is not None:
            after = self._ref(self.held(span.t_first))
            if after is not None and after.client_size == start.client_size:
                box = tab_field_box(start.client(), after.client())
        self._fields[span.span_id] = _Field(box, start, span.t_start)
        self.texts.open_span(span.span_id, box)
        if box is not None and start is not None:
            self.protect.add(span.span_id, box, span.t_start)
            self.tracker.register(span.span_id, box, start.client(), span.t_start)

    # ------------------------------------------------------------ 스텝 만들기

    def _new_step(self, kind: StepKind, t_ns: int, node_type: str, title: str) -> Step:
        return Step(f"rs{next(self._ids)}", kind, t_ns, node_type, title)

    def _insert(self, step: Step) -> None:
        index = len(self.steps)
        while index > 0 and self.steps[index - 1].t_ns > step.t_ns:
            index -= 1
        self.steps.insert(index, step)

    def refresh(self) -> bool:
        """만들 수 있는 스텝을 만들고 판정 재료를 본다. 바뀌었으면 True (`rev` 올림)."""
        self.scan_frames()
        changed = False
        if self.finished or self.converter.settled(self.latest_ns, SETTLE_NS):
            for action in self.converter.actions():
                key = _action_key(action)
                if key in self._built:
                    continue
                if not self._build(action):
                    break  # 기하를 아직 모른다 — 다음에
                self._built.add(key)
                changed = True
        changed = self._classify() or changed
        if self.revalidate():
            changed = True
        if changed:
            self.rev += 1
        return changed

    def _build(self, action: Action) -> bool:
        ref = self._ref(self.held(action.t_ns))
        if isinstance(action, ClickAction | DragAction):
            return self._build_pointer(action, ref)
        if isinstance(action, TextAction):
            info = self._fields.get(action.span_id)
            box = None if info is None else info.box
            self.texts.add_text_action(action, box)
            step = self._new_step("text", action.t_ns, "core.input.type_text", "글자 입력")
            step.span_id = action.span_id
            step.clear = action.clear
            step.needs_review = list(action.needs_review)
            step.badges = list(action.badges)
            # Tab으로 옮긴 칸: 앞 칸 테두리가 꺼지고 이 칸이 켜진 것뿐이다 (두 칸을 합친 상자 안)
            field = box
            if action.start_kind == "tab":
                field = _union(self._last_text_box, box)
            self._before(step, ref, field_box=field)
            self._add(step, ref)
            self._prev = _Prev(action.t_ns, ref, box)
            self._last_text_box = box
            return True
        if isinstance(action, KeyAction):
            step = self._new_step("key", action.t_ns, "core.input.key", f"키 입력 {action.keys}")
            step.input = {"keys": action.keys}
            if action.hold_ms:
                step.input["hold_ms"] = action.hold_ms
        elif isinstance(action, ScrollAction):
            step = self._new_step("scroll", action.t_ns, "core.input.scroll", "휠")
            step.input = {"amount": action.amount}
            if action.point is not None:
                step.input["point"] = list(action.point)
            else:
                step.needs_review.append("geometry_unresolved")
        else:
            return True
        step.needs_review = sorted({*step.needs_review, *action.needs_review})
        step.badges = list(action.badges)
        self._before(step, ref)
        self._add(step, ref)
        self._prev = _Prev(action.t_ns, ref, None)
        return True

    def _build_pointer(self, action: ClickAction | DragAction, ref: FrameRef | None) -> bool:
        is_click = isinstance(action, ClickAction)
        screen = action.screen if isinstance(action, ClickAction) else action.screen_start
        frame = click_frame(self.held(action.t_ns), self.timeline, action.t_ns, screen)
        if isinstance(frame, Unresolved) and frame.reason == "pending":
            if not self.finished:
                return False
            frame = Unresolved("geometry_unresolved")
        if is_click:
            step = self._new_step("click", action.t_ns, "core.image.click", "이미지 클릭")
            assert isinstance(action, ClickAction)
            step.input = {"button": action.button, "count": action.count}
            if action.point is not None:
                step.input["point"] = list(action.point)
        else:
            assert isinstance(action, DragAction)
            step = self._new_step("drag", action.t_ns, "core.input.drag", "끌기")
            step.input = {"button": action.button, "duration_ms": action.duration_ms}
            if action.start is not None:
                step.input["point"] = list(action.start)
            if action.end is not None:
                step.input["end"] = list(action.end)
        step.needs_review = list(action.needs_review)
        step.badges = list(action.badges)
        if isinstance(frame, Unresolved):
            if frame.reason not in step.needs_review:
                step.needs_review.append(frame.reason)
        else:
            self._click_target(step, frame)
            step.frames["pre_click"] = FrameRef(frame.entry, frame.generation)
        self._before(step, ref)
        self._add(step, ref)
        self._prev = _Prev(action.t_ns, ref, None)
        return True

    def _meta(self, size: tuple[int, int], dpi: int) -> FrameMeta:
        return FrameMeta(size, dpi, backend="recorder")

    def _name(self, image: Pixels, box: Box, t_ns: int, fallback: str) -> str:
        return name_for_box(
            image,
            box,
            read_text=self.read_text,
            protect=self.protect,
            t_ns=t_ns,
            raw_texts=list(self.texts.protected_texts()),
            fallback=fallback,
        )

    def _click_target(self, step: Step, frame: ClickFrame) -> None:
        client = np.ascontiguousarray(frame.client_pixels())
        arrival = frame.entry.arrival_ns
        crop = crop_click(client, frame.client_point, protect=self.protect, t_ns=arrival)
        step.badges = sorted({*step.badges, *crop.badges})
        step.peaks = crop.same_shape
        if crop.box is None:
            step.needs_review = sorted({*step.needs_review, *crop.needs_review})
            return
        image, used = client, frame
        hover = pre_hover(
            self.source.ring, self.timeline, frame, crop.box, list(self.converter.moves)
        )
        if hover.badge is not None:
            step.badges.append(hover.badge)
        if hover.source == "pre_hover" and not self.protect.overlaps(
            crop.box, hover.frame.entry.arrival_ns, hover.frame.client_pixels()
        ):
            image, used = np.ascontiguousarray(hover.frame.client_pixels()), hover.frame
            step.frames["pre_hover"] = FrameRef(used.entry, used.generation)
        size = frame.generation.geometry.client_size
        meta = self._meta(size, frame.generation.geometry.dpi)
        kind, key = self.targets.resolve(
            image,
            meta,
            crop,
            name=lambda n: self._name(image, crop.box or (0, 0, 1, 1), arrival, f"click_{n}"),
            frame_t_ns=used.entry.arrival_ns,
        )
        step.target = key
        if kind == "reuse":
            step.reused = True
            step.badges.append("reused")
            step.name = key.rsplit("/", 1)[-1].removesuffix(".target.json")
        else:
            draft = self.targets.drafts[key]
            step.name = draft.name
            self.draft_frames.setdefault(key, FrameRef(used.entry, used.generation))
        step.title = f'이미지 클릭 "{step.name}"' if step.kind == "click" else f'끌기 "{step.name}"'

    def _spec_of(self, key: str) -> Any:
        for candidate in self.targets.candidates():
            if candidate.key == key:
                return candidate.spec
        return None

    def _before(
        self, step: Step, ref: FrameRef | Pixels | None, *, field_box: Box | None = None
    ) -> None:
        """앞 동작과 이 동작 사이 대기 (M4 계획 2.7 "대기 추론")."""
        prev = self._prev
        if prev is None or prev.ref is None or ref is None:
            return
        a = prev.ref.client() if isinstance(prev.ref, FrameRef) else prev.ref
        b = ref.client() if isinstance(ref, FrameRef) else ref
        if a.shape != b.shape:
            return
        field = _union(prev.field_box, field_box)
        click_found_in: Callable[[Pixels], bool] | None = None
        spec = None if step.target is None else self._spec_of(step.target)
        if step.kind == "click" and spec is not None:
            size = (int(b.shape[1]), int(b.shape[0]))
            dpi = ref.dpi if isinstance(ref, FrameRef) else 96
            meta = self._meta(size, dpi)

            def found(image: Pixels) -> bool:
                try:
                    return self.vision.find(image, meta, spec).match is not None
                except Exception:
                    return False

            click_found_in = found

        last_change = max((c for c in self._changes if prev.t_ns < c < step.t_ns), default=None)
        t_b = ref.arrival_ns if isinstance(ref, FrameRef) else step.t_ns
        plan = infer_wait(
            a,
            b,
            prev_t_ns=prev.t_ns,
            t_ns=step.t_ns,
            last_change_ns=last_change,
            next_kind=_NEXT_KIND[step.kind],
            field_box=field,
            click_found_in=click_found_in,
            protect=self.protect,
        )
        decision = plan.decision
        gap_ms = max(0, (step.t_ns - prev.t_ns) // MS)
        if decision.kind == "none":
            if decision.timeout_ms is not None and step.kind == "click":
                step.timeout_ms = decision.timeout_ms
            return
        if decision.kind == "image_wait" and plan.box is not None:
            size = (int(b.shape[1]), int(b.shape[0]))
            dpi = ref.dpi if isinstance(ref, FrameRef) else 96
            box = plan.box
            draft = self.targets.add_draft(
                b,
                self._meta(size, dpi),
                box,
                name=lambda n: self._name(b, box, t_b, f"wait_{n}"),
                frame_t_ns=t_b,
            )
            self.draft_frames.setdefault(draft, ref)
            name = self.targets.drafts[draft].name
            wait = self._new_step(
                "wait", step.t_ns - 1, "core.image.wait", f'나타날 때까지 대기 "{name}"'
            )
            wait.target, wait.name = draft, name
            wait.timeout_ms = decision.timeout_ms
        else:
            wait = self._new_step("delay", step.t_ns - 1, "core.flow.delay", "")
            wait.ms = decision.ms
            wait.title = f"{decision.ms} ms 기다리기"
            wait.needs_review = list(decision.needs_review)
        wait.input = {"gap_ms": gap_ms}
        self._insert(wait)

    def _add(self, step: Step, ref: FrameRef | Pixels | None) -> None:
        if isinstance(ref, FrameRef):
            step.frames.setdefault("pre_click" if step.kind == "click" else "pre_next", ref)
            if self._on_store_frame is not None:
                self._on_store_frame(ref)
        self._insert(step)

    # ------------------------------------------------------------ 확인 넣기

    def insert_check(
        self, kind: Literal["visible", "text"], pixels: Pixels, dpi: int, rect: Box, t_ns: int
    ) -> Step:
        """사람이 고른 영역(그 정지 화면 `pixels`) → 화면 확인·값 확인 스텝. 보호 영역과 겹치면
        `SecretRegionOverlap`."""
        self.protect.require_clear(rect, t_ns, pixels)
        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        image = np.ascontiguousarray(pixels)
        draft = self.targets.add_draft(
            image,
            self._meta(size, dpi),
            rect,
            name=lambda n: self._name(image, rect, t_ns, f"check_{n}"),
            frame_t_ns=t_ns,
        )
        self.draft_frames[draft] = image
        name = self.targets.drafts[draft].name
        if kind == "visible":
            step = self._new_step(
                "check_visible", t_ns, "core.assert.visible", f'화면 확인 "{name}"'
            )
        else:
            step = self._new_step("check_text", t_ns, "core.assert.text", f'문구 확인 "{name}"')
            text = None if self.read_text is None else self.read_text(image, rect)
            step.equals = text or ""
        step.target, step.name = draft, name
        # 보호 영역 밖이라도 다른 자리에 다시 보인 비밀값 원문을 OCR이 읽을 수 있다:
        # 응답·알림·저장 전에 본다
        self.scrub_equals(step)
        step.frames["pre_next"] = image
        self._before(step, image)
        self._insert(step)
        self._prev = _Prev(t_ns, image, None)
        self.rev += 1
        return step

    # ------------------------------------------------------------ 판정

    def _classify(self) -> bool:
        """글자 스텝의 판정 재료: 구간 시작 직전 프레임의 라벨, 구간 뒤(다음 동작 직전 또는 정지 때
        마지막) 프레임의 칸 OCR. 칸 없음이 먼저 확정됐으면 볼 프레임이 없다."""
        changed = False
        for step in self.steps:
            if step.span_id is None or step.classified or step.deleted:
                continue
            span = step.span_id
            info = self._fields.get(span)
            state = self.texts.classifier.get(span)
            if info is None or info.box is None:
                step.classified = True
                changed = True
                continue
            if not state.label_checked:
                text = None
                if info.start is not None and self.read_text is not None:
                    text = label_text(self.read_text, info.start.client(), info.box)
                self.texts.classifier.label(span, text)
            if not state.final_checked:
                t_end = step.t_ns
                for action in self.converter.actions():
                    if isinstance(action, TextAction) and action.span_id == span:
                        t_end = action.t_end
                after = self._ref(self._held_after(t_end))
                if after is None and self.finished:
                    after = self.final_frame
                if after is None:
                    continue  # 다음 동작을 기다린다
                gone = self.tracker.gone_at(span)
                if (gone is not None and gone <= after.arrival_ns) or self.read_text is None:
                    self.texts.classifier.no_final_frame(span)
                else:
                    typed = self.texts.typed_so_far(span)
                    seen = field_text(self.read_text, after.client(), info.box)
                    self.texts.classifier.final(span, seen, typed)
            step.classified = True
            changed = True
            if self.texts.state(span) == "ordinary":
                self.protect.release(span)
        return changed

    # ------------------------------------------------------------ 보호 상태가 바뀐 뒤 재검사

    def revalidate(self) -> list[str]:
        """만든 초안·이름·제목·문구를 **지금** 보호 영역·원문 목록으로 다시 본다 (B3 검수 H1).

        일반 글자로 판정됐던 구간이 비밀값이 되면(자동·사람) 그 칸을 덮은 초안 그림과 그 원문을 읽은
        이름·문구가 남는다. 걸린 스텝은 초안을 버리고(이름·제목은 대체 이름, 문구는 비움)
        `secret_overlap` 확인 필요로 둔다. 버린 초안 ID를 돌려준다 (써진 파일 정리는 세션)."""
        raws = [t for t in self.texts.protected_texts() if t]
        bad_drafts: set[str] = set()
        for draft_id, draft in self.targets.drafts.items():
            source = self.draft_frames.get(draft_id)
            if source is None:
                continue
            pixels = source.client() if isinstance(source, FrameRef) else source
            if self.protect.overlaps(draft.box, draft.frame_t_ns, pixels) or _leaks(
                draft.name, raws
            ):
                bad_drafts.add(draft_id)
        hit = False
        for step in self.steps:
            if step.deleted:
                continue
            # 이름·제목·문구와 함께 재사용 target 경로 문자열도 본다 (공개 스텝·저장소로 나감)
            leaked = (
                (step.target in bad_drafts)
                or _leaks(step.name, raws)
                or (step.target is not None and _leaks(step.target, raws))
            )
            if step.equals and any(_contains(step.equals, raw) for raw in raws):
                leaked = True
            if leaked:
                self._invalidate(step)
                hit = True
        for draft_id in bad_drafts:
            self.targets.drafts.pop(draft_id, None)
            self.draft_frames.pop(draft_id, None)
        if hit or bad_drafts:
            self.rev += 1
        return sorted(bad_drafts)

    def invalidate(self, step: Step) -> None:
        """세션이 미리 쓴 target 파일(materialize)의 초안이 버려졌을 때 그 스텝도 버린다."""
        self._invalidate(step)

    def leaks_secret(self, text: str) -> bool:
        """`text`가 세션의 비밀값·판정 대기·확인 필요 원문을 담는가 (값 확인 기댓값·글자 읽기)."""
        raws = [t for t in self.texts.protected_texts() if t]
        return bool(text) and any(_contains(text, raw) for raw in raws)

    def scrub_equals(self, step: Step) -> bool:
        """값 확인 기댓값이 원문을 담으면 비우고 스텝을 `secret_overlap`으로 버린다(재검사와 같은
        처리). 기댓값을 내보내는 모든 경로(새 확인 스텝·`step_json`)가 이것을 거친다."""
        if step.equals and self.leaks_secret(step.equals):
            self._invalidate(step)
            self.rev += 1
            return True
        return False

    def _invalidate(self, step: Step) -> None:
        """초안이든 기존 파일 재사용이든 스텝의 target 참조를 버린다 — 재사용 경로도 공개 스텝·
        저장소로 나가지 않게 (기존 사용자 파일은 그대로 둔다)."""
        step.target = None
        step.reused = False
        step.badges = [b for b in step.badges if b != "reused"]
        step.name = ""
        step.title = _PLAIN_TITLE.get(step.kind, step.title)
        if step.equals:
            step.equals = ""
        if "secret_overlap" not in step.needs_review:
            step.needs_review.append("secret_overlap")
        step.invalidated = True

    def pending_classification(self) -> list[Step]:
        return [
            s
            for s in self.steps
            if s.span_id is not None and not s.deleted and self.texts.state(s.span_id) == "pending"
        ]

    # ------------------------------------------------------------ 보이기

    def text_title(self, step: Step) -> str:
        assert step.span_id is not None
        return "비밀값 입력" if self.texts.state(step.span_id) == "secret" else "글자 입력"

    def step_json(self, step: Step, *, reveal: bool, base_ns: int = 0) -> dict[str, Any]:
        """`RecorderStep`. `reveal=False`면 일반 글자도 싣지 않는다 (세션 저장소)."""
        # 직렬화 방어: 어떤 경로로 만든 기댓값이든 내보내기 직전에 원문 목록과 대조한다
        if step.kind == "check_text":
            self.scrub_equals(step)
        review = set(step.needs_review)
        title = step.title
        out: dict[str, Any] = {
            "step": step.step_id,
            "kind": step.kind,
            "t_ms": max(0, (step.t_ns - base_ns) // MS),
        }
        if step.span_id is not None:
            view = self.texts.view(step.span_id)
            if not reveal:
                view.pop("text", None)
            out.update(view)
            review.update(self.texts.classifier.get(step.span_id).review_reasons)
            title = self.text_title(step)
        if step.kept:
            review.clear()
        out["node"] = {"type": step.node_type, "title": title}
        out["input"] = dict(step.input)
        badges = [_badge(code) for code in sorted(set(step.badges))]
        if step.span_id is not None and self.texts.state(step.span_id) == "secret":
            view_key = out.get("secret_key")
            if view_key is None:
                badges.append(_badge("secret_required"))
        out["badges"] = badges
        out["needs_review"] = sorted(review)
        if step.kind == "check_text":
            # 위 scrub_equals를 지난 값 (원문을 담았으면 비었다)
            out["equals"] = step.equals or ""
        if step.needs_target:
            out["target"] = self.target_json(step)
        frames = sorted(step.frames)
        if frames:
            out["frames"] = frames
        return out

    def target_json(self, step: Step) -> dict[str, Any]:
        if step.target is None:
            return {"source": "none"}
        draft = self.targets.drafts.get(step.target)
        if draft is None:
            out: dict[str, Any] = {"source": "file", "path": step.target, "reused": step.reused}
            return out
        spec = draft.spec
        click = spec.get("click") or {}
        assert isinstance(click, dict)
        offset = click.get("offset", [0, 0])
        out = {
            "source": "draft",
            "reused": False,
            "spec": {
                "rect": list(draft.box),
                "anchor": str(click.get("anchor", "center")),
                "offset": [float(offset[0]), float(offset[1])],
                "search": _search_pixels(spec),
            },
            "frame": "pre_hover" if "pre_hover" in step.frames else "pre_click",
        }
        if step.kind in ("wait", "check_visible", "check_text"):
            out["frame"] = "pre_next"
        if step.peaks is not None:
            out["peaks"] = step.peaks
        return out

    # ------------------------------------------------------------ 수

    def counts(self) -> dict[str, int]:
        active = [s for s in self.steps if not s.deleted and s.kind not in ("wait", "delay")]
        used = {s.target for s in self.steps if not s.deleted and s.target in self.targets.drafts}
        c = self.converter.counts
        return {
            "steps": len(active),
            "targets": len(used),
            "ignored_injected": 0,
            "ignored_outside": c.ignored_outside + c.undetermined,
            "ignored_popup": c.ignored_popup,
        }

    def find_step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.step_id == step_id), None)

    def active_spans(self) -> list[int]:
        return [s.span_id for s in self.steps if s.span_id is not None and not s.deleted]

    def overlap_check(self, rect: Box, t_ns: int | None, frame: Pixels) -> None:
        """사람이 고른 영역의 보호 영역 검사 (`SecretRegionOverlap`)."""
        self.protect.require_clear(rect, t_ns, frame)

    def wipe(self) -> None:
        self.texts.wipe()
        self.converter.wipe()
        self.holds.clear()
        with self._held_lock:
            self._held_at.clear()
        self.draft_frames.clear()
        self._prev = None


_PLAIN_TITLE: Final = {
    "click": "이미지 클릭",
    "drag": "끌기",
    "wait": "나타날 때까지 대기",
    "check_visible": "화면 확인",
    "check_text": "문구 확인",
}


def _contains(text: str, raw: SecretText) -> bool:
    """`text`에 원문(또는 이름으로 정리한 원문)이 들어 있는가. 원문은 비교에만 쓴다."""
    secret = raw.reveal().casefold()
    folded = text.casefold()
    cleaned = sanitize_name(secret).casefold()
    return bool(secret) and (secret in folded or (bool(cleaned) and cleaned in folded))


def _leaks(name: str, raws: list[SecretText]) -> bool:
    return bool(name) and any(_contains(name, raw) for raw in raws)


def _badge(code: str) -> dict[str, Any]:
    severity, message = BADGE_TEXT.get(code, ("info", ""))
    out: dict[str, Any] = {"code": code, "severity": severity}
    if message:
        out["message"] = message
    return out


def _search_pixels(spec: dict[str, object]) -> list[int] | None:
    search = spec.get("search")
    recorded = spec.get("recorded")
    if not isinstance(search, dict) or not isinstance(recorded, dict):
        return None
    region, size = search.get("region"), recorded.get("client_size")
    if region is None or size is None:
        return None
    x, y, w, h = normalized_to_pixels(tuple(region), (int(size[0]), int(size[1])))  # pyright: ignore
    return [int(x), int(y), int(w), int(h)]


def _union(a: Box | None, b: Box | None) -> Box | None:
    if a is None:
        return b
    if b is None:
        return a
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _action_key(action: Action) -> tuple[Any, ...]:
    return (
        action.kind,
        action.t_ns,
        getattr(action, "span_id", None),
        getattr(action, "event_id", None),
    )
