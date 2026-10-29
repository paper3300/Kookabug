"""고장 주입 지점 (구현 계획 M0b 2.3)."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kookabug_sdk import _faults


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(_faults.ENV, raising=False)
    _faults.reset()
    yield
    _faults.reset()


def use(monkeypatch: pytest.MonkeyPatch, *rules: dict[str, Any], role: Any = "runner") -> None:
    monkeypatch.setenv(_faults.ENV, json.dumps(list(rules)))
    _faults.set_role(role)


def rule(point: str = "runner.after_hello", **extra: Any) -> dict[str, Any]:
    return {"action": "raise", "point": point, "role": "runner", **extra}


def run_script(code: str, rules: list[dict[str, Any]]) -> subprocess.Popen[bytes]:
    env = {**os.environ, _faults.ENV: json.dumps(rules)}
    return subprocess.Popen([sys.executable, "-c", code], env=env)


def test_no_env_is_noop() -> None:
    _faults.set_role("runner")
    for point in _faults.POINTS:
        _faults.fault_point(point, event="log")
        assert _faults.check(point) is None
    # 역할을 정하지 않은 프로세스에서는 규칙이 있어도 아무것도 하지 않는다
    _faults.reset()
    assert _faults.check("runner.after_hello") is None


def test_role_not_set_ignores_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_faults.ENV, json.dumps([rule()]))
    _faults.fault_point("runner.after_hello")  # set_role 전: 규칙을 읽지도 않는다


def test_exit_action() -> None:
    code = (
        "from kookabug_sdk import _faults\n"
        "_faults.set_role('runner')\n"
        "_faults.fault_point('runner.after_run_end')\n"
        "raise SystemExit(0)\n"
    )
    proc = run_script(code, [rule("runner.after_run_end", action="exit:7")])
    assert proc.wait(timeout=30) == 7


def test_raise_action(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, rule())
    with pytest.raises(RuntimeError, match=r"runner\.after_hello"):
        _faults.fault_point("runner.after_hello")
    _faults.fault_point("runner.after_hello")  # once: 소비됐다


def test_wait_action_ready_and_go(tmp_path: Path) -> None:
    barrier = tmp_path / "b1"
    out = tmp_path / "out.txt"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from kookabug_sdk import _faults\n"
        "_faults.set_role('worker')\n"
        "_faults.fault_point('worker.before_hello_reply')\n"
        f"Path({str(out)!r}).write_text('passed')\n"
    )
    proc = run_script(
        code,
        [
            {
                "action": f"wait:{barrier}",
                "point": "worker.before_hello_reply",
                "role": "worker",
            }
        ],
    )
    try:
        ready = Path(f"{barrier}.ready")
        deadline = time.monotonic() + 30
        while not ready.exists():
            assert time.monotonic() < deadline, "ready 파일이 생기지 않았다"
            assert proc.poll() is None
            time.sleep(0.02)
        assert proc.poll() is None and not out.exists()  # go 전에는 지나가지 않는다
        Path(f"{barrier}.go").touch()
        assert proc.wait(timeout=30) == 0
        assert out.read_text() == "passed"
    finally:
        proc.kill()


def test_hang_action(tmp_path: Path) -> None:
    code = (
        "from kookabug_sdk import _faults\n"
        "_faults.set_role('supervisor')\n"
        "_faults.fault_point('recovery.before_finalize')\n"
    )
    proc = run_script(
        code, [{"action": "hang", "point": "recovery.before_finalize", "role": "supervisor"}]
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=1)
    finally:
        proc.kill()
        proc.wait(timeout=30)


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ([rule("runner.nowhere")], "모르는 지점"),
        ([rule(role="daemon")], "모르는 역할"),
        ([rule("worker.in_import")], "지나지 않는다"),
        ([rule(action="explode")], "모르는 동작"),
        ([rule(action="exit:x")], "exit"),
        ([rule(action="wait:")], "모르는 동작"),
        ([rule(when={"nth": 0})], "nth"),
        ([rule(when={"event": 1})], "event"),
        ([rule(when={"evnt": "log"})], "when"),
        ([rule(once="yes")], "once"),
        ([rule(extra=1)], "모르는 필드"),
        ([["runner.after_hello"]], "객체"),
    ],
)
def test_unknown_point_or_role_rejected(
    monkeypatch: pytest.MonkeyPatch, rules: list[Any], message: str
) -> None:
    monkeypatch.setenv(_faults.ENV, json.dumps(rules))
    with pytest.raises(_faults.FaultConfigError, match=message):
        _faults.set_role("runner")


def test_bad_env_and_role_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_faults.ENV, "{not json")
    with pytest.raises(_faults.FaultConfigError, match="JSON"):
        _faults.set_role("runner")
    monkeypatch.setenv(_faults.ENV, json.dumps(rule()))
    with pytest.raises(_faults.FaultConfigError, match="목록"):
        _faults.set_role("runner")
    monkeypatch.delenv(_faults.ENV)
    with pytest.raises(_faults.FaultConfigError, match="역할"):
        _faults.set_role("daemon")  # type: ignore[arg-type]
    _faults.set_role("runner")
    with pytest.raises(_faults.FaultConfigError, match="지점"):
        _faults.fault_point("runner.typo")


def test_role_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    # runner용 부분 줄 규칙은 감독자의 마무리 쓰기에는 걸리지 않는다
    partial = {
        "action": "raise",
        "point": "journal.partial_line",
        "role": "runner",
        "when": {"event": "run.end"},
    }
    use(monkeypatch, partial, role="supervisor")
    assert _faults.check("journal.partial_line", event="run.end") is None
    _faults.reset()
    use(monkeypatch, partial, role="runner")
    assert _faults.check("journal.partial_line", event="run.end") is not None


def test_when_event_and_nth_once(monkeypatch: pytest.MonkeyPatch) -> None:
    use(
        monkeypatch,
        {
            "action": "raise",
            "point": "journal.partial_line",
            "role": "runner",
            "when": {"event": "log", "nth": 3},
        },
    )
    hits = [
        _faults.check("journal.partial_line", event=kind) is not None
        for kind in ["log", "step.start", "log", "step.end", "log", "log", "log"]
    ]
    # 3번째 log에서만 한 번, 그 뒤 같은 지점은 통과
    assert hits == [False, False, False, False, True, False, False]


def test_once_false_fires_from_nth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, rule(when={"nth": 2}, once=False))
    hits = [_faults.check("runner.after_hello") is not None for _ in range(4)]
    assert hits == [False, True, True, True]


def test_points_table_matches_plan() -> None:
    assert set(_faults.POINTS) == {
        "journal.partial_line",
        "runner.after_run_end",
        "runner.before_run_json_final",
        "runner.before_worker_shutdown",
        "runner.before_lease_release",
        "runner.after_hello",
        "runner.before_validate",
        "actor.before_backend",
        "worker.before_hello_reply",
        "worker.in_import",
        "recovery.runner_exit_observed",
        "recovery.before_finalize",
        "recovery.before_input_recovery",
        "lease.before_recovery",
    }
    assert _faults.POINTS["journal.partial_line"] == frozenset(_faults.ROLES)
