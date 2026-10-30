"""runner의 엔진 설정(`kookabug.json` `ocr`)은 실행 스냅샷의 복사본에서 읽는다 (T9 검수 4).

원본 워크스페이스를 연 뒤 스냅샷 전에 설정이 바뀌어도, 플랫폼 엔진은 스냅샷에 고정된 값으로 만든다
(그래프 JSON 스키마 v0 5장 "실행 시작 때 고정"). 실제 `_prepare_and_run`·`take_snapshot`·
`_open_platform`을 쓰고, 실행(`_run_program`)만 멈춘다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from helpers.graphs import GraphBuilder, make_workspace

from kookabug_core.record.snapshot import take_snapshot
from kookabug_core.runner import run as runner_module
from kookabug_core.runner.run import Runner, _End
from kookabug_core.runner.spec import ControlSpec, PlatformSpec, RunSpec
from kookabug_core.win import current

GRAPH = "tests/t.graph.json"


def test_runner_ocr_settings_follow_copied_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = make_workspace(tmp_path / "ws")
    GraphBuilder().entry("n_pass").node("n_pass", "core.test.pass").write(ws, GRAPH)
    config_path = ws.root / "kookabug.json"
    initial = json.loads(config_path.read_text(encoding="utf-8-sig"))
    initial["ocr"] = {"engine": "rapidocr", "det": {"tile_side": 640}}
    config_path.write_text(json.dumps(initial), encoding="utf-8")
    seen: dict[str, Any] = {}

    def snapshot_after_change(workspace: Any, *args: Any, **kwargs: Any) -> Any:
        # 원본을 연 뒤·복사 직전에 설정이 바뀐다
        changed = {**initial, "ocr": {"engine": "rapidocr", "det": {"tile_side": 960}}}
        config_path.write_text(json.dumps(changed), encoding="utf-8")
        snap = take_snapshot(workspace, *args, **kwargs)
        seen["snapshot"] = snap.workspace.config["ocr"]["det"]["tile_side"]
        return snap

    def stop(self: Runner, program: Any, registry: Any) -> _End:
        return _End.error("test_stop", "플랫폼까지 만든 뒤 멈춘다")

    monkeypatch.setattr(runner_module, "take_snapshot", snapshot_after_change)
    monkeypatch.setattr(Runner, "_run_program", stop)
    spec = RunSpec(
        "t9snap00",
        tmp_path / "run",
        ws.root,
        GRAPH,
        ControlSpec("unused", b""),
        "unused",
        current(),
        60_000,
        platform=PlatformSpec("fake"),
    )
    runner = Runner(spec)
    runner.controller = SimpleNamespace()  # pyright: ignore[reportAttributeAccessIssue]
    runner.journal = object()  # pyright: ignore[reportAttributeAccessIssue]
    runner._run_json = {"conditions": {}}  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(runner, "_save_running", lambda: None)
    end = runner._prepare_and_run()  # pyright: ignore[reportPrivateUsage]
    assert end.code == "test_stop", end
    engines = runner.platform.engines
    assert engines is not None
    assert seen["snapshot"] == 960
    assert engines._ocr_options["det"]["tile_side"] == 960  # pyright: ignore[reportPrivateUsage]
