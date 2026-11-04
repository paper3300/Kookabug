"""훅 프로세스의 콜백·묶음·관측·IME 표본·송신 (M4 계획 2.1, T3 CI — 실제 훅은 걸지 않는다).

훅 콜백 함수(`HookCore.on_mouse`·`on_key`, `make_hook_procs`)를 직접 부르고, 받는 쪽 연속성 검사기
(`ContinuityChecker`)로 결과를 본다. Win32 조회는 `FakeApi`로 바꾼다.
"""

from __future__ import annotations

import ctypes
import itertools
import json
import subprocess
import sys
import threading
import time
from collections import deque
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kookabug_core.recorder.continuity import ContinuityChecker
from kookabug_core.recorder.contract import obs_usable
from kookabug_core.schema import check_shape
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.recorder import hookwin32
from kookabug_platform.recorder.fake import FAKE_HWND, SEND_INTERVAL_NS, FakeHookSource
from kookabug_platform.recorder.hookproc import HookCore
from kookabug_platform.recorder.hookwin32 import (
    IME_KEY_SETTLE_NS,
    ImeSampler,
    Observer,
    Sender,
    make_hook_procs,
)
from kookabug_platform.win32 import user32
from kookabug_platform.win32.user32 import KBDLLHOOKSTRUCT, MSLLHOOKSTRUCT

MS = 1_000_000
VK_A, VK_HANGUL = 0x41, 0x15


class Clock:
    def __init__(self) -> None:
        self.t = 0

    def __call__(self) -> int:
        return self.t

    def advance(self, ms: float) -> None:
        self.t += int(ms * MS)


def move(core: HookCore, x: int = 10, y: int = 20, extra: int = 0) -> None:
    core.on_mouse(user32.WM_MOUSEMOVE, x, y, 0, 0, extra)


def click(core: HookCore, x: int = 10, y: int = 20, extra: int = 0) -> None:
    core.on_mouse(user32.WM_LBUTTONDOWN, x, y, 0, 0, extra)
    core.on_mouse(user32.WM_LBUTTONUP, x, y, 0, 0, extra)


def key(core: HookCore, vk: int = VK_A, extra: int = 0) -> None:
    core.on_key(user32.WM_KEYDOWN, vk, 0x1E, 0, extra)
    core.on_key(user32.WM_KEYUP, vk, 0x1E, 0, extra)


def drain(core: HookCore, now: int | None = None) -> list[dict[str, Any]]:
    batches = []
    while (batch := core.take_batch(now)) is not None:
        batches.append(batch)
    return batches


