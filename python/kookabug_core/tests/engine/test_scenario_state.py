"""장면 가짜 게임의 검사 전용 상태 파일 (M7 계획 3.12): 제어 실행(= runner 프로세스 하나)마다 새로
만드는 `FakeScenario`가 같은 게임 상태(장면·지연 전이·칸 값·포커스·선택·창)를 잇는다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kb_testing.packaging import REPO_ROOT
from kookabug_core.engine.scenario import STATE_FORMAT, FakeScenario

FRAMES = REPO_ROOT / "fixtures" / "sample-game" / "frames"


def table(tmp_path: Path, patch: Any = None) -> Path:
    data = json.loads((FRAMES / "scenario.json").read_text(encoding="utf-8"))
    data["running"] = True
    if patch is not None:
        patch(data)
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    for png in FRAMES.glob("*.png"):
        (tmp_path / png.name).write_bytes(png.read_bytes())
    return path


def run_once(path: Path, state: Path, *steps: tuple[str, Any]) -> FakeScenario:
    """제어 실행 하나: 새 `FakeScenario`(새 프로세스와 같다)에서 입력·캡처."""
    scenario = FakeScenario.load(path, state_file=state)
    game = scenario.latest()
    for kind, arg in steps:
        if kind == "capture":
            scenario.frame(game)
        elif kind == "click":
            scenario.apply(game, "click", arg[0], arg[1], "left")
        else:
            scenario.apply(game, kind, arg)
    return scenario


def scene(path: Path, state: Path) -> str:
    return FakeScenario.load(path, state_file=state).latest().state.scene


def test_state_persists_across_control_runs(tmp_path: Path) -> None:
    path, state = table(tmp_path), tmp_path / "state.json"
    assert scene(path, state) == "title"  # 파일 없음 = 표의 start
    run_once(path, state, ("click", (512, 412)))  # 시작 → 로그인
    assert scene(path, state) == "login"
    run_once(path, state, ("click", (560, 230)), ("text", "qa_tester_01"))
    run_once(path, state, ("key", "tab"), ("text", "sample-pass-01"))
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["format"] == STATE_FORMAT
    assert saved["forms"]["login"]["values"] == {
        "account": "qa_tester_01",
        "password": "sample-pass-01",
    }
    run_once(path, state, ("click", (512, 408)))  # 맞는 값 → 로비
    assert scene(path, state) == "lobby"
    # 깨진 파일 = 표의 start (검사 전용이라 조용히 처음부터)
    state.write_text("{", encoding="utf-8")
    assert scene(path, state) == "title"
    # 상태 파일 없이 만든 장면 표는 실행마다 처음부터 (기존 동작 그대로)
    plain = FakeScenario.load(path)
    plain.apply(plain.latest(), "click", 512, 412, "left")
    assert FakeScenario.load(path).latest().state.scene == "title"


def test_pending_transition_survives_runner_exit(tmp_path: Path) -> None:
    # 로그인 → (로비 → 서버 → 시작) 로딩 → 월드: 로딩의 자동 전이(캡처 3번)와, 클릭의 지연
    # 전이(after_frames — `_pending`)가 실행 경계를 넘어 이어진다
    def slow_start(data: dict[str, Any]) -> None:
        for edge in data["transitions"]:
            if edge["from"] == "lobby_server1" and edge["to"] == "loading":
                edge["after_frames"] = 2

    path, state = table(tmp_path, slow_start), tmp_path / "state.json"
    run_once(path, state, ("click", (512, 412)))
    run_once(path, state, ("click", (560, 230)), ("text", "qa_tester_01"), ("key", "tab"))
    run_once(path, state, ("text", "sample-pass-01"), ("click", (512, 408)))
    run_once(path, state, ("click", (512, 232)))  # 서버 1
    assert scene(path, state) == "lobby_server1"
    run_once(path, state, ("click", (512, 450)))  # 시작: 2프레임 뒤 로딩
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["pending"] and saved["pending"][0]["to"] == "loading"
    assert saved["pending"][0]["after_frames_left"] == 2
    run_once(path, state, ("capture", None))  # 실행 하나에서 한 프레임
    run_once(path, state, ("capture", None))
    assert json.loads(state.read_text(encoding="utf-8"))["pending"][0]["after_frames_left"] == 0
    run_once(path, state, ("capture", None))  # 이 캡처에서 로딩
    assert scene(path, state) == "loading"
    for _ in range(4):  # 로딩 자동 전이(보인 프레임 3) — 실행마다 한 번씩
        run_once(path, state, ("capture", None))
    assert scene(path, state) == "world"


def test_focus_selection_persist(tmp_path: Path) -> None:
    path, state = table(tmp_path), tmp_path / "state.json"
    run_once(path, state, ("click", (512, 412)), ("click", (560, 310)))  # 비밀번호 칸
    run_once(path, state, ("text", "abc"), ("key", "ctrl+a"))  # 전부 고름
    saved = json.loads(state.read_text(encoding="utf-8"))["forms"]["login"]
    assert (saved["focus"], saved["selected"]) == ("password", True)
    run_once(path, state, ("text", "z"))  # 고른 것을 갈아 끼움 — 다음 실행에서도
    form = json.loads(state.read_text(encoding="utf-8"))["forms"]["login"]
    assert form["values"]["password"] == "z" and form["selected"] is False
    # 창: 검사가 닫거나 다른 PID로 바꾼 것이 다음 실행에 보인다
    data = json.loads(state.read_text(encoding="utf-8"))
    data["window"] = {"pid": 5555, "open": False}
    state.write_text(json.dumps(data), encoding="utf-8")
    loaded = FakeScenario.load(path, state_file=state)
    assert loaded.games() == []
    assert loaded._games[0].window.pid == 5555  # pyright: ignore[reportPrivateUsage]
