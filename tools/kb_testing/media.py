"""`media` 검사 표시: 실제 Media Foundation H.264 인코딩·디코딩 (구현 계획 M3 2.5 "CI").

실행 조건 `KOOKABUG_MEDIA_TESTS`:
- `off`: 전부 건너뜀
- `auto`(기본): 세션당 한 번 `probe_media()`로 탐지하고, **"MF H.264 인코더가 등록돼 있지 않음"**
  (또는 MF DLL·OpenCV MSMF 백엔드 없음)일 때만 그 이유를 적어 건너뜀. 인코더가 있는데 쓰기·디코드가
  실패하면 검사 실패다 (건너뛰기로 바꾸지 않는다)
- `require`: 탐지가 없음이어도 실패 (개발자 PC)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

MODE_ENV: Final = "KOOKABUG_MEDIA_TESTS"
MARKER: Final = "media"

_probe: tuple[bool, str] | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    action: Literal["run", "skip", "fail"]
    reason: str = ""


def mode_from_env(env: Mapping[str, str]) -> str:
    raw = env.get(MODE_ENV, "").strip().lower() or "auto"
    if raw not in ("off", "auto", "require"):
        raise ValueError(f"{MODE_ENV}는 off·auto·require 중 하나다: {raw!r}")
    return raw


def session_probe() -> tuple[bool, str]:
    """(쓸 수 있음, 설명). 세션에 한 번."""
    global _probe
    if _probe is None:
        from kookabug_platform.video import probe_media

        found = probe_media()
        _probe = (found.available, f"{found.reason or 'ok'}: {found.detail}")
    return _probe


def decide(env: Mapping[str, str] | None = None) -> Decision:
    mode = mode_from_env(os.environ if env is None else env)
    if mode == "off":
        return Decision("skip", f"{MODE_ENV}=off")
    available, detail = session_probe()
    if available:
        return Decision("run")
    if mode == "require":
        return Decision("fail", f"{MODE_ENV}=require인데 영상 인코더가 없다 — {detail}")
    return Decision("skip", f"영상 인코더 없음 (명시적 탐지) — {detail}")
