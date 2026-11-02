"""시작 메뉴 바로 가기(.lnk) 읽기·쓰기 — 셸의 IShellLinkW(유니코드)를 ctypes로 부른다.

WScript.Shell의 `CreateShortcut(...).TargetPath`는 시스템 ANSI 코드 페이지를 거쳐, 그 코드 페이지에
없는 글자(예: cp1252 러너의 한글)를 `?`로 바꿔 돌려준다. 바로 가기 자체는 유니코드로 저장되어 있어도
검사가 틀리게 실패하므로 W 인터페이스로 직접 읽는다.
"""

from __future__ import annotations

import ctypes
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any, Final

_ole32 = ctypes.OleDLL("ole32")

_CLSID_SHELL_LINK: Final = uuid.UUID("00021401-0000-0000-C000-000000000046")
_IID_ISHELL_LINK_W: Final = uuid.UUID("000214F9-0000-0000-C000-000000000046")
_IID_IPERSIST_FILE: Final = uuid.UUID("0000010B-0000-0000-C000-000000000046")
_CLSCTX_INPROC_SERVER: Final = 1
_COINIT_APARTMENTTHREADED: Final = 2
_RPC_E_CHANGED_MODE: Final = -2147417850  # 0x80010106: 이 스레드가 이미 다른 모드로 초기화됨
_STGM_READ: Final = 0
_MAX_PATH_W: Final = 32768
# MS-SHLLINK ShellLinkHeader: 크기 0x4C, LinkFlags는 0x14, IsUnicode는 그 0x80
_LINK_HEADER_SIZE: Final = 0x4C
_LINK_FLAGS_AT: Final = 0x14
_IS_UNICODE: Final = 0x80

# vtable 순서 (IUnknown 0~2 뒤)
_RELEASE: Final = 2
_QUERY_INTERFACE: Final = 0
_LINK_GET_PATH: Final = 3
_LINK_GET_ICON_LOCATION: Final = 16
_LINK_SET_ICON_LOCATION: Final = 17
_LINK_SET_PATH: Final = 20
_FILE_LOAD: Final = 5
_FILE_SAVE: Final = 6


def _guid(value: uuid.UUID) -> Any:
    return (ctypes.c_byte * 16).from_buffer_copy(value.bytes_le)


def _method(obj: ctypes.c_void_p, index: int, *argtypes: Any) -> Any:
    """COM 객체 `obj`의 vtable `index`번 메서드 (HRESULT 반환, 실패면 OSError)."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(obj, *args)


def _release(obj: ctypes.c_void_p) -> None:
    if obj:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtbl[_RELEASE])(obj)


@contextmanager
def _com() -> Iterator[None]:
    try:
        _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    except OSError as exc:
        if exc.winerror != _RPC_E_CHANGED_MODE:
            raise
        yield  # 이미 MTA로 초기화된 스레드: ShellLink는 그대로 쓸 수 있고 해제는 남의 몫
        return
    try:
        yield
    finally:
        _ole32.CoUninitialize()


@contextmanager
def _shell_link() -> Iterator[tuple[ctypes.c_void_p, ctypes.c_void_p]]:
    """(IShellLinkW, IPersistFile) 한 쌍."""
    with _com():
        link = ctypes.c_void_p()
        _ole32.CoCreateInstance(
            _guid(_CLSID_SHELL_LINK),
            None,
            _CLSCTX_INPROC_SERVER,
            _guid(_IID_ISHELL_LINK_W),
            ctypes.byref(link),
        )
        persist = ctypes.c_void_p()
        try:
            _method(link, _QUERY_INTERFACE, ctypes.c_void_p, ctypes.c_void_p)(
                _guid(_IID_IPERSIST_FILE), ctypes.byref(persist)
            )
            yield link, persist
        finally:
            _release(persist)
            _release(link)


def read_shortcut(link_file: Path) -> tuple[str, str]:
    """.lnk의 (대상 경로, 아이콘 위치 `"<경로>,<번호>"`) — WScript.Shell과 같은 모양."""
    with _shell_link() as (link, persist):
        _method(persist, _FILE_LOAD, wintypes.LPCWSTR, wintypes.DWORD)(str(link_file), _STGM_READ)
        target = ctypes.create_unicode_buffer(_MAX_PATH_W)
        get_path = _method(
            link, _LINK_GET_PATH, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        )
        get_path(target, _MAX_PATH_W, None, 0)
        icon = ctypes.create_unicode_buffer(_MAX_PATH_W)
        index = ctypes.c_int()
        _method(link, _LINK_GET_ICON_LOCATION, wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p)(
            icon, _MAX_PATH_W, ctypes.byref(index)
        )
        return target.value, f"{icon.value},{index.value}"


def is_unicode(link_file: Path) -> bool:
    """MS-SHLLINK 머리의 `IsUnicode` 표시. 꺼져 있으면 문자열이 만든 PC의 ANSI 코드 페이지로
    저장되어 다른 로캘에서 한글 경로가 깨진다."""
    head = link_file.read_bytes()[:_LINK_HEADER_SIZE]
    if len(head) < _LINK_HEADER_SIZE or head[:4] != _LINK_HEADER_SIZE.to_bytes(4, "little"):
        return False
    return bool(int.from_bytes(head[_LINK_FLAGS_AT : _LINK_FLAGS_AT + 4], "little") & _IS_UNICODE)


def write_shortcut(link_file: Path, target: Path, icon: Path, icon_index: int = 0) -> None:
    """유니코드 .lnk를 만든다 (NSIS CreateShortCut과 같은 IShellLinkW 경로, 검사용)."""
    with _shell_link() as (link, persist):
        _method(link, _LINK_SET_PATH, wintypes.LPCWSTR)(str(target))
        _method(link, _LINK_SET_ICON_LOCATION, wintypes.LPCWSTR, ctypes.c_int)(
            str(icon), icon_index
        )
        _method(persist, _FILE_SAVE, wintypes.LPCWSTR, wintypes.BOOL)(str(link_file), True)