def message(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


# ── 이동 합치기·큐 ──────────────────────────────────────────


def test_move_coalescing_keeps_last_before_button() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    for i in range(5):
        clock.advance(1)
        move(core, 100 + i, 200 + i)
    clock.advance(1)
    core.on_mouse(user32.WM_LBUTTONDOWN, 104, 204, 0, 0, 0)
    (batch,) = drain(core, clock.t)
    kinds = [(e["kind"], e["event_id"], e.get("x")) for e in batch["events"]]
    # 앞 이동 넷은 합쳐지고, 버튼 직전 위치(마지막 이동)는 반드시 버튼보다 먼저 간다
    assert kinds == [("mouse_move", 5, 104), ("mouse_down", 6, 104)]
    assert batch["coalesced_moves"] == 4
    assert "crit_seq" not in batch["events"][0]
    assert (batch["crit_first"], batch["crit_last"]) == (1, 1)
    assert ContinuityChecker().feed_events(batch) is None


def test_moves_alone_sent_at_most_every_8ms() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    sent = []
    for _ in range(100):  # 1 ms마다 이동, 4 ms마다 송신 틱
        clock.advance(1)
        move(core)
        if clock.t % (4 * MS) == 0:
            sent += [e["t_ns"] for b in drain(core, clock.t) for e in b["events"]]
    gaps = [b - a for a, b in itertools.pairwise(sent)]
    assert sent and min(gaps) >= 8 * MS - MS  # 합치기 8 ms (보낸 이동의 t_ns 간격)
    pending = core._move is not None and core._move["event_id"] > core._sent_id
    assert core.coalesced_moves + len(sent) + pending == 100


def test_critical_queue_full_of_keys_drops_without_wait_and_flags_overflow() -> None:
    clock = Clock()
    core = HookCore(clock=clock, crit_capacity=64)
    durations = []
    for _ in range(50):  # 키 100개, 이동 없음, 아무도 꺼내지 않음
        started = time.perf_counter()
        key(core)
        durations.append(time.perf_counter() - started)
        clock.advance(0.1)
    assert core.crit_seq == 100
    assert core.overflow == 36
    assert len(core._crit) == 64
    # 콜백은 큐가 차도 기다리지 않는다 (잠금·대기 없음 — 넉넉한 상한)
    assert max(durations) < 0.05
    batches = drain(core, clock.t)
    checker = ContinuityChecker()
    results = [checker.feed_events(b) for b in batches]
    violation = next(r for r in results if r is not None)
    assert violation.reason == "overflow"
    assert violation.cut_crit_seq == 65  # 첫 버린 번호부터 쓰지 않는다


def test_mixed_stream_coalesced_moves_and_marker_drops_continue_real_loss_stops() -> None:
    clock = Clock()
    core = HookCore(clock=clock, crit_capacity=32, max_batch=16)
    checker = ContinuityChecker()
    accepted: list[dict[str, Any]] = []

    def round_(n: int) -> None:
        for i in range(n):
            clock.advance(1)
            move(core, i, i)
            move(core, i + 1, i)  # 합쳐진다
            key(core, extra=KOOKABUG_INPUT_MARK)  # 우리 입력 — 버린다
            key(core)  # 사람 키
            if i % 3 == 0:
                click(core, i, i)
            if i % 4 == 3:
                send(clock.t)
        send(clock.t + 100 * MS)  # 기다리던 이동까지 보낸다

    def send(now: int) -> None:
        for batch in drain(core, now):
            if checker.feed_events(batch) is None:
                accepted.extend(batch["events"])

    round_(10)
    assert checker.violation is None
    assert core.dropped_marker == 20  # 표식 키 10번 (누름·뗌)
    before_loss = [e for e in accepted if "crit_seq" in e]
    assert [e["crit_seq"] for e in before_loss] == list(range(1, core.crit_seq + 1))

    # 송신이 멈춘 사이 사람 키로 중요 큐를 가득 채워 하나를 잃는다
    last_good = core.crit_seq
    for _ in range(16):
        key(core)
    key(core, extra=KOOKABUG_INPUT_MARK)
    assert core.overflow == 0
    key(core)  # 33번째 — 큐가 찼다
    assert core.overflow >= 1
    send(clock.t)
    assert checker.violation is not None
    assert checker.violation.reason == "overflow"
    assert checker.violation.cut_crit_seq == last_good + 33
    # 유실 전 동작은 남는다
    assert [e["crit_seq"] for e in accepted if "crit_seq" in e][: len(before_loss)] == [
        e["crit_seq"] for e in before_loss
    ]


def test_marker_drops_and_moves_alone_never_stop() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    checker = ContinuityChecker()
    batches = 0
    for i in range(10_000):
        clock.advance(0.3)
        kind = i % 4
        if kind == 0:
            move(core, i % 500, i % 300)
        elif kind == 1:
            core.on_key(user32.WM_KEYDOWN, VK_A, 0x1E, 0, KOOKABUG_INPUT_MARK)
        elif kind == 2:
            core.on_mouse(user32.WM_LBUTTONDOWN, 1, 1, 0, 0, KOOKABUG_INPUT_MARK)
        else:
            move(core, i % 400, i % 200)
        if i % 13 == 0:
            for batch in drain(core, clock.t):
                batches += 1
                assert checker.feed_events(batch) is None
    for batch in drain(core, clock.t + 100 * MS):
        assert checker.feed_events(batch) is None
    assert checker.violation is None
    assert core.overflow == 0 and core.crit_seq == 0
    assert core.dropped_marker == 5_000
    assert core.event_id == 10_000
    assert batches > 0


def test_marker_only_drops_are_reported_in_empty_batch() -> None:
    """조율자 실제 입력 검사 지적: 우리 표식 입력만 버리고 그 뒤 입력이 없어도 `dropped_marker`가
    받는 쪽에 간다 (빈 묶음). 전에는 다음 묶음이 생길 때까지 알리지 않아 0으로 보였다."""
    core = HookCore()
    checker = ContinuityChecker()
    key(core)
    first = core.take_batch(0)
    assert first is not None and checker.feed_events(first) is None
    key(core, extra=KOOKABUG_INPUT_MARK)
    click(core, extra=KOOKABUG_INPUT_MARK)
    batch = core.take_batch(0)
    assert batch is not None
    assert batch["events"] == [] and batch["dropped_marker"] == 4
    assert (batch["crit_first"], batch["crit_last"]) == (None, None)
    assert check_shape(message("hook.events", batch), "recorder-hook") == []
    assert checker.feed_events(batch) is None
    assert checker.counters["dropped_marker"] == 4
    assert core.take_batch(0) is None  # 바뀐 것이 없으면 보내지 않는다


def test_batches_keep_event_id_order_with_small_batches() -> None:
    clock = Clock()
    core = HookCore(clock=clock, max_batch=4)
    checker = ContinuityChecker()
    for i in range(200):
        clock.advance(0.5)
        move(core, i, i)
        if i % 5 == 0:
            key(core)
        if i % 7 == 0:
            click(core, i, i)
        if i % 9 == 0:
            for batch in drain(core, clock.t):
                assert len(batch["events"]) <= 4
                assert checker.feed_events(batch) is None
    for batch in drain(core, clock.t + 100 * MS):
        assert checker.feed_events(batch) is None
    assert checker.last_crit == core.crit_seq


def test_concurrent_callback_and_sender_keep_order() -> None:
    """콜백 스레드와 송신 스레드가 잠금 없이 같은 큐·이동 칸을 쓴다 — 빠짐·중복·역순 없음."""
    core = HookCore(coalesce_ns=0, crit_capacity=1_000_000)  # 넘침 없이 차례만 본다
    checker = ContinuityChecker()
    done = threading.Event()
    sent: list[int] = []

    def sender() -> None:
        while True:
            finished = done.is_set()
            while (batch := core.take_batch()) is not None:
                assert checker.feed_events(batch) is None, checker.violation
                sent.extend(e["event_id"] for e in batch["events"])
            if finished:
                return

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # 스레드를 아주 자주 바꿔 경쟁 창을 연다
    worker = threading.Thread(target=sender)
    try:
        worker.start()
        for i in range(20_000):
            if i % 3 == 0:
                key(core)
            elif i % 7 == 0:
                click(core, i % 100, 0)
            else:
                move(core, i % 100, i % 50)
        done.set()
        worker.join(30)
    finally:
        sys.setswitchinterval(interval)
    assert not worker.is_alive()
    assert checker.violation is None
    assert checker.last_crit == core.crit_seq
    assert sent == sorted(set(sent))


# ── 훅 콜백이 부르는 Win32 ──────────────────────────────────


class Spy:
    """바인딩 모듈 대역: 쓰인 함수 이름을 기록한다."""

    def __init__(self, calls: list[str], real: Any) -> None:
        self._calls = calls
        self._real = real

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._real, name)
        if not callable(value) or isinstance(value, type):
            return value  # 상수·구조체

        def record(*args: Any, **kwargs: Any) -> int:
            self._calls.append(f"{self._real.__name__.rsplit('.', 1)[-1]}.{name}")
            return 0

        return record


