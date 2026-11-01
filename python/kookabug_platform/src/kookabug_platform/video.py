"""Media Foundation H.264 MP4 인코더 (구현 계획 M3 2.5, 조율자 결정 Q1).

OpenCV `cv2.VideoWriter`의 **MSMF 백엔드**(Windows Media Foundation)로 H.264 MP4(`avc1`)를 쓴다.
백엔드 코드는 이미 감사한 `cv2.pyd`에 있고 인코더는 OS 구성요소다(배포하지 않음). FFmpeg 백엔드로
넘어가지 않게 `cv2.CAP_MSMF`를 명시한다(설치본은 `opencv_videoio_ffmpeg*.dll`을 빼고 배포한다).

Media Foundation이 없는 Windows(N·KN 판에서 미디어 기능 팩 없음, Server Core)에서도 이 모듈의
import는 실패하지 않는다. 인코더는 녹화를 시작할 때만 연다(`MsmfFactory.probe`): MF DLL 로드 실패는
`mf_missing`, OpenCV에 MSMF 쓰기 백엔드가 없으면 `backend_missing`, 열기 실패는
`encoder_open_failed`. 그때 실행은 영상 없이 돈다.

`probe_media()`는 "MF H.264 인코더가 등록돼 있는가"를 `MFTEnumEx`로 명시적으로 탐지한다(검사의
건너뛰기 조건, `kookabug doctor` "영상 인코더" 항목).
"""

from __future__ import annotations

import contextlib
import ctypes
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from kookabug_core.record.video import (
    FPS,
    Encoder,
    EncoderUnavailable,
    VideoFrame,
)

__all__ = [
    "FOURCC",
    "MF_DLLS",
    "MediaProbe",
    "MsmfEncoder",
    "MsmfFactory",
    "probe_media",
]

MF_DLLS: Final = ("mfplat.dll", "mfreadwrite.dll")
"""Media Foundation 핵심 DLL (없으면 `mf_missing`)."""
FOURCC: Final = "avc1"
PROBE_FILE: Final = ".probe.mp4"
_PROBE_SIZE: Final = (64, 64)


def _cv2() -> Any:
    import cv2  # 무거운 의존성은 쓸 때만 (MF·OpenCV가 없어도 이 모듈은 불러온다)

    return cv2


@dataclass(frozen=True, slots=True)
class MsmfFactory:
    """MSMF 조각 인코더 공장. 숨은 검사 설정(`KOOKABUG_VIDEO_TEST`의 `msmf`)으로 DLL 이름·백엔드·
    FourCC를 바꿔 사용 불가 경로를 실제 코드로 시험한다."""

    mf_dlls: tuple[str, ...] = MF_DLLS
    backend: int | None = None
    """쓰기 백엔드 번호 (None = `cv2.CAP_MSMF`)."""
    fourcc: str = FOURCC

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> MsmfFactory:
        return cls(
            mf_dlls=tuple(data.get("mf_dlls", MF_DLLS)),
            backend=data.get("backend"),
            fourcc=str(data.get("fourcc", FOURCC)),
        )

    def check(self) -> int:
        """MF DLL과 OpenCV MSMF 쓰기 백엔드를 확인하고 백엔드 번호를 돌려준다."""
        for name in self.mf_dlls:
            try:
                ctypes.WinDLL(name)
            except OSError as exc:
                raise EncoderUnavailable("mf_missing", f"{name}을(를) 읽을 수 없다: {exc}") from exc
        try:
            cv2 = _cv2()
        except ImportError as exc:
            raise EncoderUnavailable("backend_missing", f"OpenCV가 없다: {exc}") from exc
        backend = cv2.CAP_MSMF if self.backend is None else self.backend
        writers = list(cv2.videoio_registry.getWriterBackends())
        if backend not in writers:
            raise EncoderUnavailable(
                "backend_missing", f"OpenCV에 MSMF 쓰기 백엔드가 없다 (백엔드 {backend})"
            )
        return int(backend)

    def probe(self, folder: Path) -> None:
        """`folder` 안 임시 파일로 인코더를 열어 한 장 써 본다."""
        backend = self.check()
        path = folder / PROBE_FILE
        try:
            encoder = self._open(path, _PROBE_SIZE, backend)
            np = _numpy()
            encoder.write(VideoFrame(np.zeros((64, 64, 3), np.uint8), _PROBE_SIZE, 0.0))
            encoder.release()
        except EncoderUnavailable:
            raise
        except Exception as exc:
            raise EncoderUnavailable("encoder_open_failed", f"{type(exc).__name__}: {exc}") from exc
        finally:
            with contextlib.suppress(OSError):
                path.unlink()

    def open(self, path: Path, size: tuple[int, int]) -> Encoder:
        return self._open(path, size, self.check())

    def _open(self, path: Path, size: tuple[int, int], backend: int) -> MsmfEncoder:
        cv2 = _cv2()
        writer = cv2.VideoWriter(
            str(path), backend, cv2.VideoWriter.fourcc(*self.fourcc[:4].ljust(4)), FPS, size
        )
        if not writer.isOpened():
            writer.release()
            raise EncoderUnavailable(
                "encoder_open_failed",
                f"MSMF H.264 인코더를 열 수 없다 ({self.fourcc}, {size[0]}x{size[1]})",
            )
        return MsmfEncoder(writer, size)


