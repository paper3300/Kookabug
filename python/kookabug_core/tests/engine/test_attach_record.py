"""붙여 실행 기록 (UX7 D): 창 제목·게임 비밀값을 가리지 않는다 (UX11 B, 2026-11-16 — 로컬 툴).
보통 실행의 포커스 실패 경고는 제목 대신 HWND·프로세스 이름 그대로다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.m1 import ScenePlatform
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import (
    ExecOptions,
    Executor,
    FakeClock,
    InProcessInvoker,
    MemoryArtifacts,
    RunResult,
)
from kookabug_core.engine.context import FOREGROUND_NOT_ACQUIRED
from kookabug_core.engine.executor import AttachStart
from kookabug_core.ir import Node
from kookabug_core.loader import load_program
from kookabug_core.record.journal import Journal
from kookabug_core.registry import NodeDef
from kookabug_core.runner.run import _JournalSink  # pyright: ignore[reportPrivateUsage]
from kookabug_sdk import Result
from kookabug_sdk.context import Context
from kookabug_sdk.types import ProcessRef, WindowRef

ACCOUNT = "review-account-77"
SECRET_VALUE = "pw-Zq81-secret"


class LockedForeground(ScenePlatform):
    """첫 창을 앞으로 가져오지 못한다 (포커스 획득 실패 경고만 대역)."""

    def bring_forward(self, window: WindowRef, step: str | None) -> bool:
        return False


class TitleFails(InProcessInvoker):
    """`n_fail`은 지금 창의 **실제 제목**과 비밀값을 메시지에 넣어 실패, `n_raise`는 예외로."""

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        title = ctx.window.title if ctx.window is not None else ""
        if node.id == "n_log":
            ctx.log.info(f"지금 창 {title} · {SECRET_VALUE}")
            return Result("ok", "ok")
        if node.id == "n_fail":
            return Result("fail", "fail", {}, f"창 '{title}'에서 못 찾았다 ({SECRET_VALUE})")
        if node.id == "n_raise":
            raise RuntimeError(f"창 '{title}'이 응답하지 않는다")
        if node.id == "n_ok":
            return Result("ok", "ok")
        return super().invoke(nodedef, node, ctx, inputs)


def run_attached(
    tmp_path: Path, last: str, *, attached: bool = True
) -> tuple[RunResult, Path, ScenePlatform]:
    platform = LockedForeground(ScenePlatform.sample().scenario)
    launched = platform.scenario.launch_game("game.exe", ())
    launched.window = replace(launched.window, title=f"ReviewGame [Account : {ACCOUNT}]")
    ws = make_workspace(tmp_path)
    graph = (
        tk()
        .entry("n_attach")
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": "ReviewGame"},
            next={"found": "n_log"},
        )
        .node("n_log", "testkit.fail_once", next={"ok": last})
        .node(last, "testkit.fail_once", next={"ok": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    graph.write(ws, "tests/review.graph.json")
    program = load_program(ws, "tests/review.graph.json")
    start = (
        AttachStart(
            launched.window,
            ProcessRef(launched.window.pid),
        )
        if attached
        else None
    )
    journal_path = tmp_path / "events.jsonl"
    with Journal(journal_path, "reviewr2", writer="runner") as journal:
        executor = Executor(
            registry_with_testkit(),
            platform=platform,
            clock=FakeClock(),
            artifacts=MemoryArtifacts(),
            sink=_JournalSink(journal),
            invoker=TitleFails(),
        )
        result = executor.run(program, ExecOptions(run_id="reviewr2", attach=start))
    return result, journal_path, platform


def agent_events(tmp_path: Path, journal: Path, result: RunResult) -> str:
    """Agent가 읽는 기록 (daemon `AgentRun` — events.jsonl에서)."""
    folder = tmp_path / "runs" / "2026-11-16T00-00-00_review_reviewr2"
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_bytes(journal.read_bytes())
    (folder / "run.json").write_text(
        json.dumps({"run_id": "reviewr2", "agent_mask": 1, "reason": result.reason}),
        encoding="utf-8",
    )
    from kookabug_daemon.agent_view import AgentRun

    view = AgentRun.load("reviewr2", folder)
    return json.dumps(view.events, ensure_ascii=False)


@pytest.mark.parametrize("last", ["n_ok", "n_fail", "n_raise"])
def test_attach_records_keep_title_and_secret(tmp_path: Path, last: str) -> None:
    """붙여 실행도 창 제목·비밀값을 가리지 않는다 (UX11 B — 로컬 툴): 로그·노드 오류·예외·최종
    판정 사유의 원문이 디스크 `events.jsonl`·`RunResult`·Agent 보기에 그대로 남는다."""
    result, journal, _ = run_attached(tmp_path, last)
    recorded = journal.read_text(encoding="utf-8")
    shown = agent_events(tmp_path, journal, result)
    for text in (recorded, json.dumps(result.events, ensure_ascii=False), shown):
        assert ACCOUNT in text and SECRET_VALUE in text
        assert "[가림]" not in text and "***" not in text
    assert FOREGROUND_NOT_ACQUIRED in recorded
    if last == "n_ok":
        assert result.verdict == "pass"
    else:
        assert result.verdict in ("fail", "error") and ACCOUNT in str(result.reason)


def test_normal_run_warning_has_no_title(tmp_path: Path) -> None:
    """보통 실행의 포커스 실패 경고도 창 제목 대신 HWND·프로세스 이름 (제목에 계정이 든 게임)."""
    result, journal, _ = run_attached(tmp_path, "n_ok", attached=False)
    warns = [e for e in result.events if e["event"] == "log" and e.get("level") == "warn"]
    assert len(warns) == 1
    assert FOREGROUND_NOT_ACQUIRED in journal.read_text(encoding="utf-8")
    message = warns[0]["message"]
    assert message.startswith(f"{FOREGROUND_NOT_ACQUIRED}: ")
    assert "HWND 0x" in message and "프로세스 " in message
    assert ACCOUNT not in message and "ReviewGame" not in message
