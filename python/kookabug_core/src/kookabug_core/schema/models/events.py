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


class EvidenceCandidate(BaseModel):
    """
    매칭 후보 하나. rect는 찾은 이미지 좌표(코어 노드는 창 전체 캡처라 _fail과 같다). 후보끼리는 서로 다른 자리다(점수 지도 봉우리에서 고르면 겹치지 않는다. 프레임 저장소가 없거나 봉우리 다시 고르기를 못 한 경우의 대체 경로는 크게 겹치는 것(IoU 0.3 초과)만 하나로 줄여 조금 겹칠 수 있다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rect: Annotated[list[int], Field(description="[x, y, w, h] 픽셀", max_length=4, min_length=4)]
    scale: Annotated[float, Field(ge=0.0)]
    score: Annotated[float, Field(ge=-1.0, le=1.0)]


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


class LeaseOwnerKind(RootModel[Literal["recorder", "runner", "supervisor"]]):
    root: Annotated[
        Literal["recorder", "runner", "supervisor"],
        Field(
            description="입력 임대권 소유자 종류: 실행(runner), 감독자 복구(supervisor), 녹화 세션을 연 daemon(recorder, M4)",
            title="LeaseOwnerKind",
        ),
    ]


class Omitted(BaseModel):
    """
    정책으로 남기지 않은 증거와 그 이유
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Annotated[
        Literal["screenshot", "text", "thumbnail"],
        Field(
            description="증거 종류: screenshot(스크린샷·실패 증거), text(OCR 글자), thumbnail(스텝 썸네일, M3)"
        ),
    ]
    name: str | None = None
    reason: Annotated[
        Literal["capture_policy", "policy_off", "secret_input", "sensitive_target"],
        Field(description="sensitive_target = sensitive target 영역에서 읽은 OCR 글자"),
    ]
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


class ResumeMode(RootModel[Literal["continue", "step_into", "step_out", "step_over"]]):
    root: Annotated[
        Literal["continue", "step_into", "step_out", "step_over"],
        Field(
            description="재개 방식: continue 다음 브레이크포인트·일시정지 요청까지, step_over 호출 깊이가 같거나 얕은 다음 경계, step_into 다음 경계, step_out 더 얕은 다음 경계",
            title="ResumeMode",
        ),
    ]


class RunId(RootModel[str]):
    root: Annotated[
        str,
        Field(description="실행 ID: 소문자·숫자 8자", pattern="^[a-z0-9]{8}$", title="RunId"),
    ]


