"""에이전트 정지 화면 보호 `frame_guard` (M7 계획 3.5a, 10장 R1·R3, 12장) — 엄격: 비밀값.

가짜 예제 게임(`kb_testing.fake_game`: 상태 파일 + 칸 값 그리기)과 실제 runner 제어 실행으로 본다.
모든 검사는 먼저 **양성 대조군**(사람 연결의 원본 캡처에서 테스트 비밀값이 OCR로 읽힌다)을 확인한 뒤
에이전트 출구(캡처 이미지·agent 캐시·편집기 캐시·OCR·crop)에 이미지·값이 없음을 본다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

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
from kookabug_daemon.frame_guard import FILE, FrameGuard
from kookabug_daemon.screen_source import Grab

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


def test_without_guard_image_would_leak(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch, ocr_models: Path
) -> None:
    # 음성 대조: 보호 판정을 끄면(늘 clear) 비밀값을 넣은 창의 에이전트 이미지(MCP로 나가는 agent
    # 캐시 PNG)에서 값이 OCR로 읽힌다 — 아래 검사들이 막는 것이 실제 유출 경로임을 보인다
    from kookabug_daemon import frame_guard
    from kookabug_platform.frames import decode_image
    from kookabug_platform.ocr import models
    from kookabug_platform.ocr.engine import Ocr, RapidOcrEngine

    monkeypatch.setattr(frame_guard.FrameGuard, "check", lambda self, frame: frame_guard.CLEAR)
    with daemon.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        frame = capture(agent)
        sent = game.root / ".kookabug" / "cache" / "agent" / frame["agent_image"]["cache"]
        pixels = decode_image(sent.read_bytes())
    reader = Ocr(RapidOcrEngine(models.find_models(dirs=[ocr_models])))
    text = reader.read(pixels, region=PASSWORD_BOX).text
    assert SECRET in text.replace(" ", "").upper(), text


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


# ---------------------------------------------------------------- 비밀값을 입력한 창


def test_secret_field_protected_until_absent(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client() as ui:
        to_login(agent)
        type_password_after_click(agent)
        raw_secret_visible(ui)
        frame = capture(agent)
        assert_withheld(game, frame, "secret_field")
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "frame_protected" and error.data["reason"] == "secret_field"
        # 기록 파일: 키 이름·창·칸 상자만 (값 없음)
        record = (game.root / FILE).read_text(encoding="utf-8")
        assert SECRET not in record and "acc.pw" in record
        assert json.loads(record)["windows"][0]["fields"][0] is not None
        # 칸이 없는 화면(로비)으로 넘어가면 다시 이미지가 온다
        click(agent, LOGIN_BUTTON)
        assert game.state()["scene"] == "lobby"
        lobby = capture(agent)
        assert "protected" not in lobby and lobby["agent_image"]["cache"]
        # 옛 보호 프레임은 그대로 막힌다 (캡처 시점 판정)
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "frame_protected"
    assert SECRET not in "".join(p.read_text("utf-8", "replace") for p in game.root.rglob("*.json"))


def test_field_reappears_protected_again(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        click(agent, LOGIN_BUTTON)
        assert "protected" not in capture(agent)
        # 로그인 화면으로 돌아옴 (칸이 다시 보임 — 값은 지워졌어도 칸 자리는 보호)
        state = game.state()
        state["scene"] = "login"
        game.state_file.write_text(json.dumps(state), encoding="utf-8")
        assert capture(agent)["protected"]["reason"] == "secret_field"


def test_unknown_field_protected_until_window_gone(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        to_login(agent)
        control(agent, "control.key", keys="tab")
        control(agent, "control.type", secret="acc.pw")  # 칸을 누르지 않고 입력
        kept = capture(agent)
        assert_withheld(game, kept, "secret_field_unknown")
        assert "kb_input_click" in kept["protected"]["hint"]
        control(agent, "control.key", keys="enter")
        assert game.state()["scene"] == "lobby"
        assert capture(agent)["protected"]["reason"] == "secret_field_unknown"  # 창 수명 동안
        # 창이 닫히면: 그 창의 원본 프레임을 먼저 버리고 기록을 지운다 (frame_expired)
        game.set_window(open=False)
        for method, params in (
            ("screen.read_text", {"frame_id": kept["frame_id"]}),
            (
                "target.save",
                {
                    "path": "targets/new.target.json",
                    "spec": {"format": "kookabug.target/0", "image": "new.png"},
                    "crop": {"frame_id": kept["frame_id"], "rect": [0, 0, 10, 10]},
                    "base_revision": None,
                },
            ),
        ):
            assert refused(agent, method, params).kind == "frame_expired", method
        assert json.loads((game.root / FILE).read_text("utf-8"))["windows"] == []
        # 같은 HWND를 다른 프로세스가 쓰면 옛 보호는 적용되지 않는다
        game.set_window(open=True, pid=4999)
        fresh = capture(agent)
        assert "protected" not in fresh and fresh["agent_image"]["cache"]
        # 비밀값 키 목록은 창 수명과 따로 남는다 (저장 글자 검사)
        assert json.loads((game.root / FILE).read_text("utf-8"))["secret_keys"] == ["acc.pw"]


def test_protection_survives_session_end_and_restart(game: FakeGame) -> None:
    env = env_of(game)
    with game.daemon(env) as d:
        with d.client(AGENT) as agent:
            to_login(agent)
            type_password_after_click(agent)
        # 연결이 끝나도 보호는 그대로
        with d.client(AGENT) as other:
            assert capture(other)["protected"]["reason"] == "secret_field"
    # daemon 재시작: 기준 프레임이 없으므로 창이 살아 있는 동안 늘 보호
    with game.daemon(env) as d, d.client(AGENT) as agent:
        assert_withheld(game, capture(agent), "secret_field_unknown")


def test_ocr_miss_still_omits(game: FakeGame, daemon: ThreadDaemon) -> None:
    class Blind:
        name = "blind"

        def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
            return []  # OCR이 아무것도 못 읽음 (오인식·미검출 주입)

    with daemon.client(AGENT) as agent, daemon.client() as ui:
        to_login(agent)
        type_password_after_click(agent)
        raw_secret_visible(ui)  # 원본에는 값이 보인다 (실제 OCR)
        daemon.daemon.targets.ocr_factory = lambda: Blind()  # pyright: ignore[reportAttributeAccessIssue]
        frame = capture(agent)
        assert_withheld(game, frame, "secret_field")


def test_ocr_read_refused_on_protected(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        frame = capture(agent)
        for rect in (PASSWORD_BOX, [0, 0, 100, 40], None):
            params: dict[str, Any] = {"frame_id": frame["frame_id"]}
            if rect is not None:
                params["rect"] = rect
            error = refused(agent, "screen.read_text", params)
            assert error.kind == "frame_protected" and SECRET not in json.dumps(error.data)


def test_target_create_refused_on_protected(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        frame = capture(agent)
        params = {
            "path": "targets/grab.target.json",
            "spec": {"format": "kookabug.target/0", "image": "grab.png"},
            "crop": {"frame_id": frame["frame_id"], "rect": [0, 0, 200, 60]},  # 칸과 먼 곳
            "base_revision": None,
        }
        assert refused(agent, "target.save", params).kind == "frame_protected"
        assert not (game.root / "targets" / "grab.png").exists()


# ---------------------------------------------------------------- 기록 쓰기·파일 손상 (R1)


def test_record_write_failure_sends_no_input(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        raise OSError("디스크 가득 (주입)")

    with daemon.client(AGENT) as agent:
        to_login(agent)
        click(agent, PASSWORD_FIELD)
        before = len(game.inputs())
        monkeypatch.setattr("kookabug_daemon.frame_guard.write_atomic", broken)
        error = refused(agent, "control.type", {"window": WINDOW, "secret": "acc.pw"})
        assert error.kind == "protect_record_failed"
        assert len(game.inputs()) == before  # 입력이 나가지 않았다
        assert game.state()["forms"]["login"]["values"]["password"] == ""


def test_corrupt_protect_file_fails_closed_across_restarts(game: FakeGame) -> None:
    path = game.root / FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text("{깨짐", encoding="utf-8")
    env = env_of(game)
    for _ in range(2):  # 원본이 깨진 동안은 다시 시작해도 매번 같다
        with game.daemon(env) as d, d.client(AGENT) as agent:
            assert_withheld(game, capture(agent), "protect_state_unknown")
            assert d.daemon.guard.save_blocked
            error = refused(agent, "control.type", {"window": WINDOW, "secret": "acc.pw"})
            assert error.kind == "protect_record_failed"
    assert path.read_text(encoding="utf-8") == "{깨짐"  # 원본은 그대로
    assert list(path.parent.glob("agent-protect.json.corrupt.*"))
    # 사람이 지우면 풀린다 (그 시점에 새로 뜬 창처럼)
    path.unlink()
    with game.daemon(env) as d, d.client(AGENT) as agent:
        assert "protected" not in capture(agent)


# ---------------------------------------------------------------- 칸 상자 근거 (R3)


def recorded_fields(game: FakeGame) -> list[Any]:
    return json.loads((game.root / FILE).read_text("utf-8"))["windows"][0]["fields"]


def test_box_needs_fresh_click_by_same_connection(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent, daemon.client(AGENT) as other:
        to_login(agent)
        # 클릭 → Tab → 비밀값: 사이에 다른 입력
        click(agent, PASSWORD_FIELD)
        control(agent, "control.key", keys="tab")
        control(agent, "control.type", secret="acc.pw")
        assert recorded_fields(game) == [None]
        # 다른 연결의 클릭 뒤 비밀값
        click(other, PASSWORD_FIELD)
        control(agent, "control.type", secret="acc.pw")
        assert recorded_fields(game)[-1] is None
        assert capture(agent)["protected"]["reason"] == "secret_field_unknown"


def test_box_needs_no_scene_change_and_estimate(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        # 클릭이 장면을 바꿈(타이틀 → 로그인) → 그 뒤 바로 비밀값
        click(agent, START_BUTTON)
        control(agent, "control.type", secret="acc.pw")
        # 경계를 추정할 수 없는 점(평평한 배경)
        click(agent, (5, 5))
        control(agent, "control.type", secret="acc.pw")
        assert recorded_fields(game) == [None, None]


def test_box_needs_click_within_10s(game: FakeGame, daemon: ThreadDaemon) -> None:
    guard: FrameGuard = daemon.daemon.guard
    now = [1000.0]
    guard.clock = lambda: now[0]
    with daemon.client(AGENT) as agent:
        to_login(agent)
        click(agent, PASSWORD_FIELD)
        now[0] += 11.0
        control(agent, "control.type", secret="acc.pw")
        assert recorded_fields(game) == [None]


def test_box_needs_same_size_and_dpi(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = daemon.daemon.screen_source
    original = source.capture
    dpi = [96]

    def scaled(hwnd: int) -> Grab:
        grab = original(hwnd)
        return replace(grab, dpi=dpi[0])

    monkeypatch.setattr(source, "capture", scaled)
    with daemon.client(AGENT) as agent:
        to_login(agent)
        click(agent, PASSWORD_FIELD)
        dpi[0] = 120  # 클릭 뒤 배율이 바뀜
        control(agent, "control.type", secret="acc.pw")
        assert recorded_fields(game) == [None]


def test_dpi_only_change_keeps_protection(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = daemon.daemon.screen_source
    original = source.capture
    dpi = [96]
    monkeypatch.setattr(source, "capture", lambda hwnd: replace(original(hwnd), dpi=dpi[0]))
    with daemon.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        assert recorded_fields(game)[0] is not None
        click(agent, LOGIN_BUTTON)
        assert "protected" not in capture(agent)  # 로비, 같은 DPI: 칸 없음 확정
        dpi[0] = 144  # 픽셀 크기는 같고 DPI만 다름 → 비교하지 않고 보호
        assert capture(agent)["protected"]["reason"] == "secret_field"


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
    # daemon도 runner도 같은 규칙이라 붙지 않고, 입력·보호 기록 없이 실패한다
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
        assert "protected" not in capture(agent)  # 값이 없으니 보호할 것도 없다


def test_binding_swapped_between_lookup_and_input(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 보호 기록을 쓴 뒤 runner가 붙기 전에 같은 HWND를 다른 프로세스가 쓰면 붙지 않는다
    # (재검색 없음)
    guard = daemon.daemon.guard
    original = guard.record_secret

    def then_swap(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        game.set_window(pid=4999)

    with daemon.client(AGENT) as agent:
        click(agent, START_BUTTON)
        click(agent, PASSWORD_FIELD)
        monkeypatch.setattr(guard, "record_secret", then_swap)
        typed = type_secret(agent)
        assert typed["verdict"] == "fail"
        no_secret_in_game(game)


# ---------------------------------------------------------------- 기록 파일 구조 손상 (2라운드 H2)

GOOD_WINDOW = {"hwnd": 0x10010, "pid": 4001, "created": "4001"}


def record_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "format": "kookabug.agent-protect/0",
        "windows": [{"window": dict(GOOD_WINDOW), "keys": ["acc.pw"], "fields": [None]}],
        "secret_keys": ["acc.pw"],
    }
    body.update(changes)
    return body


def window_entry(**changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"window": dict(GOOD_WINDOW), "keys": ["acc.pw"], "fields": [None]}
    entry.update(changes)
    return entry


MALFORMED: dict[str, Any] = {
    "windows_object": record_body(windows={}),
    "windows_missing": {k: v for k, v in record_body().items() if k != "windows"},
    "secret_keys_missing": {k: v for k, v in record_body().items() if k != "secret_keys"},
    "secret_keys_string": record_body(secret_keys="acc.pw"),
    "secret_keys_number_item": record_body(secret_keys=[1]),
    "format_wrong": record_body(format="kookabug.agent-protect/9"),
    "extra_root_key": {**record_body(), "more": 1},
    "entry_not_object": record_body(windows=["x"]),
    "entry_fields_missing": record_body(windows=[{"window": GOOD_WINDOW, "keys": ["acc.pw"]}]),
    "entry_keys_empty": record_body(windows=[window_entry(keys=[])]),
    "entry_fields_object": record_body(windows=[window_entry(fields={})]),
    "entry_fields_empty": record_body(windows=[window_entry(fields=[])]),
    "field_box_short": record_body(windows=[window_entry(fields=[[1, 2, 3]])]),
    "field_box_zero": record_body(windows=[window_entry(fields=[[1, 2, 0, 4]])]),
    "hwnd_string": record_body(windows=[window_entry(window={**GOOD_WINDOW, "hwnd": "1"})]),
    "pid_bool": record_body(windows=[window_entry(window={**GOOD_WINDOW, "pid": True})]),
    "created_empty": record_body(windows=[window_entry(window={**GOOD_WINDOW, "created": ""})]),
    "window_extra": record_body(windows=[window_entry(window={**GOOD_WINDOW, "x": 1})]),
    "root_array": [record_body()],
    # 생성 시각: 직렬화 규칙(양의 10진 정수 그대로) 밖 (3라운드)
    **{
        f"created_{name}": record_body(
            windows=[window_entry(window={**GOOD_WINDOW, "created": value})]
        )
        for name, value in (
            ("text", "not-a-filetime"),
            ("space", " 4001"),
            ("plus", "+4001"),
            ("leading_zero", "04001"),
            ("negative", "-1"),
            ("zero", "0"),
            ("decimal", "4001.5"),
            ("too_big", str(1 << 64)),
            ("number", 4001),
        )
    },
    "pid_too_big": record_body(windows=[window_entry(window={**GOOD_WINDOW, "pid": 1 << 32})]),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_malformed_protect_file_fails_closed(game: FakeGame, case: str) -> None:
    path = game.root / FILE
    path.parent.mkdir(exist_ok=True)
    raw = json.dumps(MALFORMED[case]).encode("utf-8")
    path.write_bytes(raw)
    env = env_of(game)
    for _ in range(2):  # 재시작해도 같다
        with game.daemon(env) as d, d.client(AGENT) as agent:
            guard: FrameGuard = d.daemon.guard
            assert guard.corrupt and guard.save_blocked, case
            assert_withheld(game, capture(agent), "protect_state_unknown")
    assert path.read_bytes() == raw  # 원본 보존
    assert list(path.parent.glob("agent-protect.json.corrupt.*"))


def test_structurally_broken_record_after_real_secret(game: FakeGame) -> None:
    # 검수 재현(malformed_record)을 반대로: 실제 보호 기록의 windows만 {}로 바꾸고 재시작해도 막힌다
    env = env_of(game)
    with game.daemon(env) as d, d.client(AGENT) as agent:
        to_login(agent)
        type_password_after_click(agent)
        assert "protected" in capture(agent)
    path = game.root / FILE
    record = json.loads(path.read_text("utf-8"))
    record["windows"] = {}
    path.write_text(json.dumps(record), encoding="utf-8")
    with game.daemon(env) as d, d.client(AGENT) as agent:
        assert d.daemon.guard.corrupt and d.daemon.guard.save_blocked
        frame = capture(agent)
        assert_withheld(game, frame, "protect_state_unknown")
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "frame_protected" and SECRET not in json.dumps(error.data)


# ---------------------------------------------------------------- 손상 시 보호 범위 (2라운드 H3)


def filetime_now() -> int:
    """지금 시각 (FILETIME 100ns — 프로세스 생성 시각과 같은 단위)."""
    import time

    return int((time.time() + 11_644_473_600) * 10_000_000)


def test_corrupt_protects_every_window_including_new_processes(game: FakeGame) -> None:
    # 3라운드 새 계약: 손상 상태인 동안 에이전트의 모든 창 프레임을 보호한다 (2라운드의 "손상 뒤 새
    # 프로세스는 정상" 예외를 없앴다 — 시계 역행으로 옛 프로세스가 새 것처럼 보일 수 있다)
    path = game.root / FILE
    path.parent.mkdir(exist_ok=True)
    path.write_text("{깨짐", encoding="utf-8")
    with game.daemon(env_of(game)) as d, d.client() as ui, d.client(AGENT) as agent:
        frame = capture(agent)
        assert_withheld(game, frame, "protect_state_unknown")
        assert "agent-protect.json" in frame["protected"]["hint"]
        # 사람 연결에 알림 한 줄 (값 없음, daemon 수명에 한 번)
        note = ui.notifications.get(timeout=10)
        while note.get("method") != "agent.protect_corrupt":
            note = ui.notifications.get(timeout=10)
        assert note["params"] == {"path": FILE}
        for pid, created in ((4100, "0"), (4200, str(filetime_now() + 10_000_000))):
            game.set_window(pid=pid, created=created)  # 생성 시각 모름 / 손상 뒤 새 프로세스
            assert capture(agent)["protected"]["reason"] == "protect_state_unknown"


def test_clock_rollback_cannot_release_old_process(game: FakeGame) -> None:
    # 검수 재현(review_B2a_2 clock_rollback)을 반대로: 손상 기록으로 재시작할 때 벽시계가 뒤로 가
    # 옛 프로세스의 생성 시각이 "지금"보다 늦어 보여도 막는다
    from types import SimpleNamespace
    from unittest.mock import patch

    from kookabug_daemon import frame_guard

    created = filetime_now()
    env = env_of(game)
    with game.daemon(env) as d, d.client(AGENT) as agent, d.client() as ui:
        click(agent, START_BUTTON)
        game.set_window(created=str(created))
        to_login_fields(agent)
        assert "protected" in capture(agent)
        raw_secret_visible(ui)
    path = game.root / FILE
    path.write_text("{broken", encoding="utf-8")
    past = created / 10_000_000 - 11_644_473_600 - 60
    rewound = SimpleNamespace(time=lambda: past, monotonic=frame_guard.time.monotonic)
    with (
        patch.object(frame_guard, "time", rewound),
        game.daemon(env) as d,
        d.client(AGENT) as agent,
    ):
        frame = capture(agent)
        assert_withheld(game, frame, "protect_state_unknown")
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "frame_protected"


def to_login_fields(agent: DaemonClient) -> None:
    """(이미 로그인 화면) 계정 입력 → 비밀번호 칸 클릭 → 비밀값."""
    click(agent, ACCOUNT_FIELD)
    control(agent, "control.type", text="qa_tester_01")
    type_password_after_click(agent)


def test_invalid_created_after_real_secret(game: FakeGame) -> None:
    # 검수 재현(review_B2a_2 invalid_created)을 반대로: 기록의 생성 시각이 직렬화 규칙 밖이면 손상 —
    # 그 기록을 "다른 프로세스"로 지우거나 파일을 다시 쓰지 않는다
    env = env_of(game)
    with game.daemon(env) as d, d.client(AGENT) as agent, d.client() as ui:
        to_login(agent)
        type_password_after_click(agent)
        assert "protected" in capture(agent)
        raw_secret_visible(ui)
    path = game.root / FILE
    record = json.loads(path.read_text("utf-8"))
    record["windows"][0]["window"]["created"] = "not-a-filetime"
    path.write_text(json.dumps(record), encoding="utf-8")
    raw = path.read_bytes()
    with game.daemon(env) as d, d.client(AGENT) as agent:
        assert d.daemon.guard.corrupt and d.daemon.guard.save_blocked
        frame = capture(agent)
        assert_withheld(game, frame, "protect_state_unknown")
        error = refused(agent, "screen.read_text", {"frame_id": frame["frame_id"]})
        assert error.kind == "frame_protected" and SECRET not in json.dumps(error.data)
    assert path.read_bytes() == raw  # 원본 보존 (다시 쓰지 않음)


def test_unreadable_creation_time_refuses_secret(game: FakeGame, daemon: ThreadDaemon) -> None:
    # 생성 시각을 읽지 못한 창에는 보호 기록을 남길 수 없으므로 비밀값을 보내지 않는다
    with daemon.client(AGENT) as agent:
        click(agent, START_BUTTON)
        game.set_window(created="0")
        click(agent, PASSWORD_FIELD)
        error = refused(agent, "control.type", {"window": WINDOW, "secret": "acc.pw"})
        assert error.kind == "protect_record_failed"
        no_secret_in_game(game)


@pytest.mark.parametrize(
    ("visible", "owned"),
    [(False, False), (True, True), (True, False)],
    ids=["hidden", "owned", "shown"],
)
def test_corrupt_protection_does_not_rely_on_enumeration(
    tmp_path: Path, visible: bool, owned: bool
) -> None:
    # 검수 재현(review_B2a_1_live_probe)을 반대로: 시작 때 숨김·소유 팝업이라 창 열거에서 빠지는
    # 창도, 손상을 알기 전에 생긴 프로세스면 표시된 뒤에도 보호한다 (실제 RealSource·find_windows)
    from types import SimpleNamespace
    from unittest.mock import patch

    import numpy as np

    from kookabug_daemon.frames import EditorFrame, FrameCache
    from kookabug_daemon.screen_source import RealSource, WindowBinding
    from kookabug_daemon.targets import TargetStore
    from kookabug_platform import windows

    class Api:
        def top_level_windows(self) -> list[int]:
            return [101]

        def is_visible(self, hwnd: int) -> bool:
            return state["visible"]

        def is_cloaked(self, hwnd: int) -> bool:
            return False

        def owner(self, hwnd: int) -> int:
            return 9 if owned else 0

        def window_pid(self, hwnd: int) -> int:
            return 401

    state = {"visible": visible}
    api = Api()
    original_find = windows.find_windows
    binding = WindowBinding(101, 401, "12345")
    info = SimpleNamespace(pid=401, process_created=12345, title="review")
    root = tmp_path / "ws"
    (root / ".kookabug").mkdir(parents=True)
    (root / FILE).write_text("{broken", encoding="utf-8")
    frames = FrameCache()
    source = RealSource()
    guard = FrameGuard(root, frames, TargetStore(root, frames), source)
    with (
        patch.object(
            windows,
            "find_windows",
            lambda **kw: original_find(api=cast(Any, api), **kw),
        ),
        patch.object(windows, "window_info", lambda hwnd: info),
        patch.object(source, "alive", lambda b: b == binding),
    ):
        guard.load()
        state["visible"] = True  # 시작 때 숨겨졌던 창이 표시됨 (HWND·PID·생성 시각 같음)
        pixels = np.zeros((60, 80, 3), dtype=np.uint8)
        frame = EditorFrame(
            "f", pixels, (80, 60), 96, "unused.png", owner=1, window=True, binding=binding
        )
        verdict = guard.effective(frame)
    assert guard.corrupt and guard.save_blocked
    assert (verdict.state, verdict.reason) == ("protected", "protect_state_unknown")
    # 바인딩을 모르는 창 프레임도 보호
    unknown = replace(frame, binding=None)
    assert guard.effective(unknown).reason == "protect_state_unknown"
