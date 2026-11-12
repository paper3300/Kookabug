"""실행 첫 창 가져오기가 다른 프로세스가 쥔 포그라운드를 넘는가 (D1, `bring_to_front`).

`desktop_input`: Alt 누르기·떼기를 실제로 넣는다 — runner와 같이 입력 액터(`tap_unguarded`, 입력
기록·실패 정리)로. 다른 프로세스(`_HOLDER`)가 자기 작은 창을 앞으로 가져가 포그라운드를 쥔 상태 —
이 프로세스는 포그라운드 잠금에 걸린다 — 에서 예제 게임을 앞으로 가져온다. 눌린 키가 없는지는
**정리 전에** 보고(액터가 Alt를 남겼으면 실패), 정리는 finally에서 따로 한다.

돌리는 법: `KOOKABUG_DESKTOP_TESTS=require KOOKABUG_DESKTOP_INPUT=1 uv run pytest
python/kookabug_platform/tests/test_foreground_live.py -s`
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.keys import assert_no_keys_held, held, release_all_for_test
from kb_testing.proc import wait_until
from kb_testing.sample_game import SampleGame, launch_sample_game
from kookabug_core.inputs import InputActor
from kookabug_platform.sendinput import SendInputBackend
from kookabug_platform.win32 import user32
from kookabug_platform.windows import WIN32_FOREGROUND, Win32Foreground, bring_to_front

pytestmark = pytest.mark.desktop_input

TOOLS = Path(__file__).resolve().parents[3] / "tools"

# 포그라운드를 쥐는 다른 프로세스: 작은 창을 만들고 (자기 입력 액터의) Alt로 잠금을 넘어 자기 창을
# 앞으로 가져간다. 줄 "grab"마다 다시 가져가고 "<방법> <HWND>"를 쓴다. stdin이 닫히면 끝난다
_HOLDER = r"""
import sys
from kb_testing.desktop import _TempWindow
from kookabug_core.inputs import InputActor
from kookabug_platform.sendinput import SendInputBackend
from kookabug_platform.windows import bring_to_front
actor = InputActor(SendInputBackend()).start()
def tap():
    actor.tap_unguarded("alt")
    return True
win = _TempWindow(sys.argv[1])
for line in sys.stdin:
    how = bring_to_front(win.hwnd, tap_alt=tap)
    print(how, win.hwnd, flush=True)
