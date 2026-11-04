"""녹화 훅 프로세스를 실제 전역 훅으로 (M4 계획 2.1 T3 데스크톱 — 검수 H1·2차 N3).

`desktop_input`: 실제 SendInput을 보낸다(키는 F24 — 거의 쓰이지 않는 키, 클릭은 검사 창 안). 수신은
검사용 작은 Win32 창(`kb_testing/input_receiver.py`, 받은 순간 단조 시각 기록)이고, 녹화는 daemon과
같은 `HookClient`로 띄운 실제 훅 프로세스다. 검사 표식(`TEST_MARK`)을 `KOOKABUG_TESTING=1` 검사
옵션으로 받고, 제품 표식은 훅 프로세스가 버린다. 창은 `KOOKABUG_TEST_DISPLAY` 모니터에 놓는다.

지연 기준(p95 증가 ≤ 2 ms, 최대 ≤ 30 ms)은 측정 보고 뒤 조율자가 확정할 수 있다 (계획 T3).
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kb_testing import display
from kb_testing.hook_harness import RawHook, hook_entry_lags_ms
from kb_testing.keys import (
    assert_no_keys_held,
    button_input,
    key_input,
    release_all_for_test,
    send_inputs,
)
from kb_testing.proc import wait_until
from kookabug_daemon.recorder_hook import (
    TESTING_ENV,
    HookClient,
    HookStop,
    HookStream,
    HookTesting,
    HookUpdate,
    hook_command,
)
from kookabug_platform.dpi import per_monitor_v2_thread
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.win32 import user32
from kookabug_platform.windows import activate

pytestmark = [pytest.mark.desktop_input, pytest.mark.timeout(600)]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SetCursorPos = _user32.SetCursorPos
_SetCursorPos.restype = wintypes.BOOL
_SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
_GetKeyboardLayoutList = _user32.GetKeyboardLayoutList
_GetKeyboardLayoutList.restype = ctypes.c_int
_GetKeyboardLayoutList.argtypes = (ctypes.c_int, ctypes.c_void_p)

TEST_MARK = 0x7E57_0001
VK_F24 = 0x87
RECEIVER = Path(__file__).resolve().parents[3] / "tools" / "kb_testing" / "input_receiver.py"
SAMPLES = 2_000
WM_KEYDOWN, WM_LBUTTONDOWN = 0x0100, 0x0201
ENTRY_LIMIT_MS = 30.0
"""보낸 입력 → 훅 진입 상한 (지연 기준의 최대값과 같다)."""


# ── 수신 창 ──────────────────────────────────────────────────


class Receiver:
    def __init__(self, tmp: Path, *, hung: bool = False) -> None:
        self.dir = tmp / f"recv-{uuid.uuid4().hex[:6]}"
        self.dir.mkdir()
        self.log = self.dir / "log.jsonl"
        self.control = self.dir / "control"
        self.control.mkdir()
        x, y = display.place(400, 300) or (100, 100)
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(RECEIVER),
                "--log",
                str(self.log),
                "--control",
                str(self.control),
                "--x",
                str(x),
                "--y",
                str(y),
                *(["--hung"] if hung else []),
            ]
        )
        first = wait_until(lambda: self.lines()[:1], timeout=20)
        self.hwnd = int(first[0]["hwnd"])
        self.pid = int(first[0]["pid"])
        self._seen = 1

    def lines(self) -> list[dict[str, Any]]:
        try:
            text = self.log.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def new_lines(self) -> list[dict[str, Any]]:
        lines = self.lines()
        fresh, self._seen = lines[self._seen :], len(lines)
        return fresh

    def saw_control(self, name: str) -> bool:
        return any(line.get("control") == name for line in self.lines())

    def command(self, name: str, text: str = "") -> None:
        (self.control / name).write_text(text, encoding="utf-8")

    def center(self) -> tuple[int, int]:
        rect = wintypes.RECT()
        with per_monitor_v2_thread():
            user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        return (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.proc.kill()
        self.proc.wait(10)


# ── 녹화 쪽 ─────────────────────────────────────────────────


@dataclass
class Recording:
    client: HookClient
    mono_base_ns: int
    updates: list[tuple[int, HookUpdate]] = field(default_factory=list[tuple[int, HookUpdate]])
    stops: list[HookStop] = field(default_factory=list[HookStop])

    def events(self) -> list[dict[str, Any]]:
        return [e for _, u in self.updates for e in u.events]

    def ime(self) -> list[dict[str, Any]]:
        return [s for _, u in self.updates for s in u.ime]

    def obs(self) -> list[dict[str, Any]]:
        return [o for _, u in self.updates for o in u.obs]


def start_recording(
    tmp: Path,
    *,
    target_hwnd: int | None = None,
    ime_query_window: int | None = None,
    extra_args: tuple[str, ...] = (),
) -> Recording:
    env = {**os.environ, TESTING_ENV: "1"}
    base = time.monotonic_ns()
    holder: dict[str, Recording] = {}

    def on_update(update: HookUpdate) -> None:
        holder["r"].updates.append((time.monotonic_ns(), update))

    def on_stop(stop: HookStop) -> None:
        holder["r"].stops.append(stop)

    client = HookClient(
        mono_base_ns=base,
        on_update=on_update,
        on_stop=on_stop,
        testing=HookTesting(accept_extra_info=TEST_MARK, ime_query_window=ime_query_window),
        target_hwnd=target_hwnd,
        command=[*hook_command(), *extra_args],
        env=env,
        logs_dir=tmp,
    )
    holder["r"] = Recording(client, base)
    client.start(timeout=30)
    return holder["r"]


@pytest.fixture
def receiver(tmp_path: Path) -> Iterator[Receiver]:
    assert_no_keys_held()
    recv = Receiver(tmp_path)
    try:
        activate(recv.hwnd)
        yield recv
    finally:
        release_all_for_test()
        recv.close()


def tap(extra: int = TEST_MARK) -> int:
    sent = time.monotonic_ns()
    send_inputs(key_input(VK_F24, extra_info=extra), key_input(VK_F24, up=True, extra_info=extra))
    return sent


def measure_latency(recv: Receiver, count: int = SAMPLES) -> list[float]:
    """F24 누름을 보내고 창이 받기까지 (ms)."""
    recv.new_lines()
    out: list[float] = []
    for _ in range(count):
        sent = tap()
        deadline = time.monotonic() + 2
        got = None
        while got is None and time.monotonic() < deadline:
            for line in recv.new_lines():
                if line.get("msg") == WM_KEYDOWN and line.get("wparam") == VK_F24:
                    got = line["t_ns"]
            if got is None:
                time.sleep(0.0002)
        assert got is not None, "검사 창이 키를 받지 못했다 (포그라운드를 잃었나)"
        out.append((got - sent) / 1e6)
        time.sleep(0.002)
    return out


def p95(values: list[float]) -> float:
    return statistics.quantiles(values, n=100)[94]


def compare(control: list[float], recorded: list[float]) -> None:
    print(
        f"지연 ms: 대조 p95={p95(control):.3f} 최대={max(control):.3f} / "
        f"녹화 p95={p95(recorded):.3f} 최대={max(recorded):.3f}"
    )
    assert p95(recorded) - p95(control) <= 2.0
    assert max(recorded) <= 30.0


# ── 검사 ────────────────────────────────────────────────────


def test_hook_receives_test_marked_input_and_drops_product_mark(
    receiver: Receiver, tmp_path: Path
) -> None:
    rec = start_recording(tmp_path, target_hwnd=receiver.hwnd)
    try:
        x, y = receiver.center()
        with per_monitor_v2_thread():
            _SetCursorPos(x, y)
        for extra in (TEST_MARK, KOOKABUG_INPUT_MARK):
            send_inputs(
                button_input("mouse:left", extra_info=extra),
                button_input("mouse:left", up=True, extra_info=extra),
            )
            tap(extra)
            time.sleep(0.05)
        wait_until(lambda: len([e for e in rec.events() if "crit_seq" in e]) >= 4, timeout=5)
        time.sleep(0.3)
        crit = [e for e in rec.events() if "crit_seq" in e]
        assert [(e["kind"], e["extra_info"]) for e in crit] == [
            ("mouse_down", TEST_MARK),
            ("mouse_up", TEST_MARK),
            ("key_down", TEST_MARK),
            ("key_up", TEST_MARK),
        ]
        assert (crit[0]["x"], crit[0]["y"]) == (x, y)  # GetCursorPos와 같은 물리 좌표
        assert rec.client.stream.checker.counters["dropped_marker"] >= 4
        assert rec.stops == []
        # 양성 대조: 같은 입력이 창에도 닿았다
        got = [line for line in receiver.lines() if line.get("msg") in (WM_KEYDOWN, WM_LBUTTONDOWN)]
        assert len(got) == 4
    finally:
        rec.client.stop()


def test_input_latency_vs_control(receiver: Receiver, tmp_path: Path) -> None:
    control = measure_latency(receiver)
    rec = start_recording(tmp_path, target_hwnd=receiver.hwnd)
    try:
        recorded = measure_latency(receiver)
        assert rec.stops == []  # 훅이 떼어지지 않았다
    finally:
        rec.client.stop()
    compare(control, recorded)


def test_latency_with_hung_ime_responder(receiver: Receiver, tmp_path: Path) -> None:
    hung = Receiver(tmp_path, hung=True)  # 다른 프로세스의 멈춘 창
    try:
        activate(receiver.hwnd)
        control = measure_latency(receiver, 500)
        rec = start_recording(tmp_path, target_hwnd=receiver.hwnd, ime_query_window=hung.hwnd)
        try:
            recorded = measure_latency(receiver, 500)
            assert rec.stops == []
        finally:
            rec.client.stop()
        compare(control, recorded)
        ime = rec.ime()
        assert ime and all(s["status"] in ("timeout", "failed") for s in ime)
        assert all(s["mode"] == "unknown" for s in ime)
        # 즉시 관측은 IME 조회에 밀리지 않는다
        events = {e["event_id"]: e for e in rec.events()}
        skew = [o["obs_at_ns"] - events[o["cause_event_id"]]["t_ns"] for o in rec.obs()]
        assert skew and max(skew) < 50_000_000
    finally:
        hung.close()


def test_latency_with_pipe_stall(receiver: Receiver, tmp_path: Path) -> None:
    """daemon이 **파이프 읽기**를 멈춤 (`RawHook` — `RpcPeer`처럼 파이프를 비우지 않는다).

    훅 송신 쓰기가 막히고 중요 큐가 차서 넘치는 동안에도 입력 수신 지연은 대조군 기준 안이어야
    한다. 생존 감시는 이 검사가 돌리지 않는다(넘침을 먼저 일으키려고 — 실제 daemon에서는 2초 뒤
    `hook_lost`가 먼저 올 수 있다). 읽기를 재개하면 유실 지점에서 `input_overflow`, 그 앞은 모두."""
    control = measure_latency(receiver, 500)
    base = time.monotonic_ns()
    raw = RawHook(
        hook_command(),
        mono_base_ns=base,
        logs_dir=tmp_path,
        extra_args=("--target-hwnd", str(receiver.hwnd)),
    ).start()
    try:
        hello = raw.recv(timeout=30)
        assert hello is not None and hello["method"] == "hook.hello", raw.stderr()
        raw.adopt(hello["params"])
        stream = HookStream(mono_base_ns=base, testing=HookTesting(accept_extra_info=TEST_MARK))
        stream.feed("hook.hello", hello["params"], 0)
        # 읽지 않는 동안 키 3,000번 = 중요 이벤트 6,000개 (큐 4,096칸 + 파이프 버퍼보다 많다)
        stalled = measure_latency(receiver, 3_000)
        delivered: list[int] = []
        while stream.stop is None:
            message = raw.recv(timeout=10)
            assert message is not None, "재개 뒤 넘침이 오지 않았다"
            update = stream.feed(message["method"], message["params"], 0)
            if update is not None:
                delivered += [e["crit_seq"] for e in update.events if "crit_seq" in e]
        assert stream.stop.reason == "input_overflow", stream.stop
        cut = stream.stop.cut_crit_seq
        assert cut is not None
        assert [s for s in delivered if s < cut] == sorted(set(delivered))  # 빠짐·중복 없이
        raw.send("hook.stop", {})
    finally:
        raw.close()
    compare(control, stalled)


def test_latency_with_sender_cpu_load(receiver: Receiver, tmp_path: Path) -> None:
    control = measure_latency(receiver)
    rec = start_recording(tmp_path, target_hwnd=receiver.hwnd, extra_args=("--sender-load-ms", "3"))
    try:
        recorded = measure_latency(receiver)
        assert rec.stops == []
    finally:
        rec.client.stop()
    compare(control, recorded)


def test_target_ui_thread_hang_recovery(receiver: Receiver, tmp_path: Path) -> None:
    rec = start_recording(tmp_path, target_hwnd=receiver.hwnd)
    try:
        receiver.command("hang", "5")
        wait_until(lambda: receiver.saw_control("hang"), timeout=5)
        sent: list[int] = []
        until = time.monotonic() + 4.5
        while time.monotonic() < until:
            sent.append(tap())
            time.sleep(0.05)
        wait_until(lambda: receiver.saw_control("unhang"), timeout=10)
        time.sleep(0.3)  # 마지막 묶음이 daemon에 닿을 시간
        # 대상 UI 스레드가 멈춘 동안에도 훅 진입은 늦지 않는다: 보낸 입력 ↔ 훅 이벤트를 짝지어
        # (훅 t_ns - 보낸 시각). 수신 창 지연은 재지 않는다 (멈춘 창은 처리하지 못하는 것이 정상)
        entry = hook_entry_lags_ms(
            sent, rec.events(), mono_base_ns=rec.mono_base_ns, vk=VK_F24, extra_info=TEST_MARK
        )
        # daemon 전달 지연은 따로 남긴다 (훅 이후 경로)
        delivery = [
            (at - (e["t_ns"] + rec.mono_base_ns)) / 1e6
            for at, u in rec.updates
            for e in u.events
            if e.get("extra_info") == TEST_MARK and e["kind"] == "key_down"
        ]
        print(
            f"UI 멈춤 중 훅 진입 ms: 최대={max(entry):.3f} p95={p95(entry):.3f} / "
            f"daemon 전달 ms: 최대={max(delivery):.3f}"
        )
        assert max(entry) <= ENTRY_LIMIT_MS
        assert max(delivery) < 200.0
        hung_ime = [s for s in rec.ime() if s["status"] != "ok"]
        assert hung_ime and all(s["mode"] == "unknown" for s in hung_ime)
        assert rec.stops == []
        # 풀린 뒤 녹화가 이어진다
        before = len(rec.events())
        tap()
        wait_until(lambda: len(rec.events()) > before or None, timeout=5)
        assert rec.stops == []
    finally:
        rec.client.stop()


_DAEMON_SIDE = r"""
import json, os, sys, time
from kookabug_daemon.recorder_hook import HookClient
client = HookClient(mono_base_ns=time.monotonic_ns(), on_update=lambda u: None,
                    on_stop=lambda s: None)
