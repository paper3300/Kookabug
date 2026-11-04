"""우리 입력 표식 (M4 계획 2.2). 녹화 훅 프로세스가 무거운 모듈 없이 읽도록 따로 둔다."""

from __future__ import annotations

from typing import Final

__all__ = ["KOOKABUG_INPUT_MARK"]

KOOKABUG_INPUT_MARK: Final = 0x4B4F4F4B
"""우리 SendInput의 `dwExtraInfo` 표식 ("KOOK"). 녹화 훅은 이 값을 가진 입력을 버린다. 정수 값
규칙(2^53-1) 안이고 펜·터치 서명(`0xFF515700` 대역)과 겹치지 않는다. 바꾸면 검사 도구
`kb_testing.keys`의 같은 상수도 바꾼다 (검사가 둘이 같은지 본다)."""
