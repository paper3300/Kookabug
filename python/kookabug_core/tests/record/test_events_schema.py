"""`events`·`run` 메타스키마 (구현 계획 M0b 2.8 표, G18)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace
from helpers.run import check_ok, run_graph, tk

from kookabug_core.record import Journal, read_journal
from kookabug_core.schema import check_shape, kind_of, metaschema
from kookabug_core.schema.models.events import Event
from kookabug_core.schema.models.run import Run

RUN = "r8k2x7qm"
T = "2026-10-29T06:02:11.104Z"


def ev(event: str, seq: int = 1, **fields: Any) -> dict[str, Any]:
    return {"event": event, "run": RUN, "seq": seq, "t": T, **fields}


STEP_END = {
    "attempt": 1,
    "duration_ms": 12,
    "exit": "done",
    "outputs": {"text": "x"},
    "status": "success",
    "step": "s2",
}

# 2.8 표의 이벤트 종류마다 하나 이상
SAMPLES: dict[str, dict[str, Any]] = {
    "run.start": ev(
        "run.start",
        graph="tests/inventory_open.graph.json",
        protocol=1,
        runner={"created": 1761717731104000, "pid": 4120, "version": "0.1.0"},
    ),
    "step.start": ev(
        "step.start", attempt=1, node="n_entry", parent=None, path=["n_entry"], step="s1"
    ),
    "step.start(iteration)": ev(
        "step.start",
        attempt=1,
        iteration=0,
        node="n_x",
        parent="s3",
        path=["n_c", "n_x"],
        step="s4",
    ),
    "attempt.end": ev(
        "attempt.end",
        attempt=1,
        duration_ms=5,
        exit="timeout",
        message="못 찾음",
        outputs={},
        status="fail",
        step="s2",
    ),
    "step.end": ev("step.end", **STEP_END),
    "step.end(full)": ev(
        "step.end",
        **{
            **STEP_END,
            "artifacts": ["steps/s2_before.png"],
            "graph": "snapshot/subgraphs/enter_world.graph.json",
            "iteration": 2,
            "message": "m",
            "omitted": [
                {"kind": "screenshot", "name": "after", "reason": "secret_input"},
                {"kind": "screenshot", "reason": "policy_off", "source": "subgraphs/login"},
            ],
            "retried": True,
        },
    ),
    "step.end(error)": ev(
        "step.end",
        **{
            **STEP_END,
            "error": {"code": "worker_died", "message": "워커가 죽었다"},
            "exit": None,
            "outputs": {},
            "status": "error",
        },
    ),
    "log": ev("log", level="info", message="안녕", node="n_log", step="s2"),
    "log(runner)": ev("log", level="warn", message="채널", node=None, step=None),
    "input.down": ev("input.down", device="keyboard", key="ctrl", step="s3"),
    "input.up": ev("input.up", button="left", device="mouse"),
    "input.recovered": ev(
        "input.recovered",
        by={"kind": "runner", "run": "a1b2c3d4"},
        from_run="z9y8x7w6",
        inputs=[{"device": "keyboard", "key": "ctrl"}, {"button": "left", "device": "mouse"}],
    ),
    "cancel.requested": ev("cancel.requested", reason="supervisor_lost"),
    "control.lost": ev("control.lost", error="EOF"),
    "debug.pause": ev("debug.pause", step="s5"),
    "debug.resume": ev("debug.resume"),
    "worker.start": ev("worker.start", pid=77),
    "worker.exit": ev("worker.exit", exit_code=1, pid=77, reason="killed_after_grace"),
    "run.end": ev(
        "run.end",
        code="assertion_passed",
        duration_ms=4100,
        failure_path=None,
        failure_step=None,
        finalized_by="runner",
        reason="검증 1개 성공",
        verdict="pass",
    ),
    "run.end(supervisor)": ev(
        "run.end",
        cancel_reason="cancelled",
        code="runner_died",
        duration_ms=None,
        failure_path=["n_c", "n_block"],
        failure_step="s4",
        finalized_by="supervisor",
        input_recovery="recovered",
        reason="runner가 실행을 마무리하지 못하고 끝났다",
        runner_exit_code=4,
        truncated_bytes=37,
        verdict="error",
    ),
}

KINDS = sorted({s["event"] for s in SAMPLES.values()})


def codes(diags: list[Any]) -> list[tuple[str, str]]:
    return [(d.code, d.pointer) for d in diags]


@pytest.mark.parametrize("name", list(SAMPLES))
def test_each_event_kind_validates(name: str) -> None:
    sample = SAMPLES[name]
    assert check_shape(sample, "events") == []
    # 생성 모델도 같은 값을 읽는다
    assert Event.model_validate(sample).model_dump(mode="json", exclude_unset=True) == sample


def test_samples_cover_every_event_kind() -> None:
    defined = sorted(
        d["properties"]["event"]["const"]
        for d in metaschema("events")["$defs"].values()
        if "event" in d.get("properties", {})
    )
    assert defined == KINDS
    assert len(defined) == 15


def test_unknown_event_kind_rejected() -> None:
    diags = check_shape(ev("step.restart", step="s1"), "events")
    assert codes(diags) == [("invalid_value", "/event")]
    assert "step.start" in diags[0].message


@pytest.mark.parametrize("field", ["seq", "t", "run", "event"])
def test_seq_and_t_required(field: str) -> None:
    sample = dict(SAMPLES["log"])
    del sample[field]
    assert ("missing_field", "") in codes(check_shape(sample, "events"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seq", 0),
        ("seq", "1"),
        ("t", "2026-10-29T06:02:11Z"),
        ("t", "2026-10-29T06:02:11.104+09:00"),
        ("run", "R8K2X7QM"),
        ("run", "r8k2"),
    ],
)
def test_common_field_values_checked(field: str, value: Any) -> None:
    assert check_shape({**SAMPLES["log"], field: value}, "events") != []


def test_kind_specific_fields_checked() -> None:
    assert codes(check_shape({**SAMPLES["log"], "extra": 1}, "events")) == [
        ("unknown_field", "/extra")
    ]
    bad_status = {**SAMPLES["step.end"], "status": "interrupted"}
    assert codes(check_shape(bad_status, "events")) == [("invalid_value", "/status")]
    # 키보드는 key, 마우스는 button
    assert check_shape(ev("input.down", device="keyboard", button="left"), "events")
    assert check_shape(ev("input.up", device="mouse", key="a"), "events")
    assert check_shape({**SAMPLES["cancel.requested"], "reason": "bored"}, "events")


RUNNING = {
    "conditions": {
        "deadline_ms": 1800000,
        "platform": "fake",
        "profile": None,
        "settings": {
            "accounts.qa": {"layer": "local", "secret": True},
            "server.host": {"layer": "profile", "value": "qa.example"},
        },
    },
    "format": "kookabug.run/0",
    "game_build": None,
    "graph": "tests/inventory_open.graph.json",
    "packages": {"kookabug-core": "0.1.0.dev0"},
    "plugins": [{"id": "testkit", "version": "0"}],
    "run_id": RUN,
    "runner": {"pid": 4120, "python": "3.14.0", "version": "0.1.0.dev0"},
    "started_at": T,
    "status": "running",
}
FINISHED = {
    **RUNNING,
    "code": "runner_died",
    "ended_at": "2026-10-29T06:02:15.000Z",
    "failure_path": ["n_block"],
    "failure_step": "s2",
    "finalized_by": "supervisor",
    "pause_count": 0,
    "reason": "runner가 실행을 마무리하지 못하고 끝났다",
    "run_json_repaired": True,
    "runner_exit_code": 4,
    "status": "finished",
    "verdict": "error",
}


def test_run_json_running_and_finished_shapes() -> None:
    for data in (RUNNING, FINISHED):
        assert kind_of(data) == "run"
        assert check_shape(data) == []
        assert Run.model_validate(data).model_dump(mode="json", exclude_unset=True) == data
    # 끝나지 않은 실행에 결과 필드가 있거나, 끝난 실행에 결과 필드가 없으면 오류
    assert check_shape({**RUNNING, "verdict": "pass"})
    finished_without_result = {**RUNNING, "status": "finished"}
    assert {c for c, _ in codes(check_shape(finished_without_result))} == {"missing_field"}
    # 비밀 설정은 값을 남기지 않는다
    leaked = {"layer": "local", "secret": True, "value": "pw"}
    bad = {**RUNNING, "conditions": {**RUNNING["conditions"], "settings": {"a": leaked}}}
    assert check_shape(bad)


def test_debug_info_fields_shared_with_run_root() -> None:
    schema = metaschema("run")
    debug = schema["$defs"]["DebugInfo"]["properties"]
    assert {k: schema["properties"][k] for k in debug} == debug


class _DropRun:
    """M0a 실행기 이벤트(run_id 'r1')를 저널의 실행 ID로 쓴다."""

    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    def emit(self, event: Mapping[str, Any]) -> None:
        self.journal.emit({k: v for k, v in event.items() if k != "run"})


def test_engine_events_validate_when_journaled(tmp_path: Path) -> None:
    # 실행기가 내는 dict(재시도 attempt.end·log 포함)가 그대로 메타스키마를 통과한다
    ws = make_workspace(tmp_path / "ws")
    g = (
        tk()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "시작"}, next={"done": "n_obs"})
        .node(
            "n_obs",
            "testkit.observe.flaky",
            inputs={"script": ["timeout", "found"]},
            config={"retry": {"max_attempts": 2}},
            next={"found": "n_check"},
        )
        .node("n_check", "core.assert.compare", inputs=check_ok())
    )
    journal = Journal(tmp_path / "events.jsonl", RUN)
    with journal:
        ran = run_graph(ws, g, sink=_DropRun(journal))
    assert ran.result.verdict == "pass"
    view = read_journal(tmp_path / "events.jsonl")
    kinds = {e["event"] for e in view.events}
    assert {"step.start", "step.end", "attempt.end", "log"} <= kinds
    for event in view.events:
        assert check_shape(event, "events") == [], event
