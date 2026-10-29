# 생성물 (packages/schema/events.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CallPath(RootModel[list[str]]):
    """
    호출 경로: 테스트부터의 호출 노드들 + 노드
    """

    root: Annotated[
        list[str],
        Field(
            description="호출 경로: 테스트부터의 호출 노드들 + 노드", min_length=1, title="CallPath"
        ),
    ]


class CancelReason(RootModel[Literal["cancelled", "deadline_exceeded", "supervisor_lost"]]):
    root: Annotated[
        Literal["cancelled", "deadline_exceeded", "supervisor_lost"],
        Field(
            description="취소 사유: 외부 취소, 테스트 전체 기한 초과, 감독자 사망",
            title="CancelReason",
        ),
    ]


class FinalizedBy(RootModel[Literal["runner", "supervisor"]]):
    root: Annotated[
        Literal["runner", "supervisor"],
        Field(
            description="실행을 마무리한 쪽: runner 자신, 또는 runner가 죽은 뒤 감독자",
            title="FinalizedBy",
        ),
    ]


class InputRecovery(
    RootModel[Literal["already_recovered", "lease_busy", "not_needed", "recovered", "unavailable"]]
):
    root: Annotated[
        Literal["already_recovered", "lease_busy", "not_needed", "recovered", "unavailable"],
        Field(
            description="눌렸을 수 있는 키 복구 결과: 복구함, 다른 쪽이 이미 복구함(복구 표시 파일), 복구할 키 없음, 임대권을 얻지 못함, 복구 수단 없음",
            title="InputRecovery",
        ),
    ]


class InputRef(BaseModel):
    """
    키보드 키 또는 마우스 버튼
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Annotated[str | None, Field(min_length=1)] = None
    device: Literal["keyboard", "mouse"]
    key: Annotated[str | None, Field(min_length=1)] = None


class Omitted(BaseModel):
    """
    정책으로 남기지 않은 증거와 그 이유
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Annotated[str, Field(description="증거 종류 (screenshot 등)", min_length=1)]
    name: str | None = None
    reason: Literal["capture_policy", "policy_off", "secret_input"]
    source: Annotated[str | None, Field(description="정책을 끈 곳")] = None


class ProcessInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    created: Annotated[
        int,
        Field(
            description="프로세스 생성 시각 (Unix 기준 UTC 마이크로초). PID 재사용을 가린다", ge=0
        ),
    ]
    pid: Annotated[int, Field(ge=0)]
    version: str


class RunId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="실행 ID: 소문자·숫자 8자", pattern="^[a-z0-9]{8}$", title="RunId"),
    ]


class Seq(RootModel[int]):
    root: Annotated[int, Field(description="저널 안 순번. 1부터 빈틈 없이", ge=1, title="Seq")]


class Error(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str
    message: str


class StepId(RootModel[str]):
    root: Annotated[str, Field(pattern="^s[1-9][0-9]*$", title="StepId")]


class Timestamp(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
            pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
            title="Timestamp",
        ),
    ]


class Verdict(RootModel[Literal["error", "fail", "pass", "skipped"]]):
    root: Annotated[Literal["error", "fail", "pass", "skipped"], Field(title="Verdict")]


class WorkerExitEvent(BaseModel):
    """
    워커 프로세스 종료
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["worker.exit"]
    exit_code: int | None = None
    pid: Annotated[int, Field(ge=0)]
    reason: Annotated[
        Literal[
            "cancelled",
            "killed_after_grace",
            "shutdown",
            "start_failed",
            "start_timeout",
            "unexpected",
        ]
        | None,
        Field(
            description="shutdown: 마무리에서 정상 종료, killed_after_grace: 취소·shutdown 유예를 넘겨 끝냄, unexpected: 스스로 죽음(실행 중 kill·크래시, hello 전 종료 포함), start_timeout: hello 기한 초과로 끝냄, start_failed: hello 실패(import 오류·프로토콜 불일치)로 끝냄, cancelled: 시작 중 취소·전체 기한으로 끝냄"
        ),
    ] = None
    run: RunId
    seq: Seq
    t: Timestamp


class WorkerStartEvent(BaseModel):
    """
    워커 프로세스 시작
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["worker.start"]
    pid: Annotated[int, Field(ge=0)]
    run: RunId
    seq: Seq
    t: Timestamp


class AttemptEndEvent(BaseModel):
    """
    재시도할 중간 시도의 실패. 판정에는 들어가지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attempt: Annotated[int, Field(ge=1)]
    duration_ms: Annotated[int, Field(ge=0)]
    event: Literal["attempt.end"]
    exit: str | None
    iteration: Annotated[int | None, Field(description="반복 안 스텝의 회차 (0부터)", ge=0)] = None
    message: str | None = None
    outputs: dict[str, Any]
    run: RunId
    seq: Seq
    status: Literal["fail"]
    step: StepId
    t: Timestamp


class CancelRequestedEvent(BaseModel):
    """
    runner가 취소 순서를 시작했다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["cancel.requested"]
    reason: CancelReason
    run: RunId
    seq: Seq
    t: Timestamp


class ControlLostEvent(BaseModel):
    """
    제어 채널이 끊겼다. 감독자는 살아 있으므로 취소가 아니다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    error: str | None = None
    event: Literal["control.lost"]
    run: RunId
    seq: Seq
    t: Timestamp


class DebugPauseEvent(BaseModel):
    """
    멈춤 확정
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["debug.pause"]
    run: RunId
    seq: Seq
    step: StepId | None = None
    t: Timestamp


