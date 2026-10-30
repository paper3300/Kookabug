"""WGC 창 캡처와 정지 화면 규칙 (구현 계획 M1 2.3, 계획 검수 2).

- **세션**: 창 바인딩마다 WGC 세션 하나(`windows-capture`, 커서·테두리 끔). 콜백이
  "최신 프레임"(BGR 픽셀 복사본, 도착 시각, 프레임 크기, 그때 창 DPI, `frame_seq`)을 바꿔
  넣는다. 콜백 버퍼는 콜백 밖에서 쓰지 않는다. `frame_seq`는 프로세스 안에서 유일하다
  (세션을 다시 만들어도 이어진다)
- **시각 두 개**: `observed_at` = 이 캡처 요청이 관측으로 확정된 시각, `pixels_at` = 그
  픽셀이 WGC에서 온 시각. 판정·기록은 `observed_at`을 "이 시점의 화면"으로 쓴다
- **최신 프레임 재사용**: 요청이 오면 `fresh_wait_ms`(50) 동안 새 프레임을 기다리고, 오지
  않으면 최신 프레임을 이 관측으로 쓴다(`reused`). 조건 전부: ① 세션이 살아 있음
  (`on_closed`·콜백 예외·스레드 종료 없음), ② 이 세션의 첫 프레임을 이미 받음, ③ 바인딩
  살아 있고 최소화 아님, ④ 지금 확장 프레임 크기·창 DPI가 그 프레임의 것과 같음. WGC는
  화면이 바뀔 때만 프레임을 주므로 "새 프레임 없음 + 위 조건"은 화면이 멈춘 것이다
- **장애 구분**: 첫 프레임이 기한 안에 안 옴 → `capture_timeout`. 크기·DPI가 바뀌었는데
  맞는 프레임이 기한 안에 안 옴 → `capture_timeout`(0.25초 안에 안 오면 세션을 한 번 다시 열어
  첫 프레임을 받는다 — windows-capture는 크기가 바뀐 프레임을 프레임 풀을 다시 만들며 버리므로
  멈춘 화면은 새 크기 프레임을 주지 않는다). 세션 종료·콜백 예외 → 세션을 한 번
  다시 만들고, 그래도 첫 프레임이 없으면(또 죽으면) `capture_failed`. `on_closed`(창 닫힘)
  → 바인딩을 죽이고 `window_gone`. 최소화 → `window_minimized`(캡처 전에 확인). 세션을 만들
  수 없음 → `capture_unsupported`
- **기한**: `ObservationDeadline`(설정 기한 = `capture_timeout`, 노드 기한 =
  `ObservationTimeout`, 전체 기한 = `DeadlineExceeded`). 기다리는 동안 50 ms마다 취소 확인
- **클라이언트 자르기**: 프레임은 확장 프레임 경계(`DWMWA_EXTENDED_FRAME_BOUNDS`) 크기다.
  (클라이언트 원점 - 확장 프레임 원점)에서 클라이언트 크기만큼 자른다. Windows 10에서
  테두리를 못 끄면(`draw_border=False` 시작 실패) 기본값으로 다시 시작한다 — 노란 테두리는
  창 바깥 경계라 자르기로 빠진다
- 검은 프레임이어도 백엔드를 바꾸지 않는다(5장). 매칭이 실패할 뿐이다
"""

from __future__ import annotations

import contextlib
import ctypes
import itertools
import threading
import time
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import numpy as np

from kookabug_core.record.artifacts import StagedFrame
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import (
    CAPTURE_FAILED,
    CAPTURE_TIMEOUT,
    CAPTURE_UNSUPPORTED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    PlatformError,
)
from kookabug_platform.tracker import WindowBinding, WindowTracker
from kookabug_platform.win32 import ole32, user32
from kookabug_platform.windows import WindowInfo, window_info

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from kookabug_sdk.types import Rect

__all__ = [
    "BACKEND",
    "FRESH_WAIT_MS",
    "CaptureBackend",
    "CaptureHandle",
    "CaptureService",
    "CapturedFrame",
    "FrameInfo",
    "WgcBackend",
    "bgra_to_bgr",
    "ensure_mta",
]

