"""UX8 daemon 쪽 — 실측에서 막힌 곳.

- A `@game` 주 창: 보이고·최소화·cloaked 아님 중 클라이언트 넓이가 가장 큰 창. `explore.step`은
  창이 없으면 기다리고, 시작 화면 창이 닫히고 본 창이 생기면 따라간다(`window_changed`). 프로세스가
  끝났을 때만 실패 — 창 원천을 대본 가짜(`SplashSource`)로 바꿔 끼운다
- B `app.launch`: 같은 주체가 다시 띄우면 이전 게임을 끝낸다(`replaced_pid`). 다른 주체·사람이 띄운
  게임은 안 건드린다. 작업이 끝나면 그 작업이 띄운 게임을 끝낸다 (실제 프로세스 — 런처가 띄운
  아래 프로세스까지)
- C 클릭+입력 한 걸음: 칸 클릭과 secret을 한 요청에 — 칸이 보이면 `secret_field`(unknown 아님),
  벗어나면 clear. 비밀값은 결과·활동·기록에 없다. 따로 보낸 클릭이 10초를 넘기면 지금처럼 unknown
- F `run.status{wait_ms}`: 끝나면 바로 돌아오고, 작업 활동은 MCP 호출 하나 = 한 줄
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.graphs import GraphBuilder

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
from kb_testing.proc import wait_until
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.agent_job import jobdir
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.game_window import GameRef
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.screen_source import Grab, WindowBinding, pick_main

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

SECRET = "PWQ4417ZX"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-ux8", "attended": False}
OTHER = {**AGENT, "id": "agent-ux8-other"}


def refused(client: DaemonClient, method: str, params: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params, timeout=120)
    return caught.value


def accept_secret(scenario: dict[str, Any]) -> None:
    scenario["forms"]["login"]["expect"]["password"] = SECRET


def no_forbidden(game: FakeGame) -> FakeGame:
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
def game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ocr_models: Path) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", SECRET)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    return no_forbidden(make_fake_game(tmp_path, scenario_patch=accept_secret, screens=False))


@pytest.fixture
def daemon(game: FakeGame) -> Iterator[ThreadDaemon]:
    with game.daemon(env_of(game)) as d:
        yield d


# ---------------------------------------------------------------- A 주 창·창 바뀜 따라가기


def test_pick_main_prefers_large_visible_window() -> None:
    hidden = (WindowBinding(1, 7, "9"), "숨은 창", False, 4000 * 4000)
    splash = (WindowBinding(2, 7, "9"), "시작 화면 창", True, 720 * 370)
    main = (WindowBinding(3, 7, "9"), "본 창", True, 1280 * 720)
    assert pick_main([hidden, splash, main]) == (main[0], main[1])
    assert pick_main([hidden, splash]) == (splash[0], splash[1])
    assert pick_main([hidden]) is None


class SplashSource:
    """대본 가짜 창 원천: 한 프로세스(PID 7)의 창을 검사가 바꾼다. 지운 창의 캡처는
    `window_not_found`, 프로세스를 끝내면 모든 창이 사라진다."""

    PID = 7
    CREATED = "133000000000000000"

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.wins: dict[int, tuple[str, bool, tuple[int, int], int]] = {}
        """hwnd → (제목, 보임, 클라이언트 크기, 색)."""
        self.alive_process = True

    def put(self, hwnd: int, title: str, size: tuple[int, int], *, usable: bool = True) -> None:
        with self.lock:
            self.wins[hwnd] = (title, usable, size, 20 + (hwnd * 37) % 200)

    def drop(self, hwnd: int) -> None:
        with self.lock:
            self.wins.pop(hwnd, None)

    def kill(self) -> None:
        with self.lock:
            self.wins.clear()
            self.alive_process = False

    def binding(self, hwnd: int) -> WindowBinding:
        return WindowBinding(hwnd, self.PID, self.CREATED)

    def windows(self) -> list[dict[str, Any]]:
        with self.lock:
            return [
                {
                    "handle": h,
                    "title": t,
                    "process": "game.exe",
                    "pid": self.PID,
                    "client_size": list(s),
                    "dpi": 96,
                }
                for h, (t, ok, s, _) in self.wins.items()
                if ok
            ]

    def capture(self, hwnd: int) -> Grab:
        with self.lock:
            found = self.wins.get(hwnd)
        if found is None:
            raise RequestFailed("window_not_found", f"창 {hwnd:#x}이(가) 없다", message="창이 없다")
        _, _, (w, h), color = found
        pixels = np.full((h, w, 3), color, dtype=np.uint8)
        return Grab(pixels, (w, h), 96, self.binding(hwnd))

    def alive(self, binding: WindowBinding) -> bool:
        with self.lock:
            return binding.hwnd in self.wins

    def find(self, title: str) -> list[WindowBinding]:
        with self.lock:
            return [self.binding(h) for h, (t, *_) in self.wins.items() if t == title]

    def process_created(self, pid: int) -> str | None:
        return self.CREATED if pid == self.PID and self.alive_process else None

    def windows_of(self, pid: int, created: str) -> list[tuple[WindowBinding, str]]:
        with self.lock:
            return [(self.binding(h), t) for h, (t, *_) in self.wins.items()]

    def main_window_of(self, pid: int, created: str) -> tuple[WindowBinding, str] | None:
        with self.lock:
            items = [
                (self.binding(h), t, ok, s[0] * s[1]) for h, (t, ok, s, _) in self.wins.items()
            ]
        return pick_main(items)

    def process_alive(self, pid: int, created: str) -> bool:
        with self.lock:
            return self.alive_process


@pytest.fixture
def splash(game: FakeGame, daemon: ThreadDaemon) -> SplashSource:
    """daemon의 창 원천을 대본 가짜로 바꾸고, 에이전트 기억을 그 프로세스로."""
    source = SplashSource()
    inner = daemon.daemon
    inner.screen_source = source  # type: ignore[assignment]
    inner.game._source = source  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
    inner.guard.source = source  # type: ignore[assignment]
    refs = inner.game._refs  # pyright: ignore[reportPrivateUsage]
    refs[f"agent:{AGENT['id']}"] = GameRef(SplashSource.PID, SplashSource.CREATED)
    return source


def later(seconds: float, action: Any) -> threading.Thread:
    def run() -> None:
        time.sleep(seconds)
        action()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_game_picks_large_main_window(splash: SplashSource, daemon: ThreadDaemon) -> None:
    """(a) 보이지 않는 창·작은 창이 먼저 있어도 큰 본 창을 고른다."""
    splash.put(0x10, "숨은 창", (1600, 1200), usable=False)
    splash.put(0x20, "시작 화면 창", (720, 370))
    splash.put(0x30, "본 창", (1280, 720))
    with daemon.client(AGENT) as agent:
        step = agent.call("explore.step", {"window": "@game"}, timeout=120)
        assert (step["frame"]["width"], step["frame"]["height"]) == (1280, 720)
        assert step["window"] == "@game" and "window_changed" not in step
        # windows.list{game}도 주 창이 맨 앞 (MCP kb_screen_capture @game이 첫 창을 쓴다)
        listed = agent.call("windows.list", {"game": True})["windows"]
        assert listed[0]["handle"] == 0x30


def test_game_follows_splash_to_main_window(splash: SplashSource, daemon: ThreadDaemon) -> None:
    """(b) 기다리는 중 시작 화면 창이 닫히고 본 창이 생기면 이어서 기다려 성공."""
    splash.put(0x20, "시작 화면 창", (720, 370))
    later(1.0, lambda: splash.drop(0x20))
    later(2.5, lambda: splash.put(0x30, "본 창", (1280, 720)))
    with daemon.client(AGENT) as agent:
        step = agent.call("explore.step", {"window": "@game", "wait_ms": 20000}, timeout=120)
    assert step["window_changed"] is True and step["changed"] is True
    assert (step["frame"]["width"], step["frame"]["height"]) == (1280, 720)
    assert 2000 <= step["waited_ms"] < 20000
    assert step["window"] == "@game"
    assert "본 창" not in json.dumps(step, ensure_ascii=False)  # 실제 제목은 결과에 없다


def test_game_process_end_fails(splash: SplashSource, daemon: ThreadDaemon) -> None:
    """(c) 프로세스가 끝나면 실패 ("게임 프로세스가 끝났다")."""
    splash.put(0x20, "시작 화면 창", (720, 370))
    later(1.0, splash.kill)
    with daemon.client(AGENT) as agent:
        started = time.monotonic()
        error = refused(agent, "explore.step", {"window": "@game", "wait_ms": 20000})
        assert time.monotonic() - started < 15  # 기한까지 기다리지 않는다
    assert error.kind == "window_not_found" and "게임 프로세스가 끝났다" in error.message


def test_game_window_appears_later(splash: SplashSource, daemon: ThreadDaemon) -> None:
    """(d) 처음엔 창이 없다가 생기면 성공. 기다림 없이(wait_ms 0)는 지금처럼 바로 실패."""
    with daemon.client(AGENT) as agent:
        error = refused(agent, "explore.step", {"window": "@game"})
        assert error.kind == "window_not_found"
        later(1.5, lambda: splash.put(0x30, "본 창", (1280, 720)))
        step = agent.call("explore.step", {"window": "@game", "wait_ms": 20000}, timeout=120)
    assert (step["frame"]["width"], step["frame"]["height"]) == (1280, 720)
    assert step["waited_ms"] >= 1000


def test_titled_window_unchanged(splash: SplashSource, daemon: ThreadDaemon) -> None:
    """제목으로 준 창은 지금 동작 그대로 (사라지면 따라가지 않고 오류)."""
    splash.put(0x20, "시작 화면 창", (720, 370))
    later(1.0, lambda: splash.drop(0x20))
    later(1.5, lambda: splash.put(0x30, "본 창", (1280, 720)))
    with daemon.client(AGENT) as agent:
        error = refused(agent, "explore.step", {"window": "시작 화면 창", "wait_ms": 10000})
    assert error.kind == "window_not_found"


# ---------------------------------------------------------------- C 클릭+입력 한 걸음


def handle_of(client: DaemonClient) -> int:
    (window,) = client.call("windows.list", {})["windows"]
    return int(window["handle"])


def capture(client: DaemonClient) -> dict[str, Any]:
    return client.call("target.capture", {"window": handle_of(client)})


def to_login(agent: DaemonClient) -> None:
    """로그인 화면으로 가서 계정 칸을 채운다 (비밀번호 칸만 남김)."""
    for method, params in (
        ("control.click", {"point": list(START_BUTTON)}),
        ("control.click", {"point": list(ACCOUNT_FIELD)}),
        ("control.type", {"text": "qa_tester_01"}),
    ):
        done = agent.call(method, {"window": WINDOW, **params}, timeout=120)
        assert done["verdict"] == "pass", done


def texts_under(*folders: Path) -> str:
    out: list[str] = []
    for folder in folders:
        if folder.exists():
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix in (".json", ".jsonl", ".md", ".txt", ".log"):
                    out.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(out)


def test_explore_step_click_and_secret_one_step(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "로그인", "window": WINDOW})
        to_login(agent)
        step = agent.call(
            "explore.step",
            {
                "window": WINDOW,
                "point": list(PASSWORD_FIELD),
                "secret": "acc.pw",
                "select_all": True,
                "wait_ms": 1000,
            },
            timeout=120,
        )
        assert step["input"]["verdict"] == "pass"
        # 칸이 보이는 동안: 칸 위치를 아는 보호 (unknown 아님)
        assert step["frame"]["protected"]["reason"] == "secret_field"
        assert capture(agent)["protected"]["reason"] == "secret_field"
        # 칸에서 벗어나면 clear (로그인 → 로비)
        done = agent.call("control.click", {"window": WINDOW, "point": list(LOGIN_BUTTON)})
        assert done["verdict"] == "pass" and game.state()["scene"] == "lobby"
        lobby = capture(agent)
        assert "protected" not in lobby and lobby["agent_image"]["cache"]
        ended = agent.call("explore.end", {})
        assert SECRET not in json.dumps([step, done, ended], ensure_ascii=False)
    root = game.root
    assert SECRET not in texts_under(root / "runs", root / "screens", root / ".kookabug")


def test_input_type_with_point_one_request(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        to_login(agent)
        done = agent.call(
            "control.type",
            {"window": WINDOW, "point": list(PASSWORD_FIELD), "secret": "acc.pw"},
            timeout=120,
        )
        assert done["verdict"] == "pass" and SECRET not in json.dumps(done)
        assert capture(agent)["protected"]["reason"] == "secret_field"
        # 비밀값 칸을 target으로 누르는 조합은 받지 않는다 (칸 위치 근거가 없다)
        error = refused(
            agent,
            "control.type",
            {"window": WINDOW, "target": "targets/x.target.json", "secret": "acc.pw"},
        )
        assert error.kind == "target_invalid" and "point" in error.message
    assert SECRET not in texts_under(game.root / "runs")


def test_separate_late_click_stays_unknown(game: FakeGame, daemon: ThreadDaemon) -> None:
    """따로 보낸 클릭이 10초(`CLICK_FRESH_S`)를 넘기면 지금처럼 unknown — 힌트에 풀리는 방법."""
    guard = daemon.daemon.guard
    real = guard.clock
    with daemon.client(AGENT) as agent:
        to_login(agent)
        done = agent.call("control.click", {"window": WINDOW, "point": list(PASSWORD_FIELD)})
        assert done["verdict"] == "pass"
        guard.clock = lambda: real() + 11.0  # LLM 턴 사이 11초가 지났다
        typed = agent.call("control.type", {"window": WINDOW, "secret": "acc.pw"}, timeout=120)
        assert typed["verdict"] == "pass"
        kept = capture(agent)
    assert kept["protected"]["reason"] == "secret_field_unknown"
    hint = kept["protected"]["hint"]
    assert "kb_app_launch" in hint and "자동으로 끝" in hint and "point" in hint


# ---------------------------------------------------------------- B 같은 주체의 이전 게임 정리


def py_game(root: Path, child_file: Path | None = None) -> None:
    """게임 대신 파이썬 프로세스 (child_file이면 런처처럼 아래 프로세스를 띄우고 그 PID를 쓴다)."""
    code = "import time; time.sleep(120)"
    if child_file is not None:
        code = (
            "import subprocess, sys, time, pathlib; "
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
            f"pathlib.Path({str(child_file)!r}).write_text(str(p.pid)); time.sleep(120)"
        )
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8")) if local.exists() else {}
    body.setdefault("format", "kookabug.local/0")
    body["permissions"] = {"preset": "full"}
    body["settings"] = {"game.executable": sys.executable, "game.args": ["-c", code]}
    local.parent.mkdir(exist_ok=True)
    local.write_text(json.dumps(body), encoding="utf-8")


def alive(pid: int) -> bool:
    from kookabug_core.win import identify

    return identify(pid) is not None and _running(pid)


def _running(pid: int) -> bool:
    from kookabug_core.win.process import Process

    try:
        with Process.open(pid) as proc:
            return proc.alive()
    except ProcessLookupError:
        return False


def kill_all(pids: list[int]) -> None:
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)


@pytest.fixture
def launch_ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    py_game(root)
    return root


def test_same_principal_relaunch_replaces(launch_ws: Path) -> None:
    started: list[int] = []
    try:
        with (
            ThreadDaemon(launch_ws, platform_fake=launch_ws / "fake-platform.json") as d,
            d.client() as ui,
            d.client(AGENT) as agent,
            d.client(OTHER) as other,
        ):
            human = ui.call("app.launch", {})
            started.append(human["pid"])
            first = agent.call("app.launch", {})
            started.append(first["pid"])
            assert "replaced_pid" not in first
            others = other.call("app.launch", {})
            started.append(others["pid"])
            second = agent.call("app.launch", {})
            started.append(second["pid"])
            # 같은 주체의 이전 게임만 끝났다
            assert second["replaced_pid"] == first["pid"]
            wait_until(lambda: not alive(first["pid"]), timeout=15)
            for pid in (human["pid"], others["pid"], second["pid"]):
                assert alive(pid), pid
            # 사람이 다시 띄워도 기억하지 않는다 (아무것도 끝내지 않음)
            again = ui.call("app.launch", {})
            started.append(again["pid"])
            assert "replaced_pid" not in again and alive(human["pid"])
    finally:
        kill_all(started)


def test_job_end_stops_job_game_and_children(launch_ws: Path, tmp_path: Path) -> None:
    child_file = tmp_path / "child.pid"
    py_game(launch_ws, child_file)
    started: list[int] = []
    try:
        with ThreadDaemon(launch_ws, platform_fake=launch_ws / "fake-platform.json") as d:
            job = d.begin_job({"playbook": "entry"})
            agent = {**AGENT, "id": job["agent_id"], "job_token": job["token"]}
            with d.client(agent) as conn:
                pid = conn.call("app.launch", {})["pid"]
                started.append(pid)
                wait_until(lambda: child_file.exists() and child_file.read_text(), timeout=30)
                child = int(child_file.read_text())
                started.append(child)
                assert alive(pid) and alive(child)
                with d.client() as ui:
                    ended = ui.call(
                        "job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300
                    )
                assert ended["settled"] is True
            # 작업이 띄운 게임과 그 아래 프로세스(런처가 띄운 게임)가 끝났다
            wait_until(lambda: not alive(pid) and not alive(child), timeout=15)
    finally:
        kill_all(started)


# ---------------------------------------------------------------- F run.status 기다리기


def test_run_status_wait_returns_when_ended(game: FakeGame, daemon: ThreadDaemon) -> None:
    quick = (
        GraphBuilder()
        .entry("n_wait")
        .node("n_wait", "core.flow.delay", inputs={"ms": 1500}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
        .build()
    )
    graph = game.root / "tests" / "ux8_quick.graph.json"
    graph.write_text(json.dumps(quick, ensure_ascii=False), encoding="utf-8")
    job = daemon.begin_job({"playbook": "entry"})
    # 작업 폴더는 agent-job CLI가 만든다 (활동 기록 자리)
    (game.root / jobdir.JOBS_DIR / job["job"]).mkdir(parents=True, exist_ok=True)
    agent = {**AGENT, "id": job["agent_id"], "job_token": job["token"]}
    with daemon.client(agent) as conn, daemon.client() as ui:
        started_run = conn.call("run.start", {"path": "tests/ux8_quick.graph.json"}, call=1)
        started = time.monotonic()
        status = conn.call(
            "run.status", {"run_id": started_run["run_id"], "wait_ms": 60000}, timeout=120, call=2
        )
        took = time.monotonic() - started
        assert status["state"] == "ended" and took < 50  # 기한(60초)까지 기다리지 않는다

        # 기다림은 daemon 안에서: MCP 호출 하나 = 활동 한 줄
        def run_status_rows() -> int:
            entries = ui.call("jobs.activity", {"job": job["job"]})["entries"]
            return [e["tool"] for e in entries].count("kb_run_status")

        wait_until(lambda: run_status_rows() == 1, timeout=15)
        time.sleep(0.5)
        assert run_status_rows() == 1


# ---------------------------------------------------------------- 검수 1 재현 (High 1·Mid 2·Mid 3)


def test_watch_rejects_reused_hwnd() -> None:
    """캡처한 창의 바인딩이 고른 바인딩과 다르면(HWND 재사용) 그 픽셀은 버린다."""
    from types import SimpleNamespace

    from kookabug_daemon.methods.explore_step import _Watch  # pyright: ignore[reportPrivateUsage]

    original = WindowBinding(10, 100, "111")
    other = WindowBinding(10, 200, "222")
    leaked = Grab(np.zeros((4, 4, 3), dtype=np.uint8), (4, 4), 96, other)
    unknown = Grab(np.zeros((4, 4, 3), dtype=np.uint8), (4, 4), 96, None)
    for returned in (leaked, unknown):
        source = SimpleNamespace(capture=lambda hwnd, g=returned: g, alive=lambda binding: False)
        memory = SimpleNamespace(find=lambda principal: None, alive=lambda principal: True)
        call = SimpleNamespace(
            daemon=SimpleNamespace(screen_source=source, game=memory), principal=None
        )
        watch = _Watch(call, original, True)  # type: ignore[arg-type]
        assert asyncio.run(watch.grab()) is None


def test_explore_never_publishes_foreign_reused_hwnd(
    splash: SplashSource, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시작 화면 창이 닫히고 따라간 본 창의 HWND가 캡처 때 다른 프로세스 것이면 그 화면을 내지
    않는다 (기한까지 이 게임의 마지막 유효 프레임)."""
    splash.put(0x20, "시작 화면 창", (720, 370))
    real_capture = splash.capture
    calls = 0

    def capture(hwnd: int) -> Grab:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_capture(hwnd)
        if hwnd == 0x20:
            splash.drop(0x20)
            splash.put(0x30, "본 창", (1280, 720))
            raise RequestFailed("window_not_found", "시작 화면 창 닫힘")
        # 같은 게임의 본 창을 골랐지만 캡처 때 그 HWND의 주인이 바뀌었다
        return Grab(
            np.full((333, 987, 3), 123, dtype=np.uint8),
            (987, 333),
            96,
            WindowBinding(hwnd, 999, "133000000000000999"),
        )

    monkeypatch.setattr(splash, "capture", capture)
    with daemon.client(AGENT) as agent:
        error = refused(agent, "explore.step", {"window": "@game", "wait_ms": 3000})
    # 다른 프로세스 화면도, 닫힌 창의 옛 프레임도 내지 않는다 (검수 2 High)
    assert error.kind == "window_not_found"
    assert not list((daemon.daemon.root / ".kookabug" / "cache" / "agent").rglob("*.png"))


