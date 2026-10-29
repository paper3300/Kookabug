"""실행 사양 `RunSpec`과 감독자 ↔ runner 제어 메시지가 `rpc.schema.json`에 맞는다."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.run import tk
from helpers.runner import RunnerHarness

from kb_testing.proc import Spawned, direct_env, isolated_env, python_cmd
from kookabug_core.runner import RunSpec, SpecError
from kookabug_core.runner.run import EXIT_START_FAILED
from kookabug_core.runner.spec import (
    DEFAULT_SELF_KILL_MARGIN_MS,
    DEFAULT_SHUTDOWN_GRACE_MS,
    ident_from_json,
    ident_to_json,
)
from kookabug_core.schema import check_shape
from kookabug_core.win import current

# 메서드 → (params 부분 스키마, result 부분 스키마). None = params 없음 / 알림
METHODS: Final[dict[str, tuple[str | None, str | None]]] = {
    "runner.hello": ("RunnerHelloParams", "EmptyResult"),
    "runner.stopping": ("RunnerStoppingParams", None),
    "run.cancel": (None, "ControlStateResult"),
    "run.pause": (None, "ControlStateResult"),
    "run.resume": (None, "ControlStateResult"),
}


def spec_json(**extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "run_id": "abcd1234",
        "run_dir": "C:/runs/x",
        "workspace_root": "C:/ws",
        "graph": "tests/t.graph.json",
        "control": {"pipe": r"\\.\pipe\kookabug-test", "key": "ab" * 32},
        "job_name": "Local\\Kookabug.Run.abcd1234",
        "supervisor": ident_to_json(current()),
        "deadline_ms": 1000,
        "profile": None,
        "settings": {"a": 1},
        "plugin_modules": [],
        "platform": {"kind": "none"},
    }
    data.update(extra)
    return data


def test_spec_defaults_and_roundtrip() -> None:
    spec = RunSpec.from_json(spec_json())
    assert spec.shutdown_grace_ms == DEFAULT_SHUTDOWN_GRACE_MS
    assert spec.self_kill_margin_ms == DEFAULT_SELF_KILL_MARGIN_MS
    assert spec.supervisor == current()
    again = RunSpec.from_json(spec.to_json())
    assert again == spec
    assert check_shape(spec.to_json(), "rpc", ref="#/$defs/RunSpec") == []


def test_ident_created_is_decimal_string_beyond_rpc_int_range() -> None:
    ident = current()
    data = ident_to_json(ident)
    assert isinstance(data["created"], str) and int(data["created"]) > 2**53
    assert ident_from_json(data) == ident


@pytest.mark.parametrize(
    "bad",
    [
        {"deadline_ms": 0},
        {"platform": {"kind": "windows"}},
        {"control": {"pipe": "x", "key": "short"}},
        {"unknown": 1},
    ],
)
def test_spec_invalid_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(SpecError):
        RunSpec.from_json(spec_json(**bad))


@pytest.mark.process
def test_bad_spec_exits_start_failed(tmp_path: Path) -> None:
    proc = subprocess.run(
        python_cmd("-m", "kookabug_core.runner"),
        input=b"{not json",
        env=direct_env(isolated_env(tmp_path)),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == EXIT_START_FAILED
    assert b"SpecError" in proc.stderr


@pytest.mark.process
def test_control_session_messages_validate(tmp_path: Path, spawned: Spawned) -> None:
    signal = tmp_path / "gate.signal"
    graph = (
        tk()
        .entry("n_gate")
        .node("n_gate", "testkit.gate", inputs={"signal": str(signal)}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    h = RunnerHarness.make(tmp_path, graph).start(spawned)
    h.wait_log("gate")
    h.pause()
    signal.touch()
    h.wait_event("debug.pause")
    h.resume()
    h.finish()
    pending: dict[tuple[str, int], str] = {}
    seen: set[str] = set()
    for direction, msg in h.messages:
        assert check_shape(msg, "rpc") == [], msg
        if "method" in msg:
            method = msg["method"]
            seen.add(method)
            params_ref, _ = METHODS[method]
            if params_ref is None:
                assert "params" not in msg, msg
            else:
                problems = check_shape(msg["params"], "rpc", ref=f"#/$defs/{params_ref}")
                assert problems == [], msg
            if "id" in msg:
                pending[(direction, msg["id"])] = method
            continue
        asker = "recv" if direction == "send" else "send"
        method = pending.pop((asker, msg["id"]))
        result_ref = METHODS[method][1]
        assert result_ref is not None and "result" in msg, msg
        assert check_shape(msg["result"], "rpc", ref=f"#/$defs/{result_ref}") == [], msg
    assert seen == {"runner.hello", "runner.stopping", "run.pause", "run.resume"}
