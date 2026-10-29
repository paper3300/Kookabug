"""가짜 입력 백엔드 (구현 계획 M0b 2.4 "가짜 백엔드")."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from kb_testing.proc import Spawned, barrier, direct_env, python_cmd, read_fake_input_log
from kookabug_core.inputs import FakeBackend, create_backend
from kookabug_sdk.types import Point


def test_log_lines_fields(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    backend = create_backend("fake", input_log=log, run="r0000001", by="runner")
    backend.down("ctrl")
    backend.up("ctrl")
    backend.mouse_down("left", Point(3, 4))
    backend.mouse_up("left")
    backend.text("비밀")
    lines = read_fake_input_log(log)
    common = {"by": "runner", "run": "r0000001", "pid": os.getpid(), "thread": "MainThread"}
    assert lines == [
        {"op": "down", "device": "keyboard", "key": "ctrl", **common},
        {"op": "up", "device": "keyboard", "key": "ctrl", **common},
        {"op": "down", "device": "mouse", "button": "left", "at": [3, 4], **common},
        {"op": "up", "device": "mouse", "button": "left", **common},
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


def test_hooks_before_after_down_before_up(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    seen: list[tuple[str, int]] = []

    def at(name: str):
        return lambda: seen.append((name, len(read_fake_input_log(log))))

    backend = FakeBackend(
        log,
        hooks={
            "before_down": {"a": at("before_down"), "mouse:left": at("mouse.before_down")},
            "after_down": {"a": at("after_down")},
            "before_up": {"a": at("before_up")},
        },
    )
    backend.down("a")
    backend.up("a")
    backend.down("b")  # 훅이 없는 키
    backend.mouse_down("left")
    # 훅은 기록 줄 앞뒤 정해진 자리에서 돈다
    assert seen == [
        ("before_down", 0),
        ("after_down", 1),
        ("before_up", 1),
        ("mouse.before_down", 3),
    ]


def test_hook_actions_block_and_wait(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    gate = threading.Event()
    wall = barrier(tmp_path / "wall")
    backend = FakeBackend(
        log,
        hooks={"after_down": {"a": "block"}, "before_up": {"a": f"wait:{wall.path}"}},
        gate=gate,
    )
    done = threading.Event()

    def press() -> None:
        backend.down("a")
        backend.up("a")
        done.set()

    thread = threading.Thread(target=press, daemon=True)
    thread.start()
    # block: 게이트가 닫힐 때까지 down 안에서 기다린다
    assert not done.wait(0.2)
    assert [line["op"] for line in read_fake_input_log(log)] == ["down"]
    gate.set()
    # wait:<경로>: 파일 장벽에서 up 전에 기다린다
    wall.wait_ready()
    assert [line["op"] for line in read_fake_input_log(log)] == ["down"]
    wall.go()
    assert done.wait(10)
    assert [line["op"] for line in read_fake_input_log(log)] == ["down", "up"]


def test_bad_hooks_rejected(tmp_path: Path) -> None:
    log = tmp_path / "input.jsonl"
    with pytest.raises(ValueError, match="gate"):
        FakeBackend(log, hooks={"after_down": {"a": "block"}})
    with pytest.raises(ValueError, match="훅 동작"):
        FakeBackend(log, hooks={"after_down": {"a": "explode"}})
    with pytest.raises(ValueError, match="모르는 훅"):
        FakeBackend(log, hooks={"after_up": {"a": "hang"}})
    with pytest.raises(ValueError, match="input_log"):
        create_backend("fake")
