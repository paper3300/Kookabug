"""여러 프로세스가 같은 파일 끝에 덧붙이기.

CRT의 `O_APPEND`(`os.open`)는 쓰기마다 "끝으로 이동 → 쓰기"를 따로 해서 두 프로세스의 줄이 서로
덮어쓸 수 있다. `FILE_APPEND_DATA` 권한만으로 연 핸들의 `WriteFile`은 OS가 파일 끝에 한 번에 붙인다.
"""

from __future__ import annotations

import ctypes
import os

from kookabug_core.win import _kernel32 as k

__all__ = ["append_bytes"]


def append_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """`data`를 파일 끝에 한 번의 쓰기로 붙인다 (없으면 만든다)."""
    handle = k.CreateFileW(
        os.fspath(path),
        k.FILE_APPEND_DATA,
        k.FILE_SHARE_ALL,
        None,
        k.OPEN_ALWAYS,
        k.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle is None or handle == k.INVALID_HANDLE_VALUE:
        raise k.win_error(f"CreateFileW({os.fspath(path)})")
    try:
        written = k.DWORD()
        k.check(k.WriteFile(handle, data, len(data), ctypes.byref(written), None), "WriteFile")
        if written.value != len(data):
            raise OSError(f"덧붙이기가 끝까지 되지 않았다: {written.value}/{len(data)}바이트")
    finally:
        k.CloseHandle(handle)
