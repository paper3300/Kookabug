"""가짜 녹화 각본 만들기 (M4 계획 2.15, `recorder-script.schema.json`): 예제 게임 로그인 각본.

    lines = login_script(split=True)      # 쉬었다 이어 친 비밀번호
    write_jsonl(path, lines)

좌표는 클라이언트(예제 게임 기준 1024x640)로 적고 화면 좌표로 바꿔 넣는다. 창은 테두리 1 px·제목
표시줄 30 px인 실제 창 모양이다(`fake_capture.py`의 `(1, 30, 1, 1)`). 각본 파일
`fixtures/sample-game/recorder/*.script.jsonl`은 `python tools/kb_testing/recorder_scripts.py`로
다시 만든다 (검사가 같은지 본다).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ACCOUNT",
    "ACCOUNT_POINT",
    "CLIENT",
    "GEOMETRY",
    "LOGIN_POINT",
    "LOGIN_SCRIPTS",
    "ORIGIN",
    "PASSWORD",
    "START_POINT",
    "ScriptBuilder",
    "login_script",
    "write_jsonl",
]

MS: Final = 1_000_000
CLIENT: Final = (1024, 640)
FRAME_AT: Final = (100, 100)
ORIGIN: Final = (FRAME_AT[0] + 1, FRAME_AT[1] + 31)
GEOMETRY: Final = {
    "frame_bounds": [FRAME_AT[0], FRAME_AT[1], CLIENT[0] + 2, CLIENT[1] + 32],
    "client_origin": list(ORIGIN),
    "client_size": list(CLIENT),
    "dpi": 96,
}
START_POINT: Final = (512, 412)
ACCOUNT_POINT: Final = (560, 230)
LOGIN_POINT: Final = (512, 408)
ACCOUNT: Final = "qa_tester_01"
PASSWORD: Final = "sample-pass-01"

_VK: Final = {"tab": 0x09, "enter": 0x0D, "backspace": 0x08, "shift": 0xA0, "esc": 0x1B}
_PUNCT: Final = {"-": (0xBD, False), "_": (0xBD, True), ".": (0xBE, False), " ": (0x20, False)}


def char_vk(ch: str) -> tuple[int, bool]:
    """US 배열 글자 → (vk, shift)."""
    if ch.isalpha():
        return ord(ch.upper()), ch.isupper()
    if ch.isdigit():
        return ord(ch), False
    return _PUNCT[ch]


class ScriptBuilder:
    """각본 줄을 시각 차례로 쌓는다 (`at`·`wait`로 시각을 옮긴다)."""

    def __init__(self, scene: str = "title", title: str = "SampleRPG") -> None:
        self.t = 0
        self.lines: list[dict[str, Any]] = [
            {
                "kind": "header",
                "format": "kookabug.recorder-script/0",
                "title": title,
                "scene": scene,
                "geometry": GEOMETRY,
            }
        ]
        self.observe(fg="target", point="target", hkl="4090409", focus_password=False)

    def at(self, ms: float) -> ScriptBuilder:
        self.t = int(ms * MS)
        return self

    def wait(self, ms: float) -> ScriptBuilder:
        self.t += int(ms * MS)
        return self

    def raw(self, **fields: Any) -> ScriptBuilder:
        """원시 입력 하나. 기본은 사람 입력(표식 없음) — `injected`·`extra_info`로 바꾼다."""
        body = {"injected": False, "injected_lower_il": False, "extra_info": 0, **fields}
        if str(body["kind"]).startswith("key"):
            body.setdefault("extended", False)
        line: dict[str, Any] = {"kind": "input", "t_ns": self.t, "input": body}
        self.lines.append(line)
        return self

    def observe(self, **fields: Any) -> ScriptBuilder:
        self.lines.append({"kind": "observe", "t_ns": self.t, **fields})
        return self

    def fault(self, fault: str, **fields: Any) -> ScriptBuilder:
        self.lines.append({"kind": "fault", "t_ns": self.t, "fault": fault, **fields})
        return self

    def mark(self, label: str) -> ScriptBuilder:
        self.lines.append({"kind": "mark", "t_ns": self.t, "label": label})
        return self

    @staticmethod
    def screen(point: tuple[int, int]) -> tuple[int, int]:
        return point[0] + ORIGIN[0], point[1] + ORIGIN[1]

    def move(self, point: tuple[int, int], **marks: Any) -> ScriptBuilder:
        x, y = self.screen(point)
        return self.raw(kind="mouse_move", x=x, y=y, **marks)

    def click(self, point: tuple[int, int], *, hold_ms: float = 40, **marks: Any) -> ScriptBuilder:
        x, y = self.screen(point)
        self.move(point, **marks).wait(120)
        self.raw(kind="mouse_down", x=x, y=y, button="left", **marks).wait(hold_ms)
        return self.raw(kind="mouse_up", x=x, y=y, button="left", **marks)

    def key(self, name: str, *, hold_ms: float = 40, **marks: Any) -> ScriptBuilder:
        vk = _VK[name]
        self.raw(kind="key_down", vk=vk, scan=0, **marks).wait(hold_ms)
        return self.raw(kind="key_up", vk=vk, scan=0, **marks)

    def type(self, text: str, *, gap_ms: float = 80, **marks: Any) -> ScriptBuilder:
        for ch in text:
            vk, shift = char_vk(ch)
            if shift:
                self.raw(kind="key_down", vk=_VK["shift"], scan=0, **marks).wait(10)
            self.raw(kind="key_down", vk=vk, scan=0, **marks).wait(30)
            self.raw(kind="key_up", vk=vk, scan=0, **marks)
            if shift:
                self.wait(10).raw(kind="key_up", vk=_VK["shift"], scan=0, **marks)
            self.wait(gap_ms)
        return self


def login_script(*, split: bool = False, backspace: bool = False) -> list[dict[str, Any]]:
    """타이틀 → 시작 클릭 → 계정 칸 클릭·글자 → Tab → 비밀번호 → 로그인 클릭 → 로비.

    `split`: 비밀번호를 `sample-` → 3초 쉼 → `pass-01`로 나눠 친다. `backspace`: 끝 자리를 한 번
    틀리게 친 뒤 Backspace로 고친다. 마지막에 `mark lobby`(로비가 보이는 시각)."""
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(1500).click(ACCOUNT_POINT)
    s.at(2000).type(ACCOUNT)
    s.wait(300).key("tab")
    s.wait(500)
    if split:
        s.type("sample-").wait(3000).type("pass-0")
    else:
        s.type("sample-pass-0")
    if backspace:
        s.type("9").wait(200).key("backspace").wait(150)
    s.type("1")
    s.wait(600).click(LOGIN_POINT)
    s.wait(800).mark("lobby")
    return s.lines


LOGIN_SCRIPTS: Final[Mapping[str, Mapping[str, bool]]] = {
    "login": {},
    "login_split": {"split": True, "backspace": True},
}
"""`fixtures/sample-game/recorder/<이름>.script.jsonl` ← `login_script(**인자)`."""


def write_jsonl(path: Path, lines: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines)
    path.write_text(text, encoding="utf-8", newline="\n")


def _main() -> None:
    folder = Path(__file__).resolve().parents[2] / "fixtures" / "sample-game" / "recorder"
    for name, kwargs in LOGIN_SCRIPTS.items():
        write_jsonl(folder / f"{name}.script.jsonl", login_script(**kwargs))


if __name__ == "__main__":
    _main()
