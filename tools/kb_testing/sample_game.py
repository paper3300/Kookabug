"""예제 게임을 띄우고 기다리고 닫는 테스트 헬퍼 (구현 계획 M1 2.13 `kb_testing.sample_game`).

게임은 **테스트 하네스의 세션 Job** 안에서 뜬다(pytest가 세션 Job 소속이라 자식은 생성 시점부터
소속). 그래서 runner의 실행 Job과는 따로 살고, pytest가 강제로 끝나도 Job이 정리한다. pytest 밖
(도구·조사 스크립트)에서는 띄우는 프로세스 전용 `KILL_ON_JOB_CLOSE` Job을 같은 방식으로 만든다
(`launch_job`) — 띄운 쪽이 네이티브 크래시로 죽어도 게임이 남지 않는다.

venv의 `python.exe`는 실제 인터프리터를 자식으로 띄우는 런처라, 게임은 기반 인터프리터로 직접
띄운다(`kb_testing.proc.python_cmd`). 그러면 `Popen.pid`가 창을 가진 프로세스의 PID다.

기다림은 게임의 입력 수신 기록(`--event-log`)으로만 한다 (`wait_event`·`wait_screen`).
창 확인용 Win32 함수와 WGC 한 장 캡처(`capture_client`)도 여기 둔다 — 제품 플랫폼 코드
(`kookabug_platform`)와 독립이라 그 코드를 검사하는 데 쓸 수 있다.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

from kb_testing.proc import direct_env, python_cmd, wait_until
from kookabug_core.win import Job

__all__ = [
    "EXAMPLE_LOCAL",
    "EXAMPLE_SECRETS",
    "EXAMPLE_SECRET_ENV",
    "FRAMES_DIR",
    "FRAMES_SNAPSHOT",
    "GAME_DIR",
    "WORKSPACE_DIR",
    "SampleGame",
    "Snap",
    "capture_client",
    "client_rect",
    "copy_example_workspace",
    "game_code_digest",
    "game_command",
    "game_env",
    "is_window",
    "keep_process_mta",
    "launch_job",
    "launch_sample_game",
    "post_close",
    "read_frames_snapshot",
    "renderer_of",
    "send_signal",
    "snap_scene",
    "stale_frames",
    "window_owner",
    "window_pid",
    "window_root_owner",
    "window_title",
    "window_visible",
    "write_frames_snapshot",
]

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
GAME_DIR: Final = REPO_ROOT / "fixtures" / "sample-game"
FRAMES_DIR: Final = GAME_DIR / "frames"
WORKSPACE_DIR: Final = GAME_DIR / "workspace"
"""예제 워크스페이스 (구현 계획 M1 T12)."""
EXAMPLE_SECRETS: Final = {"accounts.qa_tester_01": "sample-pass-01"}
EXAMPLE_SECRET_ENV: Final = {"KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01": "sample-pass-01"}
"""예제 워크스페이스의 비밀값을 환경 변수로 (CI·무인 실행 방식)."""
EXAMPLE_LOCAL: Final = {"game.cwd": str(GAME_DIR), "game.executable": python_cmd()[0]}
"""사람마다 다른 설정(`.kookabug/local.json`): 게임을 띄울 인터프리터와 `-m sample_game`을 찾는
폴더."""
READY_TIMEOUT_S: Final = 20.0
CLOSE_TIMEOUT_S: Final = 10.0
CAPTURE_TIMEOUT_S: Final = 5.0
# WGC는 화면이 바뀔 때만 프레임을 준다. 마지막 프레임 뒤 이만큼 새 프레임이 없으면 그것이 지금 화면
CAPTURE_SETTLE_S: Final = 0.3
# 화면 PNG를 찍는 조건. 로딩 화면은 타이머로 넘어가므로 찍는 동안 머물게 아주 길게 잡는다
SNAP_SIZE: Final = (1024, 640)
SNAP_OPTIONS: Final = (
    "--size",
    f"{SNAP_SIZE[0]}x{SNAP_SIZE[1]}",
    "--dpi-awareness",
    "pmv2",
    "--slow-loading",
    "600000",
)

# ---------------------------------------------------------------- Win32 (테스트 확인용)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")


def _sig(fn: Any, restype: Any, *argtypes: Any) -> Any:
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


_IsWindow = _sig(_user32.IsWindow, wintypes.BOOL, wintypes.HWND)
_IsWindowVisible = _sig(_user32.IsWindowVisible, wintypes.BOOL, wintypes.HWND)
_GetWindow = _sig(_user32.GetWindow, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_GetAncestor = _sig(_user32.GetAncestor, wintypes.HWND, wintypes.HWND, wintypes.UINT)
_GetWindowThreadProcessId = _sig(
    _user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
)
_GetWindowTextW = _sig(
    _user32.GetWindowTextW, ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
)
_GetClientRect = _sig(
    _user32.GetClientRect, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT)
)
_ClientToScreen = _sig(
    _user32.ClientToScreen, wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT)
)
_PostMessageW = _sig(
    _user32.PostMessageW,
    wintypes.BOOL,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
_DwmGetWindowAttribute = _sig(
    _dwmapi.DwmGetWindowAttribute,
    ctypes.HRESULT,
    wintypes.HWND,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)

_SetThreadDpiAwarenessContext = _sig(
    _user32.SetThreadDpiAwarenessContext, ctypes.c_void_p, ctypes.c_void_p
)
_CoIncrementMTAUsage = _sig(
    ctypes.WinDLL("ole32").CoIncrementMTAUsage, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p)
)

DPI_PMV2: Final = -4
GW_OWNER: Final = 4
GA_ROOTOWNER: Final = 3
WM_CLOSE: Final = 0x0010
DWMWA_EXTENDED_FRAME_BOUNDS: Final = 9


def is_window(hwnd: int) -> bool:
    return bool(_IsWindow(hwnd))


def window_visible(hwnd: int) -> bool:
    return bool(_IsWindowVisible(hwnd))


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_owner(hwnd: int) -> int:
    return _GetWindow(hwnd, GW_OWNER) or 0


def window_root_owner(hwnd: int) -> int:
    return _GetAncestor(hwnd, GA_ROOTOWNER) or 0


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    _GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


@contextmanager
def _per_monitor_v2_thread() -> Iterator[None]:
    # 좌표를 물리 픽셀로 읽으려고 이 스레드만 잠깐 Per-Monitor V2로 둔다 (프로세스는 그대로)
    previous = _SetThreadDpiAwarenessContext(ctypes.c_void_p(DPI_PMV2))
    try:
        yield
    finally:
        if previous:
            _SetThreadDpiAwarenessContext(previous)


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    """클라이언트 영역의 화면 원점과 크기 (물리 픽셀)."""
    rect = wintypes.RECT()
    origin = wintypes.POINT(0, 0)
    with _per_monitor_v2_thread():
        if not _GetClientRect(hwnd, ctypes.byref(rect)):
            raise OSError(f"GetClientRect 실패: hwnd={hwnd}")
        _ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


def post_close(hwnd: int) -> bool:
    return bool(_PostMessageW(hwnd, WM_CLOSE, 0, 0))


def _extended_frame(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    hr = _DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
    )
    if hr != 0:
        raise OSError(f"DwmGetWindowAttribute 실패: 0x{hr & 0xFFFFFFFF:08x}")
    return rect.left, rect.top, rect.right, rect.bottom


_mta_cookie: ctypes.c_void_p | None = None


def keep_process_mta() -> None:
    """프로세스 MTA를 끝까지 살려 둔다 (한 번). WGC 세션을 열기 전에 부른다.

    제품 `kookabug_platform.capture.ensure_mta`와 같은 규칙을 제품 코드 없이 따른다:
    windows-capture가 캐시한 WinRT 객체가 속한 MTA를 다른 라이브러리(`import onnxruntime`)가
    없애면 다음 세션 시작이 접근 위반으로 프로세스를 죽인다.
    """
    global _mta_cookie
    if _mta_cookie is not None:
        return
    cookie = ctypes.c_void_p()
    hr = _CoIncrementMTAUsage(ctypes.byref(cookie))
    if hr < 0:
        raise OSError(f"CoIncrementMTAUsage 실패: 0x{hr & 0xFFFFFFFF:08x}")
    _mta_cookie = cookie


def capture_client(
    hwnd: int, *, timeout: float = CAPTURE_TIMEOUT_S, settle: float = CAPTURE_SETTLE_S
) -> Any:
    """창 하나를 WGC로 캡처해 클라이언트 영역만 BGR `numpy` 배열로 돌려준다.

    마지막 프레임 뒤 `settle`초 동안 새 프레임이 없으면 그 프레임을 지금 화면으로 본다.
    """
    import numpy as np
    from windows_capture import WindowsCapture

    keep_process_mta()

    lock = threading.Lock()
    latest: dict[str, Any] = {}
    changed = threading.Event()
    capture = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=hwnd)

    @capture.event
    def on_frame_arrived(frame: Any, control: Any) -> None:
        with lock:
            latest["pixels"] = np.array(frame.frame_buffer, copy=True)
            latest["at"] = time.monotonic()
        changed.set()

    @capture.event
    def on_closed() -> None:
        latest["closed"] = True
        changed.set()

    control = capture.start_free_threaded()
    try:
        deadline = time.monotonic() + timeout
        while True:
            changed.wait(max(0.0, min(settle, deadline - time.monotonic())))
            changed.clear()
            with lock:
                at = latest.get("at")
            if latest.get("closed"):
                raise RuntimeError("캡처 세션이 닫혔다")
            now = time.monotonic()
            if at is not None and now - at >= settle:
                break
            if now >= deadline:
                raise TimeoutError(f"{timeout}초 안에 멈춘 프레임을 얻지 못했다")
    finally:
        control.stop()
        stop_deadline = time.monotonic() + 2
        while not control.is_finished() and time.monotonic() < stop_deadline:
            time.sleep(0.02)
    with lock:
        pixels = latest["pixels"]
    left, top, _right, _bottom = _extended_frame(hwnd)
    cx, cy, cw, ch = client_rect(hwnd)
    ox, oy = cx - left, cy - top
    client = pixels[oy : oy + ch, ox : ox + cw, :3]
    if client.shape[:2] != (ch, cw):
        raise RuntimeError(f"프레임 {pixels.shape}에서 클라이언트 {cw}x{ch}+{ox}+{oy}를 못 자른다")
    return np.ascontiguousarray(client)


# ---------------------------------------------------------------- 띄우기


def send_signal(path: Path, command: str) -> None:
    """`--signal-file path`로 띄운 게임에 검사용 명령을 보낸다 (`fire`: 지금 걸린 타이머를 바로
    끝냄). 게임이 읽다 만 파일을 보지 않게 옆 파일에 쓴 뒤 바꿔 넣는다. 처리되면 `signal` 기록."""
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(command + "\n", encoding="utf-8")
    staging.replace(path)


def game_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = direct_env(base)
    env["PYTHONPATH"] = str(GAME_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def game_command(*options: str | Path) -> list[str]:
    return python_cmd("-m", "sample_game", *options)


class SampleGame:
    """띄운 예제 게임 하나. `close()`가 남은 프로세스를 끝낸다 (컨텍스트 관리자)."""

    def __init__(
        self, proc: subprocess.Popen[bytes], event_log: Path, stdout: Path, stderr: Path
    ) -> None:
        self.proc = proc
        self.event_log = event_log
        self.stdout = stdout
        self.stderr = stderr
        self.ready: dict[str, Any] = {}

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def hwnd(self) -> int:
        """지금(마지막 `ready`)의 메인 창."""
        return int(self.ready["hwnd"])

    def events(self) -> list[dict[str, Any]]:
        """입력 수신 기록. 쓰는 중인 끝 줄(줄바꿈 전)은 버린다."""
        if not self.event_log.exists():
            return []
        lines = self.event_log.read_bytes().split(b"\n")
        return [json.loads(line) for line in lines[:-1] if line.strip()]

    def diagnostics(self) -> str:
        tail = self.events()[-10:]
        err = self.stderr.read_text(encoding="utf-8", errors="replace")[-1500:]
        return f"종료 코드 {self.proc.poll()}, 마지막 기록 {tail}, stderr {err!r}"

    def wait_event(
        self,
        event: str | None = None,
        *,
        where: Callable[[dict[str, Any]], bool] | None = None,
        after: int = 0,
        timeout: float = READY_TIMEOUT_S,
        **fields: Any,
    ) -> dict[str, Any]:
        """`seq > after`이고 조건이 맞는 첫 기록을 기다린다. 게임이 먼저 끝나면 바로 실패."""

        def find() -> dict[str, Any] | None:
            for record in self.events():
                if record["seq"] <= after or (event is not None and record["event"] != event):
                    continue
                if any(record.get(k) != v for k, v in fields.items()):
                    continue
                if where is None or where(record):
                    return record
            if self.proc.poll() is not None:
                raise AssertionError(f"게임이 기다리던 기록 전에 끝났다: {self.diagnostics()}")
            return None

        found = wait_until(
            find,
            timeout=timeout,
            message=lambda: f"기록 {event} {fields}: {self.diagnostics()}",
        )
        assert found is not None
        return found

    def wait_screen(
        self, scene: str, *, after: int = 0, timeout: float = READY_TIMEOUT_S
    ) -> dict[str, Any]:
        return self.wait_event("screen", after=after, timeout=timeout, scene=scene)

    def wait_ready(self, *, after: int = 0, timeout: float = READY_TIMEOUT_S) -> dict[str, Any]:
        self.ready = self.wait_event("ready", after=after, timeout=timeout)
        return self.ready

    def last_seq(self) -> int:
        events = self.events()
        return events[-1]["seq"] if events else 0

    def close(self, timeout: float = CLOSE_TIMEOUT_S) -> int:
        """메인 창에 `WM_CLOSE`를 보내 끝나기를 기다리고, 안 끝나면 강제로 끝낸다."""
        if self.proc.poll() is None and self.ready and is_window(self.hwnd):
            post_close(self.hwnd)
            try:
                return self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                pass
        if self.proc.poll() is None:
            self.proc.kill()
        return self.proc.wait(timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _session_job() -> Job | None:
    # pytest 밖(화면 PNG 도구 등)에서는 플러그인을 불러오지 않는다
    plugin = sys.modules.get("kb_testing.pytest_plugin")
    return None if plugin is None else plugin._session_job


_own_job: Job | None = None


def launch_job() -> Job:
    """게임이 생성 시점부터 들어갈 `KILL_ON_JOB_CLOSE` Job.

    pytest 안이면 세션 Job(pytest 자신이 들어 있음). 밖(화면 PNG 도구·조사 스크립트)이면 이
    프로세스 전용 Job을 한 번 만들고 **자신을 넣는다** — 세션 Job과 같은 방식이라 이 프로세스가
    네이티브 크래시·강제 종료로 죽어도 마지막 핸들이 닫히며 OS가 게임을 끝낸다. 핸들은 닫지
    않는다(`keep_until_exit`, 닫으면 자신도 끝난다).
    """
    global _own_job
    session = _session_job()
    if session is not None:
        return session
    if _own_job is None:
        job = Job.create(kill_on_close=True).keep_until_exit()
        job.assign_current()
        _own_job = job
    return _own_job


def launch_sample_game(
    options: Sequence[str | Path] = (),
    *,
    workdir: Path,
    job: Job | None = None,
    wait_ready: bool = True,
    timeout: float = READY_TIMEOUT_S,
) -> SampleGame:
    """예제 게임을 띄운다. `workdir`에 입력 수신 기록과 stdout·stderr를 둔다.

    게임은 생성 시점부터 `launch_job()`(pytest 세션 Job 또는 이 프로세스 전용 Job) 안이다 —
    띄운 쪽이 어떻게 죽어도 게임이 남지 않는다. `job`을 주면 그 Job에도 넣는다.
    `wait_ready`면 메인 창과 첫 화면이 그려질 때까지 기다린다.
    """
    owner = launch_job()  # 띄우기 전에: 자식은 생성 시점부터 이 Job 소속
    workdir = workdir.resolve()  # 게임은 GAME_DIR에서 뜨므로 절대 경로로 넘긴다
    workdir.mkdir(parents=True, exist_ok=True)
    stem = f"sample-game-{uuid.uuid4().hex[:8]}"
    event_log = workdir / f"{stem}.events.jsonl"
    stdout, stderr = workdir / f"{stem}.out.txt", workdir / f"{stem}.err.txt"
    cmd = game_command("--event-log", event_log, *options)
    with stdout.open("wb") as out, stderr.open("wb") as err:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=game_env(),
            cwd=GAME_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW,
            close_fds=True,
        )
    game = SampleGame(proc, event_log, stdout, stderr)
    try:
        if not owner.contains(proc.pid):
            raise AssertionError(f"게임 {proc.pid}가 정리 Job(launch_job) 밖이다")
        if job is not None:
            job.assign(proc.pid)
        if wait_ready:
            game.wait_ready(timeout=timeout)
            game.wait_event("screen", timeout=timeout)
    except BaseException:
        game.close()
        raise
    return game


@dataclass(frozen=True)
class Snap:
    pixels: Any
    """클라이언트 영역 BGR `numpy` 배열."""
    renderer: dict[str, Any]
    """그 그림을 그린 환경 (`renderer_of`)."""


def snap_scene(scene: str, *, workdir: Path) -> Snap:
    """그 장면의 대표 상태를 그린 게임 창을 캡처한다 (화면 PNG와 그 신선도 검사가 같이 쓴다).

    찍는 동안 장면이 바뀌었으면(타이머 등) 실패한다 — 다른 장면을 그 이름으로 남기지 않게.
    """
    with launch_sample_game(("--start-scene", scene, *SNAP_OPTIONS), workdir=workdir) as game:
        shown = game.wait_screen(scene)
        pixels = capture_client(game.hwnd)
        later = [e for e in game.events() if e["event"] == "screen" and e["seq"] > shown["seq"]]
        if later:
            raise AssertionError(f"{scene}를 찍는 동안 장면이 바뀌었다: {later}")
        renderer = renderer_of(game.ready)
    if pixels.shape[:2] != (SNAP_SIZE[1], SNAP_SIZE[0]):
        raise AssertionError(f"{scene} 캡처 크기가 다르다: {pixels.shape}")
    return Snap(pixels, renderer)


# ---------------------------------------------------------------- 화면 PNG 기록

FRAMES_SNAPSHOT: Final = GAME_DIR / "tests" / "frames.snapshot.json"
"""커밋된 화면 PNG를 찍은 렌더러와 장면별 찍은 때의 게임 코드 해시 (`snap_frames.py`가 쓴다).
설치본에 들어가는 `frames/` 밖에 둔다 — 찍은 PC 정보라 예제가 아니다."""
FRAMES_SNAPSHOT_FORMAT: Final = "kookabug.sample-frames/0"
SPI_GETFONTSMOOTHING: Final = 0x004A
SPI_GETFONTSMOOTHINGTYPE: Final = 0x200A
FE_FONTSMOOTHINGCLEARTYPE: Final = 2

_SystemParametersInfoW = _sig(
    _user32.SystemParametersInfoW,
    wintypes.BOOL,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    wintypes.UINT,
)


def _spi_uint(action: int) -> int:
    value = wintypes.UINT()
    if not _SystemParametersInfoW(action, 0, ctypes.byref(value), 0):
        raise OSError(f"SystemParametersInfoW({action:#x}) 실패")
    return value.value


def renderer_of(ready: Mapping[str, Any]) -> dict[str, Any]:
    """게임 그림의 픽셀을 바꾸는 환경: Windows 빌드·판(창 모서리·테두리·글꼴 파일), 창 DPI, 글꼴
    다듬기. 같은 게임 코드라도 이것이 다르면 픽셀이 다르다 (예: 화면 PNG의 클라이언트 아래
    모서리에는 Windows 11 둥근 창 모서리가 찍혀 있고, CI 러너는 Server 판이다). 글꼴 이름은 UI
    언어에 따라 현지화되어(`맑은 고딕`·`Malgun Gothic`) 넣지 않는다 — 글꼴이 없으면 게임이 뜨지
    않는다."""
    version = sys.getwindowsversion()
    if not _spi_uint(SPI_GETFONTSMOOTHING):
        smoothing = "off"
    elif _spi_uint(SPI_GETFONTSMOOTHINGTYPE) == FE_FONTSMOOTHINGCLEARTYPE:
        smoothing = "cleartype"
    else:
        smoothing = "standard"
    return {
        "windows_build": version.build,
        "windows_edition": "workstation" if version.product_type == 1 else "server",
        "dpi": int(ready["dpi"]),
        "font_smoothing": smoothing,
    }


def game_code_digest() -> str:
    """화면 PNG가 따르는 게임 코드(`sample_game/*.py`)와 찍는 조건의 SHA-256. 줄 끝은 LF로 맞춘다
    (체크아웃 설정에 따라 CRLF가 된다)."""
    digest = hashlib.sha256()
    for path in sorted((GAME_DIR / "sample_game").glob("*.py")):
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    digest.update(json.dumps(SNAP_OPTIONS).encode())
    return digest.hexdigest()


def read_frames_snapshot(path: Path | None = None) -> dict[str, Any]:
    """화면 PNG 기록 (`path` 기본은 `FRAMES_SNAPSHOT`): `renderer`와 장면별 찍은 때의 게임 코드
    해시 `scenes`."""
    path = FRAMES_SNAPSHOT if path is None else path
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("format") != FRAMES_SNAPSHOT_FORMAT
        or not isinstance(data.get("renderer"), dict)
        or not isinstance(data.get("scenes"), dict)
    ):
        raise ValueError(f"{path}: {FRAMES_SNAPSHOT_FORMAT} 형식(renderer·scenes)이 아니다")
    return data


def write_frames_snapshot(
    renderer: Mapping[str, Any], scenes: Iterable[str], path: Path | None = None
) -> None:
    """방금 찍은 `scenes`만 지금 게임 코드 해시로 기록한다. 찍지 않은 장면은 예전 해시를 그대로
    두어 코드가 바뀌었으면 계속 오래된 것으로 남는다(일부만 다시 찍어 나머지를 인증하지 않게).
    렌더러가 기록과 다르면 예전 장면 기록은 버린다 — 다른 렌더러의 PNG는 같은 기준이 아니다."""
    path = FRAMES_SNAPSHOT if path is None else path
    recorded: dict[str, str] = {}
    if path.exists():
        before = read_frames_snapshot(path)
        if before["renderer"] == dict(renderer):
            recorded = dict(before["scenes"])
    digest = game_code_digest()
    recorded.update(dict.fromkeys(scenes, digest))
    body = {
        "format": FRAMES_SNAPSHOT_FORMAT,
        "renderer": dict(renderer),
        "scenes": dict(sorted(recorded.items())),
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stale_frames(scenes: Iterable[str]) -> list[str]:
    """찍은 때의 게임 코드 해시가 지금과 다르거나 기록이 없는 장면."""
    recorded = read_frames_snapshot()["scenes"]
    digest = game_code_digest()
    return [scene for scene in scenes if recorded.get(scene) != digest]


def copy_example_workspace(
    dest: Path, local: Mapping[str, Any] | None = None, *, redact_secrets: bool = False
) -> Path:
    """예제 워크스페이스를 `dest/sample-game/workspace`로(화면 PNG는 옆 `frames`로) 복사하고
    `.kookabug/local.json`(기본 `EXAMPLE_LOCAL`)을 쓴다. 복사한 워크스페이스 루트를 돌려준다.

    실행 기록(`runs/`)이 레포에 생기지 않게 복사해서 돌린다. 가짜 플랫폼 사양
    (`fake-platform.json`)의 장면 표 경로 `../frames/scenario.json`이 복사본에서도 맞는다.
    `redact_secrets`면 사본의 `kookabug.json`에만 `record.redact_secrets: true`를 넣는다(비밀값
    가림을 검사할 때 — 예제 원본은 기본값, 가리지 않음).
    """
    root = dest / "sample-game"
    ignore = shutil.ignore_patterns("runs", ".kookabug")
    shutil.copytree(WORKSPACE_DIR, root / "workspace", ignore=ignore)
    shutil.copytree(FRAMES_DIR, root / "frames")
    ws = root / "workspace"
    path = ws / ".kookabug" / "local.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = dict(EXAMPLE_LOCAL if local is None else local)
    body = {"format": "kookabug.local/0", "settings": settings}
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    if redact_secrets:
        config_path = ws / "kookabug.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["record"] = {**config.get("record", {}), "redact_secrets": True}
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return ws