def test_hook_callback_makes_no_window_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    for name in ("user32", "kernel32", "imm32", "dwmapi"):
        monkeypatch.setattr(hookwin32, name, Spy(calls, getattr(hookwin32, name)))
    core = HookCore()
    mouse_proc, key_proc = make_hook_procs(core, [11, 22])

    m = MSLLHOOKSTRUCT()
    m.pt.x, m.pt.y = 5, 6
    k = KBDLLHOOKSTRUCT()
    k.vkCode, k.scanCode = VK_A, 0x1E
    for msg in (user32.WM_MOUSEMOVE, user32.WM_LBUTTONDOWN, user32.WM_LBUTTONUP):
        mouse_proc(user32.HC_ACTION, msg, ctypes.addressof(m))
    for msg in (user32.WM_KEYDOWN, user32.WM_KEYUP):
        key_proc(user32.HC_ACTION, msg, ctypes.addressof(k))
    k.dwExtraInfo = KOOKABUG_INPUT_MARK
    key_proc(user32.HC_ACTION, user32.WM_KEYDOWN, ctypes.addressof(k))
    key_proc(-1, user32.WM_KEYDOWN, 0)  # HC_ACTION이 아니면 구조체를 읽지 않고 넘긴다

    # 허용 목록: 다음 훅으로 넘기기뿐 (창 조회·메시지 보내기·로그 없음)
    assert set(calls) == {"user32.CallNextHookEx"}
    assert len(calls) == 7
    assert core.event_id == 6 and core.dropped_marker == 1 and core.crit_seq == 4

    # 콜백 안 오류도 입력을 막지 않는다 (언제나 다음 훅으로)
    def boom(*_args: Any) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(core, "on_key", boom)
    calls.clear()
    key_proc(user32.HC_ACTION, user32.WM_KEYDOWN, ctypes.addressof(k))
    assert calls == ["user32.CallNextHookEx"]


