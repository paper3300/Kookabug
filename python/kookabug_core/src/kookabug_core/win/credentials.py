"""Windows 자격 증명 관리자 (일반 자격 증명, M4 계획 2.8 "자격 증명 관리자 읽기", C11, T7).

비밀값 이름은 `kookabug:<워크스페이스 ID>:<키>`(설계 "워크스페이스 구조" 비밀값). 값은 UTF-16LE
블롭, `CRED_PERSIST_LOCAL_MACHINE`. ctypes만 쓴다 — 코어(실행의 `$secret` 풀기)가 쓰므로 플랫폼
패키지에 두지 않는다. 검사는 다른 접두(`kookabug-test:`)로 만들고 지운다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Final

__all__ = [
    "PREFIX",
    "CredentialError",
    "CredentialSecrets",
    "CredentialStore",
    "available",
]

PREFIX: Final = "kookabug:"
CRED_TYPE_GENERIC: Final = 1
CRED_PERSIST_LOCAL_MACHINE: Final = 2
ERROR_NOT_FOUND: Final = 1168
CRED_MAX_BLOB: Final = 2560


class CredentialError(Exception):
    """자격 증명 관리자 호출이 실패했다 (없음은 오류가 아니다)."""


class _FILETIME(ctypes.Structure):
    _fields_ = (("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD))


class _CREDENTIALW(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


_PCRED = ctypes.POINTER(_CREDENTIALW)


def available() -> bool:
    return sys.platform == "win32"


class _Api:
    def __init__(self) -> None:
        dll = ctypes.WinDLL("advapi32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue,unused-ignore]
        self.read = dll.CredReadW
        self.read.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_PCRED),
        )
        self.read.restype = wintypes.BOOL
        self.write = dll.CredWriteW
        self.write.argtypes = (_PCRED, wintypes.DWORD)
        self.write.restype = wintypes.BOOL
        self.enumerate = dll.CredEnumerateW
        self.enumerate.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(ctypes.POINTER(_PCRED)),
        )
        self.enumerate.restype = wintypes.BOOL
        self.delete = dll.CredDeleteW
        self.delete.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
        self.delete.restype = wintypes.BOOL
        self.free = dll.CredFree
        self.free.argtypes = (ctypes.c_void_p,)
        self.free.restype = None


_api: _Api | None = None


def _get_api() -> _Api:
    global _api
    if not available():
        raise CredentialError("자격 증명 관리자는 Windows에서만 쓸 수 있다")
    if _api is None:
        _api = _Api()
    return _api


def _fail(what: str) -> CredentialError:
    code = ctypes.get_last_error()  # pyright: ignore[reportAttributeAccessIssue,unused-ignore]
    return CredentialError(f"{what} 실패 (Win32 오류 {code})")


class CredentialStore:
    """`<접두><워크스페이스 ID>:<키>` 이름의 일반 자격 증명."""

    def __init__(self, prefix: str = PREFIX) -> None:
        self.prefix = prefix

    def name(self, workspace_id: str, key: str) -> str:
        return f"{self.prefix}{workspace_id}:{key}"

    def read(self, workspace_id: str, key: str) -> str | None:
        api = _get_api()
        out = _PCRED()
        if not api.read(self.name(workspace_id, key), CRED_TYPE_GENERIC, 0, ctypes.byref(out)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:  # pyright: ignore[reportAttributeAccessIssue,unused-ignore]
                return None
            raise _fail("CredReadW")
        try:
            cred = out.contents
            data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            return data.decode("utf-16-le")
        finally:
            api.free(out)

    def write(self, workspace_id: str, key: str, value: str) -> None:
        api = _get_api()
        blob = value.encode("utf-16-le")
        if len(blob) > CRED_MAX_BLOB:
            raise CredentialError("비밀값이 너무 길다")
        buffer = (ctypes.c_ubyte * max(1, len(blob))).from_buffer_copy(blob or b"\0")
        cred = _CREDENTIALW()
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = self.name(workspace_id, key)
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "kookabug"
        try:
            if not api.write(ctypes.byref(cred), 0):
                raise _fail("CredWriteW")
        finally:
            ctypes.memset(buffer, 0, ctypes.sizeof(buffer))

    def keys(self, workspace_id: str) -> list[str]:
        api = _get_api()
        base = self.name(workspace_id, "")
        count = wintypes.DWORD()
        items = ctypes.POINTER(_PCRED)()
        if not api.enumerate(base + "*", 0, ctypes.byref(count), ctypes.byref(items)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:  # pyright: ignore[reportAttributeAccessIssue,unused-ignore]
                return []
            raise _fail("CredEnumerateW")
        try:
            names: list[str] = []
            for i in range(count.value):
                cred = items[i].contents
                if cred.Type == CRED_TYPE_GENERIC and cred.TargetName.startswith(base):
                    names.append(cred.TargetName[len(base) :])
            return sorted(names)
        finally:
            api.free(items)

    def delete(self, workspace_id: str, key: str) -> bool:
        api = _get_api()
        if api.delete(self.name(workspace_id, key), CRED_TYPE_GENERIC, 0):
            return True
        if ctypes.get_last_error() == ERROR_NOT_FOUND:  # pyright: ignore[reportAttributeAccessIssue,unused-ignore]
            return False
        raise _fail("CredDeleteW")


class CredentialSecrets:
    """`SecretProvider`: 워크스페이스 ID의 자격 증명 관리자 비밀값. 읽기 실패는 없음으로 본다
    (없는 비밀값과 같은 실행 오류 경로)."""

    def __init__(self, workspace_id: str, store: CredentialStore | None = None) -> None:
        self.workspace_id = workspace_id
        self.store = store or CredentialStore()

    def get(self, key: str) -> str | None:
        try:
            return self.store.read(self.workspace_id, key)
        except CredentialError:
            return None

    def __repr__(self) -> str:
        return f"CredentialSecrets({self.store.prefix}{self.workspace_id})"
