"""화면 지도 저장 `screens.save` (M7 계획 3.5·10장 R4): 자기 세션 폴더에만, 보호 프레임에서는 판정
조건·스크린샷 없음, 이미지·OCR 조건은 그 프레임에서 맞아야, 확정 화면과 같은 키 거부, 이동 합치기.
가짜 예제 게임(타이틀 화면)의 실제 캡처로 본다."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kookabug_core.screen_lock import screens_lock
from kookabug_core.screens import read_screen_file
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-s", "attended": False}
START = [412, 380, 200, 64]
"""타이틀 시작 단추."""


def env_of(game: FakeGame) -> dict[str, str]:
    env = cli_env(game.root.parent, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    return env


@pytest.fixture
def game(tmp_path: Path) -> FakeGame:
    return make_fake_game(tmp_path, draw=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


def capture(client: DaemonClient) -> dict[str, Any]:
    (window,) = client.call("windows.list", {})["windows"]
    return client.call("target.capture", {"window": window["handle"]})


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


def session_folder(game: FakeGame, session: str) -> Path:
    return game.root / "screens" / "_explored" / session


def test_save_writes_candidate_targets_shot(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "저장"})["session"]
        frame = capture(agent)
        saved = agent.call(
            "screens.save",
            {
                "key": "title_screen",
                "frame_id": frame["frame_id"],
                "title": "타이틀",
                "description": "시작 단추가 있는 첫 화면",
                "kind": "screen",
                "detect": {"all": [{"image": START}]},
                "elements": [{"name": "시작", "kind": "button", "rect": START}],
                "moves": [
                    {"via": {"click": {"element": "시작"}}, "to": "login", "status": "tried"},
                    {"via": {"key": "esc"}, "to": None, "status": "untried", "note": "끝내기"},
                ],
            },
        )
    folder = session_folder(game, session)
    rel = f"screens/_explored/{session}/title_screen.screen.json"
    assert (saved["path"], saved["key"], saved["shot"]) == (rel, "title_screen", "saved")
    # 확정 화면 title(예제 워크스페이스)도 이 프레임에 맞는다
    assert [m["node"] for m in saved["also_matches"]] == ["title"]
    screen = read_screen_file(game.root / rel, rel)
    assert screen.version == 1 and screen.origin is not None and screen.origin.session == session
    assert screen.all == (f"screens/_explored/{session}/targets/title_screen/1.target.json",)
    assert (folder / "targets" / "title_screen" / "1.png").is_file()
    assert screen.shot is not None and screen.shot.image.endswith("title_screen.shot.png")
    assert (folder / "title_screen.shot.png").is_file()
    assert screen.elements[0].rect == pytest.approx(
        (412 / 1024, 380 / 640, 200 / 1024, 64 / 640), abs=1e-3
    )
    assert [(m.to, m.status) for m in screen.moves] == [("login", "tried"), (None, "untried")]
    # 확정 화면 경로·targets/screens/에는 아무것도 쓰지 않았다
    assert not (game.root / "screens" / "title_screen.screen.json").exists()
    assert not (game.root / "targets" / "screens").exists()


def test_image_condition_must_match_frame(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from kookabug_platform.vision import Vision

    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "불일치"})["session"]
        frame = capture(agent)
        # 같은 프레임에서 찾지 못하는 경우(매칭 실패 주입): 아무것도 쓰지 않는다
        monkeypatch.setattr(Vision, "find", lambda self, *a, **k: SimpleNamespace(found=False))
        error = refused(
            agent,
            "screens.save",
            {"key": "t", "frame_id": frame["frame_id"], "detect": {"all": [{"image": START}]}},
        )
        assert error.kind == "detect_not_matching"
        # 세션이 열린 동안 본다 (연결 종료의 explore.json 쓰기와 겹치지 않게)
        folder = session_folder(game, session)
        assert sorted(p.name for p in folder.iterdir()) == ["explore.json"]


def test_ocr_condition_must_read(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "OCR"})["session"]
        frame = capture(agent)
        params = {"key": "t", "frame_id": frame["frame_id"]}
        error = refused(
            agent,
            "screens.save",
            {**params, "detect": {"all": [{"ocr": [0, 0, 1024, 640], "text": "없는 글자"}]}},
        )
        assert error.kind == "detect_not_matching"
        assert sorted(p.name for p in session_folder(game, session).iterdir()) == ["explore.json"]
        saved = agent.call(
            "screens.save",
            {**params, "detect": {"all": [{"ocr": [0, 0, 1024, 640], "text": "샘플 RPG"}]}},
        )
    rel = saved["path"]
    (cond,) = read_screen_file(game.root / rel, rel).detect()
    assert cond.ocr is not None and cond.ocr.text == "샘플 RPG"
    assert cond.ocr.rect == (0.0, 0.0, 1.0, 1.0)


def test_protected_frame_detect_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    import cv2

    # 시작 단추를 민감 target으로: 그 화면 프레임은 보호 중
    folder = game.root / "targets" / "secret"
    folder.mkdir(parents=True)
    pixels = cv2.imread(str(game.frames / "title.png"))
    assert pixels is not None
    cv2.imwrite(str(folder / "start.png"), pixels[380:444, 412:612])
    body = {"format": "kookabug.target/0", "image": "start.png", "sensitive": True}
    (folder / "start.target.json").write_text(json.dumps(body), encoding="utf-8")
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "보호"})["session"]
        frame = capture(agent)
        assert frame["protected"]["reason"] == "sensitive_visible"
        error = refused(
            agent,
            "screens.save",
            {"key": "t", "frame_id": frame["frame_id"], "detect": {"all": [{"image": START}]}},
        )
        assert (error.kind, error.data["reason"]) == ("frame_protected", "sensitive_visible")
        # 판정 조건 없이(제목·요소·이동만)는 저장된다: 스크린샷 없음
        saved = agent.call(
            "screens.save",
            {
                "key": "t",
                "frame_id": frame["frame_id"],
                "title": "보호된 화면",
                "elements": [{"name": "시작", "kind": "button", "rect": START}],
            },
        )
    assert (saved["shot"], saved["reason"], saved["incomplete"]) == (
        "omitted",
        "sensitive_visible",
        True,
    )
    out = session_folder(game, session)
    assert not list(out.rglob("*.png"))  # 스크린샷·crop 없음


def test_incomplete_candidate(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "미완성"})
        frame = capture(agent)
        saved = agent.call(
            "screens.save", {"key": "only_title", "frame_id": frame["frame_id"], "title": "제목만"}
        )
        assert saved["incomplete"] is True and saved["shot"] == "omitted"
        # of(합치기 후보)는 확정 화면 ID여야 하고, 있으면 미완성이 아니다
        merged = agent.call(
            "screens.save", {"key": "title_more", "frame_id": frame["frame_id"], "of": "title"}
        )
        assert "incomplete" not in merged
        error = refused(
            agent, "screens.save", {"key": "x", "frame_id": frame["frame_id"], "of": "no_such"}
        )
        assert error.code == -32602


def test_key_equal_confirmed_id_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "충돌"})
        frame = capture(agent)
        error = refused(agent, "screens.save", {"key": "title", "frame_id": frame["frame_id"]})
        assert error.kind == "screen_exists"
        # 키 규칙 밖 (대문자·경로)
        for key in ("Title", "../x", "a/b"):
            with pytest.raises((DaemonError, ValueError)):
                agent.call("screens.save", {"key": key, "frame_id": frame["frame_id"]})


def test_update_merges_moves(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "갱신"})
        frame = capture(agent)
        base = {"key": "card", "frame_id": frame["frame_id"]}
        agent.call(
            "screens.save",
            {
                **base,
                "title": "카드",
                "moves": [{"via": {"key": "esc"}, "to": "title", "status": "tried"}],
            },
        )
        saved = agent.call(
            "screens.save",
            {
                **base,
                "moves": [
                    {"via": {"key": "esc"}, "to": "title", "status": "tried", "note": "닫기"},
                    {"via": {"key": "enter"}, "to": "next_screen", "status": "tried"},
                    {"via": {"click": {"point": [512, 412]}}, "to": None, "status": "untried"},
                ],
            },
        )
        # to는 새 후보 키(규칙) 또는 이미 있는 확정 화면 ID만
        error = refused(
            agent,
            "screens.save",
            {**base, "moves": [{"via": {"key": "a"}, "to": "Not A Key", "status": "tried"}]},
        )
        assert error.code == -32602
    screen = read_screen_file(game.root / saved["path"], saved["path"])
    assert screen.title == "카드"  # 준 필드만 갱신
    assert [(m.key, m.to, m.note) for m in screen.moves if m.key] == [
        ("esc", "title", "닫기"),
        ("enter", "next_screen", None),
    ]
    assert screen.moves[2].point == pytest.approx((0.5, 412 / 640), abs=1e-3)


def test_other_connection_frame_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client(AGENT) as other, daemon.client() as ui:
        agent.call("explore.start", {"title": "남의 프레임"})
        theirs = capture(other)
        ui_frame = capture(ui)
        for frame in (theirs, ui_frame):
            error = refused(agent, "screens.save", {"key": "k", "frame_id": frame["frame_id"]})
            assert error.kind == "frame_not_owned"
        # 세션 없는 연결·사람 연결은 저장하지 않는다
        mine = capture(other)
        assert refused(other, "screens.save", {"key": "k", "frame_id": mine["frame_id"]}).kind == (
            "explore_not_active"
        )
        assert refused(ui, "screens.save", {"key": "k", "frame_id": ui_frame["frame_id"]}).kind == (
            "agent_only"
        )


def test_save_waits_for_screens_lock(game: FakeGame, daemon: ThreadDaemon) -> None:
    # R4: 저장도 screens.lock을 잡는다 — 다른 프로세스·작업이 쥐고 있으면 screens_busy
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "잠금"})
        frame = capture(agent)
        with screens_lock(game.root):
            error = refused(agent, "screens.save", {"key": "k", "frame_id": frame["frame_id"]})
            # explore.json 쓰기(세션 시작)도 같은 잠금 (B2b Mid 4)
            with daemon.client(AGENT) as other:
                assert refused(other, "explore.start", {"title": "잠금 중"}).kind == "screens_busy"
        assert error.kind == "screens_busy"
        assert agent.call("screens.save", {"key": "k", "frame_id": frame["frame_id"]})["key"] == "k"


def test_detection_runs_outside_screens_lock(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B2b Mid 3: crop 확인(이미지 매칭)은 잠금 밖 준비 단계 — 매칭 중에 잠금을 바로 얻을 수 있다
    from kookabug_platform.vision import Vision

    original = Vision.find
    seen: list[bool] = []

    def find_while_probing(self: Vision, *args: Any, **kwargs: Any) -> Any:
        try:
            with screens_lock(game.root, wait_s=0.0):
                seen.append(True)
        except Exception:
            seen.append(False)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Vision, "find", find_while_probing)
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "잠금 범위"})
        frame = capture(agent)
        params = {"key": "k", "frame_id": frame["frame_id"], "detect": {"all": [{"image": START}]}}
        assert agent.call("screens.save", params)["shot"] == "saved"
    assert seen and all(seen)  # 판정·식별 동안 화면 지도 잠금을 쥐지 않았다


def make_junction(link: Path, target: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def test_explored_junction_refused(game: FakeGame, tmp_path: Path) -> None:
    # 검수 재현(explored_junction)을 반대로: screens/_explored가 워크스페이스 밖으로 가는 정션이면
    # 세션을 열지 않고 아무것도 쓰지 않는다
    outside = tmp_path / "outside"
    outside.mkdir()
    (game.root / "screens").mkdir(exist_ok=True)
    make_junction(game.root / "screens" / "_explored", outside)
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        error = refused(agent, "explore.start", {"title": "정션"})
        assert error.kind == "path_outside_workspace"
    assert list(outside.rglob("*")) == []


def test_session_targets_junction_refused(game: FakeGame) -> None:
    import cv2

    # 검수 재현(targets_junction)을 반대로: 세션 폴더의 targets가 확정 targets/screens로 가는
    # 정션이면 저장을 거부하고 확정 파일 바이트는 그대로다
    confirmed = game.root / "targets" / "screens" / "card"
    confirmed.mkdir(parents=True)
    pixels = cv2.imread(str(game.frames / "title.png"))
    assert pixels is not None
    cv2.imwrite(str(confirmed / "1.png"), pixels[0:40, 0:120])
    (confirmed / "1.target.json").write_text(
        '{"format": "kookabug.target/0", "image": "1.png"}', encoding="utf-8"
    )
    before = {p.name: p.read_bytes() for p in confirmed.iterdir()}
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "crop"})["session"]
        make_junction(session_folder(game, session) / "targets", confirmed.parent)
        frame = capture(agent)
        params = {
            "key": "card",
            "frame_id": frame["frame_id"],
            "detect": {"all": [{"image": START}]},
        }
        error = refused(agent, "screens.save", params)
        assert error.kind == "path_outside_workspace"
    assert {p.name: p.read_bytes() for p in confirmed.iterdir()} == before
    assert not (session_folder(game, session) / "card.screen.json").exists()
