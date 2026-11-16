"""UX12 MCP 도구 (처리기 단위, daemon 대역).

- 2a `kb_app_launch`: 사람이 띄운 게임을 썼으면(`reused`) 새로 띄우지 않았다고 알린다
- 2c `kb_run_start`(attach): 붙여 실행이 건너뛰는 노드(`attach_skips`)를 결과·머리글에 둔다
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kookabug_mcp.tools import ATTACH_SKIPS, by_name, call_tool


class Link:
    """daemon 대역: 부른 (메서드, 인자)를 남기고 정해 둔 값을 준다 (`test_ux8_tools`와 같은 꼴)."""

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


def test_app_launch_reports_reused_human_game() -> None:
    link = Link({"app.launch": {"pid": 333, "reused": True}})
    result = run(link, "kb_app_launch", {})
    text = result["content"][0]["text"]
    assert not result["isError"] and "새로 띄우지 않고" in text and "333" in text
    assert "사람이 앱에서 띄운 게임" in by_name()["kb_app_launch"].description


START = {"run_id": "abcd1234", "run_dir": "runs/abcd1234", "graph": "tests/t.graph.json"}


def test_attach_run_lists_skipped_nodes() -> None:
    link = Link({"run.start": START})
    result = run(
        link, "kb_run_start", {"path": "tests/t.graph.json", "idempotency_key": "k", "attach": True}
    )
    assert not result["isError"]
    assert "건너뛴다" in result["content"][0]["text"]
    data = result["structuredContent"]
    assert data["attach_skips"] == list(ATTACH_SKIPS)
    assert any("core.app.close" in s for s in data["attach_skips"])
    assert any("game_exit" in s for s in data["attach_skips"])
    # 보통 실행에는 없다
    plain = run(link, "kb_run_start", {"path": "tests/t.graph.json", "idempotency_key": "k2"})
    assert "attach_skips" not in plain["structuredContent"]
    assert "보통 실행" in by_name()["kb_run_start"].description
