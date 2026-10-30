"""헤드리스용 화면 PNG(`frames/<장면>.png`)를 실제 게임 창에서 다시 찍는다.

    uv run python fixtures/sample-game/tools/snap_frames.py              # 전부
    uv run python fixtures/sample-game/tools/snap_frames.py title lobby  # 일부

장면마다 게임을 `--start-scene <장면>`과 1024x640·Per-Monitor V2로 띄우고, 그 창을 WGC로 캡처해
클라이언트 영역만 저장한다(제품 캡처와 같은 경로, `kb_testing.sample_game.snap_scene`).
대화형 데스크톱이 필요하다. 게임 그림(`sample_game.render`)이나 배치를 바꾸면 다시 찍는다.
`tests/test_frames_fresh.py`가 커밋된 PNG와 지금 그림이 같은지 검사한다.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GAME_DIR.parents[1]
sys.path[:0] = [str(GAME_DIR), str(REPO_ROOT / "tools")]

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from kb_testing.sample_game import FRAMES_DIR, snap_scene  # noqa: E402
from kookabug_core.win import Job  # noqa: E402
from sample_game.flow import Scene  # noqa: E402


def write_png(path: Path, pixels: np.ndarray) -> None:
    ok, data = cv2.imencode(".png", pixels)
    if not ok:
        raise RuntimeError(f"PNG 인코딩 실패: {path}")
    path.write_bytes(data.tobytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="헤드리스용 화면 PNG를 다시 찍는다")
    parser.add_argument("scenes", nargs="*", help=f"장면 ({', '.join(Scene)}). 없으면 전부")
    args = parser.parse_args(argv)
    try:
        scenes = [Scene(s) for s in args.scenes] or list(Scene)
    except ValueError as exc:
        parser.error(str(exc))
    # 이 도구가 띄운 게임은 이 도구가 끝나면(죽어도) 같이 끝난다
    Job.create(kill_on_close=True).keep_until_exit().assign_current()
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kb-snap-") as tmp:
        for scene in scenes:
            pixels = snap_scene(scene.value, workdir=Path(tmp))
            path = FRAMES_DIR / f"{scene.value}.png"
            write_png(path, pixels)
            print(f"{path.relative_to(REPO_ROOT).as_posix()}  {pixels.shape[1]}x{pixels.shape[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