class RunOmitted(BaseModel):
    """
    실행 단위로 남기지 않은 기록 (스텝 Omitted와 같은 모양). video/encoder_stuck: 녹화 스레드가 기다림 상한(3초, 마무리 유예가 짧으면 유예에서 기록 여유를 뺀 시간) 안에 끝나지 않아 runner가 영상 파일을 건드리지 않고 포기했다 — runner 종료를 확인한 감독자가 video/를 지운다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["video"]
    reason: Literal["encoder_stuck"]


class SecretPaths(RootModel[list[str]]):
    """
    이 이벤트 안에서 비밀값(Secret·SecretMessage)을 담았던 필드의 JSON pointer (이벤트 기준). record.redact_secrets가 꺼진 실행이면 그 자리에 원문이 있다 — daemon이 에이전트에게 줄 때 ***로 바꾼다 (M5 3.8)
    """

    root: Annotated[
        list[str],
        Field(
            description="이 이벤트 안에서 비밀값(Secret·SecretMessage)을 담았던 필드의 JSON pointer (이벤트 기준). record.redact_secrets가 꺼진 실행이면 그 자리에 원문이 있다 — daemon이 에이전트에게 줄 때 ***로 바꾼다 (M5 3.8)",
            min_length=1,
            title="SecretPaths",
        ),
    ]


class Seq(RootModel[int]):
    root: Annotated[int, Field(description="저널 안 순번. 1부터 빈틈 없이", ge=1, title="Seq")]


class Error(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: str
    message: str


class StepEvidence(BaseModel):
    """
    fail·error·stale_observation으로 끝난 스텝의 증거 (스키마 v0 6장). 파일은 artifacts에도 있다. 시각(*_at_ms)은 스텝 시작 기준 벽시계 ms. mid는 표본 중 (시작 + 끝)/2에 가장 가까운 캡처이고 최선 노력이다: 편차가 경과의 1/4을 넘거나 첫·마지막 말고 표본이 없으면 null과 mid_missing. 매칭 후보(target·threshold·candidates)는 찾기·대기 노드가 fail 출구로 끝났을 때 그 스텝이 마지막으로 찾은 캡처의 서로 다른 자리 점수 상위 3개(그 캡처에서 여러 target을 찾았으면 최고점이 가장 높은 target)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    candidates: Annotated[list[EvidenceCandidate] | None, Field(max_length=3)] = None
    first: Annotated[
        str | None, Field(description="그 스텝의 첫 캡처 (steps/<스텝>_first.png)")
    ] = None
    first_at_ms: Annotated[int | None, Field(ge=0)] = None
    last: Annotated[
        str | None,
        Field(description="그 스텝의 마지막 캡처 (steps/<스텝>_fail.png 또는 _error.png)"),
    ] = None
    last_at_ms: Annotated[int | None, Field(ge=0)] = None
    mid: Annotated[
        str | None, Field(description="중간 캡처 (steps/<스텝>_mid.png), 없으면 null")
    ] = None
    mid_at_ms: Annotated[int | None, Field(description="고른 중간 캡처의 실제 캡처 시각", ge=0)] = (
        None
    )
    mid_missing: Annotated[
        Literal["no_sample_near_mid"] | None, Field(description="중간 장면이 없는 이유")
    ] = None
    mid_offset_ms: Annotated[
        int | None, Field(description="고른 캡처와 (시작 + 끝)/2의 차이 (절댓값)", ge=0)
    ] = None
    target: Annotated[
        str | None, Field(description="마지막으로 찾은 target (스냅샷 안 워크스페이스 기준 경로)")
    ] = None
    threshold: Annotated[float | None, Field(ge=0.0, le=1.0)] = None


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
    secret_paths: SecretPaths | None = None
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


