"""target 편집 메서드의 실제 창 (M2 계획 2.9, T6): `windows.list`·`target.capture`(WGC)로
예제 게임을 찍고, 저장한 target을 새 캡처에서 다시 찾는다. 대화형 데스크톱이 필요하다(`desktop`).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from helpers.daemon_targets import START_BUTTON, Editor, target_workspace

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import client_rect, launch_sample_game
from kookabug_daemon.client import DaemonError

pytestmark = pytest.mark.desktop


def test_windows_list_has_sample_game(tmp_path: Path) -> None:
    root = target_workspace(tmp_path / "ws")
    title = f"KBT6 {uuid.uuid4().hex[:8]}"
    with launch_sample_game(("--title", title), workdir=tmp_path / "game") as game:
        with ThreadDaemon(root) as d, d.client() as client:
            windows = client.call("windows.list", {})["windows"]
        found = [w for w in windows if w["handle"] == game.hwnd]
        assert len(found) == 1, windows
        window = found[0]
        _, _, cw, ch = client_rect(game.hwnd)
        assert window["title"] == title and window["pid"] == game.pid
        assert window["client_size"] == [cw, ch] and window["dpi"] >= 96


def test_capture_then_save_then_live_find(tmp_path: Path) -> None:
    root = target_workspace(tmp_path / "ws")
    title = f"KBT6 {uuid.uuid4().hex[:8]}"
    rel = "targets/live/start.target.json"
    with (
        launch_sample_game(("--title", title), workdir=tmp_path / "game") as game,
        ThreadDaemon(root) as d,
        d.client() as client,
    ):
        ed = Editor(client)
        frame = client.call("target.capture", {"window": game.hwnd})
        cw, ch = frame["client_size"]
        assert [frame["width"], frame["height"]] == [cw, ch]
        # 화면 배율만큼 커진 시작 버튼 자리 (예제 게임은 1024x640 기준으로 그린다)
        scale = ch / 640
        x, y, w, h = (round(v * scale) for v in START_BUTTON)
        crop = (x + 4, y + 4, w - 8, h - 8)
        saved = ed.save(rel, frame, crop)
        assert saved["preview"]["found"] is True
        assert saved["preview"]["match"]["scale"] == 1.0
        opened = ed.open(rel)
        assert opened["spec"]["recorded"] == {"client_size": [cw, ch], "dpi": frame["dpi"]}
        # 새 캡처에서 저장한 파일 그대로 찾는다
        live = client.call("target.capture", {"window": game.hwnd})
        result = ed.preview(live, opened["spec"], image=opened["spec"]["image"], base=rel)
        assert result["found"] is True
        mx, my, _, _ = result["match"]["rect"]
        assert abs(mx - crop[0]) <= 2 and abs(my - crop[1]) <= 2
        # 없는 창
        with pytest.raises(DaemonError) as caught:
            client.call("target.capture", {"window": 1})
        assert caught.value.kind == "window_not_found"
