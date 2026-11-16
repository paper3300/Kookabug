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
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from kookabug_core.win import Job, Process, ProcessId
from kookabug_platform.errors import LAUNCH_FAILED, PlatformError
from kookabug_platform.win32 import kernel32, user32
from kookabug_platform.win32._ffi import last_error_text
from kookabug_platform.win32.api import DEFAULT_API, WindowApi
from kookabug_platform.windows import find_window

__all__ = [
    "GameFamily",
    "candidate_pids",
    "close",
    "family",
    "launch",
    "live_created",
    "parent_pids",
    "process_windows",
    "wait_window",
]

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


class _ProcessEntry(ctypes.Structure):
    _fields_ = (
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    )


_TH32CS_SNAPPROCESS: Final = 0x00000002
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
_k32.Process32FirstW.restype = wintypes.BOOL
_k32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
_k32.Process32NextW.restype = wintypes.BOOL
_k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ProcessEntry))
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)
_INVALID_HANDLE: Final = wintypes.HANDLE(-1).value


def parent_pids() -> dict[int, int]:
    """지금 모든 프로세스의 PID → 부모 PID (Toolhelp 스냅샷). 못 읽으면 빈 표."""
    snap = _k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE:
        return {}
    out: dict[int, int] = {}
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return out


def live_created(pid: int) -> int | None:
    """그 PID를 지금 쥔 **살아 있는** 프로세스의 생성 시각. 없거나 끝났거나 열 수 없으면 None."""
    try:
        with Process.open(pid) as proc:
            return proc.created if proc.alive() else None
    except Exception:
        return None


@dataclass
class GameFamily:
    """게임 하나의 가족 기록 (UX9 3 — 따라가기 소유 범위). 처음 정체(`root`)와 확인된 자손들
    (각각 PID+생성 시각)만이 그 게임이다. 사후 추정으로 넓히지 않는다.

    - `pending`: 직전 확인에서 한 번 본 자손 후보 (다음 확인에서 같은 정체로 다시 보면 기록)
    - `refused`: 정체가 바뀐 것을 본 PID (기록한 자손이 끝났거나 후보의 생성 시각이 달라짐 — PID
      재사용). 다시 더하지 않는다
    """

    root: ProcessId
    members: dict[int, ProcessId] = field(default_factory=dict[int, ProcessId])
    pending: dict[int, ProcessId] = field(default_factory=dict[int, ProcessId])
    refused: set[int] = field(default_factory=set[int])


def family(
    root: ProcessId | GameFamily,
    root_alive: bool,
    *,
    parents: Callable[[], Mapping[int, int]] = parent_pids,
    created: Callable[[int], int | None] = live_created,
) -> list[ProcessId]:
    """그 게임의 가족 기록을 한 번 확인·갱신하고, 지금 살아 있는 가족(원래 프로세스가 먼저)을
    돌려준다 (UX9 3). `root`가 `GameFamily`면 그 기록을 고쳐 쓴다(`ProcessId`면 이번만 쓰는
    새 기록).

    새 자손은 이 확인 안에서 다음을 모두 만족할 때만 기록에 더한다 — 하나라도 못 하면 이번에는
    더하지 않는다:
    1. 부모(이미 가족이고 살아 있는 프로세스)의 정체가 스냅샷 **전과 후** 모두 같은 생성 시각
    2. 자식의 생성 시각을 스냅샷 뒤 두 번 읽어 같고, 부모 생성 시각 이상
    3. 직전 확인에서 같은 부모 밑 같은 정체로 이미 본 후보 (연속 두 번 — 스냅샷과 생성 시각 읽기
       사이에 PID가 재사용됐으면 다음 스냅샷에서 부모가 달라지거나 생성 시각이 달라 걸린다)

    부모가 끝났거나 정체를 모르면 그 밑으로는 더하지 않는다. 이미 기록한 가족은 각자 정체가 맞으면
    계속 유효하고, 끝난 가족의 PID는 다시 받지 않는다. 실행 Job 전체가 아니다. `created`는 그
    PID를 쥔 살아 있는 프로세스의 생성 시각(없으면 None)."""
    record = root if isinstance(root, GameFamily) else GameFamily(root)
    origin = record.root

    def live(ident: ProcessId) -> bool:
        return created(ident.pid) == ident.created

    root_ok = root_alive and live(origin)
    # 1. 스냅샷 전: 부모가 될 수 있는 가족 (살아 있는 것만)
    before = ([origin] if root_ok else []) + [m for m in record.members.values() if live(m)]
    table = parents()
    children: dict[int, list[int]] = {}
    for pid, ppid in table.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    pending: dict[int, ProcessId] = {}
    for parent in before:
        if not live(parent):  # 스냅샷 뒤에도 같은 정체로 살아 있어야 그 밑 자식을 믿는다
            continue
        for pid in children.get(parent.pid, ()):
            if pid == origin.pid or pid in record.members or pid in record.refused:
                continue
            first, second = created(pid), created(pid)
            if first is None or first != second or first < parent.created:
                continue
            seen = record.pending.get(pid)
            if seen is None:
                pending[pid] = ProcessId(pid, first)
            elif seen.created != first:
                record.refused.add(pid)  # 같은 PID의 정체가 바뀌었다 (재사용)
            else:
                record.members[pid] = seen
    record.pending = pending
    alive = [origin] if root_ok else []
    for pid, member in list(record.members.items()):
        if live(member):
            alive.append(member)
        else:
            # 끝난 자손: 기록에서 빼고 그 PID는 다시 받지 않는다 (재사용된 PID가 끼지 않게)
            del record.members[pid]
            record.refused.add(pid)
    return alive


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