def _numpy() -> Any:
    import numpy

    return numpy


class MsmfEncoder:
    """조각 하나. 프레임은 BGR(또는 BGRA)이고 크기가 다르면 줄여 맞춘다."""

    def __init__(self, writer: Any, size: tuple[int, int]) -> None:
        self._writer = writer
        self._size = size

    def write(self, frame: VideoFrame) -> None:
        cv2 = _cv2()
        np = _numpy()
        pixels = frame.pixels
        if pixels is None:
            raise ValueError("녹화 프레임에 픽셀이 없다")
        if pixels.ndim == 3 and pixels.shape[2] == 4:
            pixels = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
        elif pixels.ndim == 2:
            pixels = cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR)
        w, h = self._size
        if pixels.shape[1] != w or pixels.shape[0] != h:
            pixels = cv2.resize(pixels, (w, h), interpolation=cv2.INTER_AREA)
        self._writer.write(np.ascontiguousarray(pixels))

    def release(self) -> None:
        self._writer.release()


# ---------------------------------------------------------------- 명시적 탐지


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def of(cls, text: str) -> _GUID:
        import uuid

        raw = uuid.UUID(text).bytes_le
        return cls.from_buffer_copy(raw)


class _TypeInfo(ctypes.Structure):
    _fields_ = (("guidMajorType", _GUID), ("guidSubtype", _GUID))


_MFT_CATEGORY_VIDEO_ENCODER: Final = "f79eac7d-e545-4387-bdee-d647d7bde42a"
_MF_MEDIATYPE_VIDEO: Final = "73646976-0000-0010-8000-00aa00389b71"
_MF_VIDEOFORMAT_H264: Final = "34363248-0000-0010-8000-00aa00389b71"
_MFT_ENUM_FLAG_ALL: Final = 0x3F


@dataclass(frozen=True, slots=True)
class MediaProbe:
    """MF H.264 인코더 탐지 결과. `available`이 False면 `reason`(`mf_missing`·
    `h264_encoder_missing`·`backend_missing`)과 설명."""

    available: bool
    reason: str | None
    detail: str
    encoders: int = 0


def probe_media(mf_dlls: tuple[str, ...] = MF_DLLS) -> MediaProbe:
    """Media Foundation H.264 인코더(MFT)가 등록돼 있는가 (`MFTEnumEx`). 파일을 쓰지 않는다."""
    try:
        for name in mf_dlls:
            ctypes.WinDLL(name)
        mfplat = ctypes.WinDLL("mfplat.dll")
    except OSError as exc:
        return MediaProbe(False, "mf_missing", f"Media Foundation DLL을 읽을 수 없다: {exc}")
    enum = mfplat.MFTEnumEx
    enum.restype = ctypes.HRESULT
    enum.argtypes = (
        _GUID,
        ctypes.c_uint32,
        ctypes.POINTER(_TypeInfo),
        ctypes.POINTER(_TypeInfo),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ctypes.POINTER(ctypes.c_uint32),
    )
    output = _TypeInfo(_GUID.of(_MF_MEDIATYPE_VIDEO), _GUID.of(_MF_VIDEOFORMAT_H264))
    found = ctypes.POINTER(ctypes.c_void_p)()
    count = ctypes.c_uint32(0)
    try:
        enum(
            _GUID.of(_MFT_CATEGORY_VIDEO_ENCODER),
            _MFT_ENUM_FLAG_ALL,
            None,
            ctypes.byref(output),
            ctypes.byref(found),
            ctypes.byref(count),
        )
    except OSError as exc:
        return MediaProbe(False, "h264_encoder_missing", f"MFTEnumEx 실패: {exc}")
    _release_all(found, count.value)
    if count.value == 0:
        return MediaProbe(
            False, "h264_encoder_missing", "Media Foundation H.264 인코더가 등록돼 있지 않다"
        )
    try:
        cv2 = _cv2()
        if cv2.CAP_MSMF not in list(cv2.videoio_registry.getWriterBackends()):
            return MediaProbe(False, "backend_missing", "OpenCV에 MSMF 쓰기 백엔드가 없다")
    except ImportError as exc:
        return MediaProbe(False, "backend_missing", f"OpenCV가 없다: {exc}")
    return MediaProbe(
        True, None, f"Media Foundation H.264 인코더 {count.value}개", encoders=count.value
    )


def _release_all(found: Any, count: int) -> None:
    """`IMFActivate` 배열의 각 항목을 `Release`하고 배열을 `CoTaskMemFree`한다."""
    if not found:
        return
    release_type = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    for i in range(count):
        item = found[i]
        if not item:
            continue
        vtable = ctypes.cast(item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = release_type(vtable[2])
        release(item)
    ole32 = ctypes.WinDLL("ole32.dll")
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    ole32.CoTaskMemFree.restype = None
    ole32.CoTaskMemFree(ctypes.cast(found, ctypes.c_void_p))


def summary() -> str:
    """탐지 결과 Markdown (CI 잡 요약: `python -m kookabug_platform.video`)."""
    found = probe_media()
    state = "사용 가능" if found.available else f"없음 ({found.reason})"
    return f"### 영상 인코더\n\n- {state}: {found.detail}\n"


def main() -> int:
    from kookabug_sdk.console import utf8_stdio

    utf8_stdio()
    print(summary(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