class DebugResumeEvent(BaseModel):
    """
    재개
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["debug.resume"]
    run: RunId
    seq: Seq
    step: StepId | None = None
    t: Timestamp


class InputDownEvent(BaseModel):
    """
    입력 액터가 백엔드에 누르기를 보내기 전에 쓴다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Annotated[str | None, Field(min_length=1)] = None
    device: Literal["keyboard", "mouse"]
    event: Literal["input.down"]
    key: Annotated[str | None, Field(min_length=1)] = None
    run: RunId
    seq: Seq
    step: StepId | None = None
    t: Timestamp


class By(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["runner", "supervisor"]
    run: RunId | None = None


class InputRecoveredEvent(BaseModel):
    """
    앞 실행(from_run)에서 눌렸을 수 있는 키·버튼을 뗐다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    by: By
    event: Literal["input.recovered"]
    from_run: RunId
    inputs: list[InputRef]
    run: RunId
    seq: Seq
    t: Timestamp


class InputUpEvent(BaseModel):
    """
    입력 액터가 백엔드에 떼기를 보낸 뒤에 쓴다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: Annotated[str | None, Field(min_length=1)] = None
    device: Literal["keyboard", "mouse"]
    event: Literal["input.up"]
    key: Annotated[str | None, Field(min_length=1)] = None
    run: RunId
    seq: Seq
    step: StepId | None = None
    t: Timestamp


class LogEvent(BaseModel):
    """
    노드·runner 로그
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["log"]
    level: Literal["debug", "error", "info", "warn"]
    message: str
    node: str | None
    run: RunId
    seq: Seq
    step: StepId | None
    t: Timestamp


class RunEndEvent(BaseModel):
    """
    실행 결과. runner가 쓰거나, runner가 죽으면 감독자가 쓴다 (runner_died)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cancel_reason: CancelReason | None = None
    code: str
    duration_ms: Annotated[int | None, Field(ge=0)]
    event: Literal["run.end"]
    failure_path: CallPath | None
    failure_step: StepId | None
    finalized_by: FinalizedBy
    input_recovery: InputRecovery | None = None
    reason: str
    run: RunId
    runner_exit_code: int | None = None
    seq: Seq
    t: Timestamp
    truncated_bytes: Annotated[
        int | None, Field(description="감독자가 마무리 전에 잘라 낸 저널 끝 바이트 수", ge=0)
    ] = None
    verdict: Verdict


class RunStartEvent(BaseModel):
    """
    실행 시작. runner가 저널의 첫 줄로 쓴다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["run.start"]
    graph: Annotated[str, Field(description="실행한 테스트 그래프 (워크스페이스 기준)")]
    protocol: Annotated[int, Field(ge=1)]
    run: RunId
    runner: ProcessInfo
    seq: Seq
    t: Timestamp


class StepEndEvent(BaseModel):
    """
    스텝 결과. 이 줄이 없는 스텝은 중단된 것이다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    artifacts: list[str] | None = None
    attempt: Annotated[int, Field(ge=1)]
    duration_ms: Annotated[int, Field(ge=0)]
    error: Error | None = None
    event: Literal["step.end"]
    exit: str | None
    graph: Annotated[
        str | None, Field(description="서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일")
    ] = None
    iteration: Annotated[int | None, Field(description="반복 안 스텝의 회차 (0부터)", ge=0)] = None
    message: str | None = None
    omitted: list[Omitted] | None = None
    outputs: dict[str, Any]
    retried: Literal[True] | None = None
    run: RunId
    seq: Seq
    status: Literal["cancelled", "error", "fail", "success"]
    step: StepId
    t: Timestamp


class StepStartEvent(BaseModel):
    """
    스텝 시작. 재시도해도 스텝 하나에 한 번
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    attempt: Annotated[int, Field(ge=1)]
    event: Literal["step.start"]
    iteration: Annotated[int | None, Field(description="반복 안 스텝의 회차 (0부터)", ge=0)] = None
    node: str
    parent: StepId | None
    path: CallPath
    run: RunId
    seq: Seq
    step: StepId
    t: Timestamp


class Event(
    RootModel[
        RunStartEvent
        | StepStartEvent
        | AttemptEndEvent
        | StepEndEvent
        | LogEvent
        | InputDownEvent
        | InputUpEvent
        | InputRecoveredEvent
        | CancelRequestedEvent
        | ControlLostEvent
        | DebugPauseEvent
        | DebugResumeEvent
        | WorkerStartEvent
        | WorkerExitEvent
        | RunEndEvent
    ]
):
    root: Annotated[
        RunStartEvent
        | StepStartEvent
        | AttemptEndEvent
        | StepEndEvent
        | LogEvent
        | InputDownEvent
        | InputUpEvent
        | InputRecoveredEvent
        | CancelRequestedEvent
        | ControlLostEvent
        | DebugPauseEvent
        | DebugResumeEvent
        | WorkerStartEvent
        | WorkerExitEvent
        | RunEndEvent,
        Field(
            description="events.jsonl 한 줄 (실행 이벤트 하나). event 값으로 종류를 고른다",
            title="Event",
        ),
    ]
