"""상점 그림: Windows GDI 오프스크린 렌더 → PNG 바이트 (창 없음, 같은 상태 = 같은 그림).

글꼴 `Malgun Gothic`(회색조 안티앨리어싱 고정 — 클리어타입 설정과 무관), 글자 크기는 픽셀 단위.
PNG는 표준 라이브러리(zlib)로 쓴다. 같은 Windows 판·같은 글꼴 파일이면 바이트까지 같다
(`frames/shop/frames.snapshot.json`에 찍은 환경을 남긴다).
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import zlib
from ctypes import wintypes
from pathlib import Path
from typing import Final

from sample_shop import CLIENT_SIZE
from sample_shop.flow import BUTTONS, CONSOLE_FIELD, Rect, Shop

__all__ = ["FONT", "FontMissing", "font_file", "png_of", "render"]

FONT: Final = "Malgun Gothic"
_FONT_FILE: Final = "malgun.ttf"

BG: Final = 0x1C2433
PANEL: Final = 0x2B3548
EDGE: Final = 0x4A5875
TEXT: Final = 0xF2F4F8
MUTED: Final = 0x9AA6BD
GOLD: Final = 0xF0C040
BUY: Final = 0x2F7DE1
SELL: Final = 0x3A86D6
"""판매는 구매와 같은 모양·옅게 다른 색 (음성 대조: 구매 target이 판매 단추에 맞지 않아야 한다)."""
CLOSE: Final = 0x5A6478
CHARGE: Final = 0x8E5BD9
POTION: Final = 0xD94A4A
DIM: Final = 0x0B0F16
CONSOLE: Final = 0x0E1218


class FontMissing(RuntimeError):
    """`Malgun Gothic` 글꼴이 없다 (예제 게임과 같은 전제)."""


def font_file() -> Path:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    path = Path(windir) / "Fonts" / _FONT_FILE
    if not path.is_file():
        raise FontMissing(f"글꼴 파일이 없다: {path}")
    return path


# ---------------------------------------------------------------- GDI


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _gdi() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle = ctypes.c_void_p
    for name, args in {
        "CreateCompatibleDC": [handle],
        "CreateDIBSection": [
            handle,
            ctypes.POINTER(_BITMAPINFOHEADER),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            handle,
            wintypes.DWORD,
        ],
        "SelectObject": [handle, handle],
        "DeleteObject": [handle],
        "DeleteDC": [handle],
        "CreateSolidBrush": [wintypes.DWORD],
        "CreatePen": [ctypes.c_int, ctypes.c_int, wintypes.DWORD],
        "GetStockObject": [ctypes.c_int],
        "RoundRect": [
            handle,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ],
        "Ellipse": [handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
        "SetTextColor": [handle, wintypes.DWORD],
        "SetBkMode": [handle, ctypes.c_int],
        "GdiFlush": [],
        "CreateFontW": [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR],
    }.items():
        fn = getattr(gdi32, name)
        fn.argtypes = args
        fn.restype = (
            handle if name not in ("SetBkMode", "GdiFlush", "SetTextColor") else ctypes.c_int
        )
    user32.FillRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT), ctypes.c_void_p]
    user32.FillRect.restype = ctypes.c_int
    user32.DrawTextW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.RECT),
        wintypes.UINT,
    ]
    user32.DrawTextW.restype = ctypes.c_int
    return gdi32, user32


def _ref(rgb: int) -> int:
    """0xRRGGBB → COLORREF(0x00BBGGRR)."""
    return ((rgb & 0xFF) << 16) | (rgb & 0xFF00) | ((rgb >> 16) & 0xFF)


_DT_CENTER: Final = 0x1
_DT_VCENTER: Final = 0x4
_DT_SINGLELINE: Final = 0x20
_DT_NOPREFIX: Final = 0x800
_DT_LEFT: Final = 0x0
_ANTIALIASED_QUALITY: Final = 4
_NULL_PEN: Final = 8


class _Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.gdi, self.user = _gdi()
        self.w, self.h = width, height
        self.dc = self.gdi.CreateCompatibleDC(None)
        info = _BITMAPINFOHEADER()
        info.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        info.biWidth, info.biHeight = width, -height  # 위에서 아래로
        info.biPlanes, info.biBitCount = 1, 32
        self.bits = ctypes.c_void_p()
        self.bitmap = self.gdi.CreateDIBSection(
            self.dc, ctypes.byref(info), 0, ctypes.byref(self.bits), None, 0
        )
        if not self.dc or not self.bitmap:
            raise OSError("GDI 오프스크린 비트맵을 만들지 못했다")
        self.gdi.SelectObject(self.dc, self.bitmap)
        self.gdi.SetBkMode(self.dc, 1)  # TRANSPARENT
        self._objects: list[int] = []

    def _keep(self, obj: int) -> int:
        self._objects.append(obj)
        return obj

    def fill(self, rect: Rect, rgb: int) -> None:
        x, y, w, h = rect
        r = wintypes.RECT(x, y, x + w, y + h)
        brush = self._keep(self.gdi.CreateSolidBrush(_ref(rgb)))
        self.user.FillRect(self.dc, ctypes.byref(r), brush)

    def round(self, rect: Rect, rgb: int, edge: int | None = None, radius: int = 12) -> None:
        x, y, w, h = rect
        brush = self._keep(self.gdi.CreateSolidBrush(_ref(rgb)))
        pen = (
            self._keep(self.gdi.CreatePen(0, 2, _ref(edge)))
            if edge is not None
            else self.gdi.GetStockObject(_NULL_PEN)
        )
        self.gdi.SelectObject(self.dc, brush)
        self.gdi.SelectObject(self.dc, pen)
        self.gdi.RoundRect(self.dc, x, y, x + w + 1, y + h + 1, radius, radius)

    def circle(self, cx: int, cy: int, r: int, rgb: int) -> None:
        brush = self._keep(self.gdi.CreateSolidBrush(_ref(rgb)))
        self.gdi.SelectObject(self.dc, brush)
        self.gdi.SelectObject(self.dc, self.gdi.GetStockObject(_NULL_PEN))
        self.gdi.Ellipse(self.dc, cx - r, cy - r, cx + r + 1, cy + r + 1)

    def text(
        self, rect: Rect, text: str, size: int, rgb: int, *, bold: bool = False, center: bool = True
    ) -> None:
        font = self._keep(
            self.gdi.CreateFontW(
                -size,
                0,
                0,
                0,
                700 if bold else 400,
                0,
                0,
                0,
                1,
                0,
                0,
                _ANTIALIASED_QUALITY,
                0,
                FONT,
            )
        )
        self.gdi.SelectObject(self.dc, font)
        self.gdi.SetTextColor(self.dc, _ref(rgb))
        x, y, w, h = rect
        r = wintypes.RECT(x, y, x + w, y + h)
        flags = _DT_VCENTER | _DT_SINGLELINE | _DT_NOPREFIX | (_DT_CENTER if center else _DT_LEFT)
        self.user.DrawTextW(self.dc, text, -1, ctypes.byref(r), flags)

    def rgb_rows(self) -> bytes:
        """위에서 아래로 RGB 바이트 (알파 버림)."""
        self.gdi.GdiFlush()
        raw = ctypes.string_at(self.bits, self.w * self.h * 4)
        out = bytearray(self.w * self.h * 3)
        out[0::3] = raw[2::4]
        out[1::3] = raw[1::4]
        out[2::3] = raw[0::4]
        return bytes(out)

    def close(self) -> None:
        for obj in self._objects:
            self.gdi.DeleteObject(obj)
        self.gdi.DeleteObject(self.bitmap)
        self.gdi.DeleteDC(self.dc)


def png_of(width: int, height: int, rgb: bytes) -> bytes:
    """RGB 8비트 PNG (필터 없음, zlib 9 — 결정적)."""
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------- 장면


def _gold(value: int) -> str:
    return f"{value:,}"


def _draw(c: _Canvas, shop: Shop, *, boot: bool) -> None:
    w, h = CLIENT_SIZE
    c.fill((0, 0, w, h), BG)
    if boot:
        c.text((0, 0, w, h), "상점에 들어가는 중…", 28, MUTED)
        return
    if shop.closed:
        c.text((0, 260, w, 60), "상점을 닫았다", 40, TEXT, bold=True)
        c.text((0, 330, w, 40), "다시 열려면 게임을 다시 시작한다", 20, MUTED)
        return
    c.text((40, 28, 300, 48), "상점", 34, TEXT, bold=True, center=False)
    if shop.layout == "default":
        c.round(BUTTONS["charge"], CHARGE)
        c.text(BUTTONS["charge"], "다이아 충전", 22, TEXT, bold=True)
    # 골드
    c.round((40, 96, 340, 76), PANEL, EDGE)
    c.text((60, 96, 80, 76), "골드", 22, MUTED, center=False)
    c.text((140, 96, 220, 76), _gold(shop.gold), 34, GOLD, bold=True)
    # 상품
    c.round((40, 196, 600, 236), PANEL, EDGE)
    c.circle(120, 300, 44, POTION)
    c.text((190, 236, 420, 48), "체력 물약", 30, TEXT, bold=True, center=False)
    c.text((190, 290, 420, 40), "가격 100골드 · 재고 1", 22, MUTED, center=False)
    # 가방
    c.round((680, 196, 304, 340), PANEL, EDGE)
    c.text((700, 206, 260, 44), "가방", 24, MUTED, center=False)
    c.text((700, 262, 260, 44), f"물약 {shop.potions}", 26, TEXT, center=False)
    if shop.blade:
        c.text((700, 314, 260, 44), "낡은 칼 1", 26, TEXT, center=False)
    # 단추
    buy = {"default": "buy", "moved": "buy_moved", "missing": None}[shop.layout]
    if buy is not None:
        c.round(BUTTONS[buy], BUY)
        c.text(BUTTONS[buy], "구매", 28, TEXT, bold=True)
    c.round(BUTTONS["sell"], SELL)
    c.text(BUTTONS["sell"], "판매", 28, TEXT, bold=True)
    c.round(BUTTONS["close"], CLOSE)
    c.text(BUTTONS["close"], "닫기", 24, TEXT, bold=True)
    notice = {"bought": "구매 완료", "sold": "판매 완료", "cheat": None, None: None}[shop.done]
    if notice is not None:
        c.text((40, 392, 600, 40), notice, 24, GOLD, bold=True)
    if shop.overlay == "confirm":
        c.round((312, 160, 400, 290), PANEL, EDGE, radius=18)
        c.text((312, 184, 400, 50), "다이아 100개", 30, TEXT, bold=True)
        c.text((312, 250, 400, 40), "결제 금액 1,100원", 24, MUTED)
        c.text((312, 296, 400, 40), "정말 결제할까요?", 22, MUTED)
        c.round(BUTTONS["pay"], CHARGE)
        c.text(BUTTONS["pay"], "결제", 26, TEXT, bold=True)
        c.round(BUTTONS["cancel"], CLOSE)
        c.text(BUTTONS["cancel"], "취소", 26, TEXT, bold=True)
    if shop.overlay == "console":
        c.fill((0, 556, w, 84), CONSOLE)
        c.fill(CONSOLE_FIELD, DIM)
        x, y, fw, fh = CONSOLE_FIELD
        c.text((x + 12, y, fw - 24, fh), "> " + shop.command, 22, TEXT, center=False)


def render(shop: Shop, *, boot: bool = False) -> bytes:
    """상태 → PNG 바이트 (1024x640)."""
    w, h = CLIENT_SIZE
    canvas = _Canvas(w, h)
    try:
        _draw(canvas, shop, boot=boot)
        return png_of(w, h, canvas.rgb_rows())
    finally:
        canvas.close()


def font_sha256() -> str:
    return hashlib.sha256(font_file().read_bytes()).hexdigest()
