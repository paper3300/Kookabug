"""플랫폼 오류 코드 (구현 계획 M1 2.2). M1 완료 기준 5의 "정확한 사유"가 이 코드다.

`PlatformError`는 `EngineError`라 실행기에서 그 스텝의 `error`(코드 그대로)가 된다. 메시지에는
대상 창 제목·프로세스와, 포그라운드·가림 판정이면 지금 그 자리에 있는 창을 넣는다.

| 코드 | 뜻 |
|---|---|
| `window_gone` | 대상 창이 닫혔다(바인딩이 죽음·`IsWindow` 거짓·PID나 생성 시각이 다름) |
| `window_minimized` | 대상 창이 최소화돼 있다 |
| `window_not_foreground` | 키보드·글자 대상이 포그라운드가 아니다(대상·그 소유 팝업 아님) |
| `point_obscured` | 클릭 지점의 최상위 창이 대상 창이 아니다(다른 창·소유 팝업이 덮음) |
| `window_mismatch` | 관측값(`Match`)의 창과 입력 요청의 창이 다르다 |
| `target_elevated` | 대상 프로세스의 무결성 수준이 runner보다 높다(UIPI가 입력을 버림) |
| `input_desktop_unavailable` | 입력 데스크톱을 열 수 없다(잠금 화면·UAC 화면·세션 없음) |
| `dpi_awareness_unavailable` | 프로세스를 Per-Monitor V2로 둘 수 없다 |
| `capture_unsupported`·`capture_timeout`·`capture_failed` | 캡처 (T4) |
| `launch_failed` | 프로세스를 띄울 수 없다 |
| `frame_expired` | 버린 프레임을 썼다 (T4) |
| `key_unknown` | 모르는 키 이름 (T5) |
| `ocr_model_missing`·`ocr_model_corrupt` | OCR 모델 (T7) |
| `target_image_invalid` | target 이미지를 읽을 수 없다 (T6) |

처리되지 않은 fail로 끝나는 `stale_observation`(출구 없음)은 이 표의 `error`와 다르다 (T8·T9).
"""

from __future__ import annotations

from typing import Final

from kookabug_core.engine.errors import EngineError
from kookabug_core.win.dpi import CODE as DPI_AWARENESS_UNAVAILABLE

__all__ = [
    "CAPTURE_FAILED",
    "CAPTURE_TIMEOUT",
    "CAPTURE_UNSUPPORTED",
    "CODES",
    "DPI_AWARENESS_UNAVAILABLE",
    "FRAME_EXPIRED",
    "INPUT_DESKTOP_UNAVAILABLE",
    "KEY_UNKNOWN",
    "LAUNCH_FAILED",
    "OCR_MODEL_CORRUPT",
    "OCR_MODEL_MISSING",
    "POINT_OBSCURED",
    "STALE_OBSERVATION",
    "TARGET_ELEVATED",
    "TARGET_IMAGE_INVALID",
    "WINDOW_GONE",
    "WINDOW_MINIMIZED",
    "WINDOW_MISMATCH",
    "WINDOW_NOT_FOREGROUND",
    "PlatformError",
]

WINDOW_GONE: Final = "window_gone"
WINDOW_MINIMIZED: Final = "window_minimized"
WINDOW_NOT_FOREGROUND: Final = "window_not_foreground"
POINT_OBSCURED: Final = "point_obscured"
WINDOW_MISMATCH: Final = "window_mismatch"
TARGET_ELEVATED: Final = "target_elevated"
INPUT_DESKTOP_UNAVAILABLE: Final = "input_desktop_unavailable"
CAPTURE_UNSUPPORTED: Final = "capture_unsupported"
CAPTURE_TIMEOUT: Final = "capture_timeout"
CAPTURE_FAILED: Final = "capture_failed"
LAUNCH_FAILED: Final = "launch_failed"
FRAME_EXPIRED: Final = "frame_expired"
KEY_UNKNOWN: Final = "key_unknown"
OCR_MODEL_MISSING: Final = "ocr_model_missing"
OCR_MODEL_CORRUPT: Final = "ocr_model_corrupt"
TARGET_IMAGE_INVALID: Final = "target_image_invalid"
STALE_OBSERVATION: Final = "stale_observation"

CODES: Final = frozenset(
    {
        WINDOW_GONE,
        WINDOW_MINIMIZED,
        WINDOW_NOT_FOREGROUND,
        POINT_OBSCURED,
        WINDOW_MISMATCH,
        TARGET_ELEVATED,
        INPUT_DESKTOP_UNAVAILABLE,
        DPI_AWARENESS_UNAVAILABLE,
        CAPTURE_UNSUPPORTED,
        CAPTURE_TIMEOUT,
        CAPTURE_FAILED,
        LAUNCH_FAILED,
        FRAME_EXPIRED,
        KEY_UNKNOWN,
        OCR_MODEL_MISSING,
        OCR_MODEL_CORRUPT,
        TARGET_IMAGE_INVALID,
    }
)
"""`error`로 끝나는 플랫폼 코드 (`stale_observation`은 처리되지 않은 fail이라 따로)."""


class PlatformError(EngineError):
    """플랫폼이 찾은 지원하지 않는 조건·고장. `code`는 `CODES` 중 하나."""

    def __init__(self, code: str, message: str) -> None:
        if code not in CODES:
            raise ValueError(f"모르는 플랫폼 오류 코드: {code}")
        super().__init__(code, message)
