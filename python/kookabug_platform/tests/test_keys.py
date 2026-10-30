"""키 이름표와 SendInput 키 값 (구현 계획 M1 2.4 "키")."""

from __future__ import annotations

from pathlib import Path

import pytest

from kb_testing.proc import read_fake_input_log
from kookabug_core.inputs import FakeBackend, InputActor, split_combo
from kookabug_core.inputs.keys import KEYS, KeyUnknown, canonical_key
from kookabug_platform import keys
from kookabug_platform.errors import KEY_UNKNOWN, PlatformError
from kookabug_platform.win32 import user32


@pytest.mark.parametrize(
    ("name", "canonical"),
    [
        ("A", "a"),
        ("Ctrl", "ctrl"),
        ("CONTROL", "ctrl"),
        ("Escape", "esc"),
        ("Return", "enter"),
        ("PgDn", "pagedown"),
        ("Right_Ctrl", "rctrl"),
        ("F12", "f12"),
        ("Num5", "numpad5"),
        ("+", "="),
    ],
)
def test_names_case_insensitive(name: str, canonical: str) -> None:
    assert canonical_key(name) == canonical
    assert keys.stroke(name).name == canonical
    assert keys.stroke(name).vk == KEYS[canonical].vk


@pytest.mark.parametrize(
    ("name", "extended"),
    [
        ("rctrl", True),
        ("ralt", True),
        ("up", True),
        ("delete", True),
        ("home", True),
        ("pageup", True),
        ("divide", True),
        ("numpad_enter", True),
        ("lctrl", False),
        ("ctrl", False),
        ("a", False),
        ("enter", False),
        ("numpad8", False),
    ],
)
def test_extended_keys_flag(name: str, extended: bool) -> None:
    value = keys.stroke(name)
    assert bool(value.flags & user32.KEYEVENTF_EXTENDEDKEY) is extended
    # 지금 자판에 스캔 코드가 있으면 스캔 코드로 보낸다. 없으면(한국어 자판의 오른쪽 Ctrl·Alt는
    # 한자·한/영 키라 VK_RCONTROL·VK_RMENU의 스캔 코드가 없다) 가상 키 코드로만
    assert bool(value.flags & user32.KEYEVENTF_SCANCODE) is bool(value.scan)


def test_right_and_left_ctrl_differ_by_extended(monkeypatch: pytest.MonkeyPatch) -> None:
    # 미국 자판처럼 둘 다 스캔 코드 0x1D이면 확장 플래그로만 구별된다
    monkeypatch.setattr(user32, "MapVirtualKeyW", lambda vk, kind: 0x1D)
    left, right = keys.stroke("lctrl"), keys.stroke("rctrl")
    assert left.scan == right.scan == 0x1D
    assert left.flags == user32.KEYEVENTF_SCANCODE
    assert right.flags == user32.KEYEVENTF_SCANCODE | user32.KEYEVENTF_EXTENDEDKEY


def test_no_scan_code_falls_back_to_virtual_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user32, "MapVirtualKeyW", lambda vk, kind: 0)
    right = keys.stroke("rctrl")
    assert (right.vk, right.scan, right.flags) == (0xA3, 0, user32.KEYEVENTF_EXTENDEDKEY)
    assert keys.stroke("a").flags == 0


@pytest.mark.parametrize(
    "name", ["nosuchkey", "ctrl+", "f25", "", "mouse:left", "+a", "ctrl++a", "ctrl+a+"]
)
def test_unknown_key_code(name: str) -> None:
    # 모르는 이름도 잘못 쓴 조합(빈 이름)도 같은 key_unknown이다
    with pytest.raises(PlatformError) as caught:
        keys.combo(name)
    assert caught.value.code == KEY_UNKNOWN
    with pytest.raises(PlatformError) as single:
        keys.stroke(name or "x x")
    assert single.value.code == KEY_UNKNOWN
    with pytest.raises(KeyUnknown) as core:
        [canonical_key(n) for n in split_combo(name)]
    assert core.value.code == KEY_UNKNOWN


@pytest.mark.parametrize(
    ("combo", "names"),
    [
        ("ctrl+shift+a", ["ctrl", "shift", "a"]),
        ("ctrl++", ["ctrl", "="]),
        ("+", ["="]),
        ("Alt+F4", ["alt", "f4"]),
        ("right_ctrl+End", ["rctrl", "end"]),
    ],
)
def test_combo_split_matches_actor(combo: str, names: list[str], tmp_path: Path) -> None:
    assert [s.name for s in keys.combo(combo)] == names
    assert [canonical_key(n) for n in split_combo(combo)] == names
    # 액터가 누르는 차례도 같다 (가짜 백엔드 기록), 떼기는 거꾸로
    log = tmp_path / "input.jsonl"
    actor = InputActor(FakeBackend(log)).start()
    actor.press(combo)
    assert [k.name for k in actor.held] == names
    assert actor.stop(10)
    ops = [(line["op"], line["key"]) for line in read_fake_input_log(log)]
    assert ops == [("down", n) for n in names] + [("up", n) for n in reversed(names)]
