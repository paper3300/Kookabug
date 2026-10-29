"""명령 진입점의 콘솔 출력."""

from __future__ import annotations

import sys


def utf8_stdio() -> None:
    """stdout·stderr를 UTF-8로 다시 설정한다. 진입점에서 출력 전에(argparse보다 먼저) 부른다.

    파이프·파일로 나가는 출력은 시스템 코드 페이지를 따르므로, 영문 Windows(cp1252)에서는
    한국어 메시지를 쓰다 `UnicodeEncodeError`로 죽는다. 콘솔에 직접 쓸 때는 원래 UTF-8이다.
    """
    for stream in (sys.stdout, sys.stderr):
        # pythonw에서는 None, 바꿔 끼운 스트림에는 reconfigure가 없을 수 있다
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
