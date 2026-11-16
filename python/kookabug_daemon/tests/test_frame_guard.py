"""에이전트 정지 화면 보호 `frame_guard` (M7 계획 3.5a, UX11 B).

가짜 예제 게임(`kb_testing.fake_game`: 상태 파일 + 칸 값 그리기)과 실제 runner 제어 실행으로 본다.
- 민감 target이 보이는(또는 확인 못 한) 화면은 에이전트 출구에 이미지·글자를 내지 않는다
- UX11 B: 비밀값을 입력한 창은 가리지 않는다 — 캡처 이미지·OCR·crop·화면 저장이 막히지 않고 값이
  그대로 보인다. 보호 기록 파일도 쓰지 않는다
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import (
    ACCOUNT_FIELD,
    LOGIN_BUTTON,
    PASSWORD_FIELD,
    START_BUTTON,
    WINDOW,
    FakeGame,
    make_fake_game,
)
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.frame_guard import FILE

pytestmark = [pytest.mark.process, pytest.mark.timeout(600)]

SECRET = "PWQ4417ZX"
"""검사 전용 가짜 비밀값 (예제 게임 로그인 비밀번호로 쓴다)."""
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-g", "attended": False}
PASSWORD_BOX = [400, 285, 320, 50]


def accept_secret(scenario: dict[str, Any]) -> None:
    scenario["forms"]["login"]["expect"]["password"] = SECRET


@pytest.fixture
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)  # daemon 사전 검증 (이 프로세스)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    return without_forbidden(make_fake_game(tmp_path, scenario_patch=accept_secret))


def without_forbidden(game: FakeGame) -> FakeGame:
    """이 파일은 보호 판정만 본다: 예제 워크스페이스의 금지 동작(M8 "결제")을 비운다. 금지 문구가
    있으면 칸 상자를 모르는 보호 화면에서는 Agent 입력이 확인 못 함으로 거부된다(M8 R6 —
    `test_forbidden.py`가 본다)."""
    path = game.root / "kookabug.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["automation"]["forbidden"] = []
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return game


def env_of(game: FakeGame) -> dict[str, str]:
    tmp = game.root.parent
    env = cli_env(tmp, None, KOOKABUG_SECRET_ACC_PW=SECRET)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp / "user")
    return env


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


# ---------------------------------------------------------------- 조작


def control(agent: DaemonClient, method: str, **params: Any) -> dict[str, Any]:
    done = agent.call(method, {"window": WINDOW, **params}, timeout=120)
    assert done["verdict"] == "pass", done
    return done


def click(agent: DaemonClient, point: tuple[int, int]) -> None:
    control(agent, "control.click", point=list(point))


def handle(client: DaemonClient) -> int:
    (window,) = client.call("windows.list", {})["windows"]
    return int(window["handle"])


def capture(client: DaemonClient) -> dict[str, Any]:
    return client.call("target.capture", {"window": handle(client)})


def to_login(agent: DaemonClient) -> None:
    click(agent, START_BUTTON)
    click(agent, ACCOUNT_FIELD)
    control(agent, "control.type", text="qa_tester_01")


def type_password_after_click(agent: DaemonClient) -> None:
    """칸을 누른 뒤 비밀값 입력 (칸 상자 근거가 있다)."""
    click(agent, PASSWORD_FIELD)
    control(agent, "control.type", secret="acc.pw")


def raw_secret_visible(ui: DaemonClient) -> None:
    """양성 대조군: 사람 연결의 원본 캡처에서 그 칸의 값이 OCR로 읽힌다."""
    frame = capture(ui)
    read = ui.call("target.read_text", {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX})
    assert SECRET in read["text"].replace(" ", "").upper(), read


def images(root: Path, sub: str) -> list[Path]:
    folder = root / ".kookabug" / "cache" / sub
    return sorted(folder.rglob("*.png")) if folder.exists() else []


def assert_withheld(game: FakeGame, frame: dict[str, Any], reason: str) -> None:
    assert "agent_image" not in frame, frame
    assert frame["protected"]["reason"] == reason, frame
    assert frame["protected"]["hint"]
    assert images(game.root, "agent") == []
    cached = {p.name for p in images(game.root, "editor")}
    assert frame["image"]["cache"] not in cached  # 에이전트 프레임은 편집기 캐시에도 없다


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


# ---------------------------------------------------------------- 기본 출구


def test_agent_frame_not_written_to_editor_cache(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        frame = capture(agent)
        assert "protected" not in frame and frame["agent_image"]["cache"]
        # 에이전트 프레임: agent 캐시(보호 통과한 축소본)만, 편집기 캐시에는 쓰지 않는다
        assert images(game.root, "editor") == []
        human = capture(ui)
        assert [p.name for p in images(game.root, "editor")] == [human["image"]["cache"]]


def test_sensitive_visible_omits_whole_image(game: FakeGame, daemon: ThreadDaemon) -> None:
    import cv2
    import numpy as np

    # 같은 모양 두 곳 + 민감 target 둘: 가장 좋은 한 곳만 찾는 매칭으로는 상자만 가릴 수 없다
    title = game.frames / "title.png"
    read = cv2.imread(str(title))
    assert read is not None
    pixels = np.asarray(read)
    button = pixels[380:444, 412:612].copy()
    pixels[480:544, 412:612] = button
    cv2.imwrite(str(title), pixels)
    folder = game.root / "targets" / "secret"
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "start.png"), button)
    cv2.imwrite(str(folder / "logo.png"), pixels[100:180, 312:712])
    for name in ("start", "logo"):
        body = {"format": "kookabug.target/0", "image": f"{name}.png", "sensitive": True}
        (folder / f"{name}.target.json").write_text(json.dumps(body), encoding="utf-8")
    with daemon.client(AGENT) as agent:
        frame = capture(agent)
        assert_withheld(game, frame, "sensitive_visible")
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "sensitive_region"


def test_sensitive_unchecked_omits(game: FakeGame, daemon: ThreadDaemon) -> None:
    folder = game.root / "targets" / "secret"
    folder.mkdir(parents=True, exist_ok=True)
    body = {"format": "kookabug.target/0", "image": "missing.png", "sensitive": True}
    (folder / "broken.target.json").write_text(json.dumps(body), encoding="utf-8")
    with daemon.client(AGENT) as agent:
        assert_withheld(game, capture(agent), "sensitive_unchecked")


# ---------------------------------------------------------------- 비밀값을 입력한 창 (UX11 B)


def test_secret_field_not_protected(game: FakeGame, daemon: ThreadDaemon, ocr_models: Path) -> None:
    """비밀값을 입력한 창도 가리지 않는다: 에이전트 캡처 이미지·OCR에 값이 그대로 보이고, 칸을 겹쳐
    자르는 crop도 된다. 보호 기록 파일은 쓰지 않는다."""
    from kookabug_platform.frames import decode_image
    from kookabug_platform.ocr import models
    from kookabug_platform.ocr.engine import Ocr, RapidOcrEngine

    with daemon.client(AGENT) as agent, daemon.client() as ui:
        to_login(agent)
        type_password_after_click(agent)
        raw_secret_visible(ui)
        frame = capture(agent)
        assert "protected" not in frame and frame["agent_image"]["cache"]
        sent = game.root / ".kookabug" / "cache" / "agent" / frame["agent_image"]["cache"]
        pixels = decode_image(sent.read_bytes())
        read = agent.call(
            "screen.read_text", {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX}, timeout=120
        )
        assert SECRET in read["text"].replace(" ", "").upper(), read
        agent.call(
            "target.save",
            {
                "path": "targets/password_box.target.json",
                "spec": {"format": "kookabug.target/0", "image": "password_box.png"},
                "crop": {"frame_id": frame["frame_id"], "rect": PASSWORD_BOX},
                "base_revision": None,
            },
            timeout=120,
        )
        assert (game.root / "targets" / "password_box.png").exists()
        # 칸이 없어지기를 기다리지 않아도 다른 화면도 그대로
        click(agent, LOGIN_BUTTON)
        assert "protected" not in capture(agent)
    reader = Ocr(RapidOcrEngine(models.find_models(dirs=[ocr_models])))
    text = reader.read(pixels, region=PASSWORD_BOX).text
    assert SECRET in text.replace(" ", "").upper(), text
    assert not (game.root / FILE).exists()


def test_guard_error_is_unchecked(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(frame: Any) -> Any:
        raise RuntimeError("판정 실패 (주입)")

    monkeypatch.setattr(daemon.daemon.targets, "sensitive_visible", boom)
    with daemon.client(AGENT) as agent:
        frame = capture(agent)
        assert_withheld(game, frame, "guard_error")
        assert refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]}).kind == (
            "frame_protected"
        )


# ---------------------------------------------------------------- 보호 창 = 입력 창 (2라운드 H1)


def no_secret_in_game(game: FakeGame) -> None:
    """게임에 비밀값이 가지 않았다 (가짜 입력 기록에 글자 입력 없음, 칸 값 없음)."""
    assert [x for x in game.inputs() if x["op"] == "text"] == []
    # 상태 파일이 없으면 게임에 아무 입력·캡처도 닿지 않은 것이다
    forms = game.state().get("forms", {}) if game.state_file.exists() else {}
    assert SECRET not in json.dumps(forms)


def type_secret(agent: DaemonClient) -> dict[str, Any]:
    return agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)


def test_title_trailing_newline_sends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 재현(review_B2a_1 title_mismatch)을 반대로: 실제 제목 끝 개행이면 정확히 같은 창이 없다 —
    # daemon도 runner도 같은 규칙이라 붙지 않고, 입력 없이 실패한다
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)

    def newline_title(scenario: dict[str, Any]) -> None:
        accept_secret(scenario)
        scenario["window"]["title"] = WINDOW + "\n"

    game = make_fake_game(tmp_path, scenario_patch=newline_title)
    with game.daemon(env_of(game)) as d, d.client(AGENT) as agent:
        assert d.daemon.screen_source.find(WINDOW) == []
        click_result = agent.call(
            "control.click", {"window": WINDOW, "point": list(START_BUTTON)}, timeout=120
        )
        assert click_result["verdict"] == "fail"
        typed = type_secret(agent)
        assert typed["verdict"] == "fail" and SECRET not in json.dumps(typed)
        no_secret_in_game(game)
        # 클릭도 가지 않았다 (마우스 입력 없음, 장면 그대로)
        assert [x for x in game.inputs() if x.get("device") == "mouse"] == []
        assert not game.state_file.exists() or game.state()["scene"] == "title"


def test_window_appearing_after_lookup_gets_nothing(game: FakeGame, daemon: ThreadDaemon) -> None:
    # 검수 재현(window_appears)을 반대로: daemon 조회 때 창이 없으면 그 뒤 창이 떠도 입력하지 않는다
    with daemon.client(AGENT) as agent:
        click(agent, START_BUTTON)
        click(agent, PASSWORD_FIELD)
        game.set_window(open=False)
        source = daemon.daemon.screen_source
        original = source.find

        def appeared(title: str) -> Any:
            found = original(title)
            assert found == []
            game.set_window(open=True)
            return found

        source.find = appeared  # type: ignore[method-assign]
        try:
            typed = type_secret(agent)
        finally:
            source.find = original  # type: ignore[method-assign]
        assert typed["verdict"] == "fail"
        no_secret_in_game(game)
        assert "protected" not in capture(agent)


def test_binding_swapped_between_lookup_and_input(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 창을 정한 뒤 runner가 붙기 전에 같은 HWND를 다른 프로세스가 쓰면 붙지 않는다 (재검색 없음)
    from kookabug_daemon.methods import control as control_methods

    original = control_methods.check_agent_input

    def then_swap(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        game.set_window(pid=4999)

    with daemon.client(AGENT) as agent:
        click(agent, START_BUTTON)
        click(agent, PASSWORD_FIELD)
        monkeypatch.setattr(control_methods, "check_agent_input", then_swap)
        typed = type_secret(agent)
        assert typed["verdict"] == "fail"
        no_secret_in_game(game)
