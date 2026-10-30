"""실행 옵션."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sample_game import (
    BASE_SIZE,
    DEFAULT_ACCOUNT,
    DEFAULT_FONT,
    DEFAULT_LOADING_MS,
    DEFAULT_PASSWORD,
    DEFAULT_TITLE,
)
from sample_game.flow import GameConfig, Scene

__all__ = ["DPI_MODES", "Options", "parse_args"]

DPI_MODES = ("unaware", "system", "pmv2")
MIN_SIZE = (320, 200)


@dataclass(frozen=True, slots=True)
class Options:
    config: GameConfig
    size: tuple[int, int]
    dpi_awareness: str
    title: str
    event_log: Path | None
    second_window: bool
    owned_popup: bool
    recreate_after: int | None
    start_scene: Scene | None
    font: str


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"WxH 형식이 아니다: {text!r}") from None
    if w < MIN_SIZE[0] or h < MIN_SIZE[1]:
        raise argparse.ArgumentTypeError(f"너무 작다 (최소 {MIN_SIZE[0]}x{MIN_SIZE[1]}): {text}")
    return w, h


def _ms(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"0 이상이어야 한다: {text}")
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sample_game",
        description="Kookabug 예제 게임 SampleRPG (테스트·문서 예시용 가짜 게임)",
    )
    p.add_argument("--maintenance", action="store_true", help="시작을 누르면 점검 팝업")
    p.add_argument("--login-fail", action="store_true", help="로그인이 항상 실패")
    p.add_argument(
        "--slow-loading",
        type=_ms,
        default=DEFAULT_LOADING_MS,
        metavar="MS",
        help=f"월드 로딩 화면을 보여 주는 시간 (기본 {DEFAULT_LOADING_MS})",
    )
    p.add_argument(
        "--size",
        type=_size,
        default=BASE_SIZE,
        metavar="WxH",
        help=f"클라이언트 크기 (기본 {BASE_SIZE[0]}x{BASE_SIZE[1]})",
    )
    p.add_argument(
        "--dpi-awareness",
        choices=DPI_MODES,
        default="pmv2",
        help="DPI 인식 (기본 pmv2 = Per-Monitor V2)",
    )
    p.add_argument("--title", default=DEFAULT_TITLE, help=f"창 제목 (기본 {DEFAULT_TITLE})")
    p.add_argument("--event-log", type=Path, metavar="FILE", help="입력 수신 기록 JSONL")
    p.add_argument("--account", default=DEFAULT_ACCOUNT, help="맞는 계정")
    p.add_argument("--password", default=DEFAULT_PASSWORD, help="맞는 비밀번호")
    p.add_argument("--seed", type=int, default=0, help="골드·인벤토리 배치 (0 = 기본 그림)")
    p.add_argument(
        "--second-window", action="store_true", help="같은 프로세스의 독립 최상위 창 하나 더"
    )
    p.add_argument(
        "--owned-popup", action="store_true", help="메인 창이 소유한 팝업 창 (transient)"
    )
    p.add_argument(
        "--recreate-after",
        type=_ms,
        metavar="MS",
        help="MS 뒤 메인 창을 닫고 같은 제목으로 다시 만든다 (한 번)",
    )
    # 테스트·화면 PNG용 (도움말에 숨김)
    p.add_argument("--start-scene", choices=[s.value for s in Scene], help=argparse.SUPPRESS)
    p.add_argument("--font", default=DEFAULT_FONT, help=argparse.SUPPRESS)
    return p


def parse_args(argv: Sequence[str] | None = None) -> Options:
    ns = parser().parse_args(argv)
    config = GameConfig(
        maintenance=ns.maintenance,
        login_fail=ns.login_fail,
        loading_ms=ns.slow_loading,
        account=ns.account,
        password=ns.password,
        seed=ns.seed,
    )
    return Options(
        config=config,
        size=ns.size,
        dpi_awareness=ns.dpi_awareness,
        title=ns.title,
        event_log=ns.event_log,
        second_window=ns.second_window,
        owned_popup=ns.owned_popup,
        recreate_after=ns.recreate_after,
        start_scene=Scene(ns.start_scene) if ns.start_scene else None,
        font=ns.font,
    )
