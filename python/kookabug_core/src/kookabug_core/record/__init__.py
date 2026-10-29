"""실행 기록: 실행 폴더·`run.json`, `events.jsonl` 작성·읽기, 멱등 마무리, 실행 시작 스냅샷
(스키마 v0 5장), 기록 정책·artifacts (6장 "화면에 찍힌 비밀값")."""

from kookabug_core.record.artifacts import ArtifactStore, FileArtifacts, Recorder
from kookabug_core.record.finalize import (
    FinalizeResult,
    InputRecoveryOutcome,
    RecoverInputs,
    finalize_run,
)
from kookabug_core.record.journal import Journal, JournalClosed, JournalTruncated
from kookabug_core.record.policy import RecordPolicy, StepPolicy
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
    "ArtifactStore",
    "FileArtifacts",
    "FinalizeResult",
    "InputKey",
    "InputRecoveryOutcome",
    "Journal",
    "JournalClosed",
    "JournalTruncated",
    "RecordPolicy",
    "Recorder",
    "RecoverInputs",
    "RunFolder",
    "RunView",
    "Snapshot",
    "SnapshotError",
    "SnapshotLimits",
    "StepPolicy",
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
