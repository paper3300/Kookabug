"""커밋된 화면 PNG(`frames/*.png`)가 지금 게임 그림과 같은가 (대화형 데스크톱 필요).

다르면 `uv run python fixtures/sample-game/tools/snap_frames.py`로 다시 찍는다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR, snap_scene
from sample_game.flow import Scene

pytestmark = pytest.mark.desktop

# 글자 가장자리 안티앨리어싱 차이만 허용한다. 같은 PC에서는 0이고, 골드 숫자 다섯 자가 바뀌면
# 379픽셀이 다르다(실측) — 글자 하나가 바뀌어도 넘도록 작게 둔다
PIXEL_TOLERANCE = 48
MAX_DIFF_PIXELS = 32


def read_png(path: Path) -> np.ndarray:
    pixels = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    assert pixels is not None, f"PNG를 읽을 수 없다: {path}"
    return pixels


@pytest.mark.parametrize("scene", [s.value for s in Scene])
def test_committed_pngs_match_live_render(tmp_path: Path, scene: str) -> None:
    committed = read_png(FRAMES_DIR / f"{scene}.png")
    live = snap_scene(scene, workdir=tmp_path)
    assert live.shape == committed.shape
    diff = cv2.absdiff(live, committed).max(axis=2)
    bad = int((diff > PIXEL_TOLERANCE).sum())
    if bad > MAX_DIFF_PIXELS:
        cv2.imwrite(str(tmp_path / f"{scene}.live.png"), live)
    assert bad <= MAX_DIFF_PIXELS, (
        f"{scene}: {bad}픽셀이 다르다 (최대 차 {int(diff.max())}). "
        "fixtures/sample-game/tools/snap_frames.py로 다시 찍는다"
    )
