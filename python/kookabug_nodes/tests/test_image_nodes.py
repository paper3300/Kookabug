"""화면·이미지 노드 (MVP 노드 목록 4장, 구현 계획 M1 T11).

가짜 ctx(예제 게임 화면 PNG + 실제 매칭 엔진)로 노드의 출구·기다림·증거를 보고, 실행기 + 예제 게임
장면 표 + 프레임 저장소로 정지 화면·변하는 화면·클릭이 실제 경로에서 도는지 본다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import target
from helpers.run import tk

from kb_testing.sample_game import FRAMES_DIR
from kookabug_nodes._observe import POLL_MS
from kookabug_nodes.image import click, wait, wait_any, wait_gone
from kookabug_nodes.screen import capture, wait_stable
from kookabug_sdk.testing import FakeContext, InputCall, fake_context, load_target
from kookabug_sdk.types import Image, Match, Point, Rect, Target

TITLE: Final = FRAMES_DIR / "title.png"
LOGIN: Final = FRAMES_DIR / "login.png"
LOADING: Final = FRAMES_DIR / "loading.png"
WORLD: Final = FRAMES_DIR / "world.png"

# target 경로 → (화면, 자를 상자)
CROPS: Final[dict[str, tuple[str, tuple[int, int, int, int]]]] = {
    "targets/title/start.target.json": ("title.png", (412, 380, 200, 64)),
    "targets/title/logo.target.json": ("title.png", (300, 150, 424, 90)),
    "targets/login/title.target.json": ("login.png", (300, 95, 424, 50)),
    "targets/loading/text.target.json": ("loading.png", (300, 260, 424, 60)),
}
START: Final = "targets/title/start.target.json"
LOGO: Final = "targets/title/logo.target.json"
LOGIN_TITLE: Final = "targets/login/title.target.json"
LOADING_TEXT: Final = "targets/loading/text.target.json"


def write_targets(targets: Any) -> Callable[[Path], None]:
    def setup(root: Path) -> None:
        for rel, (frame, rect) in CROPS.items():
            targets.crop(root, rel, frame, rect)

    return setup


@pytest.fixture
def loaded(tmp_path: Path, targets: Any) -> dict[str, Target]:
    """가짜 ctx용: 잘라 둔 target들 (경로 → Target)."""
    write_targets(targets)(tmp_path)
    return {rel: load_target(tmp_path / rel) for rel in CROPS}


def frames_ctx(*frames: Path, **kw: Any) -> FakeContext:
    return fake_context(frames=list(frames), **kw)


# ---------------------------------------------------------------- core.image.wait


def test_wait_found(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE)
    result = wait(ctx, target=loaded[START])
    assert result.exit == "found"
    match = result.outputs["match"]
    assert isinstance(match, Match) and match.rect == Rect(412, 380, 200, 64)
    assert match.score > 0.99 and match.target == loaded[START].name
    assert ctx.captured == 1 and ctx.artifacts.saved == {}


def test_wait_found_after_screen_changes(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE, TITLE, LOGIN)
    assert wait(ctx, target=loaded[LOGIN_TITLE]).exit == "found"
    assert ctx.captured == 3
    assert ctx.clock.now_ms() == 2 * POLL_MS


def test_wait_for_absent_target_on_static_screen_exits_timeout(loaded: dict[str, Target]) -> None:
    """정지 화면 = 같은 프레임의 반복이다. 오류가 아니라 `timeout_ms` 안에 `timeout`으로 끝난다."""
    ctx = frames_ctx(TITLE)
    result = wait(ctx, target=loaded[LOGIN_TITLE], timeout_ms=1000)
    assert result.exit == "timeout" and result.kind == "fail"
    assert "1000ms" in (result.message or "")
    assert ctx.clock.now_ms() == 1000  # 기한을 넘겨 기다리지 않는다
    assert ctx.captured == 1000 // POLL_MS  # 0, 100, …, 900ms. 기한이 지난 뒤에는 보지 않는다


def test_timeout_saves_last_frame_artifact(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(LOGIN, TITLE)
    assert wait(ctx, target=loaded[LOADING_TEXT], timeout_ms=300).exit == "timeout"
    saved = ctx.artifacts.saved
    assert list(saved) == ["timeout"]
    assert saved["timeout"].path == TITLE  # 마지막으로 본 프레임


def test_wait_zero_timeout_looks_once(loaded: dict[str, Target]) -> None:
    """`timeout_ms: 0`은 기다리지 않고 지금 화면을 한 번 본다."""
    ctx = frames_ctx(TITLE)
    assert wait(ctx, target=loaded[START], timeout_ms=0).exit == "found"
    ctx = frames_ctx(LOGIN, TITLE)
    assert wait(ctx, target=loaded[START], timeout_ms=0).exit == "timeout"
    assert ctx.captured == 1 and ctx.clock.now_ms() == 0
    assert ctx.artifacts.saved["timeout"].path == LOGIN


# ---------------------------------------------------------------- core.image.wait_any


def test_wait_any_priority_when_both_visible(loaded: dict[str, Target]) -> None:
    targets = {"logo": loaded[LOGO], "start": loaded[START]}
    for exits in (["start", "logo"], ["logo", "start"]):
        ctx = frames_ctx(TITLE, config={"exits": exits})
        result = wait_any(ctx, targets=targets)
        assert result.exit == exits[0]
        assert result.outputs["match"].target == targets[exits[0]].name


def test_wait_any_first_visible_wins(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE, LOGIN, config={"exits": ["loading", "login"]})
    targets = {"loading": loaded[LOADING_TEXT], "login": loaded[LOGIN_TITLE]}
    result = wait_any(ctx, targets=targets)
    assert result.exit == "login" and ctx.captured == 2


def test_wait_any_timeout(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE, config={"exits": ["loading", "login"]})
    targets = {"loading": loaded[LOADING_TEXT], "login": loaded[LOGIN_TITLE]}
    result = wait_any(ctx, targets=targets, timeout_ms=200)
    assert result.exit == "timeout" and "timeout" in ctx.artifacts.saved


@pytest.mark.parametrize(
    ("exits", "names"),
    [(["a", "b"], ["a", "b", "c"]), (["a", "b", "c"], ["a", "b"])],
    ids=["extra_target", "missing_target"],
)
def test_wait_any_targets_must_match_exits(
    loaded: dict[str, Target], exits: list[str], names: list[str]
) -> None:
    ctx = frames_ctx(TITLE, config={"exits": exits})
    targets = {n: loaded[START] for n in names}
    with pytest.raises(ValueError, match=r"config\.exits"):
        wait_any(ctx, targets=targets)
    assert ctx.captured == 0


# ---------------------------------------------------------------- core.image.wait_gone


def test_wait_gone_after_loading(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(LOADING, LOADING, WORLD)
    assert wait_gone(ctx, target=loaded[LOADING_TEXT]).exit == "gone"
    assert ctx.captured == 3


def test_wait_gone_immediately_when_absent(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(WORLD)
    assert wait_gone(ctx, target=loaded[LOADING_TEXT]).exit == "gone"
    assert ctx.captured == 1


def test_wait_gone_timeout(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(LOADING)
    result = wait_gone(ctx, target=loaded[LOADING_TEXT], timeout_ms=500)
    assert result.exit == "timeout" and ctx.clock.now_ms() == 500
    assert ctx.artifacts.saved["timeout"].path == LOADING


# ---------------------------------------------------------------- core.image.click


def test_click_found_clicks_target_click_point(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE)
    result = click(ctx, target=loaded[START], button="right", count=2)
    assert result.exit == "done"
    match = result.outputs["match"]
    assert ctx.input.calls == [InputCall("click", (match,), {"button": "right", "count": 2})]
    assert match.click_point == Point(512, 412)


def test_click_not_found_does_not_input(loaded: dict[str, Target]) -> None:
    ctx = frames_ctx(TITLE)
    result = click(ctx, target=loaded[LOGIN_TITLE], timeout_ms=300)
    assert result.exit == "not_found" and result.kind == "fail"
    assert ctx.input.calls == []
    assert ctx.artifacts.saved["not_found"].path == TITLE


# ---------------------------------------------------------------- core.screen.capture


def test_capture_saves_named_artifact_and_outputs_image() -> None:
    ctx = frames_ctx(TITLE)
    result = capture(ctx, name="before")
    image = result.outputs["image"]
    assert result.exit == "done" and isinstance(image, Image)
    assert ctx.artifacts.saved == {"before": image}


def test_capture_name_and_region(scene: Any) -> None:
    """실행기에서: 영역 캡처(클라이언트 픽셀 상수 `[x, y, w, h]`)를 그 이름으로 남긴다."""
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_shot"}
        )
        .node(
            "n_shot",
            "core.screen.capture",
            inputs={"region": [412, 380, 200, 64], "name": "start button"},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = scene(g)
    assert ran.result.verdict == "pass", ran.result.reason
    end = ran.end("n_shot")
    step = ran.step("n_shot")
    assert end["artifacts"] == [f"steps/{step}_start_button.png"]
    image = end["outputs"]["image"]
    assert (image["width"], image["height"]) == (200, 64)
    pixels = ran.png(f"steps/{step}_start_button.png")
    assert pixels.shape[:2] == (64, 200)


# ---------------------------------------------------------------- core.screen.wait_stable


def test_wait_stable_on_static_screen_stable() -> None:
    ctx = frames_ctx(TITLE)
    result = wait_stable(ctx, stable_ms=500)
    assert result.exit == "stable"
    # 첫 관측부터 500ms 동안 같은 화면: 관측 6번
    assert ctx.clock.now_ms() == 500 and ctx.captured == 6


def test_wait_stable_changing_then_static() -> None:
    ctx = frames_ctx(TITLE, LOGIN, TITLE, LOGIN, WORLD)
    result = wait_stable(ctx, stable_ms=300)
    assert result.exit == "stable"
    # 다섯 번째 관측(400ms)부터 멈췄다 → 700ms
    assert ctx.clock.now_ms() == 400 + 300


def test_wait_stable_region_ignores_changes_outside() -> None:
    # 서버를 고르면 서버 줄만 바뀌고 제목("서버 선택")은 그대로다
    lobby, chosen = FRAMES_DIR / "lobby.png", FRAMES_DIR / "lobby_server1.png"
    title = Rect(300, 90, 424, 60)
    ctx = frames_ctx(*([lobby, chosen] * 10))
    assert wait_stable(ctx, region=title, stable_ms=200).exit == "stable"
    assert ctx.clock.now_ms() == 200
    ctx = frames_ctx(*([lobby, chosen] * 10))
    assert wait_stable(ctx, stable_ms=200, timeout_ms=1000).exit == "timeout"


def test_wait_stable_never_stable_timeout() -> None:
    ctx = frames_ctx(*([TITLE, LOGIN] * 20))
    result = wait_stable(ctx, stable_ms=200, timeout_ms=1000)
    assert result.exit == "timeout" and ctx.clock.now_ms() == 1000
    assert "timeout" in ctx.artifacts.saved


def test_wait_stable_tolerance() -> None:
    # 두 화면은 조금 다르다: 기준을 넉넉히 주면 멈춘 것으로 본다
    ctx = frames_ctx(*([LOGIN, FRAMES_DIR / "login_error.png"] * 20))
    assert wait_stable(ctx, stable_ms=200, timeout_ms=1000).exit == "timeout"
    ctx = frames_ctx(*([LOGIN, FRAMES_DIR / "login_error.png"] * 20))
    assert wait_stable(ctx, stable_ms=200, tolerance=0.5, timeout_ms=1000).exit == "stable"


# ---------------------------------------------------------------- 검수 T11-1 3: 화면 밖 영역

OFFSCREEN: Final = Rect(1400, 200, 200, 100)
"""1024x640 화면 밖."""


def sized(path: Path, size: tuple[int, int] = (1024, 640)) -> Image:
    """크기를 아는 이미지 (실제 캡처의 참조 이미지처럼)."""
    return Image(size[0], size[1], path=path)


def test_offscreen_region_is_not_stable_even_when_size_unknown() -> None:
    """크기를 모르는 파일 이미지: 겹치는 픽셀이 없으면 차이 1 — 변하는 화면을 멈췄다고 하지
    않는다 (검수 반례 그대로)."""
    ctx = frames_ctx(*([TITLE, LOGIN] * 10))
    result = wait_stable(ctx, region=OFFSCREEN, stable_ms=200, timeout_ms=500)
    assert result.exit == "timeout"
    ctx = frames_ctx(TITLE)  # 같은 화면이어도
    assert wait_stable(ctx, region=OFFSCREEN, stable_ms=200, timeout_ms=500).exit == "timeout"


def test_offscreen_region_is_error_with_client_size() -> None:
    ctx = fake_context(frames=[sized(TITLE), sized(LOGIN)])
    with pytest.raises(ValueError, match=r"\[1400, 200, 200, 100\].*1024x640") as exc:
        wait_stable(ctx, region=OFFSCREEN)
    assert "set_size" in str(exc.value)
    assert ctx.captured == 1  # 첫 관측에서 끝낸다
    # 일부만 겹치면 그 부분을 본다
    ctx = fake_context(frames=[sized(TITLE)])
    assert wait_stable(ctx, region=Rect(1000, 600, 200, 200), stable_ms=200).exit == "stable"


def test_region_goes_offscreen_after_resolution_change() -> None:
    """큰 창에서 잡은 영역이 창이 작아진 뒤 밖으로 나가면 그때 `error`다."""
    big, small = (2048, 1280), (1024, 640)
    ctx = fake_context(frames=[sized(TITLE, big), sized(TITLE, big), sized(TITLE, small)])
    with pytest.raises(ValueError, match="1024x640"):
        wait_stable(ctx, region=OFFSCREEN, stable_ms=10_000, timeout_ms=5000)
    assert ctx.captured == 3


def test_offscreen_region_through_executor_is_error(scene: Any) -> None:
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_st"})
        .node(
            "n_st",
            "core.screen.wait_stable",
            inputs={"region": [1400, 200, 200, 100], "stable_ms": 200},
            next={"stable": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = scene(g)
    assert ran.result.verdict == "error"
    error = ran.end("n_st")["error"]
    assert "1024x640" in error["message"] and "[1400, 200, 200, 100]" in error["message"]


def test_offscreen_ocr_region_is_error() -> None:
    from kookabug_nodes.ocr import read

    with pytest.raises(ValueError, match="1024x640"):
        read(fake_context(frames=[sized(TITLE)]), region=OFFSCREEN)


def test_wait_stable_with_real_frame_store_small_budget(scene: Any) -> None:
    """계획 2차 검수 N2: 연속 두 관측 비교가 실제 프레임 저장소(작은 예산)에서 `frame_expired` 없이
    돈다. 로딩 화면이 3프레임 뒤 월드로 바뀐 다음 멈춘다. 저장소는 스텝의 최근 두 캡처만 쥔다."""
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_start"}
        )
        .node("n_start", "core.input.click", inputs={"point": [512, 412]}, next={"done": "n_acc"})
        .node(
            "n_acc", "core.input.type_text", inputs={"text": "qa_tester_01"}, next={"done": "n_tab"}
        )
        .node("n_tab", "core.input.key", inputs={"keys": "tab"}, next={"done": "n_pw"})
        .node(
            "n_pw",
            "core.input.type_text",
            inputs={"text": "sample-pass-01"},
            next={"done": "n_login"},
        )
        .node("n_login", "core.input.key", inputs={"keys": "enter"}, next={"done": "n_server"})
        .node(
            "n_server", "core.input.click", inputs={"point": [512, 232]}, next={"done": "n_enter"}
        )
        .node(
            "n_enter", "core.input.click", inputs={"point": [512, 450]}, next={"done": "n_stable"}
        )
        .node(
            "n_stable",
            "core.screen.wait_stable",
            inputs={"stable_ms": 300, "timeout_ms": 5000},
            next={"stable": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    frame_bytes = 1024 * 640 * 3
    ran = scene(g, budget_bytes=frame_bytes // 2)  # 한 프레임도 못 넣는 예산
    assert ran.result.verdict == "pass", ran.result.reason
    game = ran.platform.scenario.latest()
    assert game.state.scene == "world"
    # 로딩 3프레임(변함) 뒤 월드가 300ms 멈춤: 관측 사이 100ms
    assert ran.end("n_stable")["exit"] == "stable"
    # 작업 중·최근 두 개만 쥐었다 (출력 참조는 예산으로 버려짐)
    assert ran.store.peak_bytes <= 2 * frame_bytes
    assert ran.store.held() == set()


def test_wait_for_absent_target_through_executor_is_timeout_not_capture_error(
    scene: Any, targets: Any
) -> None:
    """실행기·프레임 저장소에서도 정지 화면 대기는 `capture_timeout` 오류가 아니라 `timeout`이고
    그 노드가 마지막 프레임을 `_timeout`으로, 실행기가 `_fail`로 남긴다."""
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_wait"}
        )
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOGIN_TITLE), "timeout_ms": 1500},
        )
    )
    ran = scene(g, setup=write_targets(targets))
    assert (ran.result.verdict, ran.result.code) == ("fail", "unhandled_fail")
    end = ran.end("n_wait")
    step = ran.step("n_wait")
    assert (end["status"], end["exit"]) == ("fail", "timeout") and "error" not in end
    assert end["artifacts"] == [f"steps/{step}_timeout.png", f"steps/{step}_fail.png"]
    assert end["duration_ms"] <= 1500
    title = ran.png(f"steps/{step}_timeout.png")
    assert title.shape[:2] == (640, 1024)
