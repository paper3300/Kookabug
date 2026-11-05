"""target 재사용 = 재생했을 때 같은 요소를 누르는가 (M4 계획 2.6 "재사용", 검수 M1, T6).

성공 판정은 "새 PNG 없음"이 아니라 재생 규칙(`Vision.find` — 검색 범위·오프셋 포함)으로 찾은 클릭
점이 녹화 클릭과 같은 요소 안인가다.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR, WORKSPACE_DIR
from kookabug_platform.dpi import pixels_to_normalized
from kookabug_platform.recorder.crop import crop_click
from kookabug_platform.recorder.targets import SessionTargets, find_reuse, workspace_candidates
from kookabug_platform.vision import FrameMeta, Vision

CLIENT = (1024, 640)
META = FrameMeta(CLIENT)


def frame(name: str) -> np.ndarray:
    data = np.fromfile(FRAMES_DIR / f"{name}.png", np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


def write_target(
    root: Path,
    name: str,
    image: np.ndarray,
    box: tuple[int, int, int, int],
    offset: tuple[float, float],
    region: tuple[int, int, int, int] | None = None,
) -> str:
    folder = root / "targets" / "t"
    folder.mkdir(parents=True, exist_ok=True)
    x, y, w, h = box
    ok, png = cv2.imencode(".png", image[y : y + h, x : x + w])
    assert ok
    (folder / f"{name}.png").write_bytes(png.tobytes())
    spec: dict[str, object] = {
        "format": "kookabug.target/0",
        "image": f"{name}.png",
        "click": {"anchor": "center", "offset": list(offset)},
        "recorded": {"client_size": list(CLIENT), "dpi": 96},
    }
    if region is not None:
        spec["search"] = {"region": list(pixels_to_normalized(region, CLIENT))}
    (folder / f"{name}.target.json").write_text(json.dumps(spec), encoding="utf-8")
    return f"targets/t/{name}.target.json"


def center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return box[0] + (box[2] - 1) / 2, box[1] + (box[3] - 1) / 2


def reuse(root: Path, image: np.ndarray, point: tuple[int, int], folder: str = "") -> str | None:
    crop = crop_click(image, point)
    candidates = [c for c in workspace_candidates(root, CLIENT) if c.key.startswith(folder)]
    found = find_reuse(Vision(), image, META, crop, candidates)
    return None if found is None else found.key


def test_reuse_existing_workspace_target_same_click_point() -> None:
    image = frame("login")
    # targets/broken/에 같은 그림(일부러 바꾼 시작 단추)이 있어 로그인 폴더만 본다
    found = reuse(WORKSPACE_DIR, image, (512, 408), "targets/login/")
    assert found == "targets/login/login_button.target.json"
    # 계정 칸 클릭은 비밀번호 칸 target(offset이 칸 오른쪽)을 쓰지 않는다
    assert reuse(WORKSPACE_DIR, image, (560, 230)) != "targets/login/password_field.target.json"


def test_no_reuse_when_existing_offset_clicks_elsewhere(tmp_path: Path) -> None:
    image = frame("login")
    area = (420, 370, 300, 76)  # 로그인 단추 + 오른쪽 빈 곳
    cx, cy = center(area)
    write_target(tmp_path, "right_end", image, area, (700 - cx, 408 - cy))
    assert reuse(tmp_path, image, (450, 408)) is None  # 같은 그림이지만 재생은 단추 밖을 누른다
    write_target(tmp_path, "on_button", image, area, (512 - cx, 408 - cy))
    assert reuse(tmp_path, image, (450, 408)) == "targets/t/on_button.target.json"


def test_two_points_in_one_target_area(tmp_path: Path) -> None:
    image = frame("login")
    form = (380, 195, 360, 150)  # 계정 칸 + 비밀번호 칸
    cx, cy = center(form)
    write_target(tmp_path, "form_account", image, form, (560 - cx, 230 - cy))
    assert reuse(tmp_path, image, (560, 230)) == "targets/t/form_account.target.json"
    assert reuse(tmp_path, image, (560, 310)) is None  # 같은 영역 안 다른 요소


def pattern_frame() -> np.ndarray:
    image = np.full((640, 1024, 3), (40, 36, 28), np.uint8)
    for x in (100, 420, 740):
        cv2.rectangle(image, (x, 300), (x + 160, 356), (48, 168, 240), -1)
        cv2.putText(image, "OK", (x + 55, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    return image


def test_no_reuse_when_search_region_finds_other_duplicate(tmp_path: Path) -> None:
    image = pattern_frame()
    button = (416, 296, 168, 64)
    write_target(tmp_path, "left_region", image, button, (0, 0), region=(60, 250, 260, 160))
    assert reuse(tmp_path, image, (500, 328)) is None  # 그 범위에서는 왼쪽 단추를 누른다
    write_target(tmp_path, "mid_region", image, button, (0, 0), region=(380, 250, 260, 160))
    assert reuse(tmp_path, image, (500, 328)) == "targets/t/mid_region.target.json"


def test_session_dedupe_same_button_twice() -> None:
    image = frame("title")
    session = SessionTargets(Vision())
    first = crop_click(image, (512, 412))
    kind1, key1 = session.resolve(image, META, first, name=lambda n: f"click_{n}", frame_t_ns=1)
    second = crop_click(image, (470, 400))
    kind2, key2 = session.resolve(image, META, second, name=lambda n: f"click_{n}", frame_t_ns=2)
    assert (kind1, kind2) == ("draft", "draft") and key1 == key2 == "d1"
    assert len(session.drafts) == 1 and session.drafts["d1"].uses == 2
    # 다른 단추는 새 초안
    other = crop_click(frame("login"), (512, 408))
    _, key3 = session.resolve(frame("login"), META, other, name=lambda n: "x", frame_t_ns=3)
    assert key3 == "d2"
