"""가짜 훅 원천 (M4 계획 2.9·2.15, `recorder-script.schema.json`): 각본 JSONL을 시각대로 흘린다.

실제 훅 프로세스가 보낼 메시지(`hook.hello`·`hook.events`·`hook.obs`·`hook.ime`·`hook.health`)를
같은 규칙으로 만든다 — 원시 입력은 `HookCore`가 번호를 매기고(우리 표식 제외·이동 합치기·
`crit_seq`·묶음), 관측 상태 줄(`observe`)로 중요 이벤트마다 즉시 관측을, IME 줄로 표본을, 500 ms
마다 생존 보고를 낸다. 고장 줄(`fault`)로 큐 넘침·묶음 잃음·생존 보고 끊김·훅 떼어짐·훅 종료를
흉내 낸다. daemon 녹화 검사(T8)·E2E가 쓴다. Win32를 부르지 않는다.

가짜 창 핸들: target 1001, app 1002, popup 1003(소유자 target), other 1004.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from kookabug_core.recorder.contract import (
    BATCH_MAX_EVENTS,
    HEALTH_INTERVAL_NS,
    HOOK_PROTOCOL,
    IME_KEY_SAMPLE_GAP_NS,
    IME_PERIODIC_NS,
    IME_QUERY_TIMEOUT_MS,
)
from kookabug_platform.recorder.hookproc import HookCore

__all__ = ["FAKE_HWND", "SEND_INTERVAL_NS", "FakeHookSource", "Message"]

FAKE_HWND: Final = {"target": 1001, "app": 1002, "popup": 1003, "other": 1004}
_OWNER: Final = {1003: 1001}
SEND_INTERVAL_NS: Final = 4_000_000
"""가짜 송신 스레드가 깨는 간격 (실제 송신 스레드와 같다)."""
_SETTLE_NS: Final = 30_000_000
_TICK_BASE: Final = 10_000_000
_MS: Final = 1_000_000

type Message = dict[str, Any]
"""JSON-RPC 알림 `{jsonrpc, method, params}`."""


def _note(method: str, params: dict[str, Any]) -> Message:
    return {"jsonrpc": "2.0", "method": method, "params": params}


class FakeHookSource:
    """각본 한 벌. `timeline()`은 `(t_ns, 메시지)` 목록, `stream()`은 그 시각에 맞춰 보낸다.

    `exit_ns`는 훅 프로세스가 끝나는(파이프가 닫히는) 시각 (`fault: hook_exit`, 없으면 None).
    """

    def __init__(self, lines: Iterable[Mapping[str, Any]], *, tail_ns: int = 600 * _MS) -> None:
        items = list(lines)
        if not items or items[0].get("kind") != "header":
            raise ValueError("각본 첫 줄은 header다")
        self.header = dict(items[0])
        self.lines = sorted(
            (dict(line) for line in items[1:]),
            key=lambda line: int(line.get("t_ns", line.get("arrival_ns", 0))),
        )
        self.tail_ns = tail_ns
        self.exit_ns: int | None = None
        self._timeline: list[tuple[int, Message]] | None = None

    @classmethod
    def from_jsonl(cls, path: str | Path, **kwargs: Any) -> FakeHookSource:
        text = Path(path).read_text(encoding="utf-8-sig")
        return cls((json.loads(line) for line in text.splitlines() if line.strip()), **kwargs)

    # ── 메시지 만들기 ───────────────────────────────────────

    def timeline(self) -> list[tuple[int, Message]]:
        if self._timeline is None:
            self._timeline = _Simulation(self).run()
        return self._timeline

    def stream(
        self,
        sink: Callable[[Message], None],
        *,
        speed: float = 1.0,
        stop: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> bool:
        """각 메시지를 그 시각(`speed`배 빠르게)에 `sink`로. 끝까지 보냈으면 True, 멈추면 False."""
        start = clock()
        for t_ns, message in self.timeline():
            due = start + t_ns / 1e9 / speed
            while (left := due - clock()) > 0:
                if stop is not None and stop.wait(min(left, 0.05)):
                    return False
                if stop is None:
                    sleep(left)
            if stop is not None and stop.is_set():
                return False
            sink(message)
        return True


class _Simulation:
    """훅 프로세스 한 번을 가짜 시계로 돌린다."""

    def __init__(self, source: FakeHookSource) -> None:
        self.src = source
        self.now = 0
        self.core = HookCore(clock=lambda: self.now)
        self.out: list[tuple[int, Message]] = []
        self.fg: int | None = FAKE_HWND["target"]
        self.point: int | None = FAKE_HWND["target"]
        self.focus_password: bool | None = False
        self.hkl: str | None = "4090409"
        self.obs_delay_ns = 0
        self.table_changed_ns = 0
        self.zorder_rev = 0
        self.ime_mode = "alphanumeric"
        self.ime_status = "ok"
        self.ime_respond_ns = 0
        self.last_input_tick = _TICK_BASE
        self.detached = False
        self.health_on = True
        self.skip_batches = 0
        self.pending_obs: list[tuple[int, dict[str, Any]]] = []
        self.obs_batch: list[dict[str, Any]] = []
        self.ime_due: list[tuple[int, str]] = []
        self.ime_out: list[tuple[int, dict[str, Any]]] = []
        self.last_sample_at: int | None = None
        self.next_periodic = 0
        self.next_health = 0

    def emit(self, method: str, params: dict[str, Any]) -> None:
        self.out.append((self.now, _note(method, params)))

    def run(self) -> list[tuple[int, Message]]:
        self.emit(
            "hook.hello",
            {
                "pid": 0,
                "created": "0",
                "dpi_awareness": "per_monitor_v2",
                "hooks": {"mouse": True, "keyboard": True},
                "mono_base_ns": "0",
                "protocol": HOOK_PROTOCOL,
            },
        )
        lines = list(self.src.lines)
        last = max((int(line.get("t_ns", line.get("arrival_ns", 0))) for line in lines), default=0)
        end = last + self.src.tail_ns
        index = 0
        tick = 0
        while tick <= end:
            # 이 송신 틱까지의 줄을 그 시각 차례로 적용한다
            while (
                index < len(lines)
                and int(lines[index].get("t_ns", lines[index].get("arrival_ns", 0))) <= tick
            ):
                line = lines[index]
                self.now = int(line.get("t_ns", line.get("arrival_ns", 0)))
                if not self.apply(line):
                    return self.out
                index += 1
            self.now = tick
            self.observe_pending()
            self.sample_ime()
            self.send()
            tick += SEND_INTERVAL_NS
        return self.out

    def apply(self, line: Mapping[str, Any]) -> bool:
        kind = line["kind"]
        if kind == "input":
            self.last_input_tick = _TICK_BASE + self.now // _MS
            if not self.detached:
                self.core.accept_raw(dict(line["input"]), self.now)
                self.queue_observations()
        elif kind == "observe":
            fg, point = line.get("fg", "target"), line.get("point", line.get("fg", "target"))
            new_fg = None if fg is None else FAKE_HWND[fg]
            new_point = None if point is None else FAKE_HWND[point]
            if (new_fg, new_point) != (self.fg, self.point):
                self.table_changed_ns = self.now
                self.zorder_rev += 1
                if new_fg != self.fg:
                    self.ime_due.append((self.now, "foreground"))
            self.fg, self.point = new_fg, new_point
            if "focus_password" in line:
                self.focus_password = line["focus_password"]
            if "hkl" in line:
                if line["hkl"] != self.hkl:
                    self.ime_due.append((self.now, "hkl"))
                self.hkl = line["hkl"]
            self.obs_delay_ns = int(line.get("delay_ms", 0)) * _MS
        elif kind == "ime":
            self.ime_mode = line["mode"]
            self.ime_status = line.get("status", "ok")
            default = IME_QUERY_TIMEOUT_MS if self.ime_status == "timeout" else 0
            self.ime_respond_ns = int(line.get("respond_ms", default)) * _MS
        elif kind == "fault":
            fault = line["fault"]
            if fault == "hook_exit":
                self.src.exit_ns = self.now
                return False
            if fault == "overflow":
                self.core.force_drop += int(line.get("count", 1))
            elif fault == "batch_gap":
                self.skip_batches += 1
            elif fault == "health_stop":
                self.health_on = False
            elif fault == "hook_detached":
                self.detached = True
        return True

    def queue_observations(self) -> None:
        """방금 받은 중요 이벤트마다 즉시 관측과 IME 요청 (훅 콜백이 넣는 것과 같다)."""
        while self.core.obs_requests:
            event = self.core.obs_requests.popleft()
            self.pending_obs.append((event["t_ns"] + self.obs_delay_ns, event))
        while self.core.ime_requests:
            trigger, t = self.core.ime_requests.popleft()
            due = t + _SETTLE_NS if trigger == "ime_key" else t
            self.ime_due.append((due, trigger))

    def observe_pending(self) -> None:
        ready = [(at, ev) for at, ev in self.pending_obs if at <= self.now]
        self.pending_obs = [(at, ev) for at, ev in self.pending_obs if at > self.now]
        for at, event in ready:
            obs: dict[str, Any] = {
                "cause_event_id": event["event_id"],
                "obs_at_ns": at,
                "fg": self.fg,
                "fg_thread": None if self.fg is None else self.fg + 10_000,
                "focus": self.fg,
                "hkl": self.hkl,
                "table_changed_ns": self.table_changed_ns,
                "zorder_rev": self.zorder_rev,
                "focus_password": self.focus_password,
                "fg_owner": _OWNER.get(self.fg) if self.fg else None,
            }
            if event["kind"] in ("mouse_down", "mouse_up", "wheel"):
                obs["point_window"] = self.point
                obs["point_owner"] = _OWNER.get(self.point) if self.point else None
            self.obs_batch.append(obs)

    def sample_ime(self) -> None:
        due = [d for d in self.ime_due if d[0] <= self.now]
        self.ime_due = [d for d in self.ime_due if d[0] > self.now]
        triggers = [trigger for _, trigger in due]
        chosen: str | None = None
        for strong in ("foreground", "hkl", "ime_key"):
            if strong in triggers:
                chosen = strong
                break
        stale = self.last_sample_at is None or (
            self.now - self.last_sample_at >= IME_KEY_SAMPLE_GAP_NS
        )
        if chosen is None and "key" in triggers and stale:
            chosen = "key"
        if chosen is None and self.now >= self.next_periodic:
            self.next_periodic = self.now + IME_PERIODIC_NS
            if self.fg == FAKE_HWND["target"]:
                chosen = "periodic"
        if chosen is None:
            return
        sample: dict[str, Any] = {
            "query_started_ns": self.now,
            "sampled_at_ns": self.now + self.ime_respond_ns,
            "fg": self.fg,
            "fg_thread": None if self.fg is None else self.fg + 10_000,
            "hkl": self.hkl,
            "status": self.ime_status,
            "trigger": chosen,
        }
        if self.ime_status == "ok":
            sample["mode"] = self.ime_mode
            sample["conversion"] = 1 if self.ime_mode == "native" else 0
        else:
            sample["mode"] = "unknown"
        self.last_sample_at = sample["sampled_at_ns"]
        self.ime_out.append((sample["sampled_at_ns"], sample))

    def send(self) -> None:
        while (batch := self.core.take_batch(self.now)) is not None:
            if self.skip_batches:
                self.skip_batches -= 1  # 이 묶음은 보내지 않는다 (잃은 묶음)
                continue
            self.emit("hook.events", batch)
        if self.obs_batch:
            for start in range(0, len(self.obs_batch), BATCH_MAX_EVENTS):
                self.emit("hook.obs", {"batch": self.obs_batch[start : start + BATCH_MAX_EVENTS]})
            self.obs_batch.clear()
        ready = [s for at, s in self.ime_out if at <= self.now]
        self.ime_out = [(at, s) for at, s in self.ime_out if at > self.now]
        if ready:
            self.emit("hook.ime", {"batch": ready})
        if self.health_on and self.now >= self.next_health:
            self.next_health = self.now + HEALTH_INTERVAL_NS
            self.emit(
                "hook.health",
                {
                    "batch_no": self.core.batch_no,
                    "last_event_ns": self.core.last_event_ns,
                    "last_input_tick": self.last_input_tick,
                    "sent_at_ns": self.now,
                },
            )