# ── 즉시 관측·IME 표본 ──────────────────────────────────────


class FakeApi:
    """`Win32Api` 대역 (창 1001 = 대상)."""

    def __init__(self) -> None:
        self.fg: int | None = 1001
        self.hkl = "4120412"
        self.windows = [(1003, (0, 0, 50, 50)), (1001, (0, 0, 800, 600))]
        self.ime_status = "ok"
        self.conversion = 1
        self.block: threading.Event | None = None
        self.ime_calls = 0
        self.top_calls = 0
        self.tick = 100

    def foreground(self) -> int | None:
        return self.fg

    def thread_of(self, hwnd: int) -> int | None:
        return hwnd + 10_000

    def focus_of(self, thread: int) -> int | None:
        return thread - 10_000

    def layout_of(self, thread: int) -> str | None:
        return self.hkl

    def is_password_edit(self, hwnd: int) -> bool | None:
        return False

    def owner_of(self, hwnd: int) -> int | None:
        return 1001 if hwnd == 1003 else None

    def is_top_level(self, hwnd: int) -> bool:
        return True

    def top_windows(self) -> list[tuple[int, tuple[int, int, int, int]]]:
        self.top_calls += 1
        return list(self.windows)

    def ime_window(self, hwnd: int) -> int | None:
        return hwnd + 5

    def ime_conversion(self, hwnd: int, timeout_ms: int) -> tuple[str, int | None]:
        self.ime_calls += 1
        if self.block is not None:
            self.block.wait(5)
        if self.ime_status != "ok":
            return self.ime_status, None
        return "ok", self.conversion

    def last_input_tick(self) -> int:
        return self.tick


def as_api(api: FakeApi) -> hookwin32.Win32Api:
    return cast(hookwin32.Win32Api, api)


def test_every_critical_event_gets_immediate_obs() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    api = FakeApi()
    observer = Observer(core, as_api(api))
    for i in range(20):  # 아주 빠른 키 연속 (0.1 ms 간격)
        clock.advance(0.1)
        core.on_key(user32.WM_KEYDOWN, VK_A + i % 3, 0x1E, 0, 0)
    for _ in range(10):
        move(core)
    click(core, 20, 20)
    click(core, 400, 400)
    key(core, extra=KOOKABUG_INPUT_MARK)
    assert observer.process_pending() == 24
    crit = [e for b in drain(core, clock.t) for e in b["events"] if "crit_seq" in e]
    obs = list(observer.out)
    assert [o["cause_event_id"] for o in obs] == [e["event_id"] for e in crit]
    pointer = [o for o in obs if "point_window" in o]
    assert [(o["point_window"], o["point_owner"]) for o in pointer] == [
        (1003, 1001),
        (1003, 1001),
        (1001, None),
        (1001, None),
    ]
    assert all(o["fg"] == 1001 and o["hkl"] == "4120412" for o in obs)
    assert check_shape(message("hook.obs", {"batch": obs}), "recorder-hook") == []
    # Z 순서 표는 창 이벤트가 오기 전까지 다시 만들지 않는다
    assert api.top_calls == 1
    observer.note_change()
    click(core, 1, 1)
    observer.process_pending()
    assert api.top_calls == 2
    assert observer.out[-1]["zorder_rev"] == 1


