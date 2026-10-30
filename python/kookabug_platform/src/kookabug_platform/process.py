"""게임 프로세스 띄우기·닫기와 그 창 찾기 (구현 계획 M1 2.2, 3장 "프로세스 정리").

**띄우기**는 `CreateProcessW`다. runner는 실행 Job 안에 있고 Job에 `BREAKAWAY_OK`가 없으므로, 여기서
띄운 게임(과 그 자식)은 **생성 시점부터 실행 Job 소속**이고 실행이 끝나면 Job과 함께 정리된다.
핸들은 물려주지 않는다(`bInheritHandles=FALSE`), 콘솔 창은 띄우지 않는다(`CREATE_NO_WINDOW` —
GUI 게임에는 영향 없음).

**창 찾기**: 런처형 게임은 띄운 프로세스가 아닌 자식이 창을 만든다. 그래서 띄운 게임의 창은 실행
Job 안 모든 프로세스(`JobObjectBasicProcessIdList`)의 창에서 찾는다(`candidate_pids`).

**닫기**: 그 프로세스의 보이는 최상위 창에 `WM_CLOSE` → `force_after_ms` 기다림 →
`TerminateProcess`.
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final

from kookabug_core.win import Job, Process
from kookabug_platform.errors import LAUNCH_FAILED, PlatformError
from kookabug_platform.win32 import kernel32, user32
from kookabug_platform.win32._ffi import last_error_text
from kookabug_platform.win32.api import DEFAULT_API, WindowApi
from kookabug_platform.windows import find_window

__all__ = ["candidate_pids", "close", "launch", "process_windows", "wait_window"]

_POLL_S: Final = 0.05
FORCE_EXIT_CODE: Final = 1


def _environment_block(env: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    """`이름=값\\0…\\0` 유니코드 환경 블록. 이름순 정렬(대소문자 무시)이 Win32 규칙이다.

    크기는 `create_unicode_buffer`가 UTF-16 코드 단위로 센다(비 BMP 글자는 둘). 파이썬 `len`으로
    잡으면 이모지 같은 글자에서 버퍼가 모자란다. 끝에 붙는 NUL 하나 덕에 빈 환경도 `\\0\\0`이다.
    """
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    return ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in items) + "\0")


def launch(
    path: str | Path,
    args: Sequence[str] = (),
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Process:
    """프로세스를 띄운다. 열린 핸들(`Process`: `pid`·`created`·`wait`·`terminate`)을 돌려준다.

    실패(파일 없음·실행 파일 아님·권한 상승 필요 등)는 `launch_failed`.
    """
    command = subprocess.list2cmdline([str(path), *args])
    cmdline = ctypes.create_unicode_buffer(command)  # CreateProcessW가 고쳐 쓸 수 있는 버퍼
    startup = kernel32.STARTUPINFOW()
    startup.cb = ctypes.sizeof(startup)
    info = kernel32.PROCESS_INFORMATION()
    flags = kernel32.CREATE_NO_WINDOW
    block = None
    if env is not None:
        block = _environment_block(env)
        flags |= kernel32.CREATE_UNICODE_ENVIRONMENT
    ok = kernel32.CreateProcessW(
        None,
        cmdline,
        None,
        None,
        False,
        flags,
        block,
        None if cwd is None else str(cwd),
        ctypes.byref(startup),
        ctypes.byref(info),
    )
    if not ok:
        raise PlatformError(LAUNCH_FAILED, f"{command}을 띄울 수 없다: {last_error_text()}")
    kernel32.CloseHandle(info.hThread)
    try:
        return Process(info.hProcess, info.dwProcessId)
    except BaseException:
        kernel32.CloseHandle(info.hProcess)
        raise


def candidate_pids(process: Process | int, job: Job | None = None) -> list[int]:
    """그 프로세스의 창을 찾을 PID들: 실행 Job이 있으면 Job 안 전부(띄운 프로세스가 먼저)."""
    pid = process if isinstance(process, int) else process.pid
    pids = [pid]
    if job is not None:
        pids += [p for p in job.process_ids() if p != pid]
    return pids


def wait_window(
    pids: Callable[[], Sequence[int]],
    *,
    title: str | None = None,
    timeout: float,
    should_stop: Callable[[], bool] | None = None,
    api: WindowApi = DEFAULT_API,
) -> int | None:
    """PID들의 보이는 최상위 창(제목 조건)을 기다린다. 기한·중단이면 None.

    `pids`는 매번 다시 부른다(런처가 기다리는 동안 게임을 띄우므로).
    """
    deadline = time.monotonic() + timeout
    while True:
        hwnd = find_window(title=title, pids=pids(), api=api)
        if hwnd is not None:
            return hwnd
        if time.monotonic() >= deadline or (should_stop is not None and should_stop()):
            return None
        time.sleep(min(_POLL_S, max(0.0, deadline - time.monotonic())))


def process_windows(pid: int, api: WindowApi = DEFAULT_API) -> list[int]:
    """그 프로세스의 보이는 소유자 없는 최상위 창들."""
    return [
        h
        for h in api.top_level_windows()
        if api.window_pid(h) == pid and api.is_visible(h) and not api.owner(h)
    ]


def close(process: Process, force_after_ms: int, *, api: WindowApi = DEFAULT_API) -> bool:
    """정상 종료를 청하고(`WM_CLOSE`), `force_after_ms` 안에 안 끝나면 강제로 끝낸다.

    `WM_CLOSE`로 끝났으면(또는 이미 끝나 있었으면) True, 강제로 끝냈으면 False. 보낼 창이 없으면
    기다리지 않고 바로 강제 종료한다.
    """
    if not process.alive():
        return True
    windows = process_windows(process.pid, api)
    for hwnd in windows:
        user32.PostMessageW(hwnd, user32.WM_CLOSE, 0, 0)
    if windows and process.wait(max(0, force_after_ms) / 1000) is not None:
        return True
    process.terminate(FORCE_EXIT_CODE)
    process.wait(5)
    return False
