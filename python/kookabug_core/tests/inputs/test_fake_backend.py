"""가짜 입력 백엔드 (구현 계획 M0b 2.4 "가짜 백엔드"). 키별 훅은 `test_hooked_backend.py`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kb_testing.proc import Spawned, direct_env, python_cmd, read_fake_input_log
from kookabug_core.inputs import FakeBackend, HookedBackend, create_backend
from kookabug_sdk.types import Point


def test_log_lines_fields(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    backend = create_backend("fake", input_log=log, run="r0000001", by="runner")
    backend.down("ctrl")
    backend.up("ctrl")
    backend.mouse_down("left", Point(3, 4))
    backend.mouse_up("left")
    backend.move(Point(5, 6))
    backend.wheel(-2, Point(5, 6))
    backend.text("비밀")
    lines = read_fake_input_log(log)
    common = {"by": "runner", "run": "r0000001", "pid": os.getpid(), "thread": "MainThread"}
    assert lines == [
        {"op": "down", "device": "keyboard", "key": "ctrl", **common},
        {"op": "up", "device": "keyboard", "key": "ctrl", **common},
        {"op": "down", "device": "mouse", "button": "left", "at": [3, 4], **common},
        {"op": "up", "device": "mouse", "button": "left", **common},
        {"op": "move", "device": "mouse", "at": [5, 6], **common},
        {"op": "wheel", "device": "mouse", "amount": -2, "at": [5, 6], **common},
        {"op": "text", "length": 2, **common},
    ]


_WRITER = """
import sys
from kookabug_core.inputs import FakeBackend
backend = FakeBackend(sys.argv[1], by=sys.argv[2])
for i in range(300):
    backend.down(f"k{i}")
    backend.up(f"k{i}")
"""


@pytest.mark.process
def test_two_processes_append_same_log(tmp_path: Path, spawned: Spawned) -> None:
    log = tmp_path / "input.jsonl"
    procs = [
        spawned.popen(python_cmd("-c", _WRITER, log, by), env=direct_env()) for by in ("a", "b")
    ]
    for proc in procs:
        assert proc.wait(timeout=30) == 0
    lines = read_fake_input_log(log)  # 줄이 깨지면 json 오류
    assert len(lines) == 1200
    for by in ("a", "b"):
        mine = [line for line in lines if line["by"] == by]
        assert len(mine) == 600
        # 한 프로세스 안의 순서는 그대로다
        assert [line["key"] for line in mine[:4]] == ["k0", "k0", "k1", "k1"]


def test_create_backend_wraps_hooks_only_when_given(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    assert isinstance(create_backend("fake", input_log=log), FakeBackend)
    hooked = create_backend("fake", input_log=log, hooks={"after_down": {"a": "hang"}})
    assert isinstance(hooked, HookedBackend) and isinstance(hooked.inner, FakeBackend)
    with pytest.raises(ValueError, match="input_log"):
        create_backend("fake")
