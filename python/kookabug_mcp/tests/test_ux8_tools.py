"""UX8 MCP 도구 (처리기 단위, daemon 대역).

- `kb_input_type`·`kb_explore_step`: 칸 클릭(point)·`select_all`을 함께 daemon에 넘긴다 (클릭+입력
  한 걸음)
- `kb_explore_step`: `window_changed`면 머리글에 알린다(실제 제목 없이)
- `kb_app_launch`: `replaced_pid`를 알린다
- `kb_run_status`: `wait_ms` 최대 60초
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kookabug_mcp.tools import by_name, call_tool


class Link:
    """daemon 대역: 부른 (메서드, 인자)를 남기고 정해 둔 값을 준다 (`test_ux7_tools`와 같은 꼴)."""

    def __init__(self, answers: Mapping[str, Any]) -> None:
        self.answers = dict(answers)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.toolsets = frozenset({"core"})
        self.root = Path(".")
        self.principal = {"kind": "agent", "id": "t"}

    def begin_tool(self) -> None:
        pass

    def end_tool(self) -> None:
        pass

    def call(self, method: str, params: Mapping[str, Any] | None = None, **_: Any) -> Any:
        self.calls.append((method, dict(params or {})))
        return self.answers[method]


def run(link: Link, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return call_tool(link, by_name()[tool], args)  # pyright: ignore[reportArgumentType]


FRAME = {
    "frame_id": "f1",
    "width": 1280,
    "height": 720,
    "dpi": 96,
    "client_size": [1280, 720],
    "protected": {"reason": "secret_field", "hint": "칸이 보여요"},
}


def step_result(**extra: Any) -> dict[str, Any]:
    return {
        "frame": FRAME,
        "changed": True,
        "waited_ms": 1200,
        "window": "@game",
        "input": {"run_id": "r1", "verdict": "pass"},
        "identify": {"matches": [], "unknown": []},
        "new_screen": True,
        "move": None,
        **extra,
    }


def test_input_type_passes_click_and_select_all() -> None:
    link = Link({"control.type": {"run_id": "r1", "verdict": "pass"}})
    args = {"window": "@game", "point": [560, 310], "secret": "acc.pw", "select_all": True}
    result = run(link, "kb_input_type", args)
    assert not result["isError"]
    assert link.calls[0] == ("control.type", args)
    assert "칸 클릭" in result["content"][0]["text"]


def test_explore_step_passes_select_all_and_shows_window_change() -> None:
    link = Link({"explore.step": step_result(window_changed=True)})
    args = {"window": "@game", "point": [560, 310], "secret": "acc.pw", "select_all": True}
    result = run(link, "kb_explore_step", args)
    assert not result["isError"]
    assert link.calls[0] == ("explore.step", args)
    text = result["content"][0]["text"]
    assert "다른 창으로 바뀜" in text and "@game" in text


def test_app_launch_reports_replaced() -> None:
    link = Link({"app.launch": {"pid": 222, "replaced_pid": 111}})
    result = run(link, "kb_app_launch", {})
    assert not result["isError"] and "111" in result["content"][0]["text"]


def test_run_status_wait_up_to_60s() -> None:
    link = Link({"run.status": {"state": "ended", "outcome": {"verdict": "pass"}}})
    run(link, "kb_run_status", {"run": "abcd1234", "wait_ms": 60000})
    assert link.calls[0] == ("run.status", {"run_id": "abcd1234", "wait_ms": 60000})