def test_initial_capture_gap_waits_for_main(
    splash: SplashSource, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """고른 창이 첫 캡처 전에 닫혀도 남은 기한 동안 같은 프로세스의 본 창을 기다린다."""
    splash.put(0x20, "시작 화면 창", (720, 370))
    real_find = splash.main_window_of
    calls = 0

    def find(pid: int, created: str) -> tuple[WindowBinding, str] | None:
        nonlocal calls
        calls += 1
        found = real_find(pid, created)
        if calls == 1:
            splash.drop(0x20)
        return found

    monkeypatch.setattr(splash, "main_window_of", find)
    timer = later(1.0, lambda: splash.put(0x30, "본 창", (1280, 720)))
    try:
        with daemon.client(AGENT) as agent:
            result = agent.call("explore.step", {"window": "@game", "wait_ms": 3000}, timeout=30)
        assert result["frame"]["width"] == 1280
    finally:
        timer.join(5)


def hidden_python() -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(60)"]


def test_fallback_stops_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Job에 넣지 못한 게임도 PID + 생성 시각으로(종료 권한) 끝낸다."""
    from kookabug_core.win import ProcessId, is_alive
    from kookabug_core.win.job import Job
    from kookabug_core.win.process import Process
    from kookabug_daemon.launched import LaunchedGames, spawn_game

    def reject(*args: Any) -> None:
        raise OSError("Job 할당 실패")

    monkeypatch.setattr(Job, "assign", reject)
    launched = spawn_game(hidden_python(), None, subprocess.CREATE_NO_WINDOW)
    assert launched.created is not None
    ident = ProcessId(launched.pid, launched.created)
    try:
        assert launched.job is None and is_alive(ident)
        games = LaunchedGames()
        games.put("agent:t", launched)
        assert games.stop("agent:t") == launched.pid and not is_alive(ident)
        assert games.stop("agent:t") is None  # 기록이 지워졌다
    finally:
        with contextlib.suppress(ProcessLookupError), Process.open(ident, terminate=True) as proc:
            proc.terminate()


def test_fallback_reused_pid_never_stops() -> None:
    from kookabug_core.win import identify, is_alive
    from kookabug_daemon.launched import Launched, LaunchedGames

    proc = subprocess.Popen(hidden_python(), creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ident = identify(proc.pid)
        assert ident is not None
        games = LaunchedGames()
        games.put("agent:t", Launched(ident.pid, ident.created + 1))
        assert games.stop("agent:t") is None and is_alive(ident)
    finally:
        proc.kill()
        proc.wait(5)


def test_stop_failure_keeps_record_and_refuses_relaunch(
    launch_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """끄기 실패는 이미 죽음과 구분한다: 기록을 남기고, 새 게임을 띄우지 않고 오류로 알린다."""
    from kookabug_daemon import launched as launched_module

    started: list[int] = []
    try:
        with (
            ThreadDaemon(launch_ws, platform_fake=launch_ws / "fake-platform.json") as d,
            d.client(AGENT) as agent,
        ):
            first = agent.call("app.launch", {})["pid"]
            started.append(first)
            games = d.daemon.run_manager.launched
            record = games._by_key[f"agent:{AGENT['id']}"]  # pyright: ignore[reportPrivateUsage]
            job, record.job = record.job, None  # Job 할당 실패 경로로

            def fail(pid: int, created: int) -> bool:
                raise launched_module.GameStopFailed(pid, "접근 거부")

            monkeypatch.setattr(launched_module, "_stop_process", fail)
            error = refused(agent, "app.launch", {})
            assert error.kind == "launch_failed" and str(first) in error.message
            assert alive(first)
            # 기록은 남아 다음에 다시 시도한다 (Job을 되돌리면 정상 정리)
            assert games._by_key[f"agent:{AGENT['id']}"] is record  # pyright: ignore[reportPrivateUsage]
            record.job = job
            again = agent.call("app.launch", {})
            started.append(again["pid"])
            assert again["replaced_pid"] == first
            wait_until(lambda: not alive(first), timeout=15)
    finally:
        kill_all(started)


# ---------------------------------------------------------------- 검수 2 재현 (High·Mid)


def test_old_secret_frame_not_published_after_window_gone(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비밀값 칸이 보이던 창이 첫 캡처 뒤 닫히면(프로세스는 삶) 옛 픽셀을 clear 프레임으로 내지
    않는다 — `window_not_found`이고, 에이전트 이미지·탐색 저장이 없다."""
    source = daemon.daemon.screen_source
    with daemon.client(AGENT) as agent:
        agent.call("explore.start", {"title": "닫힌 창", "window": WINDOW})
        to_login(agent)
        typed = agent.call(
            "control.type",
            {"window": WINDOW, "point": list(PASSWORD_FIELD), "secret": "acc.pw"},
            timeout=120,
        )
        assert typed["verdict"] == "pass"
        assert capture(agent)["protected"]["reason"] == "secret_field"
        agent_cache = game.root / ".kookabug" / "cache" / "agent"
        before_images = set(agent_cache.rglob("*.png")) if agent_cache.exists() else set()
        real_capture, real_main, real_alive = source.capture, source.main_window_of, source.alive
        closed = False

        def grab(hwnd: int) -> Grab:
            nonlocal closed
            if closed:
                raise RequestFailed("window_not_found", "로그인 창 닫힘")
            got = real_capture(hwnd)
            closed = True
            return got

        monkeypatch.setattr(source, "capture", grab)
        monkeypatch.setattr(
            source, "alive", lambda binding: False if closed else real_alive(binding)
        )
        monkeypatch.setattr(
            source,
            "main_window_of",
            lambda pid, created: None if closed else real_main(pid, created),
        )
        monkeypatch.setattr(source, "process_alive", lambda pid, created: True)
        error = refused(agent, "explore.step", {"window": "@game", "wait_ms": 800})
        assert error.kind == "window_not_found"
        # 기다림 없는 경로도 같다 (옛 프레임 대신 오류)
        closed = False
        error = refused(agent, "explore.step", {"window": "@game"})
        assert error.kind == "window_not_found"
        after_images = set(agent_cache.rglob("*.png")) if agent_cache.exists() else set()
        assert after_images == before_images
    explored = game.root / "screens" / "_explored"
    assert not explored.exists() or not list(explored.rglob("*.shot.png"))


def test_openprocess_denied_keeps_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """종료 권한으로 여는 `OpenProcess`가 접근 거부면 '끌 것 없음'이 아니라 실패 — 기록 유지."""
    import ctypes

    from kookabug_core.win import _kernel32 as kernel  # pyright: ignore[reportPrivateUsage]
    from kookabug_core.win import identify, is_alive
    from kookabug_daemon.launched import GameStopFailed, Launched, LaunchedGames

    proc = subprocess.Popen(hidden_python(), creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ident = identify(proc.pid)
        assert ident is not None
        games = LaunchedGames()
        record = Launched(ident.pid, ident.created)
        games.put("agent:t", record)
        original = kernel.OpenProcess

        def open_process(access: int, inherited: bool, pid: int) -> int:
            if pid == ident.pid and access & 1:  # PROCESS_TERMINATE
                ctypes.set_last_error(5)  # ERROR_ACCESS_DENIED
                return 0
            return original(access, inherited, pid)

        monkeypatch.setattr(kernel, "OpenProcess", open_process)
        with pytest.raises(GameStopFailed):
            games.stop("agent:t")
        assert is_alive(ident)
        assert games._by_key.get("agent:t") is record  # pyright: ignore[reportPrivateUsage]
        # 끝난 프로세스는 실제 OpenProcess 실패(없음)로 '끌 것 없음'
        monkeypatch.setattr(kernel, "OpenProcess", original)
        proc.kill()
        proc.wait(5)
        assert games.stop("agent:t") is None
        assert games._by_key.get("agent:t") is None  # pyright: ignore[reportPrivateUsage]
    finally:
        proc.kill()
        proc.wait(5)
