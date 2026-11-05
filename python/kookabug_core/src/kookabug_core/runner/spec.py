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

from kookabug_core.engine.debug import Breakpoint
from kookabug_core.schema import check_shape
from kookabug_core.win import ProcessId

__all__ = [
    "DEFAULT_SELF_KILL_MARGIN_MS",
    "DEFAULT_SHUTDOWN_GRACE_MS",
    "PROTOCOL",
    "VIDEO_FINISH_MAX_MS",
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
VIDEO_FINISH_MAX_MS: Final = 30_000
"""영상 마무리 단계 상한 (`runner.video_finishing`): run.end 뒤 인코더 준비를 더 기다리는 최대 실제
시간. runner가 청하는 기본값이고 감독자는 이보다 길게 허락하지 않는다 (R1 F1 3라운드)."""
DEFAULT_CAPTURE_TIMEOUT_MS: Final = 2_000
"""`run.capture_timeout_ms` 기본값: 관측 호출 하나의 설정 기한 (M1 2.6, 조율자 결정 Q2)."""
DEFAULT_FRAME_BUDGET_MIB: Final = 512
"""`run.frame_budget_mib` 기본값: 프레임 저장소 바이트 예산 (M1 2.7, Q15)."""
DEFAULT_FRAME_OUTPUT_REFS: Final = 32
"""`run.frame_output_refs` 기본값: 출력 참조로 남기는 캡처 수 (M1 2.7, Q15)."""
MIB: Final = 1 << 20


class SpecError(ValueError):
    """실행 사양이 잘못됐다 (runner가 실행을 시작할 수 없다)."""


def ident_to_json(ident: ProcessId) -> dict[str, Any]:
    """`ProcessIdent`: 생성 시각(FILETIME)은 RPC 정수 범위를 넘으므로 10진 문자열로."""
    return {"pid": ident.pid, "created": str(ident.created)}


def ident_from_json(data: Mapping[str, Any]) -> ProcessId:
    return ProcessId(pid=int(data["pid"]), created=int(data["created"]))


@dataclass(frozen=True, slots=True)
class PlatformSpec:
    """`none`(캡처·입력 없음), `fake`(가짜 프레임·장면·입력 기록), `windows`(WGC 캡처·SendInput
    입력·창·프로세스). `fake`에 `scenario`(장면 전이 표 JSON 파일, `FakeScenario`)가 있으면
    `frames` 대신 그 장면을 쓴다. `hooks`는 어느 종류에서나 입력 백엔드에 씌우는 숨은 테스트
    기능이다."""

    kind: Literal["none", "fake", "windows"] = "none"
    frames: tuple[str, ...] = ()
    input_log: str | None = None
    hooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict[str, Mapping[str, str]])
    scenario: str | None = None

    @classmethod
    def fake_from(cls, spec: Mapping[str, Any], base: Path) -> PlatformSpec:
        """숨은 테스트 옵션 `--platform-fake`의 사양 객체(`frames`·`scenario`·`input_log`·
        `hooks`) → 가짜 플랫폼. 장면 표·입력 기록 경로는 사양 파일 폴더(`base`) 기준이다 (runner는
        다른 작업 폴더에서 돈다)."""

        def beside(value: Any) -> str | None:
            return None if value is None else str((base / str(value)).resolve())

        return cls(
            "fake",
            frames=tuple(spec.get("frames", ())),
            input_log=beside(spec.get("input_log")),
            hooks=spec.get("hooks", {}),
            scenario=beside(spec.get("scenario")),
        )

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind}
        if self.frames:
            data["frames"] = list(self.frames)
        if self.input_log is not None:
            data["input_log"] = self.input_log
        if self.hooks:
            data["hooks"] = {hook: dict(names) for hook, names in self.hooks.items()}
        if self.scenario is not None:
            data["scenario"] = self.scenario
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
    capture_timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS
    frame_budget_mib: int = DEFAULT_FRAME_BUDGET_MIB
    frame_output_refs: int = DEFAULT_FRAME_OUTPUT_REFS
    breakpoints: tuple[Breakpoint, ...] = ()
    """시작할 때의 브레이크포인트 (M3 2.1). 사람이 UI에서 시작한 실행만 daemon이 채운다."""

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
                "capture_timeout_ms",
                "frame_budget_mib",
                "frame_output_refs",
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
                scenario=platform.get("scenario"),
            ),
            breakpoints=Breakpoint.many(spec.get("breakpoints", ())),
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
            "capture_timeout_ms": self.capture_timeout_ms,
            "frame_budget_mib": self.frame_budget_mib,
            "frame_output_refs": self.frame_output_refs,
            "breakpoints": [bp.to_json() for bp in self.breakpoints],
        }
