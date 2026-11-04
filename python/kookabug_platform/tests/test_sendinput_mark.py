"""우리 SendInput 표식 (M4 계획 2.2 C2·C19): 모든 `INPUT`의 `dwExtraInfo`가 `KOOKABUG_INPUT_MARK`.

실제 입력 없이 `SendInput` 자리에 받은 구조체를 남긴다. 녹화 훅은 이 표식으로 우리 입력을 버린다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from kb_testing import keys as test_keys
from kookabug_core.inputs import ClientPoint, InputActor
from kookabug_core.inputs.lease import InputLease, LeaseOwner
from kookabug_core.record.reader import InputKey
from kookabug_platform.keys import stroke
from kookabug_platform.sendinput import (
    KOOKABUG_INPUT_MARK,
    SendInputBackend,
    VirtualScreen,
    key_input,
    mouse_input,
    unicode_inputs,
)
from kookabug_platform.win32 import user32
from kookabug_sdk.types import Point

SCREEN = VirtualScreen(0, 0, 1920, 1080)


class Captured:
    """`SendInput` 자리: 받은 입력마다 (종류, 플래그, dwExtraInfo)."""

    def __init__(self) -> None:
        self.items: list[tuple[str, int, int]] = []

    def __call__(self, inputs: Sequence[user32.INPUT]) -> int:
        for item in inputs:
            if item.type == user32.INPUT_KEYBOARD:
                self.items.append(("key", item.ki.dwFlags, item.ki.dwExtraInfo))
            else:
                self.items.append(("mouse", item.mi.dwFlags, item.mi.dwExtraInfo))
        return len(inputs)

    @property
    def marks(self) -> set[int]:
        return {extra for _, _, extra in self.items}


def backend(sent: Captured) -> SendInputBackend:
    return SendInputBackend(send=sent, screen=lambda: SCREEN)


def test_all_inputs_carry_kookabug_mark() -> None:
    # 구조체를 만드는 함수 셋 (모든 백엔드 동작이 이것들로 만든다)
    assert key_input(stroke("a"), up=False).ki.dwExtraInfo == KOOKABUG_INPUT_MARK
    assert key_input(stroke("a"), up=True).ki.dwExtraInfo == KOOKABUG_INPUT_MARK
    assert mouse_input(user32.MOUSEEVENTF_LEFTUP).mi.dwExtraInfo == KOOKABUG_INPUT_MARK
    pairs = unicode_inputs("가😀")
    assert [i.ki.dwExtraInfo for pair in pairs for i in pair] == [KOOKABUG_INPUT_MARK] * 6

    # 백엔드의 모든 동작: 키·글자·마우스(누르기·떼기·이동·휠)
    sent = Captured()
    b = backend(sent)
    b.down("ctrl")
    b.up("ctrl")
    b.text("ab가")
    b.mouse_down("left", at=Point(10, 20))
    b.mouse_up("left")
    b.mouse_down("x2")
    b.mouse_up("x2")
    b.move(Point(30, 40))
    b.wheel(-2, at=Point(5, 5))
    b.wheel(1)
    kinds = {kind for kind, _, _ in sent.items}
    assert kinds == {"key", "mouse"} and len(sent.items) == 2 + 6 + 4 + 1 + 3
    assert sent.marks == {KOOKABUG_INPUT_MARK}

    # 입력 액터의 떼기·전부 떼기(멈춤의 RELEASE_ALL)
    sent = Captured()
    actor = InputActor(backend(sent)).start()
    actor.press("shift+a")
    actor.press_button(ClientPoint(50, 60), button="right")
    actor.release("shift+a")
    actor.press("ctrl")
    assert actor.stop(5.0)
    ups = [i for i in sent.items if i[0] == "key" and i[1] & user32.KEYEVENTF_KEYUP]
    mouse_ups = [i for i in sent.items if i[0] == "mouse" and i[1] & user32.MOUSEEVENTF_RIGHTUP]
    assert len(ups) == 3 and len(mouse_ups) == 1  # shift·a 떼기 + 전부 떼기의 ctrl·오른쪽 버튼
    assert sent.marks == {KOOKABUG_INPUT_MARK}


def test_recovery_release_carries_mark(tmp_path: Path) -> None:
    # 얻기·감독자 복구의 떼기도 같은 백엔드라 표식이 실린다
    run_dir = tmp_path / "runs" / "r"
    run_dir.mkdir(parents=True)
    (run_dir / "events.jsonl").write_text("", encoding="utf-8")
    sent = Captured()
    owner = LeaseOwner.current("supervisor", run_id="abcd1234", run_dir=run_dir)
    lease = InputLease(
        owner,
        backend(sent),
        name=f"Local\\Kookabug.InputLease.test-mark-{id(sent)}",
        directory=tmp_path / "state",
    )
    lease.acquire(0)
    try:
        held = [InputKey("keyboard", "alt"), InputKey("mouse", "left")]
        recovery = lease.recover_run_dir(run_dir, "abcd1234", held)
    finally:
        lease.release(None)
    assert recovery is not None and len(sent.items) == 2
    assert sent.marks == {KOOKABUG_INPUT_MARK}


def test_alt_foreground_tap_carries_mark() -> None:
    # P1 첫 창 앞으로 가져오기의 Alt (입력 직전 확인 없는 액터 요청)
    sent = Captured()
    actor = InputActor(backend(sent)).start()
    actor.tap_unguarded("alt")
    assert actor.stop(5.0)
    assert [(kind, bool(flags & user32.KEYEVENTF_KEYUP)) for kind, flags, _ in sent.items] == [
        ("key", False),
        ("key", True),
    ]
    assert sent.marks == {KOOKABUG_INPUT_MARK}


def test_test_tool_mark_matches_product_and_can_change() -> None:
    # 검사 도구는 제품 코드를 import하지 않고 같은 값을 따로 둔다
    assert test_keys.KOOKABUG_INPUT_MARK == KOOKABUG_INPUT_MARK
    key_up = test_keys.release_input("a")
    assert key_up.u.ki.dwExtraInfo == KOOKABUG_INPUT_MARK
    assert test_keys.release_input("mouse:left").u.mi.dwExtraInfo == KOOKABUG_INPUT_MARK
    # 녹화 검사의 "사람" 입력은 검사 표식을 준다
    human = test_keys.release_input("x", extra_info=0x5445_5354)
    assert human.u.ki.dwExtraInfo == 0x5445_5354
    assert KOOKABUG_INPUT_MARK < 2**53  # 훅 메시지 정수 값 규칙 안 (recorder-hook ExtraInfo)
