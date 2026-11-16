"""에이전트로 나가는 실행 기록 (M5 계획 3.8, 사용자 결정 U1).

게임 비밀값은 가리지 않는다 (UX11 B, 2026-11-16 — 로컬 툴): 이벤트·`run.json`은 원문 그대로,
`secret: true` 스텝·`agent_withhold` 경로의 증거도 준다. `secret_paths`·`agent_mask` 분류는 기록에
남아 있어도 쓰지 않는다. 사람(UI) 연결의 기록 보기는 이 모듈을 쓰지 않는다.

- 분류 없는 기록(M5 이전·손상)도 같은 원문을 준다. `SAFE_EVENT_FIELDS`는 안전 필드만 보는 곳(채택
  등)이 쓴다
- 파일은 `steps/`·`thumbs/` 아래 그 스텝의 증거와 `video/index.json`만. 영상 조각·`events.jsonl`·
  `logs/`·`snapshot/`은 주지 않는다

읽기만 하고 실행 폴더를 고치지 않는다. 결과는 UI 캐시(`.kookabug/cache/runs/`)에 쓰지 않는다.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

from kookabug_core.record import read_run, read_run_json
from kookabug_core.record.runfolder import RUN_JSON_FILE
from kookabug_daemon.protocol import RequestFailed

__all__ = [
    "MASK",
    "SAFE_EVENT_FIELDS",
    "AgentRun",
    "mask_pointer",
    "mask_run_summary",
]

MASK: Final = "***"
AGENT_MASK: Final = 1
SAFE_EVENT_FIELDS: Final = frozenset(
    {
        "event",
        "seq",
        "t",
        "run",
        "step",
        "parent",
        "node",
        "path",
        "attempt",
        "iteration",
        "status",
        "exit",
        "duration_ms",
        "active_duration_ms",
        "verdict",
        "code",
        "failure_step",
        "failure_path",
        "finalized_by",
        "cancel_reason",
        "level",
        "retried",
    }
)
"""분류 없는 기록에서 에이전트에게 주는 이벤트 필드 (글자·값·파일 경로 없음). `error`는 `code`만."""
SAFE_RUN_FIELDS: Final = frozenset(
    {
        "format",
        "run_id",
        "graph",
        "status",
        "started_at",
        "ended_at",
        "verdict",
        "code",
        "failure_step",
        "failure_path",
        "finalized_by",
        "duration_ms",
        "active_duration_ms",
    }
)
TEXT_SUFFIXES: Final = frozenset({".txt", ".json"})
IMAGE_SUFFIXES: Final = frozenset({".png", ".jpg", ".jpeg"})
VIDEO_INDEX: Final = "video/index.json"
_STEP_FILE = re.compile(r"^steps/(s\d+)_[^/]+$")
_THUMB_FILE = re.compile(r"^thumbs/(s\d+)\.jpg$")


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def mask_pointer(value: Any, pointer: str) -> None:
    """`value` 안 JSON pointer 자리를 `***`로 바꾼다 (없는 자리는 그대로)."""
    if not pointer.startswith("/"):
        return
    tokens = [_unescape(t) for t in pointer[1:].split("/")]
    current: Any = value
    for token in tokens[:-1]:
        if isinstance(current, dict):
            current = current.get(token)
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return
    last = tokens[-1]
    if isinstance(current, dict) and last in current:
        current[last] = MASK
    elif isinstance(current, list) and last.isdigit() and int(last) < len(current):
        current[int(last)] = MASK


def _masked(value: Mapping[str, Any]) -> dict[str, Any]:
    """에이전트용 사본 (가리지 않는다 — UX11 B)."""
    return copy.deepcopy(dict(value))


def mask_run_summary(summary: Mapping[str, Any], folder: Path | None) -> dict[str, Any]:
    """`run.status`·`run.list` 요약 하나를 에이전트용으로 (사유도 원문 그대로 — UX11 B)."""
    del folder
    return dict(summary)


@dataclass(slots=True)
class StepFacts:
    step: str
    parent: str | None
    node: str
    path: list[str]
    iteration: int | None = None
    status: str | None = None
    exit: str | None = None
    error_code: str | None = None
    duration_ms: int | None = None
    secret: bool = False
    withhold: frozenset[str] = frozenset()
    files: list[str] = field(default_factory=list[str])
    """그 스텝의 증거 파일 (artifacts + evidence 경로)."""
    end: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentRun:
    """실행 하나의 에이전트용 보기 (`events.jsonl`을 한 번 읽는다)."""

    run_id: str
    folder: Path
    run_json: dict[str, Any]
    classified: bool
    events: list[dict[str, Any]]
    steps: dict[str, StepFacts]
    hidden: frozenset[str]
    """증거를 주지 않는 스텝 (UX11 B부터 늘 비어 있다 — 비밀값 스텝도 준다)."""

    @classmethod
    def load(cls, run_id: str, folder: Path) -> AgentRun:
        run_json = read_run_json(folder / RUN_JSON_FILE) or {}
        classified = True  # 분류와 상관없이 원문을 준다 (UX11 B)
        events = read_run(folder).events
        steps: dict[str, StepFacts] = {}
        for event in events:
            kind = event.get("event")
            step = event.get("step")
            if not isinstance(step, str):
                continue
            if kind == "step.start":
                path = event.get("path")
                steps[step] = StepFacts(
                    step,
                    event.get("parent") if isinstance(event.get("parent"), str) else None,
                    str(event.get("node", "")),
                    [str(p) for p in path] if isinstance(path, list) else [],
                    event.get("iteration") if isinstance(event.get("iteration"), int) else None,
                )
            elif kind == "step.end" and step in steps:
                facts = steps[step]
                facts.end = event
                facts.status = event.get("status")
                facts.exit = event.get("exit")
                error = event.get("error")
                if isinstance(error, dict):
                    facts.error_code = str(error.get("code"))
                duration = event.get("duration_ms")
                facts.duration_ms = duration if isinstance(duration, int) else None
                facts.secret = event.get("secret") is True
                withhold = event.get("agent_withhold") or ()
                facts.withhold = frozenset(str(p) for p in withhold)
                files = [str(p) for p in event.get("artifacts") or ()]
                evidence = event.get("evidence")
                if isinstance(evidence, dict):
                    for key in ("first", "mid", "last"):
                        rel = evidence.get(key)
                        if isinstance(rel, str) and rel not in files:
                            files.append(rel)
                facts.files = files
        hidden: set[str] = set()
        return cls(run_id, folder, run_json, classified, events, steps, frozenset(hidden))

    # ------------------------------------------------------------ 이벤트·요약

    def event(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """이벤트 하나를 에이전트용으로."""
        if self.classified:
            return _masked(raw)
        out = {k: copy.deepcopy(v) for k, v in raw.items() if k in SAFE_EVENT_FIELDS}
        error = raw.get("error")
        if isinstance(error, dict) and "code" in error:
            out["error"] = {"code": error["code"]}
        return out

    def run_info(self) -> dict[str, Any]:
        """`run.json`을 에이전트용으로."""
        if self.classified:
            return _masked(self.run_json)
        return {k: copy.deepcopy(v) for k, v in self.run_json.items() if k in SAFE_RUN_FIELDS}

    def text_of(self, raw: Mapping[str, Any]) -> list[str]:
        """찾기 대상 글자 (가린 뒤의 메시지·오류 메시지·사유). 분류 없는 기록은 없음."""
        if not self.classified:
            return []
        masked = _masked(raw)
        found: list[str] = []
        for key in ("message", "reason"):
            value = masked.get(key)
            if isinstance(value, str) and value != MASK:
                found.append(value)
        error = masked.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message != MASK:
                found.append(f"{error.get('code')}: {message}")
        return found

    # ------------------------------------------------------------ 파일

    def file_step(self, rel: str) -> str | None:
        """증거 파일이 속한 스텝 (`steps/<스텝>_…`·`thumbs/<스텝>.jpg`)."""
        match = _STEP_FILE.match(rel) or _THUMB_FILE.match(rel)
        return None if match is None else match.group(1)

    def refusal(self, rel: str) -> RequestFailed | None:
        """그 파일을 에이전트에게 줄 수 없으면 그 오류 (줄 수 있으면 None)."""
        if not self.classified:
            return RequestFailed(
                "unclassified_run",
                f"실행 {self.run_id}은(는) 비밀값 분류가 없는 기록이라 파일을 주지 않는다",
                run_id=self.run_id,
            )
        if rel == VIDEO_INDEX:
            return None
        if rel.startswith("video/"):
            return RequestFailed(
                "video_not_served",
                "영상은 주지 않는다 (video/index.json 요약만)",
                path=rel,
            )
        step = self.file_step(rel)
        facts = None if step is None else self.steps.get(step)
        if facts is None or (rel not in facts.files and not rel.startswith("thumbs/")):
            return RequestFailed(
                "not_evidence", f"'{rel}'은(는) 이 실행의 증거 파일이 아니다", path=rel
            )
        return None

    def evidence_files(self, steps: Iterable[str]) -> list[str]:
        """그 스텝들의 증거 중 에이전트에게 줄 수 있는 파일 (썸네일 포함, 있는 것만)."""
        found: list[str] = []
        for step in steps:
            facts = self.steps.get(step)
            if facts is None:
                continue
            candidates = [*facts.files, f"thumbs/{step}.jpg"]
            for rel in candidates:
                if rel in found or not (self.folder / PurePosixPath(rel)).is_file():
                    continue
                if self.refusal(rel) is None:
                    found.append(rel)
        return found