client.start(timeout=30)
print(json.dumps({"hook_pid": client.pid}), flush=True)
time.sleep(600)
"""


def test_hook_removed_when_daemon_side_killed(receiver: Receiver, tmp_path: Path) -> None:
    from kookabug_core.win import Process

    side = subprocess.Popen(
        [sys.executable, "-c", _DAEMON_SIDE],
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        assert side.stdout is not None
        hook_pid = int(json.loads(side.stdout.readline())["hook_pid"])
        hook = Process.open(hook_pid)
        assert hook.alive()
        side.kill()
        side.wait(10)
        # `wait`는 종료 코드(0일 수 있다)를, 기한을 넘기면 None을 돌려준다
        assert hook.wait(5) is not None, "부모가 죽었는데 훅 프로세스가 남았다"
        # 훅이 사라진 뒤에도 입력은 정상으로 닿는다 (걸린 훅 없음)
        latency = measure_latency(receiver, 50)
        assert max(latency) < 30.0
    finally:
        with contextlib.suppress(OSError):
            side.kill()


def _has_korean_layout() -> bool:
    count = int(_GetKeyboardLayoutList(0, None))
    layouts = (ctypes.c_void_p * max(count, 1))()
    _GetKeyboardLayoutList(count, layouts)
    return any((int(h or 0) & 0xFFFF) == 0x0412 for h in layouts[:count])


def test_ime_mode_reported_for_korean_layout(receiver: Receiver, tmp_path: Path) -> None:
    if not _has_korean_layout():
        pytest.skip("한국어 자판이 설치되지 않은 PC")
    receiver.command("korean")
    rec = start_recording(tmp_path, target_hwnd=receiver.hwnd)
    try:
        receiver.command("native")
        wait_until(
            lambda: any(s["status"] == "ok" and s["mode"] == "native" for s in rec.ime()) or None,
            timeout=5,
        )
        receiver.command("alpha")
        wait_until(
            lambda: (
                any(s["status"] == "ok" and s["mode"] == "alphanumeric" for s in rec.ime()) or None
            ),
            timeout=5,
        )
        assert any(str(s["hkl"]).endswith("412") for s in rec.ime())
        assert rec.stops == []
    finally:
        rec.client.stop()
