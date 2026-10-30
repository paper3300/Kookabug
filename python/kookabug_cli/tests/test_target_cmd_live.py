"""`kookabug target test --window` 실제 캡처 (구현 계획 M1 2.11, 대화형 데스크톱·예제 게임).

CLI는 새 프로세스로 돌린다 — 창을 쓰는 명령은 프로세스 DPI 인식을 Per-Monitor V2로 정한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR, launch_sample_game
from kookabug_platform.frames import decode_image

pytestmark = pytest.mark.desktop

START_BUTTON = (412, 380, 200, 64)


def cli(*argv: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "kookabug_cli", *map(str, argv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_window_capture_preview(tmp_path: Path) -> None:
    x, y, w, h = START_BUTTON
    image = decode_image((FRAMES_DIR / "title.png").read_bytes())[y : y + h, x : x + w]
    ok, data = cv2.imencode(".png", np.ascontiguousarray(image))
    assert ok
    (tmp_path / "start.png").write_bytes(data.tobytes())
    target = tmp_path / "start.target.json"
    body = {
        "format": "kookabug.target/0",
        "image": "start.png",
        "recorded": {"client_size": [1024, 640], "dpi": 96},
    }
    target.write_text(json.dumps(body), encoding="utf-8")

    title = f"KBT6 {uuid.uuid4().hex[:8]}"
    with launch_sample_game(("--title", title), workdir=tmp_path / "game") as game:
        out = tmp_path / "preview.png"
        done = cli("target", "test", target, "--window", title, "--out", out, "--json")
        assert done.returncode == 0, done.stdout + done.stderr
        report = json.loads(done.stdout)
        source = report["source"]
        assert (source["kind"], source["hwnd"], source["title"]) == ("window", game.hwnd, title)
        cw, ch = source["client_size"]
        assert report["found"] is True
        # 클라이언트 크기 비율이 기대 배율이고, 버튼 자리는 그 배율만큼 옮겨진다
        scale = ch / 640
        assert report["expected_scale"] == pytest.approx(scale, abs=1e-3)
        mx, my, mw, mh = report["match"]["rect"]
        assert abs(mx - x * scale) <= 3 and abs(my - y * scale) <= 3
        assert abs(mw - w * scale) <= 3 and abs(mh - h * scale) <= 3
        assert report["match"]["score"] > 0.9
        preview = decode_image(out.read_bytes())
        assert preview.shape[:2] == (ch, cw)
        # --hwnd로도 같은 창
        done = cli("target", "test", target, "--hwnd", hex(game.hwnd), "--out", out, "--json")
        assert done.returncode == 0, done.stdout + done.stderr
        assert json.loads(done.stdout)["source"]["hwnd"] == game.hwnd