BACKEND: Final = "wgc"
FRESH_WAIT_MS: Final = 50
"""요청 뒤 새 프레임을 기다리는 시간 (조율자 결정 Q2)."""
_STOP_TIMEOUT_S: Final = 2.0
_RESIZE_RESTART_S: Final = 0.25
"""크기·DPI가 바뀐 뒤 이만큼 새 프레임이 없으면 세션을 한 번 다시 연다."""
_FINISH_MARGIN_S: Final = 0.025
"""새 프레임 대기를 기한보다 이만큼 앞에서 끝낸다 (자르기·확정할 시간과 Windows 대기 시간
해상도 약 15 ms의 초과분)."""

_frame_seq = itertools.count(1)
_seq_lock = threading.Lock()
# 단조 시계를 벽시계 초로 옮기는 차이 (기록용 시각이 실행 안에서 거꾸로 가지 않게)
_EPOCH_OFFSET: Final = time.time() - time.monotonic()


def _next_seq() -> int:
    with _seq_lock:
        return next(_frame_seq)


def wall_time(monotonic: float) -> float:
    """단조 시계 값 → 벽시계 초 (`observed_at`·`pixels_at`)."""
    return monotonic + _EPOCH_OFFSET


type Pixels = NDArray[np.uint8]
type FrameCallback = Callable[[Pixels], None]
"""BGRA `(높이, 너비, 4)` 뷰. 콜백 안에서만 유효하다."""


def bgra_to_bgr(buffer: Pixels) -> Pixels:
    """콜백 버퍼(행 간격이 너비보다 클 수 있는 BGRA 뷰) → 연속 BGR 복사본 (읽기 전용)."""
    if buffer.ndim != 3 or buffer.shape[2] != 4:
        raise ValueError(f"BGRA 프레임이 아니다: {buffer.shape}")
    pixels = np.array(buffer[:, :, :3], dtype=np.uint8, order="C", copy=True)
    pixels.setflags(write=False)
    return pixels


@dataclass(frozen=True, slots=True)
class FrameInfo:
    """캡처 하나의 정보 (M1 2.3). 좌표·크기는 물리 픽셀, 시각은 벽시계 초."""

    backend: str
    window: WindowBinding
    client_size: tuple[int, int]
    client_origin_screen: tuple[int, int]
    dpi: int
    region: tuple[int, int, int, int] | None
    """클라이언트 기준 `(x, y, 너비, 높이)`. 전체면 None."""
    observed_at: float
    pixels_at: float
    frame_seq: int
    reused: bool
    """새 프레임이 요청 뒤에 오지 않아 최신 프레임(요청 전 픽셀)을 다시 쓴 관측."""
    fullscreen: bool


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """캡처 결과: 클라이언트(또는 영역)의 BGR 픽셀(읽기 전용)과 정보."""

    pixels: Pixels
    info: FrameInfo
    key: Hashable
    """픽셀 동일성: 같은 WGC 프레임·같은 자르기면 같다 (프레임 저장소가 한 번만 보관)."""

    @property
    def size(self) -> tuple[int, int]:
        return int(self.pixels.shape[1]), int(self.pixels.shape[0])

    def staged(self) -> StagedFrame:
        """프레임 저장소에 넘길 것 (M1 2.7)."""
        return StagedFrame(self.key, self.pixels)


# ---------------------------------------------------------------- 백엔드


class CaptureHandle(Protocol):
    def stop(self) -> None: ...
    def is_finished(self) -> bool: ...


class CaptureBackend(Protocol):
    """창 하나의 캡처 세션을 띄운다. 실패하면 `capture_unsupported`(`PlatformError`)."""

    def start(
        self, hwnd: int, on_frame: FrameCallback, on_closed: Callable[[], None]
    ) -> CaptureHandle: ...


class _WgcHandle:
    def __init__(self, control: Any) -> None:
        self._control = control

    def stop(self) -> None:
        with contextlib.suppress(Exception):  # 이미 끝난 세션
            self._control.stop()

    def is_finished(self) -> bool:
        return bool(self._control.is_finished())


_mta_lock = threading.Lock()
_mta_cookie: ctypes.c_void_p | None = None


