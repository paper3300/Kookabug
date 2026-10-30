"""OCR 파이프라인: 예제 게임 화면 PNG를 실제 모델로 읽는다 (구현 계획 M1 2.6, T7).

모델이 없으면 `ocr_models` 픽스처가 실패한다(받기 명령 안내).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from kookabug_core.record.artifacts import StagedFrame
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.errors import FRAME_EXPIRED, PlatformError
from kookabug_platform.frames import FrameStore
from kookabug_platform.ocr import models as m
from kookabug_platform.ocr.engine import (
    Ocr,
    OcrLine,
    RapidOcrEngine,
    create_engine,
    join_lines,
    parse_number,
)
from kookabug_platform.vision import FrameMeta, Pixels, load_target_image

FRAMES = Path(__file__).resolve().parents[3] / "fixtures" / "sample-game" / "frames"


def frame(name: str) -> Pixels:
    return load_target_image(FRAMES / f"{name}.png").bgr


@pytest.fixture(scope="module")
def ocr(ocr_models: Path) -> Iterator[Ocr]:
    engine = RapidOcrEngine(m.find_models(dirs=[ocr_models]))
    engine.load()
    yield Ocr(engine)


def test_reads_korean_title(ocr: Ocr) -> None:
    assert ocr.read(frame("login"), region=(300, 95, 424, 50)).text == "로그인"
    assert ocr.read(frame("lobby"), region=(300, 90, 424, 60)).text == "서버 선택"
    body = ocr.read(frame("maintenance"), region=(262, 250, 500, 100)).text
    assert body == "서버 점검 중입니다\n잠시 후 다시 접속해 주세요"
    # 영역 없이 화면 전체
    assert "샘플 RPG" in ocr.read(frame("title")).text


def test_reads_mixed_server_list(ocr: Ocr) -> None:
    result = ocr.read(frame("lobby"), region=(262, 200, 500, 144))
    assert result.text == "Server 1 원활\nServer 2 혼잡"
    # 상자 나눔은 검출 모델 몫이라 글자만 본다: 위 줄 → 아래 줄, 줄 안은 왼 → 오른
    assert " ".join(line.text for line in result.lines) == "Server 1 원활 Server 2 혼잡"


def test_reads_number_with_commas(ocr: Ocr) -> None:
    result = ocr.read(frame("world"), region=(20, 20, 240, 52))
    assert result.text == "Gold 12,345"
    assert parse_number(result.text) == 12345


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("Gold 12,345", 12345),
        ("1,234,567원", 1234567),
        ("12 345", 12345),
        ("HP -3.5", -3.5),
        ("+7", 7),
        (chr(0x2212) + "12", -12),  # 유니코드 빼기 기호
        ("Lv.30 Server 2", 30),
        ("0.25", 0.25),
        ("1,23", 1),
    ],
)
def test_parse_number(text: str, number: float) -> None:
    value = parse_number(text)
    assert value == number
    assert isinstance(value, float) == ("." in text.split()[-1] and "Lv" not in text)


@pytest.mark.parametrize("text", ["", "골드 없음", "Server", "-", ","])
def test_parse_number_none(text: str) -> None:
    assert parse_number(text) is None


def test_region_limits_text(ocr: Ocr) -> None:
    region = (262, 200, 500, 64)
    result = ocr.read(frame("lobby"), region=region)
    assert result.text == "Server 1 원활"
    for line in result.lines:  # 상자는 이미지 좌표이고 영역 안
        x, y, w, h = line.box
        assert region[0] <= x and x + w <= region[0] + region[2]
        assert region[1] <= y and y + h <= region[1] + region[3]
    # 이미지 밖으로 나간 영역은 잘린다, 완전히 밖이면 아무것도 없다
    assert ocr.read(frame("world"), region=(-10, -10, 270, 82)).text == "Gold 12,345"
    assert ocr.read(frame("world"), region=(2000, 2000, 50, 50)).lines == ()


def test_unreadable_when_empty(ocr: Ocr) -> None:
    for pixels, region in (
        (frame("world"), (262, 200, 300, 64)),  # 풀밭
        (np.zeros((120, 400, 3), dtype=np.uint8), None),
        (np.full((40, 40, 3), 255, dtype=np.uint8), None),
    ):
        result = ocr.read(pixels, region=region)
        assert (result.text, result.lines, result.confidence) == ("", (), None)
        assert parse_number(result.text) is None


def test_line_order_top_left(ocr: Ocr) -> None:
    result = ocr.read(frame("lobby"))
    assert result.text.splitlines() == ["서버 선택", "Server 1 원활", "Server 2 혼잡", "입장"]
    # lines도 같은 순서 (위 → 아래, 줄 안은 왼 → 오른)
    tops = [line.box[1] + line.box[3] / 2 for line in result.lines]
    assert " ".join(line.text for line in result.lines) == " ".join(result.text.splitlines())
    assert tops[0] < tops[-1]
    row = ocr.read(frame("inventory"), region=(252, 170, 524, 200))
    assert row.text == "포션 검 방패 Key 지도\nGem 활 빵"


def test_join_lines_rows_and_gaps() -> None:
    lines = [
        OcrLine("오른", (300, 12, 40, 20), 0.9),
        OcrLine("아래", (10, 60, 40, 20), 0.8),
        OcrLine("왼", (10, 10, 40, 24), 0.7),
        # 맞닿거나 겹친 한글 상자(검출이 낱말을 글자마다 나눔)는 붙인다
        OcrLine("비", (100, 100, 20, 20), 1.0),
        OcrLine("밀", (120, 101, 20, 20), 1.0),
        OcrLine("번호", (133, 100, 40, 20), 1.0),
        # 겹쳐도 한글끼리가 아니면 띄운다 (확장된 상자는 띄어 쓴 낱말끼리도 겹친다)
        OcrLine("Gold", (10, 150, 64, 30), 1.0),
        OcrLine("12,345", (70, 150, 85, 30), 1.0),
        # 떨어진 한글 상자는 띄운다
        OcrLine("로그인", (10, 200, 77, 30), 1.0),
        OcrLine("실패", (89, 200, 54, 30), 1.0),
    ]
    result = join_lines(lines)
    assert result.text == "왼 오른\n아래\n비밀번호\nGold 12,345\n로그인 실패"
    assert [ln.text for ln in result.lines][:6] == ["왼", "오른", "아래", "비", "밀", "번호"]
    assert result.confidence == pytest.approx(sum(ln.score for ln in lines) / len(lines))
    assert join_lines([]).confidence is None


def test_confidence_range(ocr: Ocr) -> None:
    for name in ("title", "lobby", "world", "inventory"):
        result = ocr.read(frame(name))
        assert result.lines
        assert result.confidence is not None and 0.5 <= result.confidence <= 1.0
        assert result.confidence == pytest.approx(
            sum(line.score for line in result.lines) / len(result.lines)
        )
        assert all(0.5 <= line.score <= 1.0 for line in result.lines)


def test_read_capture_uses_store_and_client_coordinates(ocr: Ocr) -> None:
    store = FrameStore()
    full = frame("world")
    # 영역 캡처: 픽셀 (0, 0)이 클라이언트 (10, 10)
    part = np.ascontiguousarray(full[10:110, 10:310])
    store.register(1, StagedFrame("k1", part), "s1")
    meta = FrameMeta(client_size=(1024, 640), origin=(10, 10), capture_id=1)
    store_ocr = Ocr(ocr.engine, store)
    result = store_ocr.read_capture(1, meta, region=(20, 20, 240, 52))
    assert result.text == "Gold 12,345"
    direct = ocr.read(full, region=(20, 20, 240, 52))
    assert [ln.box for ln in result.lines] == [ln.box for ln in direct.lines]
    assert store.held() == {1}  # 읽는 동안만 고정, 캡처 자체는 남아 있다
    store.close_step("s1")  # 스텝 증거에서 빠지면 버려진다
    with pytest.raises(PlatformError) as info:
        store_ocr.read_capture(1, meta)
    assert info.value.code == FRAME_EXPIRED


def test_engine_by_config_name() -> None:
    assert isinstance(create_engine("rapidocr"), RapidOcrEngine)
    with pytest.raises(ValueError, match="모르는 OCR 엔진"):
        create_engine("tesseract")


def test_grayscale_and_bgra_inputs(ocr: Ocr) -> None:
    import cv2

    bgr = frame("world")
    gray = np.asarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
    bgra = np.asarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA), dtype=np.uint8)
    for pixels in (gray, bgra):
        assert ocr.read(pixels, region=(20, 20, 240, 52)).text == "Gold 12,345"


# ---------------------------------------------------------------- 크기 (T7 2라운드)


def put_text(img: Pixels, text: str, at: tuple[int, int], scale: float) -> None:
    import cv2

    thick = 1 if scale < 1 else 2
    cv2.putText(img, text, at, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick, cv2.LINE_AA)


@pytest.mark.parametrize("shape", [(1, 3840), (8, 4096), (3840, 1), (1, 1), (2, 3)])
def test_thin_regions_do_not_crash(ocr: Ocr, shape: tuple[int, int]) -> None:
    # 처리 자체가 깨지지 않고, 글자가 없으면 읽은 것이 없다 (검수 T7_1 2번)
    result = ocr.read(np.zeros((*shape, 3), dtype=np.uint8))
    assert (result.text, result.lines) == ("", ())


def test_long_single_line_region_reads(ocr: Ocr) -> None:
    # 4K 화면에서 높이 32픽셀 한 줄 영역 (검수 T7_1 2번 반례)
    strip = np.full((32, 3840, 3), 255, dtype=np.uint8)
    put_text(strip, "Server 12345", (30, 24), 0.7)
    assert ocr.read(strip).text == "Server 12345"
    # 화면 경계에서 잘린 얇은 영역
    screen = np.full((2160, 3840, 3), 255, dtype=np.uint8)
    put_text(screen, "Server 12345", (3500, 2150), 0.7)
    assert ocr.read(screen, region=(3400, 2120, 1000, 100)).text == "Server 12345"


@pytest.mark.parametrize(
    ("size", "count", "scale"),
    [
        ((1920, 1080), 1, 0.5),
        ((1920, 1080), 3, 0.6),
        ((3840, 2160), 3, 0.6),
        ((1920, 1080), 2, 2.5),
    ],
    ids=["1080p-one-small", "1080p-three-small", "4k-three-small", "1080p-large"],
)
def test_full_screen_finds_scattered_text(
    ocr: Ocr, size: tuple[int, int], count: int, scale: float
) -> None:
    # 큰 화면 전체 읽기에서 흩어진 작은 글자를 놓치지 않는다 (검수 T7_1 3번: 4K 빈 문자열)
    w, h = size
    img = np.full((h, w, 3), 245, dtype=np.uint8)
    expected = []
    places = [(80, 100), (w - 420 if scale < 1 else w // 2, h // 2), (100, h - 100)]
    for i in range(count):
        text = f"Server {12345 + i * 1111}"
        put_text(img, text, places[i], scale)
        expected.append(text)
    # 관측 기한을 넘겨 읽는다. 큰 화면 전체 읽기는 수 초라 설정 기한(`run.capture_timeout_ms`,
    # 기본 2000)을 넉넉히 줘야 한다 — 노드 기한만 늘려서는 설정 기한을 넘을 수 없다(T9 인계)
    deadline = ObservationDeadline(60_000, node_ms=60_000, run_ms=120_000)
    assert sorted(ocr.read(img, deadline=deadline).text.splitlines()) == sorted(expected)


def test_large_text_on_upscaled_frame(ocr: Ocr) -> None:
    import cv2

    # 타일 겹침(128)보다 큰 글자 (예제 화면을 3.75배)
    big = np.asarray(
        cv2.resize(frame("lobby"), (3840, 2400), interpolation=cv2.INTER_CUBIC), dtype=np.uint8
    )
    assert ocr.read(big).text.splitlines() == [
        "서버 선택",
        "Server 1 원활",
        "Server 2 혼잡",
        "입장",
    ]


def test_korean_crops_on_4k_canvas(ocr: Ocr) -> None:
    # 실제 한글 글꼴(예제 화면 조각)을 4K 바탕 곳곳에 원래 크기로 붙인다
    canvas = np.full((2160, 3840, 3), (51, 36, 28), dtype=np.uint8)
    pieces = [
        ("world", (20, 20, 240, 52), (3280, 1040), "Gold 12,345"),
        ("login_error", (262, 250, 500, 50), (40, 2040), "계정 또는 비밀번호가"),
        ("maintenance", (262, 170, 500, 56), (1720, 720), "점검 안내"),
    ]
    for name, (x, y, cw, ch), (px, py), _text in pieces:
        canvas[py : py + ch, px : px + cw] = frame(name)[y : y + ch, x : x + cw]
    lines = ocr.read(canvas).text.splitlines()
    for *_rest, text in pieces:
        # 정확히 한 줄에서 (중복 없이) 읽는다. 동전 그림이 "•"로 붙을 수 있어 포함으로 본다
        assert sum(text in line for line in lines) == 1, lines
