"""`kookabug daemon` 인자 (가벼운 모듈: CLI가 파서를 만들 때 websockets·코어를 불러오지 않는다)."""

from __future__ import annotations

import argparse
from typing import Final

__all__ = ["DEFAULT_IDLE_TIMEOUT_S", "LOG_LEVELS", "SESSION_WAIT_S", "add_arguments"]

DEFAULT_IDLE_TIMEOUT_S: Final = 600.0
SESSION_WAIT_S: Final = 15.0
"""잠금 경쟁에서 졌을 때·클라이언트가 붙을 때 유효한 세션을 기다리는 시간 (M2 계획 2.3)."""
LOG_LEVELS: Final = ("debug", "info", "warning", "error")


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError(f"'{text}'은(는) 0보다 큰 수가 아니다")
    return value


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace", metavar="DIR", help="워크스페이스 루트 (기본: 현재 폴더에서 위로 찾는다)"
    )
    parser.add_argument(
        "--idle-timeout-s",
        type=_positive_float,
        default=DEFAULT_IDLE_TIMEOUT_S,
        metavar="초",
        help="연결도 실행도 없는 상태가 이만큼 이어지면 끝낸다 (기본 600)",
    )
    parser.add_argument("--json", action="store_true", help="시작 결과를 JSON 한 줄로 출력한다")
    parser.add_argument(
        "--log-level", choices=LOG_LEVELS, default="info", help="로그 수준 (기본 info)"
    )
    # 테스트용: 가짜 플랫폼 사양 (CLI run과 같은 형식). 도움말에 보이지 않는다
    parser.add_argument("--platform-fake", metavar="FILE", help=argparse.SUPPRESS)
    # 테스트용: 경쟁에서 졌을 때 유효한 세션을 기다리는 시간
    parser.add_argument(
        "--session-wait-s", type=_positive_float, default=SESSION_WAIT_S, help=argparse.SUPPRESS
    )
