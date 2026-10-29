"""실행 사양 `RunSpec` (구현 계획 M0b 2.6, `rpc.schema.json#/$defs/RunSpec`).

감독자가 runner의 stdin에 JSON 하나로 주고 닫는다. 형식은 메타스키마로 검사하고, 빠진 시간 값은
여기 기본값으로 채운다 (감독자·테스트 하네스·runner가 같은 기본값을 쓴다).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.schema import check_shape
from kookabug_core.win import ProcessId

__all__ = [
    "DEFAULT_SELF_KILL_MARGIN_MS",
    "DEFAULT_SHUTDOWN_GRACE_MS",
    "PROTOCOL",
    "ControlSpec",
    "PlatformSpec",
    "RunSpec",
    "SpecError",
    "ident_from_json",
    "ident_to_json",
]

PROTOCOL: Final = 1
"""감독자 ↔ runner 제어 프로토콜 버전 (`runner.hello`, `run.start`)."""

DEFAULT_WORKER_CANCEL_GRACE_MS: Final = 2_000
DEFAULT_WORKER_START_TIMEOUT_MS: Final = 30_000
DEFAULT_SHUTDOWN_GRACE_MS: Final = 5_000
DEFAULT_SELF_KILL_MARGIN_MS: Final = 10_000


class SpecError(ValueError):
    """실행 사양이 잘못됐다 (runner가 실행을 시작할 수 없다)."""


def ident_to_json(ident: ProcessId) -> dict[str, Any]:
    """`ProcessIdent`: 생성 시각(FILETIME)은 RPC 정수 범위를 넘으므로 10진 문자열로."""
    return {"pid": ident.pid, "created": str(ident.created)}


def ident_from_json(data: Mapping[str, Any]) -> ProcessId:
    return ProcessId(pid=int(data["pid"]), created=int(data["created"]))


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    kind: Literal["none", "fake"] = "none"
    frames: tuple[str, ...] = ()
    input_log: str | None = None
    hooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.frames:
            data["frames"] = list(self.frames)
        if self.input_log is not None:
            data["input_log"] = self.input_log
        if self.hooks:
            data["hooks"] = {hook: dict(names) for hook, names in self.hooks.items()}
        return data


@dataclass(frozen=True, slots=True)
class ControlSpec:
    pipe: str
    key: bytes


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    run_dir: Path
    workspace_root: Path
    graph: str
    control: ControlSpec
    job_name: str
    supervisor: ProcessId
    deadline_ms: int
    profile: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    plugin_modules: tuple[str, ...] = ()
    platform: PlatformSpec = field(default_factory=PlatformSpec)
    worker_cancel_grace_ms: int = DEFAULT_WORKER_CANCEL_GRACE_MS
    worker_start_timeout_ms: int = DEFAULT_WORKER_START_TIMEOUT_MS
    shutdown_grace_ms: int = DEFAULT_SHUTDOWN_GRACE_MS
    self_kill_margin_ms: int = DEFAULT_SELF_KILL_MARGIN_MS

    @classmethod
    def from_json(cls, data: Any) -> RunSpec:
        if not isinstance(data, dict):
            raise SpecError("실행 사양은 JSON 객체다")
        problems = check_shape(data, "rpc", ref="#/$defs/RunSpec")
        if problems:
            detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:5])
            raise SpecError(f"실행 사양 형식 오류: {detail}")
        spec: dict[str, Any] = data
        platform: dict[str, Any] = spec["platform"]
        control: dict[str, Any] = spec["control"]
        optional = {
            name: spec[name]
            for name in (
                "worker_cancel_grace_ms",
                "worker_start_timeout_ms",
                "shutdown_grace_ms",
                "self_kill_margin_ms",
            )
            if name in spec
        }
        return cls(
            run_id=spec["run_id"],
            run_dir=Path(spec["run_dir"]),
            workspace_root=Path(spec["workspace_root"]),
            graph=spec["graph"],
            control=ControlSpec(control["pipe"], bytes.fromhex(control["key"])),
            job_name=spec["job_name"],
            supervisor=ident_from_json(spec["supervisor"]),
            deadline_ms=spec["deadline_ms"],
            profile=spec["profile"],
            settings=dict(spec["settings"]),
            plugin_modules=tuple(spec["plugin_modules"]),
            platform=PlatformSpec(
                kind=platform["kind"],
                frames=tuple(platform.get("frames", ())),
                input_log=platform.get("input_log"),
                hooks={h: dict(n) for h, n in platform.get("hooks", {}).items()},
            ),
            **optional,
        )

    @classmethod
    def loads(cls, text: str | bytes) -> RunSpec:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise SpecError(f"실행 사양이 JSON이 아니다: {exc}") from exc
        return cls.from_json(data)

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "workspace_root": str(self.workspace_root),
            "graph": self.graph,
            "control": {"pipe": self.control.pipe, "key": self.control.key.hex()},
            "job_name": self.job_name,
            "supervisor": ident_to_json(self.supervisor),
            "deadline_ms": self.deadline_ms,
            "profile": self.profile,
            "settings": dict(self.settings),
            "plugin_modules": list(self.plugin_modules),
            "platform": self.platform.to_json(),
            "worker_cancel_grace_ms": self.worker_cancel_grace_ms,
            "worker_start_timeout_ms": self.worker_start_timeout_ms,
            "shutdown_grace_ms": self.shutdown_grace_ms,
            "self_kill_margin_ms": self.self_kill_margin_ms,
        }
