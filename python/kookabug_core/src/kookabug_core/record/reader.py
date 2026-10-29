"""실행 기록 읽기 (스키마 v0 5장 "중단", 구현 계획 M0b 2.8).

- 끝 줄이 `\\n`으로 끝나지 않거나 JSON 객체가 아니면 버리고 `truncated`
- 중간의 깨진 줄은 경고하고 건너뛴다. `seq` 빈틈도 경고
- `step.end` 없는 스텝 = `interrupted`, `run.end` 없는 실행 = `interrupted`
- 읽기는 파일을 고치지 않는다. 아무도 마무리하지 못한 실행(이중 고장)도 이 읽기만으로 "중단"이다
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from kookabug_core.record.runfolder import EVENTS_FILE

__all__ = [
    "InputKey",
    "RunView",
    "StepView",
    "follow",
    "held_inputs",
    "read_journal",
    "read_run",
]

type StepStatus = Literal["success", "fail", "error", "cancelled", "interrupted"]
type Outcome = Literal["finalized_by_runner", "finalized_by_supervisor", "interrupted"]


@dataclass(frozen=True, slots=True, order=True)
class InputKey:
    """눌렸을 수 있는 키(`device: keyboard`) 또는 마우스 버튼(`device: mouse`)."""

    device: str
    name: str

    def to_event(self) -> dict[str, str]:
        return {"device": self.device, "key" if self.device == "keyboard" else "button": self.name}


@dataclass(slots=True)
class StepView:
    step: str
    start: dict[str, Any]
    end: dict[str, Any] | None = None

    @property
    def status(self) -> StepStatus:
        return self.end["status"] if self.end is not None else "interrupted"

    @property
    def node(self) -> str:
        return self.start.get("node", "")

    @property
    def path(self) -> list[str]:
        return list(self.start.get("path", []))


@dataclass(slots=True)
class RunView:
    """한 실행 기록을 읽은 결과.

    `valid_size`는 마지막으로 받아들인 줄 끝의 바이트 위치다 (잘린 끝 줄은 그 뒤에 있다).
    """

    path: Path
    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    truncated: bool = False
    size: int = 0
    valid_size: int = 0
    warnings: list[str] = field(default_factory=list[str])
    steps: dict[str, StepView] = field(default_factory=dict[str, StepView])

    @property
    def truncated_bytes(self) -> int:
        return self.size - self.valid_size

    @property
    def run_id(self) -> str | None:
        for event in self.events:
            run = event.get("run")
            if isinstance(run, str):
                return run
        return None

    @property
    def run_start(self) -> dict[str, Any] | None:
        return next((e for e in self.events if e.get("event") == "run.start"), None)

    @property
    def run_end(self) -> dict[str, Any] | None:
        return next((e for e in self.events if e.get("event") == "run.end"), None)

    @property
    def last_seq(self) -> int:
        seqs = [e["seq"] for e in self.events if isinstance(e.get("seq"), int)]
        return max(seqs, default=0)

    @property
    def status(self) -> Literal["finished", "interrupted"]:
        return "finished" if self.run_end is not None else "interrupted"

    @property
    def outcome(self) -> Outcome:
        """runner가 마무리한 실행 / 감독자가 마무리한 실행 / 아무도 마무리하지 못한 실행."""
        end = self.run_end
        if end is None:
            return "interrupted"
        if end.get("finalized_by") == "supervisor":
            return "finalized_by_supervisor"
        return "finalized_by_runner"

    @property
    def interrupted_steps(self) -> list[StepView]:
        return [s for s in self.steps.values() if s.end is None]

    @property
    def cancel_reason(self) -> str | None:
        reasons = [e.get("reason") for e in self.events if e.get("event") == "cancel.requested"]
        return reasons[-1] if reasons else None


def read_run(folder: str | os.PathLike[str]) -> RunView:
    """실행 폴더의 `events.jsonl`을 읽는다 (없으면 빈 기록 = 중단)."""
    return read_journal(Path(folder) / EVENTS_FILE)


def read_journal(path: str | os.PathLike[str]) -> RunView:
    path = Path(path)
    view = RunView(path)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        view.warnings.append(f"{path.name}이(가) 없다")
        return view
    view.size = len(data)
    lines = data.split(b"\n")
    tail = lines.pop()  # 마지막 \n 뒤. 온전한 파일이면 빈 바이트
    offset = 0
    parsed: list[tuple[int, int, dict[str, Any] | None]] = []  # (줄 번호, 줄 끝 위치, 값)
    for number, raw in enumerate(lines, start=1):
        offset += len(raw) + 1
        parsed.append((number, offset, _object(raw)))
    if tail:
        view.truncated = True
    elif parsed and parsed[-1][2] is None:
        # \n으로 끝나도 JSON이 아니면 잘린 끝 줄로 본다
        view.truncated = True
        parsed.pop()
    view.valid_size = parsed[-1][1] if parsed else 0

    for number, _, record in parsed:
        if record is None:
            view.warnings.append(f"{number}번째 줄이 JSON 객체가 아니라 건너뛴다")
            continue
        view.events.append(record)
    _check_seq(view)
    _collect_steps(view)
    return view


def follow(
    folder: str | os.PathLike[str],
    after_seq: int = 0,
    *,
    stop: Callable[[], bool] | None = None,
    interval: float = 0.02,
    timeout: float | None = None,
    until_run_end: bool = False,
) -> Iterator[dict[str, Any]]:
    """`seq > after_seq`인 이벤트를 완전한 줄만 차례로 준다. 새 줄을 기다린다.

    끝나는 때: `stop()`이 참이 된 뒤 남은 완전한 줄을 다 준 다음, 또는 `timeout`초가 지나면.
    `until_run_end`면 `run.end`를 본 읽기에서 그때까지 쓰인 완전한 줄을 다 준 다음에도 끝난다.
    `run.end` 뒤에도 감독자가 `input.recovered`를 더할 수 있으므로, 그것까지 받으려면 감독자
    마무리가 끝난 것을 아는 호출자가 `stop`으로 끝낸다.

    읽기 위치는 완전한 줄 끝까지만 나아간다. 잘린 끝 줄은 감독자 마무리가 잘라 내고 그 자리에
    다른 줄을 쓸 수 있으므로 매번 그 위치부터 다시 읽는다.
    """
    path = Path(folder) / EVENTS_FILE
    deadline = None if timeout is None else time.monotonic() + timeout
    position = 0
    last_seq = after_seq
    ended = False
    while True:
        stopping = stop is not None and stop()
        size, chunk = _read_from(path, position)
        if size < position:
            # 완전한 줄까지 잘려 나갔다 (정상 마무리에서는 없다): 처음부터 다시 읽고 seq로 건너뛴다
            position = 0
            size, chunk = _read_from(path, 0)
        end = chunk.rfind(b"\n") + 1
        position += end
        for raw in chunk[:end].split(b"\n")[:-1]:
            record = _object(raw)
            if record is None:
                continue
            seq = record.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                if seq <= last_seq:
                    continue
                last_seq = seq
            ended = ended or record.get("event") == "run.end"
            yield record
        if stopping or (until_run_end and ended):
            return
        if deadline is not None and time.monotonic() >= deadline:
            return
        time.sleep(interval)


def held_inputs(view: RunView) -> list[InputKey]:
    """기록상 눌렸을 수 있는 키·버튼: 마지막 입력 이벤트가 `input.down`인 것.

    `input.down`은 백엔드 호출 전에, `input.up`은 후에 쓰므로 프로세스가 어디서 죽어도 빠지지
    않는다. 이 실행을 복구했다는 `input.recovered`(`from_run`이 이 실행)는 그 키들을 뗀 것으로 본다.
    잘린 끝 줄은 읽기가 이미 버렸다.
    """
    held: dict[InputKey, bool] = {}
    for event in view.events:
        kind = event.get("event")
        if kind in ("input.down", "input.up"):
            key = _input_key(event)
            if key is not None:
                held[key] = kind == "input.down"
        elif kind == "input.recovered" and event.get("from_run") == event.get("run"):
            for item in event.get("inputs") or []:
                key = _input_key(item) if isinstance(item, Mapping) else None
                if key is not None:
                    held[key] = False
    return sorted(k for k, down in held.items() if down)


def _input_key(event: Mapping[str, Any]) -> InputKey | None:
    device = event.get("device")
    name = event.get("key") if device == "keyboard" else event.get("button")
    if isinstance(device, str) and isinstance(name, str):
        return InputKey(device, name)
    return None


def _object(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _read_from(path: Path, position: int) -> tuple[int, bytes]:
    """(파일 크기, `position`부터 끝까지). 없으면 (0, b"")."""
    try:
        with path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size < position:
                return size, b""
            f.seek(position)
            return size, f.read()
    except FileNotFoundError:
        return 0, b""


def _check_seq(view: RunView) -> None:
    expected = 1
    for event in view.events:
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            view.warnings.append(f"seq가 없는 이벤트: {event.get('event')!r}")
            continue
        if seq != expected:
            view.warnings.append(f"seq 빈틈: {expected} 자리에 {seq}")
        expected = seq + 1


def _collect_steps(view: RunView) -> None:
    for event in view.events:
        step = event.get("step")
        if not isinstance(step, str):
            continue
        kind = event.get("event")
        if kind == "step.start":
            view.steps[step] = StepView(step, event)
        elif kind == "step.end" and step in view.steps:
            view.steps[step].end = event