def test_obs_pairing_rules() -> None:
    """즉시 관측 ↔ 이벤트 짝짓기 (50 ms·이벤트 뒤 표 갱신 없음) — 가짜 원천으로 끝에서 끝."""
    header = {
        "kind": "header",
        "format": "kookabug.recorder-script/0",
        "title": "x",
        "geometry": {
            "frame_bounds": [0, 0, 800, 600],
            "client_origin": [0, 0],
            "client_size": [800, 600],
            "dpi": 96,
        },
        "scene": "title",
    }
    down = {
        "kind": "mouse_down",
        "button": "left",
        "x": 1,
        "y": 1,
        "injected": False,
        "injected_lower_il": False,
        "extra_info": 0,
    }
    lines = [
        header,
        {"kind": "input", "t_ns": 100 * MS, "input": down},  # 바로 관측 — 쓸 수 있음
        {"kind": "observe", "t_ns": 150 * MS, "fg": "target", "delay_ms": 80},
        {"kind": "input", "t_ns": 200 * MS, "input": down},  # 80 ms 늦은 관측 — 판정 불가
        {"kind": "observe", "t_ns": 300 * MS, "fg": "target", "delay_ms": 10},
        {"kind": "input", "t_ns": 400 * MS, "input": down},
        # 이벤트와 관측 사이에 포그라운드가 바뀜 — 관측이 새 상태를 볼 수 있어 판정 불가
        {"kind": "observe", "t_ns": 405 * MS, "fg": "other", "delay_ms": 10},
    ]
    timeline = FakeHookSource(lines).timeline()
    events = [e for _, m in timeline if m["method"] == "hook.events" for e in m["params"]["events"]]
    obs = {
        o["cause_event_id"]: o
        for _, m in timeline
        if m["method"] == "hook.obs"
        for o in m["params"]["batch"]
    }
    usable = [obs_usable(e, obs.get(e["event_id"])) for e in events]
    assert usable == [True, False, False]
    assert obs_usable(events[0], None) is False
    assert obs_usable(events[0], {**obs[events[0]["event_id"]], "cause_event_id": 99}) is False


def test_ime_timeout_marks_unknown() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    api = FakeApi()
    sampler = ImeSampler(core, as_api(api), target_hwnd=1001)
    ok = sampler.sample("periodic")
    assert (ok["status"], ok["mode"], ok["conversion"]) == ("ok", "native", 1)
    api.ime_status = "timeout"
    timed_out = sampler.sample("key")
    assert timed_out["status"] == "timeout"
    assert timed_out["mode"] == "unknown"
    assert "conversion" not in timed_out
    api.ime_status = "failed"
    failed = sampler.sample("key")
    assert (failed["status"], failed["mode"]) == ("failed", "unknown")
    api.fg = None
    none = sampler.sample("foreground")
    assert (none["status"], none["mode"]) == ("no_ime", "unknown")
    batch = [ok, timed_out, failed, none]
    assert check_shape(message("hook.ime", {"batch": batch}), "recorder-hook") == []


def test_ime_sampler_trigger_rules() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    api = FakeApi()
    sampler = ImeSampler(core, as_api(api), target_hwnd=1001)
    assert sampler.step() and sampler.out[-1]["trigger"] == "periodic"
    clock.advance(10)
    key(core)
    assert not sampler.step()  # 직전 표본이 100 ms 안
    clock.advance(100)
    key(core)
    assert sampler.step() and sampler.out[-1]["trigger"] == "key"
    clock.advance(5)
    core.on_key(user32.WM_KEYUP, VK_HANGUL, 0x72, 0, 0)  # 한/영 키를 뗌
    assert not sampler.step()  # 대상이 전환을 처리할 시간
    clock.advance(IME_KEY_SETTLE_NS / MS)
    assert sampler.step() and sampler.out[-1]["trigger"] == "ime_key"
    sampler.request("foreground")
    assert sampler.step() and sampler.out[-1]["trigger"] == "foreground"
    clock.advance(300)
    api.fg = 1002  # 대상이 앞에 없으면 정기 표본 없음
    assert not sampler.step()


def test_ime_query_does_not_delay_immediate_obs() -> None:
    """IME 조회가 시간 초과까지 막혀 있는 동안 들어온 이벤트도 즉시 관측이 바로 나온다 (N5)."""
    core = HookCore()
    api = FakeApi()
    api.block = threading.Event()
    sampler = ImeSampler(core, as_api(api), target_hwnd=None)
    observer = Observer(core, as_api(api))
    stop = threading.Event()

    def observe_loop() -> None:  # 관측 스레드 (창 이벤트 훅 없이 같은 처리)
        while not stop.is_set():
            if not observer.process_pending():
                time.sleep(0.0005)

    worker = threading.Thread(target=observe_loop, daemon=True)
    sampler.start()
    worker.start()
    try:
        assert sampler.querying.wait(5), "IME 조회가 시작되지 않았다"
        assert not core.obs_requests and not observer.out  # 빈 큐에서 시작
        core.on_key(user32.WM_KEYDOWN, VK_A, 0x1E, 0, 0)
        started = time.monotonic()
        while not observer.out and time.monotonic() - started < 2:
            time.sleep(0.001)
        elapsed = time.monotonic() - started
        assert observer.out, "조회가 막힌 동안 즉시 관측이 나오지 않았다"
        assert sampler.querying.is_set(), "관측이 조회가 끝난 뒤에야 나왔다"
        assert elapsed < 0.5
        assert core.last_event_ns is not None
        assert observer.out[0]["obs_at_ns"] - core.last_event_ns < 500 * MS
    finally:
        api.block.set()
        stop.set()
        sampler.stop()
        worker.join(2)


