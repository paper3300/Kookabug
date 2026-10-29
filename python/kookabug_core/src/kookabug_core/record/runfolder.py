"""실행 폴더와 `run.json` (스키마 v0 5장, 구현 계획 M0b 2.8).

```
runs/2026-10-29T06-02-11_inventory_open_r8k2x7qm/
├─ run.json            실행 정보·결과 (원자적 교체로만)
├─ events.jsonl
├─ input-recovery.json (있을 때만) 이 실행의 눌린 키를 누가 복구했는지
├─ snapshot/
├─ steps/
└─ logs/               runner·워커 stdout·stderr
```

폴더 이름은 `<UTC YYYY-MM-DDTHH-MM-SS>_<그래프 파일 줄기>_<run_id>`, `run_id`는 `[a-z0-9]` 8자
(이미 쓰인 ID면 다시 뽑는다).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

from kookabug_core.canonical import canonical_dumps

__all__ = [
    "EVENTS_FILE",
    "INPUT_RECOVERY_FILE",
    "RUN_END_FIELDS",
    "RUN_END_OPTIONAL_FIELDS",
    "RUN_FORMAT",
    "RUN_ID_ALPHABET",
    "RUN_ID_LENGTH",
    "RUN_JSON_FILE",
    "SNAPSHOT_DIR",
    "RunFolder",
    "create_run_folder",
    "finished_run_json",
    "folder_name",
    "graph_stem",
    "new_run_id",
    "read_run_json",
    "run_end_result",
    "run_id_of_folder",
    "run_json_matches",
    "write_run_json",
]

RUN_FORMAT: Final = "kookabug.run/0"
RUN_JSON_FILE: Final = "run.json"
EVENTS_FILE: Final = "events.jsonl"
INPUT_RECOVERY_FILE: Final = "input-recovery.json"
SNAPSHOT_DIR: Final = "snapshot"
RUN_ID_ALPHABET: Final = "abcdefghijklmnopqrstuvwxyz0123456789"
RUN_ID_LENGTH: Final = 8
_RUN_ID = re.compile(rf"[a-z0-9]{{{RUN_ID_LENGTH}}}")
_MAX_TRIES: Final = 100
REPLACE_RETRY_S: Final = 5.0

# run.end에서 run.json으로 옮기는 결과 필드 (run.end 필드 → run.json 필드는 같은 이름)
RUN_END_FIELDS: Final = (
    "verdict",
    "code",
    "reason",
    "failure_step",
    "failure_path",
    "finalized_by",
)
# run.end에 있을 때만 옮기는 필드 (없으면 run.json에도 없어야 한다)
RUN_END_OPTIONAL_FIELDS: Final = ("runner_exit_code",)
_END_ONLY: Final = (
    *RUN_END_FIELDS,
    *RUN_END_OPTIONAL_FIELDS,
    "status",
    "ended_at",
    "run_json_repaired",
)


@dataclass(frozen=True, slots=True)
class RunFolder:
    path: Path
    run_id: str

    @property
    def run_json(self) -> Path:
        return self.path / RUN_JSON_FILE

    @property
    def events(self) -> Path:
        return self.path / EVENTS_FILE

    @property
    def input_recovery(self) -> Path:
        return self.path / INPUT_RECOVERY_FILE

    @property
    def snapshot(self) -> Path:
        return self.path / SNAPSHOT_DIR

    @property
    def steps(self) -> Path:
        return self.path / "steps"

    @property
    def logs(self) -> Path:
        return self.path / "logs"


def new_run_id() -> str:
    return "".join(secrets.choice(RUN_ID_ALPHABET) for _ in range(RUN_ID_LENGTH))


def graph_stem(graph: str) -> str:
    """그래프 경로의 파일 줄기: `tests/inventory_open.graph.json` → `inventory_open`."""
    name = PurePosixPath(graph.replace("\\", "/")).name
    for suffix in (".graph.json", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def folder_name(started: datetime, graph: str, run_id: str) -> str:
    stamp = started.astimezone(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    return f"{stamp}_{graph_stem(graph)}_{run_id}"


def run_id_of_folder(folder: str | os.PathLike[str]) -> str | None:
    """폴더 이름 끝의 `run_id` (형식이 다르면 None)."""
    head, _, tail = Path(folder).name.rpartition("_")
    return tail if head and _RUN_ID.fullmatch(tail) else None


def create_run_folder(
    runs_root: str | os.PathLike[str],
    graph: str,
    *,
    now: datetime | None = None,
    new_id: Callable[[], str] = new_run_id,
) -> RunFolder:
    """새 실행 폴더(`snapshot/`·`steps/`·`logs/` 포함)를 만든다.

    `runs_root` 안에 같은 `run_id`로 끝나는 폴더가 이미 있거나 폴더가 이미 있으면 다른 ID를 뽑는다.
    """
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    started = now or datetime.now(UTC)
    for _ in range(_MAX_TRIES):
        run_id = new_id()
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError(f"run_id는 [a-z0-9] {RUN_ID_LENGTH}자다: {run_id!r}")
        if any(root.glob(f"*_{run_id}")):
            continue
        path = root / folder_name(started, graph, run_id)
        try:
            path.mkdir()
        except FileExistsError:
            continue
        folder = RunFolder(path, run_id)
        for sub in (folder.snapshot, folder.steps, folder.logs):
            sub.mkdir()
        return folder
    raise RuntimeError(f"겹치지 않는 run_id를 {_MAX_TRIES}번 안에 뽑지 못했다")


def write_run_json(path: str | os.PathLike[str], data: Mapping[str, Any]) -> None:
    """`run.json`을 원자적으로 바꾼다 (같은 폴더의 임시 파일 → `fsync` → `os.replace`).

    읽는 쪽은 언제나 이전 내용 전체나 새 내용 전체를 본다. Windows에서는 다른 프로세스가 대상
    파일을 열고 있으면 교체가 `PermissionError`로 실패하므로 `REPLACE_RETRY_S` 동안 다시 해 본다.
    """
    path = Path(path)
    text = canonical_dumps(dict(data)).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".run.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        deadline = time.monotonic() + REPLACE_RETRY_S
        while True:
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_run_json(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """`run.json` (없거나 JSON 객체가 아니면 None)."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError, ValueError:
        return None
    return value if isinstance(value, dict) else None


