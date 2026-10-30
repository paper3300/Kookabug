"""창 수명 추적기와 바인딩 (구현 계획 M1 2.2, 계획 검수 7).

HWND 값은 창이 닫힌 뒤 다시 쓰일 수 있고, 같은 프로세스가 같은 값으로 새 창을 만들면 PID·생성
시각으로도 구별되지 않는다. 그래서 runner는 창을 정할 때(`launch`·`attach`·`set_current`·
`in.window`로 처음 쓸 때) **바인딩** `(hwnd, pid, process_created, binding_id)`를 만들고,
그 창의 파괴 이벤트(`EVENT_OBJECT_DESTROY`, `OBJID_WINDOW`)나 그 창 WGC 세션의 `on_closed`가
오면 바인딩을 죽인다.
같은 hwnd에 새 창이 생겨도 옛 바인딩은 `window_gone`이고 새 창은 새 바인딩을 따로 만들어야 한다.

쓸 때마다(`check`) 확인: 바인딩 살아 있음 + `IsWindow` + PID·생성 시각 일치.

**보장 범위**: 파괴 이벤트는 비동기(`WINEVENT_OUTOFCONTEXT`)로 추적기 스레드에 온다. 이벤트가 도착한
뒤에는 반드시 막는다. 파괴와 도착 사이(보통 수 ms)에 같은 프로세스가 같은 hwnd 값으로 새 창을
만들면 그 짧은 틈에는 옛 바인딩으로 새 창을 쓸 수 있다. 입력 액터는 원시 동작 직전에
`check`(필요하면 `sync`로 대기 중인 이벤트를 먼저 처리)를 부른다. `generation`은 바인딩이
죽을 때마다 오르는 세대 카운터다 — 액터가 앞서 읽은 값과 비교해 그사이 죽은 바인딩이
있었는지 싸게 안다.

`binding_id`는 그 실행 안에서만 뜻이 있다. 다른 실행·플러그인이 만든(또는 바인딩 없는) 창 참조는
`resolve`가 처음 쓸 때 바인딩을 만들고, 같은 참조를 다시 쓰면 그 바인딩을 돌려준다(그사이 닫혔으면
`window_gone`).
"""

from __future__ import annotations

import ctypes
import itertools
import threading
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Final, Self

from kookabug_platform.errors import WINDOW_GONE, PlatformError
from kookabug_platform.win32 import kernel32, user32
from kookabug_platform.win32._ffi import last_error_text
from kookabug_platform.win32.api import DEFAULT_API, WindowApi

__all__ = ["WindowBinding", "WindowTracker"]

_START_TIMEOUT_S: Final = 5.0
_STOP_TIMEOUT_S: Final = 5.0
_SYNC_TIMEOUT_S: Final = 0.05
_WM_SYNC: Final = user32.WM_APP + 1


@dataclass(frozen=True, slots=True)
class WindowBinding:
    """runner가 정한 창 하나. 같은 hwnd라도 바인딩마다 `binding_id`가 다르다."""

    binding_id: str
    hwnd: int
    pid: int
    process_created: int


