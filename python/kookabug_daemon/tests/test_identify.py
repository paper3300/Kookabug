"""화면 식별 `screens.identify` (M7 계획 3.6): 확정 화면 + 자기 세션 후보의 `detect`를 그
프레임에서 평가한다. 판정 조건 없는·`of`만 있는 후보는 넣지 않는다. 보호 프레임에서는 OCR
조건을 평가하지 않는다(`unknown`) — 비밀값 추측 통로 차단. 읽은 글자는 결과에 없다."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kookabug_daemon.client import DaemonClient

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-i", "attended": False}
START = [412, 380, 200, 64]


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    return make_fake_game(tmp_path, draw=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    env = cli_env(game.root.parent, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    with game.daemon(env) as d:
        yield d


def capture(client: DaemonClient) -> dict[str, Any]:
    (window,) = client.call("windows.list", {})["windows"]
    return client.call("target.capture", {"window": window["handle"]})


def names(found: list[dict[str, Any]]) -> list[str]:
    return sorted(m["node"] for m in found)


def test_identify_confirmed_and_session_candidates(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client(AGENT) as other:
        session = agent.call("explore.start", {"title": "식별"})["session"]
        frame = capture(agent)
        # 확정 화면만: 예제 워크스페이스의 title
        found = agent.call("screens.identify", {"frame_id": frame["frame_id"]})
        assert names(found["matches"]) == ["title"]
        assert found["matches"][0]["state"] == "confirmed" and found["checked"] >= 8
        base = {"frame_id": frame["frame_id"]}
        agent.call(
            "screens.save", {**base, "key": "start_copy", "detect": {"all": [{"image": START}]}}
        )
        agent.call("screens.save", {**base, "key": "no_detect", "title": "조건 없음"})
        agent.call("screens.save", {**base, "key": "merge_only", "of": "title"})
        found = agent.call("screens.identify", {"frame_id": frame["frame_id"]})
        assert names(found["matches"]) == ["title", f"x:{session}/start_copy"]
        explored = next(m for m in found["matches"] if m["state"] == "explored")
        assert explored["key"] == "start_copy"
        # 다른 연결(다른 세션)의 후보는 보지 않는다
        other.call("explore.start", {"title": "다른 세션"})
        mine = capture(other)
        theirs = other.call("screens.identify", {"frame_id": mine["frame_id"]})
        assert names(theirs["matches"]) == ["title"]


def test_identify_ocr_unknown_on_protected(game: FakeGame, daemon: ThreadDaemon) -> None:
    import cv2

    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "보호 식별"})["session"]
        frame = capture(agent)
        ocr = {"ocr": [0, 0, 1024, 640], "text": "샘플 RPG"}
        agent.call(
            "screens.save",
            {"frame_id": frame["frame_id"], "key": "by_text", "detect": {"all": [ocr]}},
        )
        clear = agent.call("screens.identify", {"frame_id": frame["frame_id"]})
        assert f"x:{session}/by_text" in names(clear["matches"])
        # 민감 target이 보이게 해 프레임을 보호 상태로
        folder = game.root / "targets" / "secret"
        folder.mkdir(parents=True)
        pixels = cv2.imread(str(game.frames / "title.png"))
        assert pixels is not None
        cv2.imwrite(str(folder / "start.png"), pixels[380:444, 412:612])
        body = {"format": "kookabug.target/0", "image": "start.png", "sensitive": True}
        (folder / "start.target.json").write_text(json.dumps(body), encoding="utf-8")
        guarded = capture(agent)
        assert guarded["protected"]["reason"] == "sensitive_visible"
        found = agent.call("screens.identify", {"frame_id": guarded["frame_id"]})
    # OCR 조건 후보는 확인하지 않음(unknown), 이미지 조건뿐인 확정 화면은 그대로 평가
    assert names(found["unknown"]) == [f"x:{session}/by_text"]
    assert "title" in names(found["matches"])
    assert "샘플" not in json.dumps(found, ensure_ascii=False)  # 읽은 글자는 결과에 없다
