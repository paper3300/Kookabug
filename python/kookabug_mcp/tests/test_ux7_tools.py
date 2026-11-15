"""UX7 MCP 도구 (처리기 단위, daemon 대역).

- `kb_run_status`의 기다림은 daemon 요청 한 번(`run.status{wait_ms}`) — 안쪽 폴링이 없다
- 도구 호출 하나의 daemon 요청에는 같은 호출 번호가 붙는다 (작업 활동·호출 수를 MCP 호출 단위로)
- `kb_explore_step`: 입력 실패는 isError, 보호 화면은 이미지 없이, `@game` 캡처는 결과에 `@game`만
- `kb_report_note`의 headline, `kb_question_wait`의 결과에 값 없이 키 이름만
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from kookabug_mcp.results import ToolError
from kookabug_mcp.tools import by_name, call_tool

ACCOUNT_ID = "qa-acct-77Q"


class Link:
    """daemon 대역: 부른 (메서드, 인자, 호출 번호)를 남기고 정해 둔 값을 준다."""

    def __init__(self, answers: Mapping[str, Any]) -> None:
        self.answers = dict(answers)
        self.calls: list[tuple[str, dict[str, Any], int | None]] = []
        self.toolsets = frozenset({"core"})
        self.root = Path(".")
        self.principal = {"kind": "agent", "id": "t"}
        self._number = 0
        self._current: int | None = None

    def begin_tool(self) -> None:
        self._number += 1
        self._current = self._number

    def end_tool(self) -> None:
        self._current = None

    def call(self, method: str, params: Mapping[str, Any] | None = None, **_: Any) -> Any:
        self.calls.append((method, dict(params or {}), self._current))
        return self.answers[method]


def run(link: Link, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return call_tool(link, by_name()[tool], args)  # pyright: ignore[reportArgumentType]


def test_run_status_waits_in_one_request() -> None:
    link = Link({"run.status": {"state": "ended", "outcome": {"verdict": "pass"}}})
    result = run(link, "kb_run_status", {"run": "abcd1234", "wait_ms": 20000})
    assert not result["isError"]
    assert [(m, p) for m, p, _ in link.calls] == [
        ("run.status", {"run_id": "abcd1234", "wait_ms": 20000})
    ]


def test_one_call_number_per_tool_call() -> None:
    link = Link(
        {
            "run.status": {"state": "ended", "outcome": {"verdict": "fail"}},
            "run.failure": {"failure": {"node": "n", "step": "s1", "error": None}},
        }
    )
    run(link, "kb_run_status", {"run": "abcd1234"})
    run(link, "kb_run_status", {"run": "abcd1234"})
    numbers = [n for _, _, n in link.calls]
    assert numbers == [1, 1, 2, 2]


FRAME = {"frame_id": "f_1", "width": 4, "height": 4, "dpi": 96, "client_size": [4, 4],
         "image": {"cache": "f_1.png"}}  # fmt: skip
STEP = {
    "frame": FRAME,
    "changed": True,
    "waited_ms": 700,
    "window": "@game",
    "input": {"run_id": "abcd1234", "verdict": "pass"},
    "identify": {"matches": [], "unknown": [], "checked": 1, "problems": []},
    "new_screen": True,
    "move": {"from": "title", "to": None, "status": "pending"},
}


def test_explore_step_summary_and_failure() -> None:
    link = Link({"explore.step": STEP})
    result = run(link, "kb_explore_step", {"window": "@game", "point": [1, 1]})
    text = result["content"][0]["text"]
    assert "새 화면 저장 때 채움" in text and "처음 보는 화면" in text
    assert result["structuredContent"]["frame_id"] == "f_1"
    error = {"code": "window_not_found", "message": "창이 없다"}
    failed = {**STEP, "input": {"run_id": "abcd1234", "verdict": "error", "error": error}}
    link = Link({"explore.step": failed})
    with pytest.raises(ToolError) as caught:
        run(link, "kb_explore_step", {"window": "@game", "keys": "enter"})
    assert caught.value.code == "window_not_found"
    protected = {
        **STEP,
        "frame": {**FRAME, "protected": {"hint": "비밀값 칸", "reason": "secret_field"}},
    }
    link = Link({"explore.step": protected})
    result = run(link, "kb_explore_step", {"window": "@game", "secret": "acc.pw"})
    assert result["structuredContent"]["protected"]["reason"] == "secret_field"
    assert all(c["type"] == "text" for c in result["content"])  # 이미지 없음


def test_game_capture_keeps_title_out() -> None:
    window = {"handle": 7, "title": f"Game [Account : {ACCOUNT_ID}]", "process": "p", "pid": 1,
              "client_size": [4, 4], "dpi": 96}  # fmt: skip
    link = Link(
        {
            "windows.list": {"windows": [window]},
            "target.capture": {**FRAME, "protected": {"hint": "h", "reason": "secret_field"}},
        }
    )
    result = run(link, "kb_screen_capture", {"window": "@game"})
    assert link.calls[0] == ("windows.list", {"game": True}, 1)
    assert link.calls[1][1] == {"window": 7}
    assert result["structuredContent"]["window"] == "@game"
    assert ACCOUNT_ID not in str(result)
    # 기억한 게임이 없으면 window_not_found
    link = Link({"windows.list": {"windows": []}})
    with pytest.raises(ToolError) as caught:
        run(link, "kb_screen_capture", {"window": "@game"})
    assert caught.value.code == "window_not_found"


def test_question_wait_and_note_headline() -> None:
    link = Link(
        {
            "question.wait": {"id": "u-1", "state": "answered", "kind": "credential",
                              "secret_keys": ["login.id"], "answered": True, "waited_ms": 3},
            "job.note": {"job": "j-1", "bytes": 3},
        }
    )  # fmt: skip
    result = run(link, "kb_question_wait", {"id": "u-20261115-000000-abcd", "wait_ms": 1000})
    assert "login.id" in result["content"][0]["text"]
    run(link, "kb_report_note", {"text": "요약", "headline": "로그인 팝업까지 — 계정 필요"})
    assert link.calls[-1][1] == {"text": "요약", "headline": "로그인 팝업까지 — 계정 필요"}