class WindowTracker:
    """창 바인딩 표와 파괴 이벤트 스레드. `start()` 뒤 `stop()`까지 이벤트를 받는다.

    `start()` 없이 써도 바인딩·`check`는 동작한다(이벤트 없이 `IsWindow`·PID·생성 시각만 본다).
    검사는 `notify_destroyed`·`notify_capture_closed`를 직접 불러 이벤트를 넣는다.
    """

    def __init__(self, api: WindowApi = DEFAULT_API, *, run_id: str = "") -> None:
        """`run_id`를 주면 바인딩 ID가 `<run_id>.w<n>`이라 다른 실행의 ID와 겹치지 않는다(runner는
        늘 준다). 없으면 `w<n>`."""
        self._api = api
        self._prefix = f"{run_id}.w" if run_id else "w"
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._bindings: dict[str, WindowBinding] = {}
        self._dead: dict[str, str] = {}  # binding_id → 죽은 사유
        self._by_hwnd: dict[int, set[str]] = {}  # 살아 있는 바인딩만
        self._unbound: dict[tuple[int, int, int], str] = {}  # 바인딩 없는 참조 → 만든 바인딩
        self._generation = 0
        self._listeners: list[Callable[[str], None]] = []
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._start_error = ""
        self._synced = threading.Condition(self._lock)
        self._sync_seq = 0
        self._sync_done = 0
        self._callback = user32.WINEVENTPROC(self._on_win_event)

    # ------------------------------------------------------------ 스레드

    def start(self) -> Self:
        """파괴 이벤트 스레드를 띄운다. 훅을 걸 수 없으면 `OSError`."""
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="kb-window-tracker", daemon=True)
        self._thread.start()
        if not self._ready.wait(_START_TIMEOUT_S):
            raise OSError("창 수명 추적기 스레드가 시작되지 않았다")
        if self._start_error:
            self._thread.join(_STOP_TIMEOUT_S)
            self._thread = None
            raise OSError(f"창 파괴 이벤트 훅을 걸 수 없다: {self._start_error}")
        return self

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, user32.WM_QUIT, 0, 0)
        thread.join(_STOP_TIMEOUT_S)
        self._thread = None
        self._thread_id = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _run(self) -> None:
        msg = wintypes.MSG()
        # 메시지 큐를 먼저 만든다 (PostThreadMessage가 이 스레드에 닿게)
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, user32.PM_NOREMOVE)
        hook = user32.SetWinEventHook(
            user32.EVENT_OBJECT_DESTROY,
            user32.EVENT_OBJECT_DESTROY,
            None,
            self._callback,
            0,
            0,
            user32.WINEVENT_OUTOFCONTEXT,
        )
        if not hook:
            self._start_error = last_error_text()
            self._ready.set()
            return
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_SYNC and not msg.hWnd:
                    with self._lock:
                        self._sync_done = max(self._sync_done, int(msg.wParam))
                        self._synced.notify_all()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWinEvent(hook)

    def _on_win_event(
        self,
        _hook: int | None,
        event: int,
        hwnd: int | None,
        id_object: int,
        id_child: int,
        _thread: int,
        _time: int,
    ) -> None:
        if (
            event == user32.EVENT_OBJECT_DESTROY
            and id_object == user32.OBJID_WINDOW
            and id_child == user32.CHILDID_SELF
            and hwnd
        ):
            self.notify_destroyed(hwnd)

    def sync(self, timeout: float = _SYNC_TIMEOUT_S) -> bool:
        """추적기 스레드가 지금까지 큐에 들어온 메시지(대기 중인 파괴 이벤트 포함)를 처리할 때까지
        기다린다. 스레드가 없거나 기한을 넘기면 False. 보장 범위는 모듈 설명."""
        if not self.running or not self._thread_id:
            return False
        with self._lock:
            self._sync_seq += 1
            seq = self._sync_seq
        if not user32.PostThreadMessageW(self._thread_id, _WM_SYNC, seq, 0):
            return False
        with self._lock:
            return self._synced.wait_for(lambda: self._sync_done >= seq, timeout)

    # ------------------------------------------------------------ 이벤트

    def on_death(self, listener: Callable[[str], None]) -> None:
        """바인딩이 죽을 때마다 `listener(binding_id)`를 부른다 (잠금 밖, 죽인 스레드에서 —
        추적기 스레드·WGC 콜백 스레드일 수 있으므로 듣는 쪽은 그 자리에서 기다리지 않는다).
        캡처 서비스가 죽은 바인딩의 세션 픽셀을 바로 놓는 데 쓴다."""
        with self._lock:
            self._listeners.append(listener)

    def _announce(self, ids: Iterable[str]) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for binding_id in ids:
            for listener in listeners:
                listener(binding_id)

    def notify_destroyed(self, hwnd: int) -> None:
        """그 hwnd의 창이 파괴됐다: 그 hwnd의 살아 있는 바인딩을 전부 죽인다."""
        with self._lock:
            ids = self._by_hwnd.pop(hwnd, set())
            for binding_id in ids:
                self._dead[binding_id] = "창 파괴 이벤트"
            if ids:
                self._generation += 1
        self._announce(ids)

    def notify_capture_closed(self, binding_id: str) -> None:
        """그 바인딩의 WGC 세션이 `on_closed`를 받았다 (캡처 서비스가 연결한다)."""
        with self._lock:
            killed = self._kill(binding_id, "캡처 세션 종료(on_closed)")
        if killed:
            self._announce([binding_id])

    def _kill(self, binding_id: str, reason: str) -> bool:
        # 잠금 안에서 부른다. 이번에 죽였으면 True (알림은 잠금 밖에서 `_announce`)
        binding = self._bindings.get(binding_id)
        if binding is None or binding_id in self._dead:
            return False
        self._dead[binding_id] = reason
        live = self._by_hwnd.get(binding.hwnd)
        if live is not None:
            live.discard(binding_id)
            if not live:
                del self._by_hwnd[binding.hwnd]
        self._generation += 1
        return True

    @property
    def generation(self) -> int:
        """바인딩이 죽을 때마다 오르는 세대."""
        return self._generation

    # ------------------------------------------------------------ 바인딩

    def bind(self, hwnd: int) -> WindowBinding:
        """지금 그 hwnd의 창으로 새 바인딩을 만든다. 창이 없으면 `window_gone`."""
        api = self._api
        if not api.is_window(hwnd):
            raise PlatformError(WINDOW_GONE, f"창 {hwnd:#x}가 없다")
        pid = api.window_pid(hwnd)
        created = api.process_created(pid)
        if not pid or created is None:
            raise PlatformError(WINDOW_GONE, f"창 {hwnd:#x}의 프로세스(pid {pid})를 열 수 없다")
        with self._lock:
            binding = WindowBinding(f"{self._prefix}{next(self._ids)}", hwnd, pid, created)
            self._bindings[binding.binding_id] = binding
            self._by_hwnd.setdefault(hwnd, set()).add(binding.binding_id)
        return binding

    def get(self, binding_id: str) -> WindowBinding | None:
        with self._lock:
            return self._bindings.get(binding_id)

    def resolve(
        self, hwnd: int, *, pid: int = 0, process_created: int = 0, binding: str = ""
    ) -> WindowBinding:
        """창 참조를 이 실행의 바인딩으로. 확인(`check`)까지 한다.

        - `binding`이 이 추적기의 것이고 hwnd가 같으면 그 바인딩 (죽었으면 `window_gone`). 참조가
          준 PID·생성 시각이 그 바인딩과 다르면 `window_gone` — 다른 실행이 우연히 같은 ID를 쓴
          참조(같은 hwnd를 다른 프로세스가 재사용)를 이 실행의 창으로 받지 않는다
        - 아니면(바인딩 없음·다른 실행의 ID) `(hwnd, pid, process_created)` 참조로 처음 쓸 때 정한
          바인딩. 처음이면 **같은 살아 있는 창의 바인딩이 이미 있으면 그것**(참조 표현이 달라도 —
          부분 참조·완전한 참조 — 같은 창 수명은 바인딩 하나), 없으면 새로 만든다. 참조의 PID·생성
          시각이 지금 창과 다르면 `window_gone`. 같은 참조를 다시 쓰면 처음 정한 바인딩이다(그사이
          닫혔으면 `window_gone`)
        """
        known = self.get(binding) if binding else None
        if known is not None and known.hwnd == hwnd:
            if (pid and pid != known.pid) or (
                process_created and process_created != known.process_created
            ):
                raise PlatformError(
                    WINDOW_GONE,
                    f"참조한 창(hwnd {hwnd:#x}, pid {pid})은 바인딩 {binding}의 창"
                    f"(pid {known.pid})이 아니다 — 다른 실행의 참조이거나 창이 바뀌었다",
                )
            self.check(known)
            return known
        key = (hwnd, pid, process_created)
        with self._lock:
            existing = self._unbound.get(key)
            found = None if existing is None else self._bindings[existing]
        if found is not None:
            self.check(found)
            return found
        alias = self._live_binding(hwnd, pid, process_created)
        if alias is not None:
            self.check(alias)
            with self._lock:
                self._unbound[key] = alias.binding_id
            return alias
        made = self.bind(hwnd)
        if (pid and made.pid != pid) or (
            process_created and made.process_created != process_created
        ):
            with self._lock:
                killed = self._kill(made.binding_id, "참조와 다른 프로세스의 창")
            if killed:
                self._announce([made.binding_id])
            raise PlatformError(
                WINDOW_GONE,
                f"창 {hwnd:#x}는 참조한 프로세스(pid {pid})의 창이 아니다 (지금 pid {made.pid})",
            )
        with self._lock:
            self._unbound[key] = made.binding_id
        return made

    def acquire(self, hwnd: int) -> WindowBinding:
        """지금 그 hwnd의 창을 **새로 찾았을 때**(`windows.find`·`process.find_window`)의 바인딩:
        그 살아 있는 창의 바인딩이 이미 있으면 그것, 없으면 새로 만든다. 같은 HWND로 다시 만든
        창을 여러 번 찾아도 바인딩 하나다. 앞서 쓴 참조를 풀 때는 `resolve`(처음 정한 창이 죽었으면
        `window_gone`)."""
        alias = self._live_binding(hwnd, 0, 0)
        if alias is not None:
            self.check(alias)
            return alias
        return self.bind(hwnd)

    def _live_binding(self, hwnd: int, pid: int, process_created: int) -> WindowBinding | None:
        """지금 그 hwnd 창(같은 PID·생성 시각)의 살아 있는 바인딩. 참조가 준 PID·생성 시각이 지금
        창과 다르면 None (새로 만들어 `window_gone`으로 끝나게 둔다)."""
        api = self._api
        if not api.is_window(hwnd):
            return None
        now_pid = api.window_pid(hwnd)
        now_created = api.process_created(now_pid)
        if (pid and pid != now_pid) or (process_created and process_created != now_created):
            return None
        with self._lock:
            ids = sorted(self._by_hwnd.get(hwnd, ()))
            live = [
                self._bindings[i]
                for i in ids
                if i not in self._dead
                and self._bindings[i].pid == now_pid
                and self._bindings[i].process_created == now_created
            ]
        return live[0] if live else None

    def is_alive(self, binding: WindowBinding) -> bool:
        try:
            self.check(binding)
        except PlatformError:
            return False
        return True

    def check(self, binding: WindowBinding) -> None:
        """쓰기 직전 확인. 죽었거나 창·프로세스가 바뀌었으면 `window_gone` (그 바인딩을 죽인다)."""
        with self._lock:
            reason = self._dead.get(binding.binding_id)
        if reason is None:
            reason = self._mismatch(binding)
            if reason is not None:
                with self._lock:
                    killed = self._kill(binding.binding_id, reason)
                if killed:
                    self._announce([binding.binding_id])
        if reason is not None:
            raise PlatformError(
                WINDOW_GONE,
                f"대상 창(hwnd {binding.hwnd:#x}, pid {binding.pid})이 닫혔다: {reason}",
            )

    def _mismatch(self, binding: WindowBinding) -> str | None:
        api = self._api
        if not api.is_window(binding.hwnd):
            return "IsWindow 거짓"
        pid = api.window_pid(binding.hwnd)
        if pid != binding.pid:
            return f"같은 hwnd가 다른 프로세스(pid {pid})의 창"
        if api.process_created(pid) != binding.process_created:
            return "같은 PID의 다른 프로세스(생성 시각이 다름)"
        return None