# ── 송신 ────────────────────────────────────────────────────


def test_sender_messages_match_schema_and_health() -> None:
    clock = Clock()
    core = HookCore(clock=clock)
    api = FakeApi()
    observer = Observer(core, as_api(api))
    sampler = ImeSampler(core, as_api(api), target_hwnd=1001)
    written: list[dict[str, Any]] = []
    sender = Sender(
        core,
        as_api(api),
        cast(Any, None),
        observer.out,
        sampler.out,
        on_broken=lambda: None,
        write=lambda body: written.append(json.loads(body)),
    )
    move(core)
    clock.advance(10)
    click(core)
    key(core)
    observer.process_pending()
    sampler.step()
    sender.send_pending()
    methods = [m["method"] for m in written]
    assert methods == ["hook.events", "hook.obs", "hook.ime", "hook.health"]
    for m in written:
        assert check_shape(m, "recorder-hook") == [], m
    assert written[-1]["params"]["batch_no"] == 1
    assert written[-1]["params"]["last_input_tick"] == 100
    clock.advance(100)
    sender.send_pending()  # 보낼 것 없음, 생존 보고는 500 ms마다
    assert len(written) == 4
    clock.advance(400)
    sender.send_pending()
    assert [m["method"] for m in written[4:]] == ["hook.health"]


def test_pipe_stall_overflows_queue_and_receiver_stops() -> None:
    """쓰기가 막히면 송신만 기다리고, 그동안 콜백은 큐가 차면 버린다 → 받는 쪽 `overflow`."""
    core = HookCore(crit_capacity=16)
    api = FakeApi()
    gate = threading.Event()
    received: list[dict[str, Any]] = []
    first_write = threading.Event()

    def write(body: bytes) -> None:
        first_write.set()
        gate.wait(5)  # 파이프 쓰기가 막힘
        received.append(json.loads(body))

    sender = Sender(
        core,
        as_api(api),
        cast(Any, None),
        deque(),
        deque(),
        on_broken=lambda: None,
        interval_s=0.001,
        write=write,
    )
    sender.start()
    try:
        key(core)
        assert first_write.wait(5)
        durations = []
        for _ in range(20):
            started = time.perf_counter()
            key(core)
            durations.append(time.perf_counter() - started)
        assert core.overflow > 0
        assert max(durations) < 0.05  # 콜백은 막힌 쓰기를 기다리지 않는다
    finally:
        gate.set()
        sender.stop(flush=True)
    checker = ContinuityChecker()
    results = [checker.feed_events(m["params"]) for m in received if m["method"] == "hook.events"]
    assert any(r is not None and r.reason == "overflow" for r in results)


# ── 가짜 원천 시각 ──────────────────────────────────────────


