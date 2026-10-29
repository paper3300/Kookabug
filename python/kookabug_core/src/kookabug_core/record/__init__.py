"""실행 기록: 실행 폴더·`run.json`, `events.jsonl` 작성·읽기, 멱등 마무리, 실행 시작 스냅샷
(스키마 v0 5장)."""

from kookabug_core.record.finalize import (
    FinalizeResult,
    InputRecoveryOutcome,
    RecoverInputs,
    finalize_run,
)
from kookabug_core.record.journal import Journal, JournalClosed, JournalTruncated
from kookabug_core.record.reader import (
    InputKey,
    RunView,
    StepView,
    follow,
    held_inputs,
    read_journal,
    read_run,
)
from kookabug_core.record.runfolder import (
    RunFolder,
    create_run_folder,
    finished_run_json,
    new_run_id,
    read_run_json,
    write_run_json,
)
from kookabug_core.record.snapshot import (
    Snapshot,
    SnapshotError,
    SnapshotLimits,
    take_snapshot,
)

__all__ = [
    "FinalizeResult",
    "InputKey",
    "InputRecoveryOutcome",
    "Journal",
    "JournalClosed",
    "JournalTruncated",
    "RecoverInputs",
    "RunFolder",
    "RunView",
    "Snapshot",
    "SnapshotError",
    "SnapshotLimits",
    "StepView",
    "create_run_folder",
    "finalize_run",
    "finished_run_json",
    "follow",
    "held_inputs",
    "new_run_id",
    "read_journal",
    "read_run",
    "read_run_json",
    "take_snapshot",
    "write_run_json",
]
