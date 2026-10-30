"""예제 워크스페이스의 target(`workspace/targets/**`)을 화면 PNG(`frames/`)에서 잘라 다시 만든다.

    uv run python fixtures/sample-game/tools/cut_targets.py          # 쓴다
    uv run python fixtures/sample-game/tools/cut_targets.py --check  # 커밋된 것과 다르면 실패

화면 그림이나 버튼 배치를 바꿔 `frames/`를 다시 찍었으면 이것도 다시 돌린다. 어느 화면의 어느
사각형을 잘랐는지는 아래 `TARGETS` 표가 기준이다(좌표는 1024x640 클라이언트 픽셀).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

from kookabug_core.canonical import canonical_dumps

GAME_DIR: Final = Path(__file__).resolve().parents[1]
FRAMES: Final = GAME_DIR / "frames"
WORKSPACE: Final = GAME_DIR / "workspace"

type Box = tuple[int, int, int, int]
RECORDED: Final = {"client_size": [1024, 640], "dpi": 96}


@dataclass(frozen=True)
class Cut:
    """target 하나: `frame`의 `rect`를 자른다. `keep`을 주면 그 사각형들만 남기고 나머지는 투명
    (알파 0 = 비교에서 뺌). `offset`은 클릭 지점(가운데 기준), `extra`는 target 파일에 더할 키."""

    frame: str
    rect: Box
    keep: tuple[Box, ...] = ()
    offset: tuple[int, int] = (0, 0)
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


TARGETS: Final[dict[str, Cut]] = {
    "targets/title/start_button.target.json": Cut("title.png", (412, 380, 200, 64)),
    # 팝업 제목과 안내 두 줄 (로그인 오류 팝업과 틀은 같고 글자가 다르다)
    "targets/title/maintenance_popup.target.json": Cut("maintenance.png", (262, 170, 500, 190)),
    # 칸 테두리는 포커스에 따라 색이 바뀌므로 칸 왼쪽 이름표를 자르고 클릭 지점을 칸 가운데로 옮긴다
    "targets/login/account_field.target.json": Cut(
        "login.png", (320, 210, 60, 40), offset=(210, 0)
    ),
    "targets/login/password_field.target.json": Cut(
        "login.png", (280, 290, 100, 40), offset=(230, 0)
    ),
    "targets/login/login_button.target.json": Cut("login.png", (432, 380, 160, 56)),
    "targets/login/error_popup.target.json": Cut("login_error.png", (262, 170, 500, 190)),
    # 오류 문구 두 줄 (`core.ocr.read`의 영역)
    "targets/login/error_text.target.json": Cut("login_error.png", (372, 258, 280, 86)),
    # 서버 목록 전체 상자 (`core.ocr.click_text`의 영역). 줄 배경·테두리는 고른 서버에 따라 바뀌므로
    # 제목 "서버 선택" 띠만 비교하고 줄은 투명으로 둔다
    "targets/lobby/server_list.target.json": Cut(
        "lobby.png", (262, 92, 500, 256), keep=((262, 92, 500, 60),)
    ),
    "targets/lobby/enter_world_button.target.json": Cut("lobby.png", (412, 420, 200, 60)),
    "targets/common/loading.target.json": Cut("loading.png", (300, 268, 424, 106)),
    "targets/world/minimap.target.json": Cut("world.png", (824, 20, 180, 180)),
    "targets/inventory/window_title.target.json": Cut("inventory.png", (212, 90, 600, 56)),
    # 깨뜨린 변형: "게임 시작" 대신 로그인 화면의 "로그인" 버튼을 잘못 잘라 넣은 target
    "targets/broken/start_button_swapped.target.json": Cut("login.png", (432, 380, 160, 56)),
}


def decode(path: Path) -> Any:
    return cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)


def cut_image(cut: Cut) -> Any:
    """잘라 낸 픽셀 (BGR, `keep`이 있으면 BGRA)."""
    x, y, w, h = cut.rect
    pixels = np.ascontiguousarray(decode(FRAMES / cut.frame)[y : y + h, x : x + w])
    if not cut.keep:
        return pixels
    alpha = np.zeros((h, w), dtype=np.uint8)
    for kx, ky, kw, kh in cut.keep:
        alpha[ky - y : ky - y + kh, kx - x : kx - x + kw] = 255
    return np.ascontiguousarray(np.dstack([pixels, alpha]))


def target_body(rel: str, cut: Cut) -> dict[str, Any]:
    return {
        "click": {"anchor": "center", "offset": list(cut.offset)},
        "format": "kookabug.target/0",
        "image": image_name(rel),
        "recorded": RECORDED,
        **cut.extra,
    }


def image_name(rel: str) -> str:
    return rel.rsplit("/", 1)[-1].removesuffix(".target.json") + ".png"


def outputs() -> dict[Path, bytes]:
    """쓸 파일 전부 (target 파일과 그 PNG)."""
    files: dict[Path, bytes] = {}
    for rel, cut in TARGETS.items():
        path = WORKSPACE.joinpath(*rel.split("/"))
        files[path] = canonical_dumps(target_body(rel, cut)).encode("utf-8")
        ok, png = cv2.imencode(".png", cut_image(cut))
        if not ok:
            raise RuntimeError(f"{rel}: PNG로 바꿀 수 없다")
        files[path.parent / image_name(rel)] = png.tobytes()
    return files


def stale(files: dict[Path, bytes]) -> list[Path]:
    """커밋된 것과 다른 파일. PNG는 픽셀(알파 포함)로 비교한다 — 인코더 차이로 바이트가 달라도
    같다."""
    different: list[Path] = []
    for path, data in files.items():
        if not path.is_file():
            different.append(path)
        elif path.suffix == ".png":
            old = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_UNCHANGED)
            new = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            if new is None or old is None or old.shape != new.shape or not np.array_equal(old, new):
                different.append(path)
        elif path.read_bytes() != data:
            different.append(path)
    return different


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="예제 워크스페이스 target을 화면 PNG에서 자른다")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 다르면 종료 코드 1")
    args = parser.parse_args(argv)
    files = outputs()
    if args.check:
        different = stale(files)
        for path in different:
            print(f"{path}이(가) 화면 PNG와 다르다. 이 스크립트로 다시 만든다", file=sys.stderr)
        return 1 if different else 0
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