def test_fake_hook_source_timing() -> None:
    header = {
        "kind": "header",
        "format": "kookabug.recorder-script/0",
        "title": "x",
        "geometry": {
            "frame_bounds": [0, 0, 800, 600],
            "client_origin": [0, 0],
            "client_size": [800, 600],
            "dpi": 96,
        },
        "scene": "title",
    }
    base = {"injected": False, "injected_lower_il": False, "extra_info": 0}
    lines = [
        header,
        {"kind": "observe", "t_ns": 0, "fg": "target", "hkl": "4120412"},
        {"kind": "ime", "t_ns": 0, "mode": "native"},
        {
            "kind": "input",
            "t_ns": 101 * MS,
            "input": {"kind": "mouse_move", "x": 5, "y": 5, **base},
        },
        {
            "kind": "input",
            "t_ns": 103 * MS,
            "input": {"kind": "mouse_down", "button": "left", "x": 5, "y": 5, **base},
        },
        {
            "kind": "input",
            "t_ns": 201 * MS,
            "input": {"kind": "key_down", "vk": 65, "scan": 30, "extended": False, **base},
        },
        {
            "kind": "input",
            "t_ns": 202 * MS,
            "input": {
                "kind": "key_down",
                "vk": 65,
                "scan": 30,
                "extended": False,
                **base,
                "extra_info": KOOKABUG_INPUT_MARK,
            },
        },
    ]
    source = FakeHookSource(lines, tail_ns=1_000 * MS)
    timeline = source.timeline()
    assert timeline[0] == (0, timeline[0][1]) and timeline[0][1]["method"] == "hook.hello"
    assert [t for t, _ in timeline] == sorted(t for t, _ in timeline)
    for _, m in timeline:
        assert check_shape(m, "recorder-hook") == [], m
    events = [(t, m["params"]) for t, m in timeline if m["method"] == "hook.events"]
    # 이벤트는 다음 송신 틱(4 ms)에 묶여 나간다
    for t, params in events:
        for event in params["events"]:
            assert event["t_ns"] <= t < event["t_ns"] + SEND_INTERVAL_NS
    sent = [e for _, p in events for e in p["events"]]
    assert [(e["kind"], e["event_id"]) for e in sent] == [
        ("mouse_move", 1),
        ("mouse_down", 2),
        ("key_down", 3),
    ]
    assert events[-1][1]["dropped_marker"] == 1
    health = [t for t, m in timeline if m["method"] == "hook.health"]
    assert health[:3] == [0, 500 * MS, 1000 * MS]
    obs = [o for _, m in timeline if m["method"] == "hook.obs" for o in m["params"]["batch"]]
    assert [o["cause_event_id"] for o in obs] == [2, 3]
    assert obs[0]["point_window"] == FAKE_HWND["target"]
    ime = [s for _, m in timeline if m["method"] == "hook.ime" for s in m["params"]["batch"]]
    assert {s["mode"] for s in ime} == {"native"}
    assert any(s["trigger"] == "key" for s in ime)

    # stream: 같은 시각표를 시계에 맞춰 (가짜 시계 — 기다리지 않는다)
    now = [0.0]
    got: list[tuple[float, str]] = []
    assert source.stream(
        lambda m: got.append((now[0], m["method"])),
        speed=2.0,
        clock=lambda: now[0],
        sleep=lambda s: now.__setitem__(0, now[0] + s),
    )
    assert len(got) == len(timeline)
    for (at, _), (t_ns, _) in zip(got, timeline, strict=True):
        assert at == pytest.approx(t_ns / 1e9 / 2.0, abs=1e-9)
    stop = threading.Event()
    stop.set()
    assert source.stream(lambda m: None, stop=stop) is False


def test_fake_hook_source_hook_exit_ends_timeline() -> None:
    header = {
        "kind": "header",
        "format": "kookabug.recorder-script/0",
        "title": "x",
        "geometry": {
            "frame_bounds": [0, 0, 8, 6],
            "client_origin": [0, 0],
            "client_size": [8, 6],
            "dpi": 96,
        },
        "scene": "s",
    }
    source = FakeHookSource([header, {"kind": "fault", "t_ns": 700 * MS, "fault": "hook_exit"}])
    timeline = source.timeline()
    assert source.exit_ns == 700 * MS
    assert max(t for t, _ in timeline) < 700 * MS


# ── 진입점 인자 ─────────────────────────────────────────────


def test_hookproc_testing_args_need_testing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from kookabug_platform.recorder.hookproc import _parse_args

    base = ["--pipe", "p", "--parent-pid", "1", "--parent-created", "2", "--mono-base-ns", "3"]
    monkeypatch.delenv("KOOKABUG_TESTING", raising=False)
    assert _parse_args(base).sender_load_ms == 0.0
    for extra in (["--ime-query-window", "5"], ["--sender-load-ms", "3"]):
        with pytest.raises(SystemExit):
            _parse_args([*base, *extra])
    monkeypatch.setenv("KOOKABUG_TESTING", "1")
    assert _parse_args([*base, "--ime-query-window", "5"]).ime_query_window == 5


