"""ctypes 바인딩 공용 도구."""

from __future__ import annotations

import ctypes
from typing import Any

__all__ = ["bind", "last_error_text"]


def bind(dll: Any, name: str, restype: Any, *argtypes: Any) -> Any:
    fn = getattr(dll, name)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


def last_error_text(code: int | None = None) -> str:
    """`Win32 오류 N: 설명` (기본은 이 스레드의 마지막 오류)."""
    if code is None:
        code = ctypes.get_last_error()
    return f"Win32 오류 {code}: {ctypes.FormatError(code).strip()}"
