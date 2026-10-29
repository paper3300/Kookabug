"""`events.jsonl` 작성기 (스키마 v0 5장, 구현 계획 M0b 2.8).

- 한 줄 = 이벤트 하나. UTF-8·LF, `json.dumps(sort_keys=True, ensure_ascii=False)`
- 모든 줄에 `seq`(1부터 빈틈 없음), `t`(UTC 밀리초 `Z`), `run`, `event`
- 잠금 안에서 `seq`를 붙이고 한 줄을 `os.write` 한 번으로 쓴다(`O_APPEND`). `fsync`는 `run.end`와
  닫을 때
- 기존 파일에 이어 쓸 때는 마지막 `seq` 다음부터. 끝 줄이 잘린 파일에는 이어 쓰지 않는다
  (감독자 마무리가 먼저 잘라 낸다)
- runner 작성기는 `run.end`를 쓴 뒤의 쓰기를 거부한다(`JournalClosed`). 감독자 작성기는 `run.end`
  뒤에도 `input.recovered`를 더할 수 있다
- 쓰기가 도중에 실패한 저널은 그 뒤 쓰기를 모두 거부한다(`JournalClosed`). 끝의 반쯤 쓴 줄 뒤에
  이어 쓰면 읽기가 그 줄과 다음 줄을 함께 버린다 — 잘라 내는 것은 감독자 마무리 몫이다

값은 `event_value()`로 JSON 값으로 바꾼다. 비밀값은 가린 값으로만 남는다.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from kookabug_core.engine.events import event_value
from kookabug_sdk import _faults

__all__ = ["Journal", "JournalClosed", "JournalTruncated", "Writer", "format_t"]

type Writer = Literal["runner", "supervisor"]

_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)


class JournalClosed(Exception):
    """닫힌 저널, 또는 `run.end` 뒤 runner 작성기의 쓰기."""


class JournalTruncated(Exception):
    """끝 줄이 잘린 저널에는 이어 쓰지 않는다."""


def format_t(now: datetime) -> str:
    """UTC 밀리초 `Z` 시각 (`2026-10-29T06:02:11.104Z`)."""
    now = now.astimezone(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Journal:
    """한 실행의 `events.jsonl` 작성기. 여러 스레드에서 `emit()`해도 줄이 섞이지 않는다."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        run_id: str,
        *,
        writer: Writer = "runner",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.writer: Writer = writer
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        # 이미 run.end가 있는 저널을 다시 열어도 runner 작성기는 더 쓰지 못한다
        self._seq, self._ended = _existing_state(self.path)
        self._broken: BaseException | None = None
        self._fd: int | None = os.open(self.path, _FLAGS, 0o644)

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def broken(self) -> bool:
        """쓰기가 도중에 실패해 더 쓰지 않는 저널인가."""
        return self._broken is not None

    def emit(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """한 줄을 쓰고 쓴 이벤트를 돌려준다. `seq`·`t`는 작성기가 붙인다."""
        kind = event.get("event")
        if not isinstance(kind, str):
            raise ValueError(f"이벤트 종류(event)가 없다: {event!r}")
        run = event.get("run", self.run_id)
        if run != self.run_id:
            raise ValueError(f"다른 실행의 이벤트다: run {run!r} ≠ {self.run_id!r}")
        with self._lock:
            if self._fd is None:
                raise JournalClosed(f"닫힌 저널이다: {self.path}")
            if self._ended and self.writer == "runner":
                raise JournalClosed(f"run.end 뒤에는 쓰지 않는다 ({kind})")
            if self._broken is not None:
                raise JournalClosed(f"쓰기가 실패한 저널이다 ({kind}): {self._broken!r}")
            record = {
                **event_value(dict(event)),
                "run": self.run_id,
                "seq": self._seq + 1,
                "t": format_t(self._now()),
            }
            data = _line(record)
            action = _faults.check("journal.partial_line", event=kind)
            try:
                if action is None:
                    _write_all(self._fd, data)
                else:
                    # 실제로 쓰다가 멈춘 줄: 앞 절반만 쓰고 동작한다 (테스트 전용)
                    half = len(data) // 2
                    _write_all(self._fd, data[:half])
                    _faults.perform(action)
                    _write_all(self._fd, data[half:])
            except BaseException as exc:
                # 끝에 반쯤 쓴 줄이 남았을 수 있다: 그 뒤에 이어 쓰면 다음 줄까지 읽기가 버린다
                self._broken = exc
                raise
            self._seq += 1
            if kind == "run.end":
                self._ended = True
                os.fsync(self._fd)
            return record

    def close(self) -> None:
        with self._lock:
            if self._fd is None:
                return
            try:
                os.fsync(self._fd)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _line(record: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except ValueError:
        # NaN·Infinity는 JSON 숫자가 아니다. 기록을 잃지 않게 문자열로 남긴다
        text = json.dumps(_finite(record), sort_keys=True, ensure_ascii=False, allow_nan=False)
    return (text + "\n").encode("utf-8")


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        items: dict[str, Any] = value
        return {k: _finite(v) for k, v in items.items()}
    if isinstance(value, list):
        seq: list[Any] = value
        return [_finite(v) for v in seq]
    return value


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _existing_state(path: Path) -> tuple[int, bool]:
    """기존 저널의 (마지막 `seq`, `run.end`가 있는가). 없거나 빈 파일이면 (0, False)."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return 0, False
    if not data:
        return 0, False
    lines = data.split(b"\n")
    tail = lines.pop()  # 마지막 \n 뒤 (온전한 파일이면 빈 바이트)
    if tail or not isinstance(_json_or_none(lines[-1]), dict):
        # 읽기(reader)가 버리는 끝 줄 뒤에 이어 쓰면 그 줄이 중간의 깨진 줄이 된다
        raise JournalTruncated(f"끝 줄이 잘린 저널이다: {path}")
    last_seq = 0
    ended = False
    for raw in lines:
        record = _json_or_none(raw)
        if not isinstance(record, dict):
            continue
        seq: Any = record.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            last_seq = seq
        ended = ended or record.get("event") == "run.end"
    return last_seq, ended


def _json_or_none(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
