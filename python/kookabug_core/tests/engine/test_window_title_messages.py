"""UX7: 실행 중 얻은 창 참조가 메시지·사유 글이 될 때 실제 제목이 없다 (보통·붙여 실행)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from helpers.graphs import GraphBuilder, link, make_workspace
from helpers.m1 import ScenePlatform

from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts
from kookabug_core.engine.executor import AttachStart
from kookabug_core.loader import load_program
from kookabug_core.record.journal import Journal
from kookabug_core.registry import default_registry
from kookabug_core.runner.run import _JournalSink  # pyright: ignore[reportPrivateUsage]
from kookabug_sdk.types import ProcessRef, WindowRef

ACCOUNT = "qa-compare-account-77"


def test_window_ref_repr_has_no_title() -> None:
    ref = WindowRef(0x1A2B, f"Game [Account : {ACCOUNT}]", 123, "1", "b1")
    assert ACCOUNT not in repr(ref) and ACCOUNT not in str(ref)
    assert "0x1a2b" in repr(ref)
    assert ref.title.endswith(f"{ACCOUNT}]")  # 값은 그대로


@pytest.mark.parametrize("attached", [False, True])
def test_compare_message_omits_runtime_window_title(tmp_path: Path, attached: bool) -> None:
    platform = ScenePlatform.sample()
    launched = platform.scenario.launch_game("game.exe", ())
    launched.window = replace(launched.window, title=f"QAGame [Account : {ACCOUNT}]")
    ws = make_workspace(tmp_path)
    graph = (
        GraphBuilder()
        .entry("n_attach")
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": "QAGame"},
            next={"found": "n_compare"},
        )
        .node(
            "n_compare",
            "core.assert.compare",
            inputs={"a": link("n_attach.window"), "op": "==", "b": None},
        )
    )
    graph.write(ws, "tests/cmp.graph.json")
    program = load_program(ws, "tests/cmp.graph.json")
    start = (
        AttachStart(replace(launched.window, title="@game"), ProcessRef(launched.window.pid))
        if attached
        else None
    )
    path = tmp_path / "events.jsonl"
    with Journal(path, "cmpttl01", writer="runner") as journal:
        executor = Executor(
            default_registry(),
            platform=platform,
            clock=FakeClock(),
            artifacts=MemoryArtifacts(),
            sink=_JournalSink(journal),
        )
        result = executor.run(program, ExecOptions(run_id="cmpttl01", attach=start))
    assert result.verdict == "fail"
    disk = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    messages = [e["message"] for e in disk if "message" in e]
    assert messages
    assert ACCOUNT not in json.dumps(messages, ensure_ascii=False) + str(result.reason)