class CheatCallEvent(BaseModel):
    """
    M8 치트 노드 호출 (core.qa.cheat). 허용 교집합을 통과하고 구현 서브그래프를 부르기 직전. before_assertions: 이 실행에서 아직 성공한 검증 노드가 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    args_digest: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    before_assertions: bool
    cheat: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    digest: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    event: Literal["cheat.call"]
    node: str
    rev: Annotated[int, Field(ge=1)]
    run: RunId
    seq: Seq
    step: StepId
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
    멈춤 확정. step은 경계 멈춤이면 다음에 시작할 스텝(아직 step.start 전), 폴링 멈춤이면 기다리던 스텝. node·graph·path·reason·where는 M3부터 (M0b 기록에는 없다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    event: Literal["debug.pause"]
    graph: Annotated[
        str | None,
        Field(
            description="멈춘 노드가 든 그래프 (워크스페이스 기준, 브레이크포인트 열쇠와 같은 경로)"
        ),
    ] = None
    node: str | None = None
    path: CallPath | None = None
    reason: Annotated[
        Literal["breakpoint", "request", "step"] | None,
        Field(
            description="breakpoint: 브레이크포인트 적중, step: Step 목표 경계, request: 일시정지 요청"
        ),
    ] = None
    run: RunId
    seq: Seq
    step: StepId | None = None
    t: Timestamp
    where: Annotated[
        Literal["boundary", "poll"] | None,
        Field(
            description="boundary: 스텝 시작 직전, poll: 코어 노드의 멈출 수 있는 기다림 안 (일시정지 요청만)"
        ),
    ] = None


class DebugResumeEvent(BaseModel):
    """
    재개. mode·epoch·paused_ms는 M3부터 (M0b 기록에는 없다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    epoch: Annotated[
        int | None,
        Field(
            description="재개 뒤의 관측 세대 (재개마다 1 오른다. 이보다 오래된 관측값으로는 입력·분기하지 않는다)",
            ge=1,
        ),
    ] = None
    event: Literal["debug.resume"]
    mode: ResumeMode | None = None
    paused_ms: Annotated[
        int | None,
        Field(description="이번 멈춤의 길이 (멈춤 확정부터 재개까지, 기한에서 뺀 시간)", ge=0),
    ] = None
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
    kind: LeaseOwnerKind
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
    secret_paths: SecretPaths | None = None
    seq: Seq
    step: StepId | None
    t: Timestamp


class RunEndEvent(BaseModel):
    """
    실행 결과. runner가 쓰거나, runner가 죽으면 감독자가 쓴다 (runner_died). active_duration_ms·paused_ms·debug_intervened·omitted는 M3부터
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    active_duration_ms: Annotated[
        int | None, Field(description="멈춘 시간을 뺀 경과 (duration_ms는 실제 경과)", ge=0)
    ] = None
    cancel_reason: CancelReason | None = None
    code: str
    debug_intervened: Annotated[
        bool | None,
        Field(description="디버거로 한 번이라도 멈췄다 (브레이크포인트 적중·일시정지 모두)"),
    ] = None
    duration_ms: Annotated[int | None, Field(ge=0)]
    event: Literal["run.end"]
    failure_path: CallPath | None
    failure_step: StepId | None
    finalized_by: FinalizedBy
    input_recovery: InputRecovery | None = None
    omitted: Annotated[
        list[RunOmitted] | None, Field(description="실행 단위로 남기지 않은 기록", min_length=1)
    ] = None
    paused_ms: Annotated[int | None, Field(description="멈춰 있던 시간 합", ge=0)] = None
    reason: str
    run: RunId
    runner_exit_code: int | None = None
    secret_paths: SecretPaths | None = None
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
    스텝 결과. 이 줄이 없는 스텝은 중단된 것이다. active_duration_ms·evidence는 M3부터
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    active_duration_ms: Annotated[
        int | None,
        Field(
            description="멈춘 시간을 뺀 경과. 그 스텝 구간에 멈춤이 있었을 때만 쓴다 (duration_ms는 실제 경과)",
            ge=0,
        ),
    ] = None
    agent_withhold: Annotated[
        list[str] | None,
        Field(
            description="record.redact_secrets가 켜져 있었다면 남기지 않았을 증거(스크린샷·썸네일·OCR 글자·비밀값이 든 텍스트 artifact)의 실행 폴더 기준 경로. 파일은 그대로 남고 에이전트에게만 주지 않는다 (M5 3.8)"
        ),
    ] = None
    artifacts: list[str] | None = None
    attempt: Annotated[int, Field(ge=1)]
    duration_ms: Annotated[int, Field(ge=0)]
    error: Error | None = None
    event: Literal["step.end"]
    evidence: StepEvidence | None = None
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
    secret: Annotated[
        Literal[True] | None,
        Field(
            description="입력이나 출력에 비밀값이 있던 스텝 ($secret·$link·변수·호출 인자 모두, 값 형식으로 판정). 에이전트에게는 이 스텝과 안쪽 스텝의 이미지·OCR 글자를 주지 않는다 (M5 3.8)"
        ),
    ] = None
    secret_paths: SecretPaths | None = None
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
        | CheatCallEvent
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
        | CheatCallEvent
        | RunEndEvent,
        Field(
            description="events.jsonl 한 줄 (실행 이벤트 하나). event 값으로 종류를 고른다",
            title="Event",
        ),
    ]
