"""OCR 노드 (MVP 노드 목록 5장, 구현 계획 M1 T11).

실제 OCR 모델로 예제 게임 화면을 읽는다. 모델이 없으면 `ocr_models` 픽스처가 실패한다(받기 명령
안내). 느린 추론은 모델 대신 지연을 넣은 세션으로 실제 OCR 경로(추론 뒤 기한 확인)에서 본다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Final

import numpy as np
import pytest
from helpers.graphs import GraphBuilder, make_workspace
from helpers.m1 import ScenePlatform, StubEngines, clicks, run_on, write_target
from helpers.run import tk

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine.cancel import CancelToken
from kookabug_core.engine.clock import SystemClock
from kookabug_nodes.ocr import click_text, find_text, parse_number, read, wait_text
from kookabug_platform.ocr.engine import RapidOcrEngine
from kookabug_platform.ocr.engine import parse_number as platform_parse_number
from kookabug_sdk import Secret
from kookabug_sdk.testing import fake_context, load_target
from kookabug_sdk.types import Match, OcrLine, OcrResult, Point, Rect

TITLE: Final = FRAMES_DIR / "title.png"
LOBBY: Final = FRAMES_DIR / "lobby.png"
WORLD: Final = FRAMES_DIR / "world.png"
GOLD: Final = Rect(20, 20, 240, 52)
"""월드 화면 "Gold 12,345"."""
SERVERS: Final = Rect(262, 190, 500, 170)
"""로비의 서버 두 줄."""
SERVER2_ROW: Final = Rect(262, 280, 500, 64)


@pytest.fixture(autouse=True)
def _models(ocr_models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))


def gold_target(root: Path, targets: Any, *, sensitive: bool) -> Path:
    extra = {"sensitive": True} if sensitive else None
    return targets.crop(
        root, "targets/world/gold.target.json", "world.png", (20, 20, 240, 52), extra=extra
    )


# ---------------------------------------------------------------- core.ocr.read


def test_read_text_number_confidence() -> None:
    ctx = fake_context(frames=[WORLD])
    result = read(ctx, region=GOLD, parse="number")
    assert result.exit == "done"
    assert result.outputs["text"] == "Gold 12,345"
    assert result.outputs["number"] == 12345
    confidence = result.outputs["confidence"]
    assert isinstance(confidence, float) and 0.5 < confidence <= 1.0
    text_only = read(fake_context(frames=[WORLD]), region=GOLD)
    assert text_only.outputs["number"] is None  # parse: text면 수를 내지 않는다


def test_read_unreadable() -> None:
    blank = read(fake_context(frames=[TITLE]), region=Rect(0, 0, 120, 60))
    assert blank.exit == "unreadable" and blank.kind == "fail"
    no_number = read(fake_context(frames=[TITLE]), region=Rect(300, 150, 424, 90), parse="number")
    assert no_number.exit == "unreadable" and "수가 없다" in (no_number.message or "")


def test_read_region_target_reads_inside_found_box(tmp_path: Path, targets: Any) -> None:
    gold = load_target(gold_target(tmp_path, targets, sensitive=False))
    result = read(fake_context(frames=[WORLD]), region=gold, parse="number")
    assert (result.exit, result.outputs["number"]) == ("done", 12345)
    missing = read(fake_context(frames=[TITLE]), region=gold)
    assert missing.exit == "unreadable" and "gold" in (missing.message or "")


@pytest.mark.parametrize(
    "text",
    ["Gold 12,345", "-1,234.5 left", "x 1 234 567", "v0.1", "none", "12,34", chr(0x2212) + "7"],
)
def test_parse_number_same_as_platform(text: str) -> None:
    assert parse_number(text) == platform_parse_number(text)


# ---------------------------------------------------------------- core.ocr.wait_text


def test_wait_text_found_timeout() -> None:
    ctx = fake_context(frames=[TITLE, LOBBY])
    found = wait_text(ctx, region=SERVERS, contains="Server 2")
    assert found.exit == "found" and ctx.captured == 2
    assert found.outputs["text"] == "Server 1 원활\nServer 2 혼잡"
    match = found.outputs["match"]
    assert isinstance(match, Match) and match.method == "ocr"
    assert _inside(match.click_point, SERVER2_ROW)

    regex = wait_text(fake_context(frames=[LOBBY]), region=SERVERS, regex=r"Server \d 혼잡")
    assert regex.exit == "found" and _inside(regex.outputs["match"].click_point, SERVER2_ROW)

    ctx = fake_context(frames=[TITLE])
    timeout = wait_text(ctx, region=SERVERS, contains="Server", timeout_ms=300)
    assert timeout.exit == "timeout" and ctx.clock.now_ms() == 300
    assert ctx.artifacts.saved["timeout"].path == TITLE


def test_find_text_box_then_row_then_all() -> None:
    """OCR `lines`는 글자 상자다. 상자 하나 → 한 줄의 상자들 → 여러 줄 전부 순으로 찾는다."""
    a = OcrLine("Server 2", Rect(0, 0, 80, 20), 0.9)
    b = OcrLine("혼잡", Rect(90, 0, 40, 20), 0.8)
    c = OcrLine("입장", Rect(0, 40, 40, 20), 0.9)
    result = OcrResult("Server 2 혼잡\n입장", (a, b, c), 0.87)
    assert find_text(result, contains="Server") == (a,)
    assert find_text(result, regex=r"2 혼잡") == (a, b)
    assert find_text(result, regex=r"혼잡\n입장") == (a, b, c)
    assert find_text(result, contains="a.b") is None  # contains는 정규식이 아니다
    assert find_text(result, contains="없음") is None


def test_wait_text_needs_exactly_one_of_contains_regex() -> None:
    ctx = fake_context(frames=[LOBBY])
    for kwargs in ({}, {"contains": "a", "regex": "b"}):
        with pytest.raises(ValueError, match="하나만"):
            wait_text(ctx, region=SERVERS, **kwargs)
    assert ctx.captured == 0


def test_wait_text_short_timeout_with_slow_ocr_exits_timeout(scene: Any) -> None:
    """추론 한 번(500 ms)은 끊을 수 없다: 노드 기한 100 ms를 넘겨 끝난 추론의 결과는 버리고 노드는
    `timeout`이다 (글자가 맞아도). 걸린 시간 ≤ 노드 기한 + 추론 한 번."""
    infer_s = 0.5
    engine = RapidOcrEngine(det=_SlowDet(infer_s), rec=_Rec(), characters=["가", "나", "A"])
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_wait"}
        )
        .node(
            "n_wait",
            "core.ocr.wait_text",
            inputs={"region": [262, 190, 500, 170], "contains": "가A", "timeout_ms": 100},
            next={"timeout": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    began = time.monotonic()
    ran = scene(g, ocr=engine, clock=SystemClock(CancelToken()))
    elapsed = time.monotonic() - began
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_wait")
    assert (end["status"], end["exit"]) == ("fail", "timeout") and "error" not in end
    assert end["duration_ms"] <= 100 + infer_s * 1000 + 300
    assert elapsed < 5


def test_assert_text_late_first_read_not_in_fail_output(scene: Any) -> None:
    """첫 읽기는 노드 기한으로 끊지 않지만 기한 뒤에 끝났으면 버린다: `core.assert.text`의 fail
    출력·메시지에 기한 밖 글자가 나가지 않는다 (CI 수정 7 검수 H1)."""
    engine = RapidOcrEngine(det=_SlowDet(0.5), rec=_Rec(), characters=["가", "나", "A"])
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_check"}
        )
        .node(
            "n_check",
            "core.assert.text",
            inputs={"region": [262, 190, 500, 170], "equals": "가A", "timeout_ms": 100},
        )
    )
    ran = scene(g, ocr=engine, clock=SystemClock(CancelToken()))
    end = ran.end("n_check")
    assert end["exit"] == "fail" and end["outputs"]["text"] == "", end
    assert "가A" not in end["message"] and "읽지 못했다" in end["message"], end


# ---------------------------------------------------------------- core.ocr.click_text


def test_click_text_clicks_line_center() -> None:
    ctx = fake_context(frames=[LOBBY])
    result = click_text(ctx, region=SERVERS, text="Server 2")
    assert result.exit == "done"
    match = result.outputs["match"]
    (call,) = ctx.input.calls
    assert call.method == "click" and call.args == (match,)
    assert match.click_point == match.rect.center and _inside(match.click_point, SERVER2_ROW)


def test_click_text_not_found_does_not_input() -> None:
    ctx = fake_context(frames=[TITLE])
    result = click_text(ctx, region=SERVERS, text="Server 2", timeout_ms=200)
    assert result.exit == "not_found" and ctx.input.calls == []
    assert ctx.artifacts.saved["not_found"].path == TITLE


def test_click_text_through_input_service_changes_scene(scene: Any) -> None:
    """실행기에서: 로비의 "Server 2" 줄을 읽어 누르면 장면 표가 그 서버를 고른 화면이 된다."""
    g = to_lobby(tk()).node(
        "n_pick",
        "core.ocr.click_text",
        inputs={"region": [262, 190, 500, 170], "text": "Server 2"},
        next={"done": "n_pass"},
    )
    ran = scene(g.node("n_pass", "core.test.pass"))
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.platform.scenario.latest().state.scene == "lobby_server2"
    step = ran.step("n_pick")
    assert ran.artifacts.texts[f"steps/{step}_ocr.txt"] == "Server 1 원활\nServer 2 혼잡"


# ---------------------------------------------------------------- sensitive


def test_sensitive_target_outputs_secret_and_number_null(tmp_path: Path, targets: Any) -> None:
    gold = load_target(gold_target(tmp_path, targets, sensitive=True))
    result = read(fake_context(frames=[WORLD]), region=gold, parse="number")
    assert result.exit == "done"
    text = result.outputs["text"]
    assert isinstance(text, Secret) and text.reveal() == "Gold 12,345"
    assert result.outputs["number"] is None
    found = wait_text(fake_context(frames=[WORLD]), region=gold, contains="12,345")
    assert found.exit == "found" and isinstance(found.outputs["text"], Secret)
    # 수가 없으면 비밀값이어도 unreadable (메시지에는 가린 값만)
    ctx = fake_context(frames=[WORLD])
    missing = read(ctx, region=gold, parse="number")
    assert "12,345" not in repr(missing)


# ---------------------------------------------------------------- 재검증 (검수 T11-1 1)


class _ResizeDuringOcr(StubEngines):
    """OCR을 읽는 동안 창이 1024x640/96 DPI → 1536x960/144 DPI로 바뀐다 (읽은 뒤 클릭 전에)."""

    def read_text(self, image: Any, **kwargs: Any) -> OcrResult:
        assert self.platform is not None
        self.platform.resize((1536, 960), dpi=144)
        return OcrResult("Start", (OcrLine("Start", Rect(412, 380, 200, 64), 0.99),), 0.99)


def _resize_run(tmp_path: Path, area: str, *, later: bool) -> Any:
    ws = make_workspace(tmp_path)
    rel = write_target(ws, "targets/start.target.json")
    platform = ScenePlatform.sample(
        engines=_ResizeDuringOcr(answers={rel: [Rect(412, 380, 200, 64)]})
    )
    region: Any = None
    if area == "rect":
        region = [400, 360, 300, 100]
    elif area == "target":
        region = {"$target": rel}
    g = tk().entry("n_launch")
    g.node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_ocr"})
    inputs: dict[str, Any] = {"timeout_ms": 0}
    if region is not None:
        inputs["region"] = region
    if later:
        # wait_text가 낸 match를 나중에 입력 노드가 쓴다
        g.node(
            "n_ocr",
            "core.ocr.wait_text",
            inputs={**inputs, "contains": "Start"},
            next={"found": "n_click"},
        )
        g.node(
            "n_click",
            "core.input.click",
            inputs={"match": {"$link": "n_ocr.match"}},
            next={"done": "n_pass"},
        )
    else:
        g.node(
            "n_ocr",
            "core.ocr.click_text",
            inputs={**inputs, "text": "Start"},
            next={"done": "n_pass"},
        )
    g.node("n_pass", "core.test.pass")
    return run_on(ws, g, platform)


@pytest.mark.parametrize("area", ["full", "rect", "target"])
@pytest.mark.parametrize("later", [False, True], ids=["click_text", "wait_text_then_click"])
def test_ocr_match_keeps_capture_observation_for_revalidation(
    tmp_path: Path, area: str, later: bool
) -> None:
    """OCR 줄 `Match`는 영역 종류와 무관하게 읽은 캡처의 관측(크기·DPI·캡처 방식)을 싣는다. 읽은
    뒤 창 크기·DPI가 바뀌면 옛 좌표를 누르지 않고 `stale_observation`이다."""
    ran = _resize_run(tmp_path, area, later=later)
    assert (ran.result.verdict, clicks(ran.platform)) == ("fail", [])
    node = "n_click" if later else "n_ocr"
    assert ran.end(node)["message"].startswith("stale_observation:")
    if later:
        seen = ran.end("n_ocr")["outputs"]["match"]
        assert seen is not None


def test_ocr_result_carries_capture_observation() -> None:
    """가짜 ctx(파일 이미지)에서도 OCR 결과에 관측이 실린다 — 줄 `Match`의 `frame_info`."""
    result = wait_text(fake_context(frames=[LOBBY]), region=SERVERS, contains="Server 2")
    match = result.outputs["match"]
    assert match.frame_info is not None
    assert (match.frame_info.client_size, match.frame_info.dpi) == ((1024, 640), 96)


# ---------------------------------------------------------------- 도우미


def _inside(point: Point, rect: Rect) -> bool:
    return rect.x <= point.x < rect.x + rect.width and rect.y <= point.y < rect.y + rect.height


def to_lobby(g: GraphBuilder) -> GraphBuilder:
    """예제 게임을 띄워 로그인하고 로비까지 (`n_pick`으로 이어진다)."""
    return (
        g.entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_start"}
        )
        .node("n_start", "core.input.click", inputs={"point": [512, 412]}, next={"done": "n_acc"})
        .node(
            "n_acc", "core.input.type_text", inputs={"text": "qa_tester_01"}, next={"done": "n_tab"}
        )
        .node("n_tab", "core.input.key", inputs={"keys": "tab"}, next={"done": "n_pw"})
        .node(
            "n_pw", "core.input.type_text", inputs={"text": "sample-pass-01"}, next={"done": "n_go"}
        )
        .node("n_go", "core.input.key", inputs={"keys": "enter"}, next={"done": "n_lobby"})
        .node(
            "n_lobby",
            "core.ocr.wait_text",
            inputs={"region": [300, 90, 424, 60], "contains": "서버 선택"},
            next={"found": "n_pick"},
        )
    )


class _SlowDet:
    """글자 상자 하나가 있는 확률 지도를 `delay`초 걸려 준다 (실제 OCR 파이프라인의 검출 대역)."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def run(self, x: np.ndarray) -> np.ndarray:
        time.sleep(self.delay)
        _n, _c, h, w = x.shape
        prob = np.zeros((1, 1, h, w), dtype=np.float32)
        prob[0, 0, h // 3 : 2 * h // 3, w // 4 : 3 * w // 4] = 0.95
        return prob


class _Rec:
    """줄마다 "가A" (CTC: blank 0, 가 1, A 3)."""

    def run(self, x: np.ndarray) -> np.ndarray:
        out = np.zeros((x.shape[0], 4, 5), dtype=np.float32)
        for t, token in enumerate([1, 0, 3, 0]):
            out[:, t, token] = 0.9
        return out