def test_test_input_helpers_carry_given_mark() -> None:
    from kb_testing import keys

    down = keys.key_input(0x87, extra_info=0x7E57)
    up = keys.key_input(0x87, up=True)
    assert (down.u.ki.wVk, down.u.ki.dwFlags, down.u.ki.dwExtraInfo) == (0x87, 0, 0x7E57)
    assert (up.u.ki.dwFlags, up.u.ki.dwExtraInfo) == (0x0002, KOOKABUG_INPUT_MARK)
    click = keys.button_input("mouse:left", extra_info=0x7E57)
    release = keys.button_input("mouse:left", up=True)
    assert (click.type, click.u.mi.dwFlags, click.u.mi.dwExtraInfo) == (0, 0x0002, 0x7E57)
    assert (release.u.mi.dwFlags, release.u.mi.dwExtraInfo) == (0x0004, KOOKABUG_INPUT_MARK)


# ── 데스크톱 하네스의 판정 (실제 입력 없이 대역으로) ──────────


def test_hook_entry_lags_pair_sent_inputs_with_marked_events() -> None:
    from kb_testing.hook_harness import hook_entry_lags_ms

    base = 1_000
    sent = [10_000_000, 60_000_000]
    events = [
        {"kind": "key_down", "vk": 0x87, "extra_info": 7, "t_ns": 10_500_000 - base},
        {"kind": "key_down", "vk": 0x41, "extra_info": 0, "t_ns": 20_000_000},  # 사람 키
        {"kind": "key_up", "vk": 0x87, "extra_info": 7, "t_ns": 11_000_000},
        {"kind": "key_down", "vk": 0x87, "extra_info": 7, "t_ns": 62_000_000 - base},
    ]
    lags = hook_entry_lags_ms(sent, events, mono_base_ns=base, vk=0x87, extra_info=7)
    assert lags == pytest.approx([0.5, 2.0])
    with pytest.raises(AssertionError, match="받은 키"):
        hook_entry_lags_ms(sent[:1], events, mono_base_ns=base, vk=0x87, extra_info=7)


def _live_module() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).with_name("test_recorder_hook_live.py")
    spec = importlib.util.spec_from_file_location("recorder_hook_live_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("entry_lag_ms", "passes"), [(1, True), (500, False)])
def test_ui_hang_check_measures_hook_entry_lag(
    entry_lag_ms: int, passes: bool, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검수 T3-1 지적 5: UI 멈춤 회복 검사는 보낸 입력 → 훅 진입 지연을 본다 — 훅 진입만 500 ms
    늦춘 음성 대조가 실패해야 한다 (daemon 전달은 1 ms로 빠르게 둔다)."""
    live = _live_module()
    now = [0.0]
    updates: list[tuple[int, Any]] = []
    events: list[dict[str, Any]] = []

    def tap(extra: int = live.TEST_MARK) -> int:
        sent = int(now[0] * 1e9)
        event = {
            "kind": "key_down",
            "vk": live.VK_F24,
            "extra_info": extra,
            "t_ns": sent + entry_lag_ms * 1_000_000,
        }
        events.append(event)
        updates.append((event["t_ns"] + 1_000_000, SimpleNamespace(events=[event])))
        return sent

    rec = SimpleNamespace(
        updates=updates,
        stops=[],
        mono_base_ns=0,
        events=lambda: events,
        ime=lambda: [{"status": "timeout", "mode": "unknown"}],
        client=SimpleNamespace(stop=lambda: None),
    )
    recv = SimpleNamespace(hwnd=1, command=lambda *a: None, saw_control=lambda name: True)
    clock = SimpleNamespace(
        monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)
    )
    monkeypatch.setattr(live, "start_recording", lambda *a, **kw: rec)
    monkeypatch.setattr(live, "tap", tap)
    monkeypatch.setattr(live, "time", clock)
    monkeypatch.setattr(live, "wait_until", lambda fn, **kw: fn() or True)
    if passes:
        live.test_target_ui_thread_hang_recovery(recv, tmp_path)
    else:
        with pytest.raises(AssertionError):
            live.test_target_ui_thread_hang_recovery(recv, tmp_path)


# ── 가벼운 import ───────────────────────────────────────────

_PROBE = """
import json, sys
import kookabug_platform.recorder.hookproc, kookabug_platform.recorder.hookwin32
heavy = ("numpy", "cv2", "onnxruntime", "windows_capture", "pyclipper", "websockets", "asyncio")
print(json.dumps(sorted(m for m in sys.modules if m.split(".")[0] in heavy)))
"""


def test_hookproc_imports_stay_light() -> None:
    """훅 프로세스는 ctypes·표준 라이브러리만 (계획 2.1 — 훅 함수가 늦으면 시스템 입력이 늦다)."""
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []
