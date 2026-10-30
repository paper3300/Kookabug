"""이미지 매칭 (구현 계획 M1 2.5). 예제 게임 화면 PNG(`fixtures/sample-game/frames`)로 본다.

target 이미지는 검사마다 화면에서 잘라 임시 폴더에 쓴다. 정답 상자는 예제 게임의 버튼 배치
(`frames/scenario.json`과 같은 값)다.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR
from kookabug_platform.errors import TARGET_IMAGE_INVALID, PlatformError
from kookabug_platform.frames import decode_image
from kookabug_platform.vision import (
    SCALE_STEPS,
    WORKERS,
    FrameMeta,
    FrameRef,
    Pixels,
    TargetSpec,
    Vision,
    click_point,
    load_target_file,
)
from kookabug_sdk.types import Rect, Target

START_BUTTON = (412, 380, 200, 64)
"""타이틀 화면 "게임 시작" 버튼 (클라이언트 1024x640)."""


def frame(name: str) -> Pixels:
    return decode_image((FRAMES_DIR / f"{name}.png").read_bytes())


def crop(pixels: Pixels, box: tuple[int, int, int, int]) -> Pixels:
    x, y, w, h = box
    return np.ascontiguousarray(pixels[y : y + h, x : x + w])


def scaled(pixels: Pixels, scale: float) -> Pixels:
    h, w = pixels.shape[:2]
    size = (round(w * scale), round(h * scale))
    return np.asarray(cv2.resize(pixels, size, interpolation=cv2.INTER_LINEAR), dtype=np.uint8)


def write_target(folder: Path, image: Pixels, name: str = "button", **spec: Any) -> Target:
    """`<name>.png` + `<name>.target.json`을 쓰고 읽는다 (이미지는 BGR 또는 BGRA)."""
    folder.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(".png", image)
    assert ok
    (folder / f"{name}.png").write_bytes(data.tobytes())
    body = {"format": "kookabug.target/0", "image": f"{name}.png", **spec}
    path = folder / f"{name}.target.json"
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return load_target_file(path)


@pytest.fixture
def title() -> Pixels:
    return frame("title")


@pytest.fixture
def button(tmp_path: Path, title: Pixels) -> Target:
    return write_target(tmp_path, crop(title, START_BUTTON))


def test_template_found_exact(title: Pixels, button: Target) -> None:
    result = Vision().find(title, FrameMeta.of_image(title), button)
    assert result.match is not None
    assert result.match.rect == START_BUTTON
    assert result.match.score > 0.999
    assert (result.match.method, result.match.scale) == ("template_multiscale", 1.0)
    assert result.best is not None and result.best.accepted
    assert len(result.candidates) == 1  # 첫 성공에서 끝


def test_multiscale_from_recorded_client_size(tmp_path: Path, title: Pixels) -> None:
    target = write_target(
        tmp_path, crop(title, START_BUTTON), recorded={"client_size": [1024, 640], "dpi": 96}
    )
    big = scaled(title, 1.25)  # 1280x800 클라이언트, DPI는 그대로(녹화 크기가 먼저)
    result = Vision().find(big, FrameMeta.of_image(big, dpi=96), target)
    assert result.expected_scale == pytest.approx(1.25)
    assert result.match is not None
    assert result.match.scale == pytest.approx(1.25)
    assert result.match.method == "template_multiscale"
    x, y, w, h = result.match.rect
    assert abs(x - 515) <= 2 and abs(y - 475) <= 2 and (w, h) == (250, 80)
    assert result.match.score > 0.9


def test_multiscale_from_dpi_when_no_size(tmp_path: Path, title: Pixels) -> None:
    target = write_target(tmp_path, crop(title, START_BUTTON), recorded={"dpi": 96})
    big = scaled(title, 1.5)  # 96 → 144 DPI
    result = Vision().find(big, FrameMeta.of_image(big, dpi=144), target)
    assert result.expected_scale == pytest.approx(1.5)
    assert result.match is not None and result.match.scale == pytest.approx(1.5)
    # 녹화 정보가 없으면 1.0이고, 배율 단계 끝(1.2배)으로도 1.5배는 못 찾는다
    bare = write_target(tmp_path / "bare", crop(title, START_BUTTON))
    miss = Vision().find(big, FrameMeta.of_image(big, dpi=144), bare)
    assert miss.expected_scale == 1.0
    assert miss.match is None
    assert [round(c.scale, 4) for c in miss.candidates[:9]] == [round(s, 4) for s in SCALE_STEPS]


def test_methods_order_first_success_wins(tmp_path: Path, title: Pixels) -> None:
    image = crop(title, START_BUTTON)
    template_first = write_target(
        tmp_path / "a", image, match={"methods": ["template", "template_multiscale"]}
    )
    multi_first = write_target(
        tmp_path / "b", image, match={"methods": ["template_multiscale", "template"]}
    )
    meta = FrameMeta.of_image(title)
    found = Vision().find(title, meta, template_first)
    assert found.match is not None and found.match.method == "template"
    found = Vision().find(title, meta, multi_first)
    assert found.match is not None and found.match.method == "template_multiscale"
    # 1.1배 화면: template(배율 1.0)이 먼저 실패하고 그다음 방법의 1.1배에서 찾는다
    big = scaled(title, 1.1)
    result = Vision().find(big, FrameMeta.of_image(big), template_first)
    first = result.candidates[0]
    assert (first.method, first.scale, first.accepted) == ("template", 1.0, False)
    assert result.match is not None
    assert (result.match.method, result.match.scale) == ("template_multiscale", pytest.approx(1.1))
    # template만이면 못 찾는다
    only = write_target(tmp_path / "c", image, match={"methods": ["template"]})
    assert Vision().find(big, FrameMeta.of_image(big), only).match is None


def test_threshold_not_met_returns_none_with_best_score(button: Target) -> None:
    loading = frame("loading")
    result = Vision().find(loading, FrameMeta.of_image(loading), button)
    assert result.match is None
    assert result.best is not None
    assert result.best.score < result.threshold == 0.85
    assert result.best.reason == "threshold" and not result.best.accepted
    assert result.best.score == max(c.score for c in result.candidates)
    assert len(result.candidates) == len(SCALE_STEPS) + 1  # 모든 배율 + template


def gray_tone(image: Pixels) -> Pixels:
    """채널마다 무늬(평균과의 차이)는 두고 평균만 같은 회색으로 옮긴 변형 — 비활성 버튼처럼 색만
    빠진 것. `TM_CCOEFF_NORMED`는 채널별 평균을 빼고 비교하므로 모양 점수는 거의 그대로다."""
    values = image.astype(np.int16)
    means = values.reshape(-1, 3).mean(axis=0)
    shifted = values - means.astype(np.int16) + int(means.mean())
    return np.clip(shifted, 0, 255).astype(np.uint8)


def test_color_check_rejects_gray_variant(tmp_path: Path, title: Pixels) -> None:
    image = crop(title, START_BUTTON)
    gray_title = title.copy()
    x, y, w, h = START_BUTTON
    gray_title[y : y + h, x : x + w] = gray_tone(image)
    meta = FrameMeta.of_image(gray_title)
    colored = write_target(tmp_path / "rgb", image)
    result = Vision().find(gray_title, meta, colored)
    assert result.match is None
    assert result.best is not None
    # 모양 점수는 넘지만 색이 달라 실패
    assert result.best.rect == START_BUTTON
    assert result.best.score >= 0.85
    assert result.best.reason == "color"
    assert result.best.color_diff is not None and result.best.color_diff > 40
    # 색 허용 폭을 넓히거나 회색조로 비교하면 찾는다 (대조)
    loose = write_target(tmp_path / "loose", image, match={"color_tolerance": 255})
    assert Vision().find(gray_title, meta, loose).match is not None
    grayscale = write_target(tmp_path / "gray", image, match={"rgb": False})
    found = Vision().find(gray_title, meta, grayscale)
    assert found.match is not None and found.match.rect == START_BUTTON
    # 원래 화면에서는 색 확인도 통과한다
    assert Vision().find(title, FrameMeta.of_image(title), colored).match is not None
    # 완전히 회색조로 바꾼 버튼은 모양 점수부터 못 넘는다 (어느 쪽이든 찾지 않음)
    fully_gray = title.copy()
    fully_gray[y : y + h, x : x + w] = cv2.cvtColor(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR
    )
    assert Vision().find(fully_gray, FrameMeta.of_image(fully_gray), colored).match is None


def test_search_region_limits(tmp_path: Path, title: Pixels) -> None:
    image = crop(title, START_BUTTON)
    meta = FrameMeta.of_image(title)
    upper = write_target(tmp_path / "upper", image, search={"region": [0, 0, 1, 0.5]})
    result = Vision().find(title, meta, upper)
    assert result.search == (0, 0, 1024, 320)
    assert result.match is None
    lower = write_target(tmp_path / "lower", image, search={"region": [0.25, 0.5, 0.5, 0.5]})
    result = Vision().find(title, meta, lower)
    assert result.search == (256, 320, 512, 320)
    assert result.match is not None and result.match.rect == START_BUTTON
    # 호출의 region(클라이언트 좌표)이 target의 범위보다 우선한다
    result = Vision().find(title, meta, lower, region=Rect(0, 0, 400, 640))
    assert result.search == (0, 0, 400, 640) and result.match is None
    # 영역 캡처(픽셀 (0,0) = 클라이언트 (300, 300))에서도 클라이언트 좌표로 답한다
    part = np.ascontiguousarray(title[300:640, 300:1024])
    part_meta = FrameMeta((1024, 640), origin=(300, 300))
    result = Vision().find(part, part_meta, lower)
    assert result.search == (300, 320, 468, 320)
    assert result.match is not None and result.match.rect == START_BUTTON


def test_alpha_mask(tmp_path: Path, title: Pixels) -> None:
    # 버튼 둘레 12픽셀까지 넣고, 둘레를 엉뚱한 색으로 칠한 뒤 알파 0으로 지운다
    x, y, w, h = START_BUTTON
    box = (x - 12, y - 12, w + 24, h + 24)
    image = crop(title, box).copy()
    image[:12, :] = image[-12:, :] = (255, 0, 255)
    image[:, :12] = image[:, -12:] = (255, 0, 255)
    bgra = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2BGRA), dtype=np.uint8)
    bgra[:, :, 3] = 0
    bgra[12:-12, 12:-12, 3] = 255
    masked = write_target(tmp_path / "masked", bgra)
    opaque = write_target(tmp_path / "opaque", image)
    meta = FrameMeta.of_image(title)
    found = Vision().find(title, meta, masked)
    assert found.match is not None
    assert found.match.rect == box and found.match.score > 0.99
    # 알파를 빼면(둘레가 그대로 비교되면) 점수가 크게 떨어진다
    plain = Vision().find(title, meta, opaque)
    assert plain.best is not None and plain.best.score < found.match.score - 0.1
    assert Vision().target_image(TargetSpec.of(masked)).mask is not None
    assert Vision().target_image(TargetSpec.of(opaque)).mask is None


def test_korean_path_image_load(tmp_path: Path, title: Pixels) -> None:
    folder = tmp_path / "한글 폴더" / "타이틀"
    target = write_target(folder, crop(title, START_BUTTON), name="시작 버튼")
    result = Vision().find(title, FrameMeta.of_image(title), target)
    assert result.match is not None and result.match.rect == START_BUTTON
    # 깨진 이미지·없는 이미지는 target_image_invalid
    (folder / "시작 버튼.png").write_bytes(b"not a png")
    with pytest.raises(PlatformError) as broken:
        Vision().find(title, FrameMeta.of_image(title), target)
    assert broken.value.code == TARGET_IMAGE_INVALID
    (folder / "시작 버튼.png").unlink()
    with pytest.raises(PlatformError) as missing:
        Vision().find(title, FrameMeta.of_image(title), target)
    assert missing.value.code == TARGET_IMAGE_INVALID


def test_click_point_anchor_offset_scaled(tmp_path: Path, title: Pixels) -> None:
    assert click_point((10, 20, 100, 40), "center", (0, 0), 1.0) == (60, 40)  # 59.5 → 60
    assert click_point((10, 20, 100, 40), "top_left", (0, 0), 1.0) == (10, 20)
    assert click_point((10, 20, 100, 40), "bottom_right", (0, 0), 1.0) == (109, 59)
    assert click_point((10, 20, 100, 40), "left", (4, -2), 2.0) == (18, 36)  # 39.5 - 4 → 36
    target = write_target(
        tmp_path,
        crop(title, START_BUTTON),
        click={"anchor": "bottom_right", "offset": [-10, -4]},
        recorded={"client_size": [1024, 640]},
    )
    big = scaled(title, 1.25)
    result = Vision().find(big, FrameMeta.of_image(big), target)
    assert result.match is not None
    x, y, w, h = result.match.rect
    # 오른쪽 아래 끝 픽셀 + offset * 1.25
    assert result.match.click == (x + w - 1 - 12, y + h - 1 - 5)  # -12.5 → -12, -5
    assert result.match.click == click_point(result.match.rect, "bottom_right", (-10, -4), 1.25)


def test_deterministic_same_input_same_match(title: Pixels, button: Target) -> None:
    big = scaled(title, 1.1)
    results = [Vision().find(big, FrameMeta.of_image(big), button) for _ in range(3)]
    assert results[0].match is not None
    assert all(r.match == results[0].match for r in results)
    assert all(r.candidates == results[0].candidates for r in results)


def test_match_carries_frame_info_and_target(title: Pixels, button: Target) -> None:
    meta = FrameMeta(
        (1024, 640),
        dpi=120,
        backend="wgc",
        capture_id=7,
        observed_at=1234.5,
        frame=42,
        window="w-binding",
    )
    result = Vision().find(title, meta, button)
    assert result.match is not None
    assert result.match.frame_info == FrameRef("wgc", (1024, 640), 120, 7, 1234.5)
    assert result.match.target == button.name == "button.target.json"
    assert (result.match.window, result.match.frame) == ("w-binding", 42)


def test_perf_budget_reported(
    tmp_path: Path, title: Pixels, capsys: pytest.CaptureFixture[str]
) -> None:
    # 목표 (M1 2.5): 1280x720 전체, 템플릿 100x40, 배율 9개(+template) → 200 ms 이하.
    # 최악 경우(못 찾음 — 모든 방법·배율을 원래 크기로 계산)를 잰다. 방법·배율은 스레드 풀에서
    # 함께 계산하므로 CPU가 4개보다 적으면 목표를 그 비율로 늘린다
    budget_ms = 200 * max(1.0, 4 / WORKERS)
    big = scaled(title, 1.25)[:720, :1280]
    template = np.ascontiguousarray(crop(big, (590, 470, 100, 40)))
    target = write_target(tmp_path, template)
    lobby = np.ascontiguousarray(scaled(frame("lobby"), 1.25)[:720, :1280])
    vision = Vision()
    meta = FrameMeta.of_image(lobby)
    times = []
    for _ in range(5):
        result = vision.find(lobby, meta, target)
        assert result.match is None and len(result.candidates) == len(SCALE_STEPS) + 1
        times.append(result.elapsed_ms)
    found = vision.find(big[:720, :1280], FrameMeta.of_image(big[:720, :1280]), target)
    assert found.match is not None and found.match.rect[:2] == (590, 470)
    median = statistics.median(times)
    with capsys.disabled():
        print(
            f"\n[vision perf] 1280x720, 100x40, 10회 계산(못 찾음), 스레드 {WORKERS}: "
            f"중앙값 {median:.1f} ms (목표 {budget_ms:.0f} ms)"
        )
    assert median <= budget_ms


def full_search(area: Pixels, template: Pixels) -> tuple[float, tuple[int, int]]:
    """제품 코드와 독립인 전체 계산 (정답)."""
    scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(scores)
    return float(score), (int(loc[0]), int(loc[1]))


@pytest.mark.parametrize("at", [(1001, 501), (7, 663), (1163, 3), (613, 331)])
def test_exact_target_among_similar_patches_found(tmp_path: Path, at: tuple[int, int]) -> None:
    # T6 검수 1 반례: 줄이면 대상과 똑같아지는 패치(미끼)가 여럿인 화면. 대상은 원래 크기로는
    # 하나뿐이고 줄임 격자에 맞지 않는 자리에도 둔다. 방법·배율마다 점수·위치가 전체 계산과
    # 같아야 한다
    rng = np.random.default_rng(77)
    template = rng.integers(20, 235, (48, 96, 3), dtype=np.uint8)
    small = cv2.resize(template, (32, 16), interpolation=cv2.INTER_AREA)
    decoy = np.asarray(cv2.resize(small, (96, 48), interpolation=cv2.INTER_NEAREST), np.uint8)
    area = np.full((720, 1260, 3), 127, dtype=np.uint8)
    for y in (60, 200, 340):
        for x in (30, 210, 390, 570, 750):
            area[y : y + 48, x : x + 96] = decoy
    x, y = at
    area[y : y + 48, x : x + 96] = template
    meta = FrameMeta.of_image(area)
    for methods in (["template"], ["template_multiscale", "template"]):
        target = write_target(tmp_path / methods[0], template, match={"methods": methods})
        result = Vision().find(area, meta, target, exhaustive=True)
        assert result.match is not None, methods
        assert result.match.rect == (x, y, 96, 48) and result.match.score > 0.999
        for candidate in result.candidates:
            spec_template = cv2.resize(
                template,
                (candidate.rect[2], candidate.rect[3]),
                interpolation=cv2.INTER_AREA if candidate.scale < 1 else cv2.INTER_LINEAR,
            )
            if candidate.scale == 1.0:
                spec_template = template
            score, loc = full_search(area, np.asarray(spec_template, np.uint8))
            assert candidate.score == pytest.approx(score, abs=1e-6), candidate
            assert candidate.rect[:2] == loc, candidate
    # 대상이 없으면 미끼만 남아 못 찾는다 (최고 점수도 전체 계산과 같다)
    area[y : y + 48, x : x + 96] = 127
    target = write_target(tmp_path / "only", template, match={"methods": ["template"]})
    result = Vision().find(area, meta, target)
    assert result.match is None and result.best is not None
    assert result.best.score == pytest.approx(full_search(area, template)[0], abs=1e-6)


def test_empty_search_area_no_candidates(tmp_path: Path, title: Pixels) -> None:
    # T6 검수 3: 검색 범위가 프레임과 겹치지 않으면 컬러·회색조 모두 후보 없이 못 찾음
    image = crop(title, START_BUTTON)
    for rgb in (True, False):
        target = write_target(tmp_path / str(rgb), image, match={"rgb": rgb})
        outside = Vision().find(title, FrameMeta.of_image(title), target, region=(3000, 0, 10, 10))
        assert (outside.match, outside.best, outside.candidates) == (None, None, ())
        assert 0 in outside.search[2:]
        # target의 정규화 범위가 오른쪽 끝(폭 0)
        edge = write_target(
            tmp_path / f"edge{rgb}", image, match={"rgb": rgb}, search={"region": [1, 0, 0.1, 1]}
        )
        result = Vision().find(title, FrameMeta.of_image(title), edge)
        assert (result.match, result.best) == (None, None)
        # 영역 캡처(왼쪽 위 300x300)와 target 범위(아래 절반)가 겹치지 않음
        lower = write_target(
            tmp_path / f"lower{rgb}", image, match={"rgb": rgb}, search={"region": [0, 0.5, 1, 0.5]}
        )
        part = np.ascontiguousarray(title[:300, :300])
        result = Vision().find(part, FrameMeta((1024, 640)), lower)
        assert (result.match, result.best) == (None, None)


def test_empty_image_file_is_target_image_invalid(tmp_path: Path, title: Pixels) -> None:
    # T6 검수 2: 0바이트 PNG는 opencv 예외가 아니라 target_image_invalid
    target = write_target(tmp_path, crop(title, START_BUTTON))
    (tmp_path / "button.png").write_bytes(b"")
    with pytest.raises(PlatformError) as caught:
        Vision().find(title, FrameMeta.of_image(title), target)
    assert caught.value.code == TARGET_IMAGE_INVALID
    with pytest.raises(ValueError):
        decode_image(b"")
