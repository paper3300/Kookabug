"""`kookabug target test` (구현 계획 M1 2.11). 예제 게임 화면 PNG로 본다 (`--image`).

창을 쓰는 경우(`--window`·`--hwnd`)는 프로세스 DPI 인식을 바꾸므로 새 프로세스로 돌린다.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR
from kookabug_cli import main as cli
from kookabug_cli import target_cmd
from kookabug_platform.frames import decode_image
from kookabug_platform.preview import GREEN, RED

START_BUTTON = (412, 380, 200, 64)
TITLE_PNG = FRAMES_DIR / "title.png"


def write_target(folder: Path, box: tuple[int, int, int, int] = START_BUTTON, **spec: Any) -> Path:
    """타이틀 화면에서 상자를 잘라 `button.png` + `button.target.json`을 만든다."""
    folder.mkdir(parents=True, exist_ok=True)
    x, y, w, h = box
    image = decode_image(TITLE_PNG.read_bytes())[y : y + h, x : x + w]
    ok, data = cv2.imencode(".png", np.ascontiguousarray(image))
    assert ok
    (folder / "button.png").write_bytes(data.tobytes())
    path = folder / "button.target.json"
    body = {"format": "kookabug.target/0", "image": "button.png", **spec}
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


def run(*argv: str | Path) -> tuple[int, str, str]:
    args: argparse.Namespace = cli.build_parser().parse_args(["target", "test", *map(str, argv)])
    out, err = io.StringIO(), io.StringIO()
    code = target_cmd.run(args, out, err)
    return code, out.getvalue(), err.getvalue()


def pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    image = decode_image(path.read_bytes())
    b, g, r = image[y, x]
    return int(b), int(g), int(r)


def test_image_found_exit_0_and_preview_written(tmp_path: Path) -> None:
    target = write_target(tmp_path / "targets")
    out = tmp_path / "미리보기" / "found.png"
    code, stdout, _ = run(target, "--image", TITLE_PNG, "--out", out)
    assert code == 0
    assert "찾음" in stdout and str(out) in stdout
    preview = decode_image(out.read_bytes())
    assert preview.shape == (640, 1024, 3)
    # 찾은 상자의 아래 변이 초록, 검색 범위(전체) 테두리가 파랑 계열
    x, y, w, h = START_BUTTON
    assert pixel(out, x + w // 2, y + h - 1) == GREEN
    assert pixel(out, 512, 639)[0] == 255
    # 클릭 지점 십자
    assert pixel(out, 512 + 8, 412) == GREEN


def test_not_found_exit_1_preview_red(tmp_path: Path) -> None:
    target = write_target(tmp_path)
    out = tmp_path / "miss.png"
    code, stdout, _ = run(target, "--image", FRAMES_DIR / "loading.png", "--out", out)
    assert code == 1
    assert "못 찾음" in stdout
    code, stdout, _ = run(target, "--image", FRAMES_DIR / "loading.png", "--out", out, "--json")
    best = json.loads(stdout)["best"]
    bx, by, bw, bh = best["rect"]
    assert pixel(out, bx + bw // 2, by + bh - 1) == RED


def test_json_fields(tmp_path: Path) -> None:
    target = write_target(tmp_path, click={"anchor": "top_left", "offset": [3, 4]})
    out = tmp_path / "p.png"
    code, stdout, stderr = run(target, "--image", TITLE_PNG, "--out", out, "--json", "--all-scales")
    assert (code, stderr) == (0, "")
    report = json.loads(stdout)  # 한 객체만
    assert report["command"] == "target test"
    assert report["target"] == str(target)
    assert report["source"] == {"kind": "image", "path": str(TITLE_PNG)}
    assert report["found"] is True
    assert report["match"] == {
        "rect": list(START_BUTTON),
        "score": 1.0,
        "scale": 1.0,
        "method": "template_multiscale",
        "click": [415, 384],
    }
    assert report["best"]["accepted"] is True and report["best"]["reason"] is None
    assert (report["threshold"], report["expected_scale"]) == (0.85, 1.0)
    assert report["search"] == [0, 0, 1024, 640]
    # --all-scales: 찾은 뒤에도 모든 배율·방법을 계산한다
    assert len(report["candidates"]) == 10
    assert {c["method"] for c in report["candidates"]} == {"template", "template_multiscale"}
    assert report["preview"] == str(out) and out.is_file()
    assert (report["exit_code"], report["error"], report["error_code"]) == (0, None, None)
    assert isinstance(report["elapsed_ms"], float)


def test_outside_workspace_target(tmp_path: Path) -> None:
    # 워크스페이스(kookabug.json) 없는 곳의 target: image는 target 파일 기준
    folder = tmp_path / "흩어진 파일" / "버튼"
    target = write_target(folder)
    assert not any((p / "kookabug.json").exists() for p in (folder, *folder.parents))
    code, stdout, _ = run(target, "--image", TITLE_PNG, "--json", "--out", tmp_path / "o.png")
    assert code == 0 and json.loads(stdout)["found"] is True
    # 기본 미리보기 경로는 임시 폴더 (워크스페이스·target 옆에 파일을 늘리지 않는다)
    code, stdout, _ = run(target, "--image", TITLE_PNG, "--json")
    preview = Path(json.loads(stdout)["preview"])
    assert preview.is_file() and folder not in preview.parents
    # 형식이 틀린 target은 6
    target.write_text('{"format": "kookabug.target/0"}', encoding="utf-8")
    code, stdout, _ = run(target, "--image", TITLE_PNG, "--json")
    assert code == 6 and "형식" in json.loads(stdout)["error"]


def test_bad_image_and_target_image_exit_6(tmp_path: Path) -> None:
    target = write_target(tmp_path)
    code, _, stderr = run(target, "--image", tmp_path / "없음.png")
    assert code == 6 and "읽을 수 없다" in stderr
    (tmp_path / "button.png").write_bytes(b"broken")
    code, stdout, _ = run(target, "--image", TITLE_PNG, "--json")
    report = json.loads(stdout)
    assert (code, report["error_code"]) == (6, "target_image_invalid")


def cli_process(*argv: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kookabug_cli", *map(str, argv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_window_not_found_exit_6(tmp_path: Path) -> None:
    target = write_target(tmp_path)
    title = f"없는 창 {uuid.uuid4().hex}"
    done = cli_process("target", "test", target, "--window", title, "--json")
    assert done.returncode == 6, done.stderr
    report = json.loads(done.stdout)
    assert report["exit_code"] == 6 and title in report["error"]
    # 창이 아닌 핸들은 window_gone
    done = cli_process("target", "test", target, "--hwnd", "0x1", "--json")
    report = json.loads(done.stdout)
    assert (done.returncode, report["error_code"]) == (6, "window_gone")
    # 출처를 하나도 주지 않으면 사용법 오류 6
    done = cli_process("target", "test", target)
    assert done.returncode == 6 and "--image" in done.stderr


def test_empty_png_files_exit_6_with_json(tmp_path: Path) -> None:
    # T6 검수 2: 0바이트 target 이미지·화면 이미지 — opencv 예외가 새지 않고 6과 JSON 한 객체
    target = write_target(tmp_path)
    (tmp_path / "button.png").write_bytes(b"")
    done = cli_process("target", "test", target, "--image", TITLE_PNG, "--json")
    assert done.returncode == 6 and "Traceback" not in done.stderr, done.stderr
    report = json.loads(done.stdout)
    assert (report["exit_code"], report["error_code"]) == (6, "target_image_invalid")
    good = write_target(tmp_path / "good")
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    done = cli_process("target", "test", good, "--image", empty, "--json")
    assert done.returncode == 6 and "Traceback" not in done.stderr, done.stderr
    assert json.loads(done.stdout)["exit_code"] == 6


def test_grayscale_search_outside_frame_not_found(tmp_path: Path) -> None:
    # T6 검수 3: 회색조 + 프레임 밖 검색 범위 → 예외가 아니라 못 찾음(1)과 JSON
    target = write_target(tmp_path, match={"rgb": False}, search={"region": [1, 0, 0.1, 1]})
    done = cli_process("target", "test", target, "--image", TITLE_PNG, "--json")
    assert done.returncode == 1 and "Traceback" not in done.stderr, done.stderr
    report = json.loads(done.stdout)
    assert (report["found"], report["best"], report["candidates"]) == (False, None, [])
    assert Path(report["preview"]).is_file()