win.close()
actor.stop(10)
"""


class Holder:
    def __init__(self, title: str) -> None:
        env = {**os.environ, "PYTHONPATH": str(TOOLS)}
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", _HOLDER, title],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
        )
        self.hwnd = 0

    def grab(self) -> None:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write("grab\n")
        self.proc.stdin.flush()
        how, hwnd = self.proc.stdout.readline().split()
        assert how != "None", "포그라운드를 쥐는 프로세스가 자기 창을 앞으로 못 가져옴"
        self.hwnd = int(hwnd)
        wait_until(lambda: _root_foreground() == self.hwnd, timeout=5)

    def close(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class _NoAttach(Win32Foreground):
    """`AttachThreadInput`이 거부되는 경우(상위 무결성 포그라운드) 흉내: Alt 경로만 남긴다."""

    def set_foreground_attached(self, hwnd: int) -> None:
        return None


def _root_foreground() -> int:
    fg = user32.GetForegroundWindow()
    return int(user32.GetAncestor(fg, user32.GA_ROOT)) if fg else 0


@pytest.fixture
def game(tmp_path: Path) -> Iterator[SampleGame]:
    title = f"KBFG {uuid.uuid4().hex[:8]}"
    with launch_sample_game(("--title", title), workdir=tmp_path) as g:
        yield g


@pytest.fixture
def holder() -> Iterator[Holder]:
    assert_no_keys_held()
    h = Holder(f"KBFG holder {uuid.uuid4().hex[:8]}")
    try:
        yield h
    finally:
        h.close()
        release_all_for_test()


@pytest.fixture
def actor() -> Iterator[tuple[InputActor, list[dict[str, Any]]]]:
    events: list[dict[str, Any]] = []
    a = InputActor(SendInputBackend(), emit=lambda e: events.append(dict(e))).start()
    try:
        yield a, events
    finally:
        a.stop(10)


def _tap(actor: InputActor) -> bool:
    actor.tap_unguarded("alt")
    return True


def _assert_nothing_left(actor: InputActor, events: list[dict[str, Any]]) -> None:
    # 정리(release_all_for_test) 전에: 액터·기록·OS 상태 모두 Alt가 눌려 있지 않다
    assert actor.held == []
    assert [e["event"] for e in events if e.get("key") == "alt"][-1:] in ([], ["input.up"])
    assert held(["alt"]) == []


def test_bring_to_front_over_other_process(
    game: SampleGame, holder: Holder, actor: tuple[InputActor, list[dict[str, Any]]]
) -> None:
    a, events = actor
    holder.grab()
    how = bring_to_front(game.hwnd, tap_alt=lambda: _tap(a), ops=WIN32_FOREGROUND)
    _assert_nothing_left(a, events)
    assert how is not None, "다른 프로세스가 쥔 포그라운드를 넘지 못함"
    assert _root_foreground() == game.hwnd
    print(f"방법: {how}")


def test_alt_fallback_breaks_lock_without_attach(
    game: SampleGame, holder: Holder, actor: tuple[InputActor, list[dict[str, Any]]]
) -> None:
    a, events = actor
    holder.grab()
    how = bring_to_front(game.hwnd, tap_alt=lambda: _tap(a), ops=_NoAttach())
    _assert_nothing_left(a, events)
    # 잠금이 켜져 있으면 alt, 이 PC의 잠금 시간 설정이 0이면 direct로도 된다
    assert how in ("direct", "alt"), how
    assert _root_foreground() == game.hwnd
    print(f"방법: {how}")


def test_focus_before_input_brings_game_then_key_lands(game: SampleGame, holder: Holder) -> None:
    """UX4 입력 전 게임 창 앞으로: 다른 프로세스가 포그라운드를 쥔 상태에서 임대권(액터)을 쥔
    플랫폼이 입력 노드 직전처럼 `focus_before_input` → 게임이 앞에 오고 키가 게임에 들어간다.
    가져오지 않으면(옵션 끔) 지금처럼 `window_not_foreground`로 입력하지 않는다."""
    from kookabug_platform.errors import WINDOW_NOT_FOREGROUND, PlatformError
    from kookabug_platform.platform import WindowsPlatform
    from kookabug_platform.sendinput import WindowInputGuard

    platform = WindowsPlatform(run_id="ux4")
    events: list[dict[str, Any]] = []
    a = InputActor(
        SendInputBackend(),
        emit=lambda e: events.append(dict(e)),
        guard=WindowInputGuard(platform.tracker),
    ).start()
    try:
        ref = platform._ref(game.hwnd)  # pyright: ignore[reportPrivateUsage]
        target = platform.tracker.bind(game.hwnd)
        # 옵션 끔: 가져오지 않으면 입력하지 않고 오류 (지금 동작)
        holder.grab()
        mark = game.last_seq()
        with pytest.raises(PlatformError) as caught:
            a.key("a", target=target)
        assert caught.value.code == WINDOW_NOT_FOREGROUND
        # 임대권 없는 플랫폼은 가져오지 않는다
        assert platform.focus_before_input(ref, "s0") is False
        assert _root_foreground() == holder.hwnd
        # 옵션 켬: 액터를 붙인(임대권을 쥔) 플랫폼이 가져오고 키가 들어간다
        platform.attach_input(a)
        assert platform.focus_before_input(ref, "s1") is True
        assert _root_foreground() == game.hwnd
        a.key("a", target=target)
        game.wait_event("key_up", key="a", after=mark)
        _assert_nothing_left(a, events)
    finally:
        a.stop(10)
        platform.close()