def ensure_mta() -> None:
    """프로세스 MTA를 프로세스가 끝날 때까지 살려 둔다 (`CoIncrementMTAUsage`, 한 번).

    windows-capture는 첫 세션 때 WinRT 객체(활성화 팩터리 등)를 만들어 캐시하고, 그 객체는
    그때의 MTA에 속한다. 세션 스레드가 끝난 뒤 다른 라이브러리가 COM을 초기화했다 해제하면
    (실측: `import onnxruntime`) MTA가 사라지고, 다음 세션 시작이 죽은 객체를 써 **접근 위반으로
    프로세스가 죽는다**. MTA 사용 수를 하나 잡아 두면 MTA가 사라지지 않는다. 최소 재현은
    `.orchestration/M1/wgc_mta_repro.py`(레포 밖). 실패하면 `capture_unsupported`.
    """
    global _mta_cookie
    with _mta_lock:
        if _mta_cookie is not None:
            return
        cookie = ctypes.c_void_p()
        hr = ole32.CoIncrementMTAUsage(ctypes.byref(cookie))
        if hr < 0:
            raise PlatformError(
                CAPTURE_UNSUPPORTED,
                f"프로세스 MTA를 유지할 수 없다 (CoIncrementMTAUsage 0x{hr & 0xFFFFFFFF:08x})",
            )
        _mta_cookie = cookie  # 놓지 않는다 (CoDecrementMTAUsage를 부르지 않음)


class WgcBackend:
    """`windows-capture` 창 세션 (`start_free_threaded`, 커서 끔, 테두리 끔)."""

    def start(
        self, hwnd: int, on_frame: FrameCallback, on_closed: Callable[[], None]
    ) -> CaptureHandle:
        ensure_mta()
        from windows_capture import WindowsCapture

        def on_frame_arrived(frame: Any, _control: Any) -> None:
            on_frame(frame.frame_buffer)

        def closed() -> None:
            on_closed()

        errors: list[str] = []
        # 테두리를 끌 수 없는 Windows 10 빌드는 시작이 실패한다 → 기본값으로 다시
        for draw_border in (False, None):
            try:
                capture = WindowsCapture(
                    cursor_capture=False, draw_border=draw_border, window_hwnd=hwnd
                )
                capture.frame_handler = on_frame_arrived
                capture.closed_handler = closed
                return _WgcHandle(capture.start_free_threaded())
            except Exception as exc:
                errors.append(f"draw_border={draw_border}: {exc}")
        raise PlatformError(
            CAPTURE_UNSUPPORTED, f"창 {hwnd:#x}의 WGC 세션을 만들 수 없다: {'; '.join(errors)}"
        )


# ---------------------------------------------------------------- 세션


@dataclass(frozen=True, slots=True)
class _Latest:
    seq: int
    pixels: Pixels
    size: tuple[int, int]
    dpi: int
    at: float


