"""화면 판정의 OCR 조건 (M7 계획 3.1): 예제 게임 화면 PNG를 실제 OCR 모델로 본다.

모델이 없으면 `ocr_models` 픽스처가 실패한다(받기 명령 안내). OCR 조건 오라클 차단(3.5a)의 판정
쪽 몫: 글자 읽기를 넘기지 않으면 OCR 조건은 `unknown`이고, 읽은 글자는 사람 CLI가 요청할 때만
결과에 남는다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.screens import ScreenDef, parse_screen
from kookabug_platform.ocr import models as m
from kookabug_platform.ocr.engine import Ocr, OcrResult, RapidOcrEngine
from kookabug_platform.screens import (
    ScreenResult,
    TextReader,
    evaluate_screen,
    normalize_text,
    ocr_region,
)
from kookabug_platform.vision import FrameMeta, Pixels, Vision, load_target_image
from kookabug_sdk.types import Target

FRAMES = Path(__file__).resolve().parents[3] / "fixtures" / "sample-game" / "frames"
W, H = 1024, 640
TITLE = (300 / W, 95 / H, 424 / W, 50 / H)
"""로그인·로비 화면 제목 줄 (정규화)."""


def frame(name: str) -> Pixels:
    return load_target_image(FRAMES / f"{name}.png").bgr


def screen(*all_: dict[str, Any], none: tuple[dict[str, Any], ...] = ()) -> ScreenDef:
    detect: dict[str, Any] = {"all": list(all_)}
    if none:
        detect["none"] = list(none)
    return parse_screen({"format": "kookabug.screen/1", "detect": detect}, "screens/s.screen.json")


def ocr_cond(text: str, rect: tuple[float, ...] = TITLE) -> dict[str, Any]:
    return {"ocr": {"rect": list(rect), "text": text}}


def no_targets(rel: str) -> Target:
    raise AssertionError(f"target을 읽으면 안 된다: {rel}")


@pytest.fixture(scope="module")
def ocr(ocr_models: Path) -> Iterator[Ocr]:
    engine = RapidOcrEngine(m.find_models(dirs=[ocr_models]))
    engine.load()
    yield Ocr(engine)


def evaluate(s: ScreenDef, name: str, reader: TextReader | None, **kw: Any) -> ScreenResult:
    pixels = frame(name)
    return evaluate_screen(
        s, no_targets, pixels, FrameMeta.of_image(pixels), Vision(), ocr=reader, **kw
    )


def test_ocr_condition_matches_sample_frame(ocr: Ocr) -> None:
    login = screen(ocr_cond("로그인"))
    result = evaluate(login, "login", ocr)
    assert result.matched and result.state == "matched"
    (cond,) = result.conditions
    assert (cond.found, cond.ok, cond.target, cond.result) == (True, True, None, None)
    assert cond.region == (300, 95, 424, 50)
    # 공백·대소문자 무시, 부분 포함
    assert evaluate(
        screen(ocr_cond("server1", (262 / W, 200 / H, 500 / W, 144 / H))), "lobby", ocr
    ).matched
    # none 조건: 로비 제목에는 "로그인"이 없으므로 맞다
    lobby = screen(ocr_cond("서버 선택"), none=(ocr_cond("로그인"),))
    assert evaluate(lobby, "lobby", ocr).matched
    # 읽은 글자는 기본으로 결과에 남지 않는다
    assert all(c.read is None for c in result.conditions)
    shown = evaluate(login, "login", ocr, reveal_text=True).conditions[0].read
    assert shown is not None and "로그인" in shown


def test_ocr_condition_absent_text_fails(ocr: Ocr) -> None:
    login = screen(ocr_cond("서버 선택"))
    result = evaluate(login, "login", ocr)
    (cond,) = result.conditions
    assert (cond.found, cond.ok, result.matched, result.state) == (
        False,
        False,
        False,
        "not_matched",
    )
    # none 조건이 보이면 틀림
    result = evaluate(screen(ocr_cond("로그인"), none=(ocr_cond("로그인"),)), "login", ocr)
    assert [c.ok for c in result.conditions] == [True, False]
    assert not result.matched


class FixedReader:
    """늘 같은 글자를 읽는 가짜 OCR."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def read(self, pixels: Pixels, *, region: Any = None) -> OcrResult:
        self.calls += 1
        return OcrResult(self.text, (), 1.0)


def test_ocr_condition_unknown_without_reader() -> None:
    # 보호된 프레임: 글자 읽기를 넘기지 않으면 OCR 조건은 확인하지 않는다 (값 추측 통로 차단)
    result = evaluate(screen(ocr_cond("로그인")), "login", None)
    (cond,) = result.conditions
    assert (cond.found, cond.ok, cond.read) == (None, None, None)
    assert (result.matched, result.state) == (False, "unknown")


def test_reader_text_not_kept_and_not_matched_wins() -> None:
    reader = FixedReader("비밀번호 hunter2")
    result = evaluate(screen(ocr_cond("비밀번호"), ocr_cond("없는 글자")), "login", reader)
    assert reader.calls == 2
    assert [c.ok for c in result.conditions] == [True, False]
    assert result.state == "not_matched"
    # 결과 어디에도 읽은 글자가 없다 (reveal_text를 켜지 않으면)
    assert "hunter2" not in repr(result)


def test_no_conditions_is_unknown_not_matched() -> None:
    # 판정 조건 없는 후보(미완성·of만 있는 합치기 후보)는 어느 프레임에도 "맞음"이 아니다
    for data in (
        {"format": "kookabug.screen/1", "title": "미완성"},
        {"format": "kookabug.screen/1", "of": "lobby"},
    ):
        s = parse_screen(data, "screens/_explored/20261107-103000-a1b2/k.screen.json")
        result = evaluate(s, "login", FixedReader("아무 글자"))
        assert (result.conditions, result.matched, result.state) == ((), False, "unknown")


def test_region_and_normalize() -> None:
    pixels = frame("login")
    meta = FrameMeta.of_image(pixels)
    assert ocr_region((0.9, 0.9, 0.1, 0.1), pixels, meta) == (921, 576, 103, 64)
    # 영역 캡처(origin)면 프레임 좌표로 옮기고 밖은 잘라낸다
    part = pixels[100:300, 200:600]
    region_meta = FrameMeta((W, H), origin=(200, 100))
    assert ocr_region((0.0, 0.0, 0.5, 0.5), part, region_meta) == (0, 0, 312, 200)
    assert normalize_text(" Server 1 ") == normalize_text("server1") == "server1"
    assert normalize_text(chr(0xFF21) + chr(0xFF22)) == "ab"  # 전각 A·B (NFKC)
