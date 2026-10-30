"""화면 검증 노드 (MVP 노드 목록 2장, 구현 계획 M1 T11).

`assert.text`는 실제 OCR(예제 게임 화면)로 읽는다. 모델이 없으면 `ocr_models` 픽스처가 실패한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import target
from helpers.run import tk

from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.registry import default_registry
from kookabug_nodes.assert_ import not_visible, text, visible
from kookabug_sdk import Secret
from kookabug_sdk.testing import fake_context, load_target
from kookabug_sdk.types import Rect, Target

TITLE: Final = FRAMES_DIR / "title.png"
LOGIN: Final = FRAMES_DIR / "login.png"
WORLD: Final = FRAMES_DIR / "world.png"
LOGO_TEXT: Final = Rect(300, 150, 424, 90)
"""타이틀 화면 "SampleRPG"."""
START: Final = "targets/title/start.target.json"


@pytest.fixture(autouse=True)
def _models(ocr_models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))


@pytest.fixture
def start(tmp_path: Path, targets: Any) -> Target:
    return load_target(targets.crop(tmp_path, START, "title.png", (412, 380, 200, 64)))


# ---------------------------------------------------------------- visible·not_visible


def test_visible_ok_fail_and_assertion_flag(start: Target, scene: Any, targets: Any) -> None:
    ctx = fake_context(frames=[TITLE])
    ok = visible(ctx, target=start)
    assert ok.exit == "ok" and ok.outputs["match"].target == start.name
    ctx = fake_context(frames=[LOGIN])
    fail = visible(ctx, target=start, timeout_ms=300)
    assert (fail.exit, fail.kind) == ("fail", "fail") and "보이지 않는다" in (fail.message or "")
    assert ctx.clock.now_ms() == 300  # 기다리다 판정한다
    for name in ("core.assert.visible", "core.assert.not_visible", "core.assert.text"):
        nodedef = default_registry().get(name)
        assert nodedef is not None and nodedef.assertion, name

    # 검증 노드 하나만 성공한 테스트는 통과다 (판정 5행)
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_see"}
        )
        .node("n_see", "core.assert.visible", inputs={"target": target(START)})
    )
    ran = scene(g, setup=lambda root: targets.crop(root, START, "title.png", (412, 380, 200, 64)))
    assert ran.result.verdict == "pass", ran.result.reason


def test_visible_zero_timeout_looks_once(start: Target) -> None:
    ctx = fake_context(frames=[LOGIN, TITLE])
    assert visible(ctx, target=start, timeout_ms=0).exit == "fail"
    assert ctx.captured == 1 and ctx.clock.now_ms() == 0  # 지금 화면 한 번, 기다리지 않음
    ctx = fake_context(frames=[TITLE])
    assert visible(ctx, target=start, timeout_ms=0).exit == "ok"


def test_not_visible(start: Target) -> None:
    assert not_visible(fake_context(frames=[LOGIN]), target=start).exit == "ok"
    ctx = fake_context(frames=[TITLE, TITLE, LOGIN])
    assert not_visible(ctx, target=start).exit == "ok"  # 사라질 때까지 본다
    assert ctx.captured == 3
    ctx = fake_context(frames=[TITLE])
    result = not_visible(ctx, target=start, timeout_ms=200)
    assert result.exit == "fail" and "계속 보인다" in (result.message or "")


# ---------------------------------------------------------------- text


@pytest.mark.parametrize(
    ("check", "ok"),
    [
        ({"equals": "SampleRPG"}, True),
        ({"equals": "  SampleRPG "}, True),
        ({"equals": "Sample"}, False),
        ({"contains": "RPG"}, True),
        ({"contains": "rpg"}, False),
        ({"regex": r"^Sample\w+$"}, True),
        ({"regex": r"\d"}, False),
    ],
)
def test_text_equals_contains_regex(check: dict[str, str], ok: bool) -> None:
    ctx = fake_context(frames=[TITLE])
    result = text(ctx, region=LOGO_TEXT, timeout_ms=0 if not ok else 5000, **check)
    assert result.exit == ("ok" if ok else "fail")
    if ok:
        assert result.outputs["text"] == "SampleRPG"


def test_text_waits_until_matches() -> None:
    ctx = fake_context(frames=[FRAMES_DIR / "login.png", TITLE])
    result = text(ctx, region=LOGO_TEXT, equals="SampleRPG")
    assert result.exit == "ok" and ctx.captured == 2


def test_text_failure_shows_read_text() -> None:
    ctx = fake_context(frames=[TITLE])
    result = text(ctx, region=LOGO_TEXT, equals="Other", timeout_ms=200)
    assert result.exit == "fail"
    assert result.outputs["text"] == "SampleRPG"
    assert "'SampleRPG'" in (result.message or "") and "'Other'" in (result.message or "")


def test_text_needs_exactly_one_check() -> None:
    ctx = fake_context(frames=[TITLE])
    with pytest.raises(ValueError, match="하나만"):
        text(ctx, region=LOGO_TEXT)
    with pytest.raises(ValueError, match="하나만"):
        text(ctx, region=LOGO_TEXT, equals="a", contains="b")
    assert ctx.captured == 0


def test_text_sensitive_masks_failure_message(tmp_path: Path, targets: Any) -> None:
    gold = load_target(
        targets.crop(
            tmp_path,
            "targets/world/gold.target.json",
            "world.png",
            (20, 20, 240, 52),
            extra={"sensitive": True},
        )
    )
    ctx = fake_context(frames=[WORLD])
    result = text(ctx, region=gold, equals="Gold 0", timeout_ms=200)
    assert result.exit == "fail"
    read = result.outputs["text"]
    assert isinstance(read, Secret) and read.reveal() == "Gold 12,345"
    message = result.message or ""
    assert "***" in message and "12,345" not in message
    # 맞으면 ok, 글자는 비밀값으로
    ok = text(fake_context(frames=[WORLD]), region=gold, contains="12,345")
    assert ok.exit == "ok" and isinstance(ok.outputs["text"], Secret)


def test_text_region_target_missing_fails(start: Target) -> None:
    ctx = fake_context(frames=[LOGIN])
    result = text(ctx, region=start, contains="게임", timeout_ms=200)
    assert result.exit == "fail" and "보이지 않는다" in (result.message or "")