class _Calls:
    """네이티브 콜백 호출 수 (세션을 버린 뒤에 온 것까지 — 검사: 종료 뒤 콜백 없음)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.count = 0

    def hit(self) -> None:
        with self._lock:
            self.count += 1


class _Relay:
    """네이티브 세션이 붙잡는 콜백. 세션을 멈추면 `target`을 끊는다.

    windows-capture는 멈춘 세션의 콜백 객체를 놓지 않는다(세션마다 수 MB씩 남는 것을 soak
    검사에서 확인). 그래서 네이티브 쪽에는 이 작은 중계만 넘기고, 끊은 뒤에는 세션(최신 프레임
    픽셀)이 거기에 묶여 남지 않게 한다.
    """

    __slots__ = ("calls", "target")

    def __init__(self, target: _Session, calls: _Calls) -> None:
        self.target: _Session | None = target
        self.calls = calls

    def frame(self, buffer: Pixels) -> None:
        self.calls.hit()
        target = self.target
        if target is not None:
            target.on_frame(buffer)

    def closed(self) -> None:
        self.calls.hit()
        target = self.target
        if target is not None:
            target.on_closed()


class _Session:
    """창 바인딩 하나의 세션 상태. `cond`가 최신 프레임·종료 표시를 지킨다."""

    def __init__(
        self,
        binding: WindowBinding,
        dpi_of: Callable[[int], int],
        clock: Callable[[], float],
        on_closed: Callable[[str], None],
        calls: _Calls,
    ) -> None:
        self.binding = binding
        self.relay = _Relay(self, calls)
        self.cond = threading.Condition()
        self.latest: _Latest | None = None
        self.closed = False
        self.error: BaseException | None = None
        self.handle: CaptureHandle | None = None
        self.stopping = False
        self.stop_requested = False
        """회수 쪽이 네이티브 세션에 멈추라고 했다 (`_reap`가 두 번 부르지 않게)."""
        self.client: tuple[tuple[int, ...], Pixels] | None = None
        self.mismatch: tuple[tuple[int, int, int], float] | None = None
        """(창 기하, 처음 본 시각): 최신 프레임과 창 크기·DPI가 다른 상태가 시작된 때."""
        self._dpi_of = dpi_of
        self._clock = clock
        self._on_closed = on_closed

    def on_frame(self, buffer: Pixels) -> None:
        if self.stopping:
            return
        try:
            pixels = bgra_to_bgr(buffer)
            latest = _Latest(
                _next_seq(),
                pixels,
                (int(pixels.shape[1]), int(pixels.shape[0])),
                self._dpi_of(self.binding.hwnd),
                self._clock(),
            )
        except BaseException as exc:
            with self.cond:
                self.error = exc
                self.cond.notify_all()
            return
        with self.cond:
            if not self.stopping:
                self.latest = latest
            self.cond.notify_all()

    def on_closed(self) -> None:
        if self.stopping:
            return
        # 창이 닫혔다: 픽셀은 바로 놓는다 (같은 바인딩을 다시 캡처하지 않아도). 세션 회수는
        # 추적기 알림을 받은 서비스가 한다 — 이 콜백 스레드에서 세션을 멈추고 기다리지 않는다
        with self.cond:
            self.closed = True
            self.latest = None
            self.client = None
            self.cond.notify_all()
        self._on_closed(self.binding.binding_id)

    @property
    def failed(self) -> bool:
        """콜백 예외나 (멈추라고 하지 않았는데) 세션 스레드가 끝남. `on_closed`는 따로(`closed`)."""
        if self.error is not None:
            return True
        handle = self.handle
        return handle is not None and not self.stopping and handle.is_finished()

    @property
    def finished(self) -> bool:
        return self.handle is None or self.handle.is_finished()

    def release(self) -> None:
        """더는 콜백을 받지 않고 픽셀을 놓는다. 네이티브 세션은 멈추지 않는다 (콜백·추적기
        스레드에서 불러도 된다)."""
        self.stopping = True
        self.relay.target = None
        with self.cond:
            self.latest = None
            self.client = None
            self.cond.notify_all()

    def detach(self) -> None:
        """`release` + 멈추라고 한다 (끝나기는 기다리지 않음)."""
        self.release()
        if self.handle is not None:
            self.handle.stop()

    def stop(self, timeout_s: float) -> bool:
        """멈추고 끝나기를 기다린다. 끝났으면 True."""
        self.detach()
        handle = self.handle
        if handle is None:
            return True
        end = time.monotonic() + timeout_s
        while not handle.is_finished():
            if time.monotonic() >= end:
                return False
            time.sleep(0.01)
        return True


# ---------------------------------------------------------------- 캡처


def _window_dpi(hwnd: int) -> int:
    return int(user32.GetDpiForWindow(hwnd))


class CaptureService:
    """창 바인딩별 WGC 세션과 캡처 요청 처리. runner 안에 하나.

    `window_info`·`backend`·`dpi_of`는 검사에서 바꿔 끼운다. 실행이 끝나면 `close_all()`.
    """

    def __init__(
        self,
        tracker: WindowTracker,
        *,
        backend: CaptureBackend | None = None,
        info: Callable[[int], WindowInfo] = window_info,
        dpi_of: Callable[[int], int] = _window_dpi,
        fresh_wait_ms: int = FRESH_WAIT_MS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tracker = tracker
        self._backend: CaptureBackend = backend or WgcBackend()
        self._info = info
        self._dpi_of = dpi_of
        self._fresh_wait_s = fresh_wait_ms / 1000
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}
        self._retired: list[_Session] = []
        self._dead: deque[str] = deque()
        """사망 알림이 넣은 바인딩 (잠금 없이 넣고, 잠금 안에서 `_collect_dead`가 꺼낸다)."""
        self._calls = _Calls()
        self._restarted: dict[str, tuple[int, int, int]] = {}
        """바인딩 → 크기 불일치로 세션을 다시 연 창 기하 (같은 기하로는 한 번만)."""
        self.sessions_started = 0
        tracker.on_death(self._binding_dead)

    # ------------------------------------------------------------ 세션

    def _open(self, binding: WindowBinding) -> _Session:
        """그 바인딩의 세션(죽었어도 그대로 — 다시 만들기는 `capture`가 정한다)을 주거나, 없으면
        새로 만든다 (잠금 안에서)."""
        self._collect_dead()
        session = self._sessions.get(binding.binding_id)
        if session is not None:
            return session
        session = _Session(
            binding, self._dpi_of, self._clock, self._tracker.notify_capture_closed, self._calls
        )
        try:
            session.handle = self._backend.start(
                binding.hwnd, session.relay.frame, session.relay.closed
            )
        except PlatformError:
            raise
        except Exception as exc:
            raise PlatformError(
                CAPTURE_UNSUPPORTED, f"창 {binding.hwnd:#x}의 캡처 세션을 만들 수 없다: {exc}"
            ) from exc
        self.sessions_started += 1
        self._sessions[binding.binding_id] = session
        return session

    # 잠금 규칙: 서비스 잠금(`_lock`) 안에서는 상태(세션 표·회수 목록)만 바꾼다. 네이티브 세션
    # 멈추기(`handle.stop`은 콜백 스레드를 join한다)는 잠금 밖 `_reap`·`close`·`close_all`만 한다.
    # 추적기 사망 알림(`_binding_dead`)은 콜백·추적기 스레드에서 오므로 잠금을 기다리지 않고
    # 픽셀만 놓은 뒤 큐에 넣는다 — 잠금을 쥔 쪽(세션 시작 중 동기 `on_closed`, join 중인 회수)과
    # 서로 기다리지 않게. 세션 시작(`backend.start`)은 잠금 안이지만 그 안에서 오는 콜백은 위
    # 이유로 잠금이 필요 없다.

    def _retire(self, session: _Session) -> None:
        # 잠금 안에서 부른다. 표에서 빼고 픽셀을 놓을 뿐, 멈추기는 잠금 밖 `_reap`이 한다
        if self._sessions.get(session.binding.binding_id) is session:
            del self._sessions[session.binding.binding_id]
        session.release()
        if session not in self._retired:
            self._retired.append(session)

    def _collect_dead(self) -> None:
        # 잠금 안에서. 사망 알림이 큐에 넣은 바인딩의 세션을 회수 목록으로
        while self._dead:
            session = self._sessions.get(self._dead.popleft())
            if session is not None:
                self._retire(session)

    def _binding_dead(self, binding_id: str) -> None:
        """추적기 알림(파괴 이벤트·`on_closed`·확인 실패): 그 바인딩 세션의 픽셀을 바로 놓고,
        회수는 큐로 넘긴다. 서비스 잠금을 기다리지 않는다(위 잠금 규칙)."""
        session = self._sessions.get(binding_id)  # 잠금 없이 읽는다 (dict 조회는 원자적)
        if session is not None:
            session.release()
        self._dead.append(binding_id)

    def _reap(self) -> None:
        """회수 목록의 세션을 잠금 밖에서 멈추라고 하고, 끝난 세션은 놓는다."""
        with self._lock:
            self._collect_dead()
            pending = [s for s in self._retired if not s.stop_requested]
            for s in pending:
                s.stop_requested = True
        for s in pending:
            s.detach()
        with self._lock:
            self._retired = [s for s in self._retired if not s.finished]

    def _stop_and_wait(self, sessions: list[_Session], timeout_s: float) -> bool:
        """잠금 밖에서 멈추고 끝나기를 기다린다. 끝나지 않은 세션은 회수 목록에 남긴다."""
        unfinished = []
        for s in sessions:
            s.stop_requested = True
            if not s.stop(timeout_s):
                unfinished.append(s)
        with self._lock:
            kept = [s for s in self._retired if not s.finished and s not in unfinished]
            self._retired = kept + unfinished
        return not unfinished

    def cached_bytes(self) -> int:
        """세션들이 들고 있는 픽셀 바이트 (검사·진단: 죽은 바인딩은 0이어야 한다)."""
        with self._lock:
            sessions = [*self._sessions.values(), *self._retired]
        total = 0
        for s in sessions:
            with s.cond:
                latest = s.latest.pixels if s.latest is not None else None
                if latest is not None:
                    total += latest.nbytes
                if s.client is not None and s.client[1] is not latest:
                    total += s.client[1].nbytes
        return total

    def close(self, binding_id: str) -> bool:
        """그 바인딩의 세션(사망 알림으로 회수 목록에 옮겨진 것 포함)을 멈추고 끝나기를
        기다린다. 전부 끝났으면 True — 끝나지 않은 세션은 성공으로 보고하지 않는다."""
        with self._lock:
            self._collect_dead()
            current = self._sessions.get(binding_id)
            if current is not None:
                self._retire(current)
            targets = [s for s in self._retired if s.binding.binding_id == binding_id]
        return self._stop_and_wait(targets, _STOP_TIMEOUT_S)

    def close_all(self, timeout_s: float = _STOP_TIMEOUT_S) -> bool:
        """모든 세션(앞서 버린 것 포함)을 멈추고 끝나기를 기다린다. 전부 끝났으면 True."""
        with self._lock:
            self._collect_dead()
            for session in list(self._sessions.values()):
                self._retire(session)
            targets = list(self._retired)
        return self._stop_and_wait(targets, timeout_s)

    def all_finished(self) -> bool:
        """띄운 세션이 전부 끝났다 (끝나지 않은 세션은 끝날 때까지 이 서비스가 붙잡고 있다)."""
        with self._lock:
            sessions = [*self._sessions.values(), *self._retired]
        return all(s.finished for s in sessions)

    def callbacks(self) -> int:
        """지금까지 네이티브 세션이 부른 콜백 수 (버린 세션 것 포함 — 검사: 종료 뒤 콜백 없음)."""
        return self._calls.count

    # ------------------------------------------------------------ 캡처

    def _window(self, binding: WindowBinding) -> WindowInfo:
        """③ 바인딩 살아 있음·최소화 아님. 지금 창 정보."""
        try:
            self._tracker.check(binding)
            info = self._info(binding.hwnd)
        except PlatformError as exc:
            if exc.code == WINDOW_GONE:
                self.close(binding.binding_id)
            raise
        if info.minimized:
            raise PlatformError(
                WINDOW_MINIMIZED, f"대상 창 {info.title!r}(hwnd {binding.hwnd:#x})이 최소화돼 있다"
            )
        return info

    def capture(
        self,
        binding: WindowBinding,
        region: Rect | None = None,
        *,
        deadline: ObservationDeadline,
    ) -> CapturedFrame:
        """그 창의 지금 화면(클라이언트 영역, `region`이면 그 부분). 규칙은 모듈 설명.

        설정 기한 안에 프레임을 주지 못한 세션(`capture_timeout`·`capture_failed`)은 버린다 —
        다음 요청은 새 세션으로 시작해 첫 프레임을 곧바로 받는다(멈춘 화면의 세션은 다시 프레임을
        주지 않을 수 있다). 노드 기한(`ObservationTimeout`)으로 끝났으면 세션을 그대로 둔다 — 짧은
        기한으로 폴링하는 노드가 세션을 계속 새로 만들어 첫 프레임을 영영 못 받는 일을 막는다.
        """
        used: list[_Session] = []
        self._reap()  # 사망 알림·앞선 요청이 남긴 회수 대기 세션을 실행 중에 정리한다
        try:
            return self._capture(binding, region, deadline, used)
        except PlatformError as exc:
            if exc.code in (CAPTURE_TIMEOUT, CAPTURE_FAILED) and used:
                with self._lock:
                    if self._sessions.get(binding.binding_id) is used[-1]:
                        self._retire(used[-1])
                self._reap()
            raise

    def _capture(
        self,
        binding: WindowBinding,
        region: Rect | None,
        deadline: ObservationDeadline,
        used: list[_Session],
    ) -> CapturedFrame:
        what = f"창 hwnd {binding.hwnd:#x}"
        recreated = False

        def timeout(reason: str) -> Callable[[], BaseException]:
            def make() -> BaseException:
                if recreated:
                    return PlatformError(
                        CAPTURE_FAILED,
                        f"{what}: 캡처 세션을 다시 만들었지만 {reason} — 캡처 세션 장애",
                    )
                return PlatformError(
                    CAPTURE_TIMEOUT,
                    f"{what}: {deadline.config_ms}ms 안에 {reason} — 캡처 세션 장애이거나 "
                    "전체화면 독점 창일 수 있다",
                )

            return make

        deadline.start(timeout("시작 전 기한이 끝났다"))
        # 이 시각 뒤에 도착한 픽셀이 "새 프레임"이다 (콜백과 같은 시계)
        requested = self._clock()
        # 새 프레임 대기는 기한 직전까지만 — 멈춘 화면이면 남은 기한 안에서 최신 프레임을 준다
        fresh_until = min(deadline.now() + self._fresh_wait_s, deadline.end - _FINISH_MARGIN_S)
        fresh_waited = False
        changed = ""
        self._window(binding)
        with self._lock:
            session = self._open(binding)
        used.append(session)

        def waiting_for() -> str:
            """지금 기다리는 것 (기한이 어느 확인 지점에서 끝나도 같은 사유를 남긴다)."""
            if session.latest is None:
                if changed:
                    return f"크기·DPI가 바뀌어 세션을 다시 연 뒤({changed}) 첫 프레임이 오지 않았다"
                return "첫 프레임이 오지 않았다"
            if changed:
                return f"크기·DPI가 바뀐 뒤({changed}) 새 프레임이 오지 않았다"
            return "프레임이 오지 않았다"

        while True:
            # 세션 시작·창 정보 읽기 같은 끊을 수 없는 호출 뒤마다: 취소·기한
            deadline.ensure(timeout(waiting_for()))
            # ① 세션 상태
            if session.closed:
                self.close(binding.binding_id)
                self._tracker.check(binding)  # on_closed가 바인딩을 죽였다 → window_gone
                raise PlatformError(WINDOW_GONE, f"{what}: 캡처 세션이 닫혔다(on_closed)")
            if session.stopping:
                # 다른 쪽(추적기 알림·다른 요청의 다시 열기)이 이 세션을 놓았다
                self._window(binding)  # 죽은 바인딩이면 window_gone
                with self._lock:
                    session = self._open(binding)
                used.append(session)
                fresh_waited = True
                continue
            if session.failed:
                cause = session.error
                with self._lock:
                    self._retire(session)
                self._reap()
                if recreated:
                    raise PlatformError(
                        CAPTURE_FAILED, f"{what}: 다시 만든 캡처 세션도 죽었다 ({cause})"
                    )
                recreated = True
                self._window(binding)
                with self._lock:
                    session = self._open(binding)
                used.append(session)
                fresh_waited = True  # 새 세션의 프레임은 모두 요청 뒤 것이다
                continue

            def dead(s: _Session = session) -> bool:
                return s.closed or s.stopping or s.failed

            # ② 첫 프레임
            with session.cond:
                frame = session.latest
                if frame is None:
                    deadline.wait(
                        session.cond,
                        lambda s=session: s.latest is not None or dead(s),
                        timeout(
                            f"크기·DPI가 바뀌어 세션을 다시 연 뒤({changed}) 첫 프레임이 오지 "
                            "않았다"
                            if changed
                            else "첫 프레임이 오지 않았다"
                        ),
                    )
                    continue
                # 요청 뒤 새 프레임을 잠깐 기다린다 (안 오면 화면이 멈춘 것)
                if not fresh_waited and frame.at < requested:
                    fresh_waited = True
                    deadline.wait(
                        session.cond,
                        lambda s=session: (
                            (s.latest is not None and s.latest.at >= requested) or dead(s)
                        ),
                        timeout("프레임이 오지 않았다"),
                        until_s=fresh_until,
                    )
                    continue
            # ③·④ 지금 창과 프레임이 맞는가
            info = self._window(binding)
            left, top, right, bottom = info.frame_bounds
            geometry = (right - left, bottom - top, info.dpi)
            if (*frame.size, frame.dpi) == geometry:
                session.mismatch = None
                self._restarted.pop(binding.binding_id, None)
                break
            # 크기·DPI가 바뀌었다: 그 뒤 프레임을 기다린다. 불일치를 처음 본 시각은 세션에 남겨
            # 짧은 기한의 요청이 이어져도 0.25초 뒤 다시 열기가 진행된다
            changed = (
                f"창 {geometry[0]}x{geometry[1]} DPI {info.dpi}, "
                f"마지막 프레임 {frame.size[0]}x{frame.size[1]} DPI {frame.dpi}"
            )
            now = self._clock()
            if session.mismatch is None or session.mismatch[0] != geometry:
                session.mismatch = (geometry, now)
            may_restart = self._restarted.get(binding.binding_id) != geometry
            restart_in = session.mismatch[1] + _RESIZE_RESTART_S - now
            with session.cond:
                arrived = deadline.wait(
                    session.cond,
                    lambda s=session, seq=frame.seq: (
                        (s.latest is not None and s.latest.seq > seq) or dead(s)
                    ),
                    timeout(f"크기·DPI가 바뀐 뒤({changed}) 새 프레임이 오지 않았다"),
                    until_s=deadline.now() + max(0.0, restart_in) if may_restart else None,
                )
            if not arrived:
                # windows-capture는 크기가 바뀐 프레임에서 프레임 풀을 다시 만들며 그 프레임을
                # 버린다. 그 뒤 화면이 멈춰 있으면 새 크기 프레임이 오지 않는다 → 그 기하로 한 번
                # 세션을 다시 연다(새 세션은 첫 프레임을 곧바로 준다). 장애 재생성과 다르다
                self._restarted[binding.binding_id] = geometry
                with self._lock:
                    self._retire(session)
                self._reap()
                with self._lock:
                    session = self._open(binding)
                used.append(session)
                fresh_waited = True

        client = self._client(session, frame, info)
        pixels, region_box = client, None
        if region is not None:
            region_box = _region_box(region, info.client_size)
            x, y, w, h = region_box
            # 자기 메모리를 가진 복사본 — 뷰는 전체 프레임 할당을 붙잡아 저장소 예산을 속인다
            pixels = np.array(client[y : y + h, x : x + w], copy=True)
            pixels.setflags(write=False)
        crop = (info.client_origin[0] - left, info.client_origin[1] - top, *info.client_size)
        # 기한 뒤에 확정된 관측은 내보내지 않는다
        deadline.ensure(timeout("관측이 기한 뒤에 확정됐다"))
        observed = self._clock()
        return CapturedFrame(
            pixels=pixels,
            info=FrameInfo(
                backend=BACKEND,
                window=binding,
                client_size=info.client_size,
                client_origin_screen=info.client_origin,
                dpi=info.dpi,
                region=region_box,
                observed_at=wall_time(observed),
                pixels_at=wall_time(frame.at),
                frame_seq=frame.seq,
                reused=frame.at < requested,
                fullscreen=info.fullscreen,
            ),
            key=(BACKEND, frame.seq, crop, region_box),
        )

    def _client(self, session: _Session, frame: _Latest, info: WindowInfo) -> Pixels:
        """프레임에서 클라이언트 영역만 (같은 프레임·같은 자르기면 앞서 자른 것)."""
        ox = info.client_origin[0] - info.frame_bounds[0]
        oy = info.client_origin[1] - info.frame_bounds[1]
        cw, ch = info.client_size
        key = (frame.seq, ox, oy, cw, ch)
        cached = session.client
        if cached is not None and cached[0] == key:
            return cached[1]
        fw, fh = frame.size
        if ox < 0 or oy < 0 or cw <= 0 or ch <= 0 or ox + cw > fw or oy + ch > fh:
            raise PlatformError(
                CAPTURE_FAILED,
                f"프레임 {fw}x{fh}에서 클라이언트 {cw}x{ch}+{ox}+{oy}를 자를 수 없다",
            )
        if (ox, oy, cw, ch) == (0, 0, fw, fh):
            client = frame.pixels
        else:
            # 자기 메모리를 가진 복사본 (전체 너비 행 슬라이스도 뷰가 되지 않게)
            client = np.array(frame.pixels[oy : oy + ch, ox : ox + cw], copy=True)
            client.setflags(write=False)
        session.client = (key, client)
        return client


def _region_box(region: Rect, client_size: tuple[int, int]) -> tuple[int, int, int, int]:
    cw, ch = client_size
    box = (region.x, region.y, region.width, region.height)
    x, y, w, h = box
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > cw or y + h > ch:
        raise ValueError(f"캡처 영역 {box}이 클라이언트 {cw}x{ch} 밖이다")
    return box
