"""입력 전 게임 창 앞으로 (UX4): 입력 효과 노드를 부르기 직전에 실행기가 `focus_before_input`을
부른다. 노드 `focus_before_input`(없으면 그래프 기본값, 그래프에도 없으면 켜짐)이 꺼진 노드는
부르지 않는다. 가져오기는 임대권을 쥔 플랫폼만 하고, 가져와도 포그라운드가 아니면 입력의 지금
포그라운드 확인 오류(`window_not_foreground`) 그대로다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.graphs import make_workspace
from helpers.m1 import ScenePlatform, run_on
from helpers.run import tk

from kookabug_core.engine.errors import EngineError
from kookabug_core.engine.scenario import ScenarioPlatform
from kookabug_sdk.types import WindowRef


class _ForegroundInput:
    """입력 앞에서 포그라운드를 확인하는 입력 (실제 입력 서비스의 포그라운드 확인 흉내)."""

    def __init__(self, inner: Any, platform: FocusPlatform, window: WindowRef | None) -> None:
        self._inner = inner
        self._platform = platform
        self._window = window

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)

        def call(*args: Any, **kwargs: Any) -> Any:
            if self._window is None or self._platform.foreground != self._window.handle:
                raise EngineError("window_not_foreground", "대상 창이 포그라운드가 아니다 (검사)")
            return attr(*args, **kwargs)

        return call


class FocusPlatform(ScenePlatform):
    """`focus_before_input`을 기록한다. `leased`가 아니면 가져오지 않고, `can_focus`가 아니면 불러도
    포그라운드가 바뀌지 않는다. 노드 `activate`·실행 첫 창 `bring_forward`는 포그라운드를 바꾸지
    않는다 (다른 창이 앞에 있는 상황)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.focused: list[tuple[int, str | None]] = []
        self.foreground: int | None = None
        self.leased = True
        self.can_focus = True

    def activate(self, window: WindowRef) -> bool:
        return False

    def bring_forward(self, window: WindowRef, step: str | None) -> bool:
        return False

    def focus_before_input(self, window: WindowRef, step: str | None) -> bool:
        if not self.leased:
            return False
        self.focused.append((window.handle, step))
        if self.can_focus:
            self.foreground = window.handle
        return self.can_focus

    def input_for(self, step: str, window: WindowRef | None, observer: Any, sleep: Any) -> Any:
        inner = ScenarioPlatform.input_for(self, step, window, observer, sleep)
        return _ForegroundInput(inner, self, window)


def _graph(*, graph_focus: bool | None = None, node_focus: bool | None = None) -> Any:
    g = (
        tk()
        .entry("n_launch")
        .node("n_launch", "testkit.m1.launch", inputs={"path": "game.exe"}, next={"done": "n_key"})
        .node("n_key", "testkit.m1.key", inputs={"key": "enter"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    if node_focus is not None:
        g.nodes["n_key"]["focus_before_input"] = node_focus
    if graph_focus is not None:
        build = g.build

        def built() -> dict[str, Any]:
            data = build()
            data["focus_before_input"] = graph_focus
            return data

        g.build = built  # type: ignore[method-assign]
    return g


def _platform() -> FocusPlatform:
    return FocusPlatform(ScenePlatform.sample().scenario)


def test_on_by_default_focuses_before_input_node(tmp_path: Path) -> None:
    platform = _platform()
    ran = run_on(make_workspace(tmp_path), _graph(), platform)
    assert ran.result.verdict == "pass", ran.result.reason
    handle = ran.end("n_launch")["outputs"]["handle"]
    # 입력 효과 노드(n_key)에서만, 그 스텝으로 (launch는 입력 효과가 아니다)
    assert platform.focused == [(handle, ran.end("n_key")["step"])]


def test_node_off_skips_focus_and_fails_like_today(tmp_path: Path) -> None:
    platform = _platform()
    ran = run_on(make_workspace(tmp_path), _graph(node_focus=False), platform)
    assert platform.focused == []
    assert ran.result.verdict != "pass"
    assert ran.end("n_key")["error"]["code"] == "window_not_foreground"


def test_graph_default_inherited_and_node_override(tmp_path: Path) -> None:
    # 그래프 기본값 끔 → 노드가 따르면 가져오지 않는다
    platform = _platform()
    run_on(make_workspace(tmp_path / "a"), _graph(graph_focus=False), platform)
    assert platform.focused == []
    # 그래프 끔 + 노드 켬 → 가져온다
    platform = _platform()
    ran = run_on(
        make_workspace(tmp_path / "b"), _graph(graph_focus=False, node_focus=True), platform
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert len(platform.focused) == 1
    # 그래프 켬(명시) → 가져온다
    platform = _platform()
    run_on(make_workspace(tmp_path / "c"), _graph(graph_focus=True), platform)
    assert len(platform.focused) == 1


def test_without_lease_does_not_focus(tmp_path: Path) -> None:
    platform = _platform()
    platform.leased = False
    ran = run_on(make_workspace(tmp_path), _graph(), platform)
    assert platform.focused == []
    assert ran.end("n_key")["error"]["code"] == "window_not_foreground"


def test_focus_failed_still_window_not_foreground(tmp_path: Path) -> None:
    platform = _platform()
    platform.can_focus = False
    ran = run_on(make_workspace(tmp_path), _graph(), platform)
    assert len(platform.focused) == 1
    assert ran.result.verdict != "pass"
    assert ran.end("n_key")["error"]["code"] == "window_not_foreground"
