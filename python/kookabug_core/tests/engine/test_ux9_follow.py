"""UX9 A: runner — 띄운 게임의 시작 화면(splash) 창 → 본 창 따라가기.

언리얼 계열 게임은 작은 시작 화면 창을 먼저 띄웠다가 닫고 본 창을 새로 만든다. `core.app.launch`가
시작 화면 창에 붙은 뒤 그 창이 닫혀도, 이 실행이 띄운 프로세스가 살아 있으면 같은 프로세스의 새
주 창으로 바꾸고(`window.changed`, 제목 없음) 진행 중 노드(`ocr.wait_text`)의 캡처도 이어진다.

- 프로세스가 끝났으면 지금처럼 `window_gone`
- 띄우지 않은 창(제목으로 붙은 창)이 닫히면 지금처럼 `window_gone` (같은 프로세스에 새 창이 있어도)
- 캡처한 프레임의 창(HWND·PID)이 대상 창과 다르면(다른 프로세스가 같은 HWND를 다시 씀) 그 프레임은
  저장소·노드로 가지 않는다
- 붙여 실행은 붙은 게임 프로세스 기준으로 같은 규칙
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, make_workspace
from helpers.m1 import SCENARIO, ScenePlatform, clicks, run_on
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import (
    ExecOptions,
    Executor,
    FakeClock,
    InProcessInvoker,
    MemoryArtifacts,
)
from kookabug_core.engine.context import _check_binding  # pyright: ignore[reportPrivateUsage]
from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.executor import AttachStart
from kookabug_core.engine.scenario import FakeScenario
from kookabug_core.loader import load_program
from kookabug_core.record.video import VideoGate
from kookabug_platform.frames import FrameStore, decode_image
from kookabug_sdk import Result
from kookabug_sdk.types import Image, OcrLine, OcrResult, ProcessRef, Rect, Target, WindowRef

SPLASH_IMAGE = Path("splash.png")
"""시작 화면 창 캡처의 표시 (가짜 캡처 경로 — 읽지 않는다)."""
MAIN_OFFSET = 0x1000
"""본 창 HWND = 시작 화면 창 HWND + 이것."""


@dataclass
class Splash:
    splash: int
    main: int
    left: int
    """시작 화면 창을 몇 번 더 찍으면 닫히나."""
    gap: int
    """닫힌 뒤 본 창이 뜨기까지 창 찾기 횟수 (그동안 창 없음)."""
    end: bool = False
    """닫힐 때 프로세스도 끝난다."""
    closed: bool = False


class OcrStub:
    """시작 화면 창 캡처는 "Loading", 본 창 캡처는 "게임 시작"으로 읽는다. 읽은 이미지를 남긴다."""

    def __init__(self) -> None:
        self.read: list[Image] = []

    def read_text(
        self, image: Image, *, region: Rect | None, sensitive: bool, limits: Any
    ) -> OcrResult:
        self.read.append(image)
        text = "Loading" if image.path == SPLASH_IMAGE or image.frame == 999 else "게임 시작"
        return OcrResult(text, (OcrLine(text, Rect(412, 380, 200, 64), 0.9),), 0.9)

    def find(self, image: Image, target: Target, *, region: Rect | None, limits: Any) -> None:
        return None

    def diff(self, a: Image, b: Image, *, region: Rect | None) -> float:
        return 0.0


class SplashPlatform(ScenePlatform):
    """띄운 가짜 게임이 시작 화면 창을 `left`번 찍힌 뒤 닫고, 창 찾기 `gap`번 뒤 본 창(새 HWND, 같은
    PID)을 내놓는다."""

    def __init__(self, *, left: int = 2, gap: int = 2, end: bool = False, **kwargs: Any) -> None:
        self.ocr = OcrStub()
        super().__init__(FakeScenario.load(SCENARIO), engines=self.ocr, **kwargs)
        self.left, self.gap, self.end = left, gap, end
        self.splashes: dict[int, Splash] = {}
        self.splash_on_launch = True

    def make_splash(self, pid: int, handle: int) -> Splash:
        s = Splash(handle, handle + MAIN_OFFSET, self.left, self.gap, self.end)
        self.splashes[pid] = s
        return s

    def launch(self, path: str, args: Any, cwd: str | None) -> ProcessRef:
        process = super().launch(path, args, cwd)
        game = self.scenario.game_of_process(process)
        assert game is not None
        if self.splash_on_launch:
            self.make_splash(process.pid, game.window.handle)
        return process

    def _close_splash(self, window: WindowRef) -> None:
        game = self.scenario.game_of(window)
        s = self.splashes[game.process.pid]
        s.closed = True
        if s.end:
            game.open = False
        else:
            game.window = replace(game.window, handle=s.main, binding=f"fake-{s.main:x}")

    def splash_frame(self, window: WindowRef | None) -> bool:
        """그 창이 열린 시작 화면 창이면 한 번 센다. 다 셌으면 닫고 `window_gone`."""
        if window is None:
            return False
        game = self.scenario.game_of(window)  # 닫힌 창이면 window_gone
        s = self.splashes.get(game.process.pid)
        if s is None or s.closed or game.window.handle != s.splash:
            return False
        if s.left <= 0:
            self._close_splash(window)
            raise EngineError("window_gone", f"가짜 창 {window.handle:#x}이(가) 닫혔다")
        s.left -= 1
        return True

    def capture(self, window: WindowRef | None, region: Rect | None) -> Image:
        if self.splash_frame(window):
            return Image(360, 180, path=SPLASH_IMAGE, frame=1)
        return super().capture(window, region)

    def process_window(
        self, process: ProcessRef, title: str | None, limits: Any
    ) -> WindowRef | None:
        s = self.splashes.get(process.pid)
        if s is not None and s.closed and s.gap > 0:
            s.gap -= 1
            return None
        return super().process_window(process, title, limits)


def launch_wait(*, then: str = "n_w") -> GraphBuilder:
    return (
        tk()
        .entry("n_launch")
        .node(
            "n_launch",
            "core.app.launch",
            inputs={"path": "game.exe", "window_title": "Sample"},
            next={"attached": "n_wait"},
        )
        .node(
            "n_wait",
            "core.ocr.wait_text",
            inputs={"contains": "게임 시작", "timeout_ms": 20000},
            next={"found": then},
        )
        .node("n_w", "testkit.m1.window", next={"done": "n_click"})
        .node("n_click", "core.input.click", inputs={"point": [30, 40]}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_launch_follows_splash_to_main_window(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = SplashPlatform()
    ran = run_on(ws, launch_wait(), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    splash = ran.end("n_launch")["outputs"]["window"]["handle"]
    main = splash + MAIN_OFFSET
    (changed,) = ran.of("window.changed")
    assert changed["from_hwnd"] == splash and changed["hwnd"] == main
    pid = platform.scenario.games()[0].process.pid
    assert changed["node"] == "n_wait" and changed["pid"] == pid
    assert "title" not in changed  # 제목은 남기지 않는다
    # 진행 중 노드가 새 창에서 이어 읽어 찾았다 (시작 화면은 "Loading")
    assert [i.path == SPLASH_IMAGE for i in platform.ocr.read][:2] == [True, True]
    assert platform.ocr.read[-1].path != SPLASH_IMAGE
    assert ran.end("n_wait")["exit"] == "found"
    assert ran.end("n_wait")["outputs"]["match"]["window"]["handle"] == main
    # 다음 스텝의 현재 창·입력도 새 창
    assert ran.end("n_w")["outputs"]["handle"] == main
    assert clicks(platform) == [(main, 30, 40)]
    log = [e["message"] for e in ran.of("log") if "새 주 창" in str(e["message"])]
    assert len(log) == 1 and "Sample" not in log[0]


def test_follow_bounded_by_node_deadline(tmp_path: Path) -> None:
    """본 창이 노드 기한 안에 안 뜨면 그 노드는 timeout(fail 출구), 다음 노드가 이어 따라간다."""
    ws = make_workspace(tmp_path)
    platform = SplashPlatform(gap=6)  # 0.5초 간격 6번 = 3초
    graph = (
        tk()
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_a"})
        .node(
            "n_a",
            "core.ocr.wait_text",
            inputs={"contains": "게임 시작", "timeout_ms": 1500},
            next={"found": "n_pass", "timeout": "n_b"},
        )
        .node(
            "n_b",
            "core.ocr.wait_text",
            inputs={"contains": "게임 시작", "timeout_ms": 20000},
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, graph, platform)
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.ends("n_a")[-1]["exit"] == "timeout"
    (changed,) = ran.of("window.changed")
    assert changed["node"] == "n_b"


def test_process_end_fails_as_before(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = SplashPlatform(end=True)
    ran = run_on(ws, launch_wait(), platform)
    assert ran.result.verdict == "error" and ran.result.code == "window_gone", ran.result
    assert ran.of("window.changed") == []
    assert clicks(platform) == []


def test_window_not_launched_by_run_fails_as_before(tmp_path: Path) -> None:
    """제목으로 붙은 창(이 실행이 띄우지 않음)은 닫히면 지금처럼 끝난다 — 같은 프로세스에 본 창이
    떠도 따라가지 않는다."""
    ws = make_workspace(tmp_path)
    platform = SplashPlatform(gap=0)
    game = platform.scenario.launch_game("game.exe")  # 사람이 띄운 게임
    platform.make_splash(game.process.pid, game.window.handle)
    graph = (
        tk()
        .entry("n_set")
        .node("n_set", "testkit.m1.set_window", inputs={"title": "Sample"}, next={"done": "n_wait"})
        .node(
            "n_wait",
            "core.ocr.wait_text",
            inputs={"contains": "게임 시작", "timeout_ms": 20000},
            next={"found": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )
    ran = run_on(ws, graph, platform)
    assert ran.result.verdict == "error" and ran.result.code == "window_gone", ran.result
    assert ran.of("window.changed") == []


def test_attach_follows_attached_game_process(tmp_path: Path) -> None:
    """붙여 실행: 붙은 게임 프로세스의 창이면 같은 규칙으로 따라간다."""
    ws = make_workspace(tmp_path)
    platform = SplashPlatform()
    game = platform.scenario.launch_game("game.exe")  # 켜져 있는 게임 (@game)
    platform.make_splash(game.process.pid, game.window.handle)
    launch_wait().write(ws, "tests/ux9.graph.json")
    program = load_program(ws, "tests/ux9.graph.json")
    executor = Executor(
        registry_with_testkit(), platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()
    )
    start = AttachStart(game.window, game.process)
    result = executor.run(program, ExecOptions(run_id="r1", attach=start))
    assert result.verdict == "pass", result.reason
    main = game.window.handle
    assert main == platform.splashes[game.process.pid].main
    changed = [e for e in result.events if e["event"] == "window.changed"]
    assert [(e["from_hwnd"], e["hwnd"]) for e in changed] == [(main - MAIN_OFFSET, main)]
    assert clicks(platform) == [(main, 30, 40)]
    assert len(platform.scenario.games()) == 1  # 새로 띄우지 않았다


class ReusePlatform(SplashPlatform):
    """프레임 저장소 경로: 대상 창의 첫 캡처가 다른 프로세스(같은 HWND를 다시 쓴 창)의 프레임으로
    온다. 그때 원래 창은 이미 닫혔고 같은 게임 프로세스에 본 창이 있다."""

    def __init__(self) -> None:
        super().__init__(left=0, gap=0, decode=decode_image)
        self.foreign_sent = 0

    def capture_staged(
        self, window: WindowRef | None, region: Rect | None, limits: Any = None
    ) -> Any:
        assert window is not None
        s = next(iter(self.splashes.values()))
        if window.handle == s.splash and not s.closed:
            self._close_splash(window)
            # 닫힌 창의 HWND를 다른 프로세스가 다시 쓴 화면: 프레임은 왔지만 그 창의 것이 아니다
            game = self.scenario.games()[0]
            fake = replace(game.window, handle=s.splash, title="Sample")
            image, staged = super().capture_staged(fake, region, limits)
            stranger = replace(window, pid=window.pid + 777, process_created="1")
            self.foreign_sent += 1
            assert staged.meta is not None
            return replace(image, frame=999), replace(
                staged, meta=replace(staged.meta, window=stranger)
            )
        return super().capture_staged(window, region, limits)

    def _game(self, window: WindowRef | None) -> Any:
        if window is not None:
            for s in self.splashes.values():
                if window.handle == s.splash:  # 시작 화면 창 참조도 그 게임으로 (위에서 닫음)
                    return self.scenario.games()[0]
        return super()._game(window)


def test_reused_hwnd_frame_never_used(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    platform = ReusePlatform()
    store = FrameStore()
    ran = run_on(ws, launch_wait(), platform, frames=store)
    assert ran.result.verdict == "pass", ran.result.reason
    assert platform.foreign_sent == 1
    # 다른 프로세스 창의 프레임은 노드(OCR)로 가지 않았다
    assert all(i.frame != 999 for i in platform.ocr.read)
    assert ran.of("window.changed")[0]["hwnd"] == ran.end("n_w")["outputs"]["handle"]


# ---------------------------------------------------------------- UX9 2 (검수1 High 3·Mid 4)

ACCOUNT_TITLE = "ReviewGame [Account : synthetic-user-ux9]"
"""본 창 제목에 계정 ID가 들어가는 게임 흉내 (합성 값)."""


class NewTitlePlatform(SplashPlatform):
    """시작 화면 창이 닫히면 본 창 제목이 계정 ID를 담는다."""

    def _close_splash(self, window: WindowRef) -> None:
        super()._close_splash(window)
        game = self.scenario.games()[0]
        game.window = replace(game.window, title=ACCOUNT_TITLE)

    def window_title(self, window: WindowRef) -> str:
        return self.scenario.game_of(window).window.title


class ObserveSwitch(InProcessInvoker):
    """대기 노드 대신: 캡처(시작 화면 닫힘 → 따라가기) 직후 창 제목을 출력 없이 바로 로그로 남기고,
    그때 녹화 게이트의 대상 창을 기록한다."""

    def __init__(self, gate: VideoGate) -> None:
        self.gate = gate
        self.current: WindowRef | None = None
        self.video_window: WindowRef | None = None
        self.old_title = ""

    def invoke(self, nodedef: Any, node: Any, ctx: Any, inputs: Any) -> Any:
        if node.id == "n_wait":
            self.old_title = ctx.window.title
            ctx.capture()
            self.current = ctx.window
            self.video_window = self.gate.view().window
            ctx.log.info(f"현재 게임 창: {ctx.window.title} / 이전: {self.old_title}")
            return Result("found", "ok")
        return super().invoke(nodedef, node, ctx, inputs)


def run_switch(tmp_path: Path) -> tuple[Any, ObserveSwitch]:
    ws = make_workspace(tmp_path)
    platform = NewTitlePlatform(left=0, gap=0)
    game = platform.scenario.launch_game("game.exe")
    platform.make_splash(game.process.pid, game.window.handle)
    start = AttachStart(game.window, game.process)
    launch_wait().write(ws, "tests/ux9_2.graph.json")
    gate = VideoGate()
    invoker = ObserveSwitch(gate)
    executor = Executor(
        registry_with_testkit(),
        platform=platform,
        clock=FakeClock(),
        artifacts=MemoryArtifacts(),
        invoker=invoker,
        video=gate,
    )
    result = executor.run(
        load_program(ws, "tests/ux9_2.graph.json"), ExecOptions(run_id="ux9two", attach=start)
    )
    assert result.verdict == "pass", result.reason
    assert any(e["event"] == "window.changed" for e in result.events)
    return result, invoker


def test_followed_window_title_recorded_as_is(tmp_path: Path) -> None:
    """붙여 실행: 노드는 따라간 새 창을 바로 받고, 그 제목(계정 ID)은 기록에 그대로 남는다
    (UX11 B — 창 제목을 가리지 않는다)."""
    result, invoker = run_switch(tmp_path)
    logs = [str(e["message"]) for e in result.events if e["event"] == "log"]
    mine = [m for m in logs if m.startswith("현재 게임 창")]
    assert mine == [f"현재 게임 창: {ACCOUNT_TITLE} / 이전: {invoker.old_title}"], mine
    assert invoker.old_title and invoker.old_title != ACCOUNT_TITLE
    assert "@game" not in json.dumps(result.events, ensure_ascii=False)


def test_video_tracks_new_window_within_current_node(tmp_path: Path) -> None:
    """녹화 대상이 같은 노드 안에서 새 창으로 바뀐다 (다음 스텝까지 닫힌 창에 남지 않는다)."""
    _, invoker = run_switch(tmp_path)
    assert invoker.current is not None
    assert invoker.video_window == invoker.current


def test_video_retarget_keeps_policy() -> None:
    gate = VideoGate()
    old = WindowRef(0x10, pid=1, process_created="1", binding="a")
    new = WindowRef(0x20, pid=1, process_created="1", binding="b")
    gate.hold("s1")
    gate.classify("s1", "off", window=old)
    before = gate.view()
    gate.retarget(old, new)
    after = gate.view()
    assert after.window == new and after.generation > before.generation
    assert (after.state, after.gap) == (before.state, before.gap) == ("off", "policy_off")
    # 녹화 대상이 아닌 창의 전환은 무시
    gate.retarget(WindowRef(0x99, pid=9), WindowRef(0x98, pid=9))
    assert gate.view().window == new


@pytest.mark.parametrize(
    ("changes", "meta"),
    [
        ({"process_created": ""}, True),
        ({"binding": "replacement"}, True),
        ({"pid": 202}, True),
        ({}, False),  # 프레임 창을 모름 (식별 불능)
    ],
)
def test_frame_binding_complete(changes: dict[str, Any], meta: bool) -> None:
    want = WindowRef(0x1001, pid=101, process_created="10", binding="old")
    seen = (
        SimpleNamespace(window=replace(want, **changes)) if meta else SimpleNamespace(window=None)
    )
    with pytest.raises(EngineError, match="프레임을 버린다"):
        _check_binding(want, seen)


def test_frame_binding_partial_ref_allowed() -> None:
    """플랫폼이 주지 않은 부분 참조(HWND만)는 아는 것만 비교한다 (지금 동작)."""
    _check_binding(WindowRef(0x1001), SimpleNamespace(window=None))
    _check_binding(WindowRef(0x1001), SimpleNamespace(window=WindowRef(0x1001, pid=5, binding="x")))