def finished_run_json(start: Mapping[str, Any], run_end: Mapping[str, Any]) -> dict[str, Any]:
    """시작 때 `run.json`의 필드에 `run.end` 결과를 더한 완료 `run.json`."""
    data = {k: v for k, v in start.items() if k not in _END_ONLY}
    data.update(format=RUN_FORMAT, **run_end_result(run_end))
    return data


def run_end_result(run_end: Mapping[str, Any]) -> dict[str, Any]:
    """`run.end`에서 완료 `run.json`으로 옮기는 결과 필드 전부."""
    result = {"status": "finished", "ended_at": run_end["t"]}
    result.update({key: run_end.get(key) for key in RUN_END_FIELDS})
    result.update({key: run_end[key] for key in RUN_END_OPTIONAL_FIELDS if key in run_end})
    return result


def run_json_matches(data: Mapping[str, Any] | None, run_end: Mapping[str, Any]) -> bool:
    """완료 `run.json`이 `run.end`의 결과를 빠짐없이·같은 값으로 담고, `run.end`에 없는 선택 결과
    필드를 따로 갖고 있지 않은가."""
    if data is None or data.get("format") != RUN_FORMAT:
        return False
    result = run_end_result(run_end)
    if any(key not in data or data[key] != value for key, value in result.items()):
        return False
    return not any(key in data for key in RUN_END_OPTIONAL_FIELDS if key not in result)
