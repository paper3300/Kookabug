"""커밋된 화면 PNG(`frames/*.png`)가 지금 게임 그림과 같은가.

다르면 `uv run python fixtures/sample-game/tools/snap_frames.py`로 다시 찍는다.

- 게임 코드 해시(어디서나): 장면마다 PNG를 찍은 뒤 게임 코드(`sample_game/*.py`)가 바뀌지
  않았다. 그림을 바꾸고 다시 찍지 않았거나 일부 장면만 다시 찍었으면 남은 장면이 여기서 걸린다
- 픽셀(대화형 데스크톱, PNG를 찍은 렌더러에서만): 지금 그린 창과 PNG가 같다. 렌더러(Windows
  빌드·판, DPI, 글꼴 다듬기)가 다르면 같은 코드라도 창 모서리·글자 가장자리가 달라
  비교하지 않는다 — CI 러너(Server 판)가 그렇다. 그 경우 신선도는 위 해시 검사가 본다
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path
from types import ModuleType, SimpleNamespace

import cv2
import numpy as np
import pytest

from kb_testing import sample_game as sg
from kb_testing.sample_game import (
    FRAMES_DIR,
    FRAMES_SNAPSHOT,
    GAME_DIR,
    read_frames_snapshot,
    snap_scene,
    stale_frames,
)
from sample_game.flow import Scene

# 글자 가장자리 안티앨리어싱 차이만 허용한다. 같은 PC에서는 0이고, 골드 숫자 다섯 자가 바뀌면
# 379픽셀이 다르다(실측) — 글자 하나가 바뀌어도 넘도록 작게 둔다
PIXEL_TOLERANCE = 48
MAX_DIFF_PIXELS = 32
RESNAP = "fixtures/sample-game/tools/snap_frames.py로 다시 찍는다"


def read_png(path: Path) -> np.ndarray:
    pixels = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert pixels is not None, f"PNG를 읽을 수 없다: {path}"
    return pixels


def assert_frames_fresh(frames: Path) -> None:
    """장면마다 PNG와 기록이 있고, 찍은 때의 게임 코드 해시가 지금과 같다."""
    scenes = [s.value for s in Scene]
    assert {p.stem for p in frames.glob("*.png")} == set(scenes)
    assert set(read_frames_snapshot()["scenes"]) == set(scenes)
    stale = stale_frames(scenes)
    assert not stale, (
        f"이 장면 PNG를 찍은 뒤 게임 코드(sample_game/*.py)가 바뀌었다: {', '.join(stale)}. "
        f"{RESNAP}"
    )


def test_snapshot_matches_game_code() -> None:
    assert_frames_fresh(FRAMES_DIR)


# ---------------------------------------------------------------- 찍기 도구 (창 없이)


def load_snap_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "snap_frames_under_test", GAME_DIR / "tools" / "snap_frames.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def game_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ModuleType]:
    """게임 코드·화면 PNG·기록을 임시 사본으로 돌리고, 찍기 도구의 창 캡처만 대역으로 바꾼다."""
    game = tmp_path / "sample-game"
    shutil.copytree(GAME_DIR / "sample_game", game / "sample_game")
    shutil.copytree(FRAMES_DIR, game / "frames")
    (game / "tests").mkdir()
    snapshot = game / "tests" / FRAMES_SNAPSHOT.name
    shutil.copyfile(FRAMES_SNAPSHOT, snapshot)
    renderer = read_frames_snapshot()["renderer"]
    monkeypatch.setattr(sg, "GAME_DIR", game)
    monkeypatch.setattr(sg, "FRAMES_SNAPSHOT", snapshot)
    tool = load_snap_tool()
    monkeypatch.setattr(tool, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(tool, "FRAMES_DIR", game / "frames")
    monkeypatch.setattr(tool, "FRAMES_SNAPSHOT", snapshot)
    job = SimpleNamespace(keep_until_exit=lambda: SimpleNamespace(assign_current=lambda: None))
    monkeypatch.setattr(tool, "Job", SimpleNamespace(create=lambda **_: job))
    blank = np.zeros((640, 1024, 3), dtype=np.uint8)
    monkeypatch.setattr(tool, "snap_scene", lambda *_a, **_k: sg.Snap(blank, renderer))
    return game, tool


def change_drawing(game: Path) -> None:
    render = game / "sample_game" / "render.py"
    text = render.read_text(encoding="utf-8")
    changed, count = re.subn(r'"#[0-9a-fA-F]{6}"', '"#ff00ff"', text)
    assert count > 0
    render.write_text(changed, encoding="utf-8")


def test_partial_snap_after_code_change_leaves_other_scenes_stale(
    game_copy: tuple[Path, ModuleType],
) -> None:
    # 검수 재현: 그림 코드를 바꾼 뒤 title만 다시 찍으면 world 등은 옛 PNG 그대로다. 기록이 그
    # 장면들까지 새 코드로 인증하면(CI는 렌더러가 달라 픽셀 비교도 건너뛴다) 오래된 PNG가 통과한다
    game, tool = game_copy
    change_drawing(game)
    world = (game / "frames" / "world.png").read_bytes()
    assert tool.main(["title"]) == 1  # 안 찍은 장면이 남았다고 알린다
    assert (game / "frames" / "world.png").read_bytes() == world
    stale = stale_frames(s.value for s in Scene)
    assert "title" not in stale and "world" in stale
    assert set(stale) == {s.value for s in Scene} - {"title"}
    with pytest.raises(AssertionError, match="world"):
        assert_frames_fresh(game / "frames")


def test_full_snap_after_code_change_is_fresh(game_copy: tuple[Path, ModuleType]) -> None:
    game, tool = game_copy
    change_drawing(game)
    assert stale_frames(s.value for s in Scene)
    assert tool.main([]) == 0
    assert stale_frames(s.value for s in Scene) == []
    assert_frames_fresh(game / "frames")


def test_partial_snap_without_code_change_is_fresh(game_copy: tuple[Path, ModuleType]) -> None:
    _, tool = game_copy
    assert tool.main(["title", "world"]) == 0
    assert stale_frames(s.value for s in Scene) == []


@pytest.mark.desktop
@pytest.mark.parametrize("scene", [s.value for s in Scene])
def test_committed_pngs_match_live_render(tmp_path: Path, scene: str) -> None:
    committed = read_png(FRAMES_DIR / f"{scene}.png")
    snap = snap_scene(scene, workdir=tmp_path)
    live = snap.pixels
    assert live.shape == committed.shape
    diff = cv2.absdiff(live, committed).max(axis=2)
    bad_mask = diff > PIXEL_TOLERANCE
    bad = int(bad_mask.sum())
    if bad > MAX_DIFF_PIXELS:
        cv2.imwrite(str(tmp_path / f"{scene}.live.png"), live)
    snapped_by = read_frames_snapshot()["renderer"]
    if snap.renderer != snapped_by:
        ys, xs = np.nonzero(bad_mask)
        where = f", x {xs.min()}~{xs.max()} y {ys.min()}~{ys.max()}" if bad else ""
        pytest.skip(
            f"렌더러가 PNG를 찍은 곳과 다르다 (지금 {snap.renderer}, 찍은 곳 {snapped_by}, "
            f"{FRAMES_SNAPSHOT.name}). 참고로 {bad}픽셀이 다르다{where}. "
            "신선도는 test_snapshot_matches_game_code가 본다"
        )
    assert bad <= MAX_DIFF_PIXELS, (
        f"{scene}: {bad}픽셀이 다르다 (최대 차 {int(diff.max())}). {RESNAP}"
    )
