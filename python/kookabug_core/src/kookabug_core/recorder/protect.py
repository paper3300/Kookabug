"""녹화 상자 도구: 상자 형식(`Box`)·겹침·이름 정리.

UX11 B (2026-11-16 사용자 결정): Kookabug은 로컬 툴이라 **녹화는 비밀값 칸을 가리지 않는다** — 자동
자르기·대기 자르기·수동 영역·확인 넣기·이름 OCR이 칸과 겹쳐도 그대로 쓴다. 칸 보호 목록
(`ProtectionSet`·`SecretRegionOverlap`)은 UX12에서 지웠다. 비밀번호 칸 입력을 `$secret` 참조로
바꾸는 분류는 `recorder.classify`·`recorder.secrets`가 그대로 한다.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

__all__ = ["NAME_MAX", "Box", "boxes_overlap", "sanitize_name"]

type Box = tuple[int, int, int, int]
"""`(x, y, w, h)` 클라이언트 물리 픽셀."""

NAME_MAX: Final = 20
"""이름에 쓰는 글자 수 상한 (파일 이름·노드 제목)."""
_NAME_BAD: Final = re.compile(r"[\\/:*?\"<>|\x00-\x1f.\s]+")


def boxes_overlap(a: Box, b: Box) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def sanitize_name(text: str) -> str:
    """파일 이름·노드 제목에 쓸 수 있게 정리 (앞 20자). 남는 것이 없으면 빈 문자열."""
    text = unicodedata.normalize("NFC", text)
    text = _NAME_BAD.sub("_", text).strip("_")
    return text[:NAME_MAX].strip("_")
