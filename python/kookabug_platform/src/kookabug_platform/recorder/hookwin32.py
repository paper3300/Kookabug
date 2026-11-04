"""녹화 훅 프로세스의 Win32 부분 (M4 계획 2.1): 훅 스레드·관측 스레드·IME 표본 스레드·송신·읽기.

- **훅 콜백**(`make_hook_procs`)은 구조체 필드를 `HookCore`에 넘기고 `CallNextHookEx`만 부른다.
  다른 Win32 함수(창 조회·메시지 보내기)는 부르지 않는다 — 검사가 바인딩을 기록 대역으로 바꿔
  확인한다. 입력을 막지 않는다(언제나 다음 훅으로 넘김, 반환값으로 삼키지 않음)
- **관측**(`Observer`)은 중요 이벤트마다 즉시 관측 하나를 만든다(합치지 않음). 메시지 없는 API만
  쓴다: 포그라운드·스레드·포커스(`GetGUIThreadInfo`)·자판(`GetKeyboardLayout`)·스타일. 점 아래
  최상위 창은 `WindowFromPoint`(대상에 메시지를 보낼 수 있음) 대신 창 이벤트(포그라운드·보임·
  숨김·Z 순서·위치)로 무효화하는 Z 순서 표(`EnumWindows`)에서 고른다
- **IME 표본**(`ImeSampler`)은 대상에 묻는 유일한 조회(`SendMessageTimeoutW` 50 ms)이고 **관측과
  다른 스레드**다 — 조회가 시간 초과까지 막혀도 그 사이 들어온 이벤트의 즉시 관측은 밀리지 않는다
  (3차 검수 N5). 실패도 조회 구간(`query_started_ns`)을 실어 보낸다(N6 — 받는 쪽이 그 구간과 겹치는
  키를 판정 불가로 만든다)
- **송신**(`Sender`)은 묶음·관측·표본·생존 보고(500 ms)를 파이프로 쓴다. 쓰기가 막히면 기다린다
  (훅 콜백과 무관) — 그동안 중요 큐가 차면 콜백이 `overflow`를 올리고, 받는 쪽이 `input_overflow`로
  멈춘다
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import threading
import time
from collections import deque
from collections.abc import Callable
from ctypes import wintypes
from typing import Any, Final

from kookabug_core.recorder.contract import (
    BATCH_MAX_EVENTS,
    HEALTH_INTERVAL_NS,
    IME_KEY_SAMPLE_GAP_NS,
    IME_PERIODIC_NS,
    IME_QUERY_TIMEOUT_MS,
)
from kookabug_platform.recorder.hookproc import HookCore, encode
from kookabug_platform.win32 import dwmapi, imm32, kernel32, user32
from kookabug_platform.win32.user32 import HC_ACTION, KBDLLHOOKSTRUCT, MSLLHOOKSTRUCT
from kookabug_sdk.pipe import PipeConnection, PipeError

__all__ = [
    "IME_KEY_SETTLE_NS",
    "HookThread",
    "ImeSampler",
    "Observer",
    "Sender",
    "Win32Api",
    "make_hook_procs",
    "start_reader",
]

IME_KEY_SETTLE_NS: Final = 30_000_000
"""IME 전환 키를 뗀 뒤 표본을 뜨기까지 (대상 스레드가 전환을 처리할 시간)."""
_ERROR_TIMEOUT: Final = 1460
_POINTER_KINDS: Final = frozenset({"mouse_down", "mouse_up", "wheel"})
_OBJID_WINDOW: Final = 0
_CHILDID_SELF: Final = 0
_GA_ROOT: Final = 2
_GW_OWNER: Final = 4
_WM_QUIT: Final = 0x0012


def _hwnd(value: Any) -> int | None:
    return int(value) if value else None


class Win32Api:
    """관측·IME 표본·생존 보고가 쓰는 Win32 호출 (검사가 대역으로 바꾼다). 메시지를 보내는 것은
    `ime_conversion` 하나다 (`SendMessageTimeoutW`)."""

    def foreground(self) -> int | None:
        return _hwnd(user32.GetForegroundWindow())

    def thread_of(self, hwnd: int) -> int | None:
        thread = int(user32.GetWindowThreadProcessId(hwnd, None))
        return thread or None

    def focus_of(self, thread: int) -> int | None:
        info = user32.GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
            return None
        return _hwnd(info.hwndFocus)

    def layout_of(self, thread: int) -> str | None:
        hkl = user32.GetKeyboardLayout(thread)
        return None if not hkl else format(int(hkl) & 0xFFFFFFFFFFFFFFFF, "x")

    def is_password_edit(self, hwnd: int) -> bool | None:
        buf = ctypes.create_unicode_buffer(64)
        if not user32.GetClassNameW(hwnd, buf, len(buf)):
            return None
        if "edit" not in buf.value.casefold():
            return False
        return bool(user32.GetWindowLongPtrW(hwnd, user32.GWL_STYLE) & user32.ES_PASSWORD)

    def owner_of(self, hwnd: int) -> int | None:
        return _hwnd(user32.GetWindow(hwnd, _GW_OWNER))

    def is_top_level(self, hwnd: int) -> bool:
        return _hwnd(user32.GetAncestor(hwnd, _GA_ROOT)) == hwnd

    def top_windows(self) -> list[tuple[int, tuple[int, int, int, int]]]:
        """보이는 최상위 창을 Z 순서(위부터)로, (창, 사각형). 최소화·숨김(cloaked)은 뺀다."""
        found: list[tuple[int, tuple[int, int, int, int]]] = []

        def each(hwnd: int, _param: int) -> bool:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            cloaked = wintypes.DWORD()
            dwmapi.DwmGetWindowAttribute(
                hwnd, dwmapi.DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if cloaked.value:
                return True
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                found.append((int(hwnd), (rect.left, rect.top, rect.right, rect.bottom)))
            return True

        user32.EnumWindows(user32.WNDENUMPROC(each), 0)
        return found

    def ime_window(self, hwnd: int) -> int | None:
        return _hwnd(imm32.ImmGetDefaultIMEWnd(hwnd))

    def ime_conversion(self, hwnd: int, timeout_ms: int) -> tuple[str, int | None]:
        """`(status, conversion)`: ok·timeout·failed."""
        result = ctypes.c_size_t()
        flags = user32.SMTO_ABORTIFHUNG | user32.SMTO_BLOCK
        sent = user32.SendMessageTimeoutW(
            hwnd,
            user32.WM_IME_CONTROL,
            user32.IMC_GETCONVERSIONMODE,
            0,
            flags,
            timeout_ms,
            ctypes.byref(result),
        )
        if sent:
            return "ok", int(result.value) & 0xFFFFFFFF
        error = ctypes.get_last_error()
        return ("timeout" if error in (_ERROR_TIMEOUT, 0) else "failed"), None

    def last_input_tick(self) -> int:
        info = user32.LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        user32.GetLastInputInfo(ctypes.byref(info))
        return int(info.dwTime)


# ── 훅 콜백·훅 스레드 ────────────────────────────────────────


def make_hook_procs(
    core: HookCore, handles: list[int]
) -> tuple[Callable[[int, int, int], int], Callable[[int, int, int], int]]:
    """마우스·키보드 훅 프로시저. 필드 복사 → `HookCore` → `CallNextHookEx`뿐이다."""

    def mouse(n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == HC_ACTION:
                s = MSLLHOOKSTRUCT.from_address(l_param)
                core.on_mouse(w_param, s.pt.x, s.pt.y, s.mouseData, s.flags, s.dwExtraInfo)
        except BaseException:
            pass
        return user32.CallNextHookEx(handles[0], n_code, w_param, l_param)

    def keyboard(n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code == HC_ACTION:
                s = KBDLLHOOKSTRUCT.from_address(l_param)
                core.on_key(w_param, s.vkCode, s.scanCode, s.flags, s.dwExtraInfo)
        except BaseException:
            pass
        return user32.CallNextHookEx(handles[1], n_code, w_param, l_param)

    return mouse, keyboard


class HookThread:
    """`SetWindowsHookExW`(마우스·키보드 저수준) + 메시지 루프. 콜백 말고는 일하지 않는다."""

    def __init__(self, core: HookCore) -> None:
        self.core = core
        self.error: str | None = None
        self.thread_id = 0
        self.installed = False
        self._handles: list[int] = [0, 0]
        self._procs: tuple[Any, Any] | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hook-thread", daemon=True)

    def start(self, timeout: float = 5.0) -> bool:
        self._thread.start()
        if not self._ready.wait(timeout):
            self.error = "훅 스레드가 준비되지 않았다"
        return self.error is None

    def _run(self) -> None:
        self.thread_id = int(kernel32.GetCurrentThreadId())
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), kernel32.THREAD_PRIORITY_HIGHEST)
        mouse, keyboard = make_hook_procs(self.core, self._handles)
        procs = (user32.HOOKPROC(mouse), user32.HOOKPROC(keyboard))
        self._procs = procs  # 콜백이 사는 동안 쥔다
        module = kernel32.GetModuleHandleW(None)
        m = user32.SetWindowsHookExW(user32.WH_MOUSE_LL, procs[0], module, 0)
        k = user32.SetWindowsHookExW(user32.WH_KEYBOARD_LL, procs[1], module, 0)
        if not m or not k:
            self.error = f"SetWindowsHookExW 실패 (Win32 오류 {ctypes.get_last_error()})"
            for handle in (m, k):
                if handle:
                    user32.UnhookWindowsHookEx(handle)
            self._ready.set()
            return
        self._handles[:] = [int(m), int(k)]
        self.installed = True
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(m)
        user32.UnhookWindowsHookEx(k)
        self.installed = False

    def stop(self, timeout: float = 2.0) -> None:
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, _WM_QUIT, 0, 0)
        self._thread.join(timeout)


# ── 즉시 관측 ────────────────────────────────────────────────


class Observer:
    """중요 이벤트마다 즉시 관측 하나 (`out`). 창 이벤트로 Z 순서 표를 무효화한다."""

    def __init__(
        self,
        core: HookCore,
        api: Win32Api,
        *,
        on_change: Callable[[str], None] | None = None,
        idle_s: float = 0.001,
    ) -> None:
        self.core = core
        self.api = api
        self.out: deque[dict[str, Any]] = deque()
        self.table_changed_ns = 0
        self.zorder_rev = 0
        self._on_change = on_change
        self._idle_s = idle_s
        self._dirty = True
        self._table: list[tuple[int, tuple[int, int, int, int]]] = []
        self._last_fg: int | None = None
        self._last_hkl: str | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hook-observer", daemon=True)
        self._hooks: list[int] = []
        self._proc: Any = None

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def note_change(self) -> None:
        """Z 순서·포그라운드 표가 바뀌었다 (창 이벤트)."""
        self.table_changed_ns = self.core.now()
        self.zorder_rev += 1
        self._dirty = True

    def _on_win_event(
        self, _hook: Any, event: int, hwnd: Any, id_object: int, id_child: int, *_rest: Any
    ) -> None:
        if not hwnd or id_object != _OBJID_WINDOW or id_child != _CHILDID_SELF:
            return
        if event != user32.EVENT_SYSTEM_FOREGROUND and not self.api.is_top_level(int(hwnd)):
            return
        self.note_change()

    def _install_win_events(self) -> None:
        self._proc = user32.WINEVENTPROC(self._on_win_event)
        flags = user32.WINEVENT_OUTOFCONTEXT
        for low, high in (
            (user32.EVENT_SYSTEM_FOREGROUND, user32.EVENT_SYSTEM_FOREGROUND),
            (user32.EVENT_OBJECT_SHOW, user32.EVENT_OBJECT_REORDER),
            (user32.EVENT_OBJECT_LOCATIONCHANGE, user32.EVENT_OBJECT_LOCATIONCHANGE),
        ):
            hook = user32.SetWinEventHook(low, high, None, self._proc, 0, 0, flags)
            if hook:
                self._hooks.append(hook)

    def _run(self) -> None:
        self._install_win_events()
        msg = wintypes.MSG()
        try:
            while not self._stop.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, user32.PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                if not self.process_pending():
                    time.sleep(self._idle_s)
        finally:
            for hook in self._hooks:
                user32.UnhookWinEvent(hook)

    def process_pending(self) -> int:
        """기다리는 중요 이벤트마다 즉시 관측을 만든다. 만든 수."""
        count = 0
        while self.core.obs_requests:
            event = self.core.obs_requests.popleft()
            self.out.append(self.observe(event))
            count += 1
        return count

    def observe(self, event: dict[str, Any]) -> dict[str, Any]:
        api = self.api
        fg = api.foreground()
        fg_thread = api.thread_of(fg) if fg else None
        focus = api.focus_of(fg_thread) if fg_thread else None
        hkl = api.layout_of(fg_thread) if fg_thread else None
        obs: dict[str, Any] = {
            "cause_event_id": event["event_id"],
            "fg": fg,
            "fg_thread": fg_thread,
            "focus": focus,
            "hkl": hkl,
            "table_changed_ns": self.table_changed_ns,
            "zorder_rev": self.zorder_rev,
        }
        obs["focus_password"] = api.is_password_edit(focus) if focus else None
        obs["fg_owner"] = api.owner_of(fg) if fg else None
        if event["kind"] in _POINTER_KINDS:
            window = self.window_at(int(event["x"]), int(event["y"]))
            obs["point_window"] = window
            obs["point_owner"] = api.owner_of(window) if window else None
        obs["obs_at_ns"] = self.core.now()
        if fg != self._last_fg:
            self._last_fg, self._last_hkl = fg, hkl
            if self._on_change is not None:
                self._on_change("foreground")
        elif hkl != self._last_hkl:
            self._last_hkl = hkl
            if self._on_change is not None:
                self._on_change("hkl")
        return obs

    def window_at(self, x: int, y: int) -> int | None:
        if self._dirty:
            self._table = self.api.top_windows()
            self._dirty = False
        for hwnd, (left, top, right, bottom) in self._table:
            if left <= x < right and top <= y < bottom:
                return hwnd
        return None


# ── IME 표본 ────────────────────────────────────────────────


class ImeSampler:
    """IME 모드 표본 (`out`). 관측과 다른 스레드다 — 조회가 막혀도 즉시 관측은 돈다 (N5).

    뜨는 때: 키 뒤 직전 표본이 100 ms보다 오래됐으면, IME 전환 키를 뗀 뒤(30 ms 뒤 — 대상이 전환을
    처리할 시간), 포그라운드·자판이 바뀌면, 대상이 앞에 있는 동안 250 ms마다."""

    def __init__(
        self,
        core: HookCore,
        api: Win32Api,
        *,
        target_hwnd: int | None = None,
        query_window: int | None = None,
        timeout_ms: int = IME_QUERY_TIMEOUT_MS,
        idle_s: float = 0.002,
    ) -> None:
        self.core = core
        self.api = api
        self.target_hwnd = target_hwnd
        self.query_window = query_window
        self.timeout_ms = timeout_ms
        self.out: deque[dict[str, Any]] = deque()
        self.querying = threading.Event()
        """조회 중 (검사가 '조회 도중 들어온 이벤트'를 만든다)."""
        self._requests: deque[tuple[str, int]] = deque()
        self._pending_ime_key: int | None = None
        self._last_at: int | None = None
        self._next_periodic = 0
        self._idle_s = idle_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hook-ime", daemon=True)

    def request(self, trigger: str) -> None:
        """다른 스레드(관측)가 표본을 청한다: foreground·hkl."""
        self._requests.append((trigger, self.core.now()))

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.step():
                time.sleep(self._idle_s)

    def step(self) -> bool:
        """청한 것·때가 된 것이 있으면 표본 하나를 뜬다. 떴으면 True."""
        now = self.core.now()
        key_pending = False
        while self.core.ime_requests:
            trigger, t = self.core.ime_requests.popleft()
            if trigger == "ime_key":
                self._pending_ime_key = t
            else:
                key_pending = True
        changed: str | None = None
        while self._requests:
            changed = self._requests.popleft()[0]
        if changed is not None:
            self.sample(changed)
            return True
        if self._pending_ime_key is not None and now - self._pending_ime_key >= IME_KEY_SETTLE_NS:
            self._pending_ime_key = None
            self.sample("ime_key")
            return True
        if key_pending and (self._last_at is None or now - self._last_at >= IME_KEY_SAMPLE_GAP_NS):
            self.sample("key")
            return True
        if now >= self._next_periodic:
            self._next_periodic = now + IME_PERIODIC_NS
            if self.target_hwnd is None or self.api.foreground() == self.target_hwnd:
                self.sample("periodic")
                return True
        return False

    def sample(self, trigger: str) -> dict[str, Any]:
        api = self.api
        started = self.core.now()
        fg = api.foreground()
        fg_thread = api.thread_of(fg) if fg else None
        hkl = api.layout_of(fg_thread) if fg_thread else None
        window = self.query_window or (api.ime_window(fg) if fg else None)
        conversion: int | None = None
        if window is None:
            status = "no_ime"
        else:
            self.querying.set()
            try:
                status, conversion = api.ime_conversion(window, self.timeout_ms)
            finally:
                self.querying.clear()
        sample: dict[str, Any] = {
            "query_started_ns": started,
            "sampled_at_ns": self.core.now(),
            "fg": fg,
            "fg_thread": fg_thread,
            "hkl": hkl,
            "status": status,
            "trigger": trigger,
        }
        if status == "ok" and conversion is not None:
            sample["mode"] = "native" if conversion & user32.IME_CMODE_NATIVE else "alphanumeric"
            sample["conversion"] = conversion
        else:
            sample["status"] = "failed" if status == "ok" else status
            sample["mode"] = "unknown"
        self._last_at = sample["sampled_at_ns"]
        self.out.append(sample)
        return sample


# ── 송신·읽기 ────────────────────────────────────────────────


class _Broken(Exception):
    pass


class Sender:
    """묶음·관측·표본·생존 보고를 파이프로. 쓰기가 막히면 기다린다 (그동안 콜백이 `overflow`)."""

    def __init__(
        self,
        core: HookCore,
        api: Win32Api,
        conn: PipeConnection,
        obs_out: deque[dict[str, Any]],
        ime_out: deque[dict[str, Any]],
        *,
        on_broken: Callable[[], None],
        interval_s: float = 0.004,
        health_ns: int = HEALTH_INTERVAL_NS,
        write: Callable[[bytes], None] | None = None,
        load_s: float = 0.0,
    ) -> None:
        self.core = core
        self._load_s = load_s
        """검사 전용: 틱마다 CPU를 붙잡는 시간 (`--sender-load-ms`)."""
        self.api = api
        self._write = write or (lambda body: conn.send_frame(body, timeout=None))
        self._obs = obs_out
        self._ime = ime_out
        self._on_broken = on_broken
        self._interval_s = interval_s
        self._health_ns = health_ns
        self._last_health: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hook-sender", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, *, flush: bool = False, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if flush:
            with contextlib.suppress(_Broken):  # 파이프가 이미 끊겼으면 보낼 곳이 없다
                self.send_pending(force_health=True)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.send_pending()
                if self._load_s > 0:
                    until = time.perf_counter() + self._load_s
                    while time.perf_counter() < until:  # 순수 파이썬 연산으로 GIL을 쥔다
                        pass
                time.sleep(self._interval_s)
        except _Broken:
            self._on_broken()

    def _send(self, method: str, params: dict[str, Any]) -> None:
        try:
            self._write(encode(method, params))
        except (PipeError, OSError) as exc:
            raise _Broken from exc

    def send_pending(self, *, force_health: bool = False) -> None:
        while (batch := self.core.take_batch()) is not None:
            self._send("hook.events", batch)
        for method, source in (("hook.obs", self._obs), ("hook.ime", self._ime)):
            while source:
                chunk: list[dict[str, Any]] = []
                while source and len(chunk) < BATCH_MAX_EVENTS:
                    chunk.append(source.popleft())
                self._send(method, {"batch": chunk})
        now = self.core.now()
        if force_health or self._last_health is None or now - self._last_health >= self._health_ns:
            self._last_health = now
            self._send(
                "hook.health",
                {
                    "batch_no": self.core.batch_no,
                    "last_event_ns": self.core.last_event_ns,
                    "last_input_tick": self.api.last_input_tick(),
                    "sent_at_ns": now,
                },
            )


def start_reader(conn: PipeConnection, *, on_stop: Callable[[], None]) -> threading.Thread:
    """daemon이 보낸 `hook.stop`(또는 파이프 끊김)을 기다린다."""

    def run() -> None:
        while True:
            try:
                frame = conn.recv_frame(timeout=None)
            except PipeError, OSError:
                on_stop()
                return
            try:
                message = json.loads(frame)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("method") == "hook.stop":
                on_stop()
                return

    thread = threading.Thread(target=run, name="hook-reader", daemon=True)
    thread.start()
    return thread
