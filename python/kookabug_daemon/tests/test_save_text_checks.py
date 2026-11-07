"""저장·내보내는 글자 검사 (M7 계획 3.5b) — 엄격: 비밀값.

보호 기록의 비밀값 키(`FrameGuard.secret_keys` — 에이전트가 `kb_input_type{secret}`으로 넣은 키)의
값이 표의 글자 필드 어디에 들어 있어도(공백·대소문자 무시) 아무것도 쓰지 않고 `secret_in_text`(필드
이름만). 키를 하나라도 못 읽거나 보호 기록이 손상됐으면 `secret_unchecked`. 값은 응답·로그·
`explore.json`·파일 어디에도 없다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kb_testing.proc import wait_until
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값."""
SPACED = "pwq 4417 zx"
"""공백·대소문자만 다른 같은 값."""
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-t", "attended": False}


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    return make_fake_game(tmp_path, draw=False)


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    env = cli_env(game.root.parent, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(game.root.parent / "user")
    with game.daemon(env) as d:
        # 에이전트가 앞서 이 키로 비밀값을 입력했다 (보호 기록의 키 목록)
        d.daemon.guard.secret_keys = {"acc.pw"}
        yield d


def capture(client: DaemonClient) -> dict[str, Any]:
    (window,) = client.call("windows.list", {})["windows"]
    return client.call("target.capture", {"window": window["handle"]})


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=60)
    return caught.value


def our_logs(caplog: pytest.LogCaptureFixture) -> str:
    """Kookabug 로그만 (websockets 라이브러리의 DEBUG 프레임 덤프는 에이전트가 보낸 요청 그대로라
    검사 대상이 아니다)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("kookabug"))


def no_value(*texts: str) -> None:
    for text in texts:
        assert SECRET not in text and SECRET.lower() not in text.lower().replace(" ", "")


# 3.5b 표: (필드 이름, 저장 인자) — 각각 그 필드에만 비밀값
SAVE_CASES: list[tuple[str, dict[str, Any]]] = [
    ("key", {"key": SECRET.lower()}),
    ("of", {"of": SPACED}),
    ("moves[0].to", {"moves": [{"via": {"key": "esc"}, "to": SECRET.lower(), "status": "tried"}]}),
    ("title", {"title": f"로그인 {SPACED}"}),
    # NFKC(전각)·서식 문자(폭 없는 공백) 변형도 같은 값 (B2b Low 7)
    ("title", {"title": "".join(chr(ord(c) + 0xFEE0) for c in SECRET)}),
    ("title", {"title": SECRET[:3] + "​" + SECRET[3:]}),
    ("description", {"description": f"비밀번호는 {SECRET}"}),
    ("elements[0].name", {"elements": [{"name": SECRET, "kind": "text", "rect": [0, 0, 8, 8]}]}),
    (
        "moves[0].via.click.element",
        {
            "elements": [{"name": "칸", "kind": "field", "rect": [0, 0, 8, 8]}],
            "moves": [{"via": {"click": {"element": SPACED}}, "to": None, "status": "untried"}],
        },
    ),
    ("moves[0].via.key", {"moves": [{"via": {"key": SECRET}, "to": None, "status": "untried"}]}),
    (
        "moves[0].note",
        {"moves": [{"via": {"key": "esc"}, "to": None, "status": "untried", "note": SECRET}]},
    ),
    ("detect.all[0].text", {"detect": {"all": [{"ocr": [0, 0, 100, 40], "text": SPACED}]}}),
]


@pytest.mark.parametrize(("field", "extra"), SAVE_CASES, ids=[c[0] for c in SAVE_CASES])
def test_save_field_with_secret_refused(
    game: FakeGame,
    daemon: ThreadDaemon,
    field: str,
    extra: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    with daemon.client(AGENT) as agent:
        session = agent.call("explore.start", {"title": "글자 검사"})["session"]
        frame = capture(agent)
        params = {"key": "card", "frame_id": frame["frame_id"], **extra}
        error = refused(agent, "screens.save", params)
        assert (error.kind, error.data.get("field")) == ("secret_in_text", field)
        no_value(error.message, json.dumps(error.data, ensure_ascii=False))
    folder = game.root / "screens" / "_explored" / session
    # 연결이 끝나 세션이 닫히는 쓰기(임시 파일 → 바꾸기)가 끝난 뒤에 본다
    wait_until(lambda: '"ended"' in (folder / "explore.json").read_text("utf-8"), timeout=30)
    assert sorted(p.name for p in folder.iterdir()) == ["explore.json"]  # 아무것도 쓰지 않음
    no_value((folder / "explore.json").read_text("utf-8"), our_logs(caplog))


@pytest.mark.parametrize("field", ["title", "goal", "window"])
def test_session_fields_with_secret_refused(
    game: FakeGame, daemon: ThreadDaemon, field: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with daemon.client(AGENT) as agent:
        params = {"title": "탐색", field: f"x {SPACED}"}
        error = refused(agent, "explore.start", params)
        assert (error.kind, error.data.get("field")) == ("secret_in_text", field)
        no_value(error.message, our_logs(caplog))
    assert not (game.root / "screens" / "_explored").exists()


def test_unreadable_key_or_corrupt_record_is_unchecked(
    game: FakeGame, daemon: ThreadDaemon
) -> None:
    guard = daemon.daemon.guard
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "검사 불가"})
        frame = capture(agent)
        params = {"key": "card", "frame_id": frame["frame_id"], "title": "아무 글자"}
        guard.secret_keys = {"acc.pw", "acc.missing"}  # 값을 못 읽는 키
        error = refused(agent, "screens.save", params)
        assert (error.kind, error.data.get("reason")) == ("secret_unchecked", "acc.missing")
        guard.secret_keys = {"acc.pw"}
        guard.save_blocked = True  # 보호 기록 손상 (B2a R1)
        assert refused(agent, "screens.save", params).kind == "secret_unchecked"
        guard.save_blocked = False
        assert agent.call("screens.save", params)["key"] == "card"
