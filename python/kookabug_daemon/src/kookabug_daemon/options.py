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
    # 개발·테스트용: 실행의 워커가 import할 플러그인 모듈 (CLI run --plugin-module과 같다. 플러그인
    # 설치가 생기기 전까지). 사전 검증·팔레트도 이 모듈의 노드를 안다
    parser.add_argument(
        "--plugin-module",
        dest="plugin_modules",
        action="append",
        default=[],
        metavar="모듈",
        help=argparse.SUPPRESS,
    )
    # 검사 전용 (M4 계획 2.2, KOOKABUG_TESTING=1일 때만 — 아니면 시작하지 않는다): 녹화가 이
    # dwExtraInfo를 가진 합성 입력을 사람 입력으로 받는다 / IME 표본 조회 대상을 바꿔 끼운다
    parser.add_argument(
        "--recorder-accept-extra-info", type=int, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--recorder-ime-query-window", type=int, default=None, help=argparse.SUPPRESS
    )
    # 테스트·E2E용 (M4 계획 2.9 "가짜 원천", --platform-fake와 함께): 녹화가 흘릴 가짜 각본 JSONL과
    # 흘리는 빠르기 (inf = 기다리지 않음)
    parser.add_argument("--recorder-script", metavar="FILE", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--recorder-script-speed", type=float, default=1.0, help=argparse.SUPPRESS)
    # 테스트용: 경쟁에서 졌을 때 유효한 세션을 기다리는 시간
    parser.add_argument(
        "--session-wait-s", type=_positive_float, default=SESSION_WAIT_S, help=argparse.SUPPRESS
    )
