"""헤드리스용 화면 PNG(`frames/<장면>.png`)를 실제 게임 창에서 다시 찍는다.

    uv run python fixtures/sample-game/tools/snap_frames.py              # 전부
    uv run python fixtures/sample-game/tools/snap_frames.py title lobby  # 일부

장면마다 게임을 `--start-scene <장면>`과 1024x640·Per-Monitor V2로 띄우고, 그 창을 WGC로 캡처해
클라이언트 영역만 저장한다(제품 캡처와 같은 경로, `kb_testing.sample_game.snap_scene`).
대화형 데스크톱이 필요하다. 게임 코드(`sample_game/*.py`)를 바꾸면 다시 찍는다.

찍은 PC의 렌더러(Windows 빌드·판, DPI, 글꼴 다듬기)와 **찍은 장면마다** 그때의 게임 코드 해시를
`tests/frames.snapshot.json`에 남긴다. 일부 장면만 찍으면 나머지 장면의 해시는 그대로라, 코드가
바뀐 뒤라면 그 장면들은 계속 오래된 것으로 남고 도구는 종료 코드 1로 알린다.
`tests/test_frames_fresh.py`가 어디서나 장면별 해시를, 같은 렌더러에서는 커밋된 PNG와 지금 그림의
픽셀을 비교한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = GAME_DIR.parents[1]
sys.path[:0] = [str(GAME_DIR), str(REPO_ROOT / "tools")]

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from kb_testing.sample_game import (  # noqa: E402
    FRAMES_DIR,
    FRAMES_SNAPSHOT,
    read_frames_snapshot,
    snap_scene,
    stale_frames,
    write_frames_snapshot,
)
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
    everything = set(scenes) == set(Scene)
    with tempfile.TemporaryDirectory(prefix="kb-snap-") as tmp:
        snaps = {scene: snap_scene(scene.value, workdir=Path(tmp)) for scene in scenes}
    renderers = {json.dumps(s.renderer, sort_keys=True) for s in snaps.values()}
    if len(renderers) != 1:
        raise SystemExit(f"찍는 동안 렌더러가 바뀌었다: {sorted(renderers)}")
    renderer = next(iter(snaps.values())).renderer
    if not everything and FRAMES_SNAPSHOT.exists():
        before = read_frames_snapshot()["renderer"]
        if before != renderer:
            # 장면마다 다른 PC에서 찍은 PNG가 섞이면 픽셀 비교 기준이 하나가 아니다
            raise SystemExit(
                f"이 PC 렌더러 {renderer}가 기존 PNG를 찍은 렌더러 {before}와 다르다. "
                "장면을 고르지 말고 전부 다시 찍는다"
            )
    for scene, snap in snaps.items():
        path = FRAMES_DIR / f"{scene.value}.png"
        write_png(path, snap.pixels)
        size = f"{snap.pixels.shape[1]}x{snap.pixels.shape[0]}"
        print(f"{path.relative_to(REPO_ROOT).as_posix()}  {size}")
    write_frames_snapshot(renderer, [scene.value for scene in snaps])
    print(f"{FRAMES_SNAPSHOT.relative_to(REPO_ROOT).as_posix()}  {renderer}")
    stale = stale_frames(s.value for s in Scene)
    if stale:
        # 일부만 찍었고 게임 코드가 바뀌었다: 찍지 않은 장면은 오래된 그대로 남는다
        print(f"게임 코드가 바뀐 뒤 아직 안 찍은 장면: {', '.join(stale)}. 이것도 다시 찍는다")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
