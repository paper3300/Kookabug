# 생성물 (packages/schema/rpc.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CancelParams(BaseModel):
    """
    cancel 알림 (runner → 워커): 이후 ctx 호출·sleep·check_cancel이 Cancelled
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class ControlState(RootModel[Literal["cancelling", "paused", "pausing", "running"]]):
    root: Annotated[
        Literal["cancelling", "paused", "pausing", "running"],
        Field(
            description="runner 상태 (제어 요청의 응답): running 실행 중, pausing 다음 경계에서 멈출 것, paused 멈춤, cancelling 취소 순서 진행 중",
            title="ControlState",
        ),
    ]


class ControlStateResult(BaseModel):
    """
    run.cancel·run.pause·run.resume·run.breakpoints (감독자 → runner)의 결과. 노드가 실행 중이어도 받는 즉시 답한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    state: ControlState


class CtxArtifactsSaveResult(BaseModel):
    """
    실행 폴더 기준 경로. 기록 정책으로 생략하면 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    path: str | None


class CtxProcessCloseResult(BaseModel):
    """
    closed: 강제 종료 없이 끝났는가
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    closed: bool


class CtxVisionDiffResult(BaseModel):
    """
    채널 평균 절대 차이 / 255 (0 = 같음, 1 = 완전히 다름)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    value: Annotated[float, Field(ge=0.0, le=1.0)]


class CtxWindowsSetClientSizeResult(BaseModel):
    """
    ok: 다시 읽은 크기가 요청과 같은가
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ok: bool


class DeadlineMs(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="관측 요청의 노드 기한 남은 시간 (밀리초, 0 이상). runner는 min(설정 기한, 이것, 전체 기한 남은 시간)으로 관측하고, 이것 때문에 끝나면 observation_timeout으로 답한다. 없으면 노드 기한 없음",
            ge=0,
            le=9007199254740991,
            title="DeadlineMs",
        ),
    ]


class EmptyResult(BaseModel):
    """
    결과 없음 (ctx.log·ctx.vars.set·ctx.input.*·ctx.windows.activate·ctx.set_window·worker.shutdown)
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class ErrorCode(
    RootModel[
        Literal[
            -32700,
            -32600,
            -32601,
            -32602,
            -32603,
            -32001,
            -32002,
            -32003,
            -32004,
            -32005,
            -32006,
            -32007,
        ]
    ]
):
    root: Annotated[
        Literal[
            -32700,
            -32600,
            -32601,
            -32602,
            -32603,
            -32001,
            -32002,
            -32003,
            -32004,
            -32005,
            -32006,
            -32007,
        ],
        Field(
            description="표준: -32700 parse_error, -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32001 cancelled, -32002 node_error, -32003 context_violation, -32004 node_contract, -32005 protocol_version, -32006 observation_timeout(관측이 노드 기한 안에 끝나지 않음 — 워커에서 ObservationTimeout), -32007 stale_observation(입력 직전 재검증 실패 — 워커에서 StaleObservation, 처리되지 않은 fail)",
            title="ErrorCode",
        ),
    ]


class ErrorObject(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: ErrorCode
    data: Annotated[
        Any | None, Field(description="오류별 추가 정보 (node_error: 예외 이름·메시지·traceback)")
    ] = None
    message: str


class InvokeId(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="노드 실행 번호 (runner가 워커마다 1부터 붙인다). 워커의 ctx 요청은 자기를 부른 node.invoke의 번호를 싣고, runner는 지금 기다리는 실행의 번호가 아니면 처리하지 않는다(context_violation)",
            ge=1,
            le=9007199254740991,
            title="InvokeId",
        ),
    ]


class JsonRpcVersion(RootModel[Literal["2.0"]]):
    root: Annotated[Literal["2.0"], Field(title="JsonRpcVersion")]


class MethodName(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="점으로 나눈 소문자 이름 (예: node.invoke, run.cancel)",
            pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$",
            title="MethodName",
        ),
    ]


class Millis(RootModel[int]):
    root: Annotated[
        int,
        Field(description="시간 길이 (밀리초, 0 이상)", ge=0, le=9007199254740991, title="Millis"),
    ]


class Params(BaseModel):
    """
    이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다)
    """

    model_config = ConfigDict(
        extra="allow",
    )


class ProcessIdent(BaseModel):
    """
    프로세스 식별 (PID + 생성 시각). created는 Windows FILETIME(100ns 단위)을 10진 문자열로 — RPC 정수 범위(2^53)를 넘는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    created: Annotated[str, Field(pattern="^[0-9]+$")]
    pid: Annotated[int, Field(ge=0)]


class RecordOverride(BaseModel):
    """
    실행별 기록 강제 (M7 3.4a·R2): 에이전트 제어 실행은 스크린샷·영상을 끄고 비밀값을 가린다. 그래프 계층 규칙(워크스페이스 → 그래프 → 노드)과 별개로 실행 시작 정책에 덮는다. run.json에 그대로 남는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    by: Literal["agent_control"]
    redact_secrets: Literal[True]
    screenshots: Literal["off"]
    video: Literal["off"]


class RequestId(RootModel[int]):
    root: Annotated[
        int,
        Field(
            description="보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다 (양쪽이 따로 센다)",
            ge=1,
            le=9007199254740991,
            title="RequestId",
        ),
    ]


class RunBreakpointsParams(BaseModel):
    """
    run.breakpoints (감독자 → runner, M3): 브레이크포인트 목록 전체를 바꾼다. 다음 스텝 경계부터 적용. 결과는 ControlStateResult
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    breakpoints: Annotated[
        Any, Field(description="urn:kookabug:breakpoints:0#/$defs/BreakpointList")
    ]


class RunCancelParams(BaseModel):
    """
    run.cancel (감독자 → runner) params: 감독자가 이미 건 하드 종료 타이머의 기한. 타이머는 미루지 않는다(영상 마무리 단계로 다시 건 타이머는 지금 + 유예로 당긴다 — RunnerVideoFinishingResult). runner는 이 기한에서 기록 여유를 뺀 때까지만 녹화를 기다리고 그 전에 run.end·run.json을 쓴다. hard_stop_at_mono: 하드 종료 시각의 단조 시계 초(Python time.monotonic). 감독자·runner는 같은 Windows PC의 프로세스이고 time.monotonic은 시스템 전역 QueryPerformanceCounter라 원점이 같다는 것이 계약이다 — 전달 지연과 상관없이 정확한 기한이다. hard_stop_in_ms: 보내기 직전에 잰 남은 실제 시간(ms). runner는 min(hard_stop_at_mono, 꺼낸 시각 + hard_stop_in_ms)를 기한으로 쓰고(어느 쪽도 늦게 잡지 않게), hard_stop_at_mono가 이미 지났거나 꺼낸 시각 + 마무리 유예보다 멀면(시계 원점이 다르다고 본다) 녹화를 기다리지 않고 바로 기록한다. hard_stop_at_mono 없이 hard_stop_in_ms만 오면 꺼낸 시각 + 남은 시간을 쓰지만 전달 지연만큼 늦게 잡힐 수 있다(상한 없음). params가 없으면 runner.stopping 시각 + shutdown_grace_ms로 본다 (M0b 호출과 같다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hard_stop_at_mono: float | None = None
    hard_stop_in_ms: Annotated[int | None, Field(ge=0)] = None


class RunResumeParams(BaseModel):
    """
    run.resume (감독자 → runner) params. mode를 빼거나 params가 없으면 continue (M0b 호출과 같다). Step 목표는 멈춘 자리의 호출 깊이로 정한다 (M3). 멈춰 있지 않은데 step_*이면 runner는 아무것도 바꾸지 않고 invalid_params 오류(data {reason: not_paused, state})로 답한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Annotated[Any | None, Field(description="urn:kookabug:events:0#/$defs/ResumeMode")] = None


class Agent(BaseModel):
    """
    그 실행을 낸 에이전트 (M5 에이전트 제어 실행)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: str


class BoundWindow(BaseModel):
    """
    에이전트 제어 실행의 대상 창 (M7 R1): daemon이 정한 바인딩. runner는 다시 찾지 않고 이 창에만 붙는다(PID·생성 시각·제목이 정확히 같아야). hwnd 0은 daemon이 창을 하나로 정하지 못함 — 붙지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    created: str
    hwnd: Annotated[int, Field(ge=0, le=9007199254740991)]
    pid: Annotated[int, Field(ge=0, le=9007199254740991)]
    title: str


class Control(BaseModel):
    """
    제어 채널: 감독자가 연 파이프 이름과 상호 인증 키(32바이트 hex)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    key: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    pipe: str


class ForbiddenItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["screen", "target", "text"]
    value: Annotated[str, Field(min_length=1)]


class Overlay(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    file: Annotated[
        str,
        Field(
            description="실행 폴더 기준 고정 사본 경로 (overlay/<n>.bin)",
            pattern="^overlay/[0-9]{1,6}\\.bin$",
        ),
    ]
    sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class Hooks(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after_down: dict[str, str] | None = None
    before_down: dict[str, str] | None = None
    before_up: dict[str, str] | None = None


class RunSpecPlatform(BaseModel):
    """
    플랫폼: none(캡처·입력 없음), fake(frames를 차례로 캡처하거나 scenario 장면 전이 표를 따름, 입력은 input_log JSONL에 기록) 또는 windows(WGC 캡처·SendInput 입력·창·프로세스). hooks는 어느 종류에서나 입력 백엔드에 씌우는 키별 훅(숨은 테스트 기능)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frames: list[str] | None = None
    hooks: Hooks | None = None
    input_log: str | None = None
    kind: Literal["fake", "none", "windows"]
    scenario: Annotated[
        str | None,
        Field(
            description="fake: 장면 전이 표 파일(kookabug.fake-scenario/0, 절대 경로). 있으면 frames 대신 이 장면·가짜 창·프로세스를 쓴다"
        ),
    ] = None
    state_file: Annotated[
        str | None,
        Field(
            description="fake·scenario 검사 전용 (M7 3.12): 첫 가짜 게임의 지금 상태(kookabug.fake-scenario-state/0)를 실행 사이에 잇는 파일(절대 경로). windows에는 쓸 수 없다"
        ),
    ] = None


class RunnerHelloParams(BaseModel):
    """
    runner.hello (runner → 감독자): 제어 채널에 붙은 직후. runner는 자기 식별을 스스로 알린다 (venv 런처를 거쳐 띄웠어도 실제 runner 프로세스)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    protocol: int
    run_id: str
    runner: ProcessIdent


class RunnerStoppingParams(BaseModel):
    """
    runner.stopping 알림 (runner → 감독자): 종료 단계에 들어갔다 (정상 마무리 finish 또는 취소 사유). 감독자는 처음 받은 때부터 마무리 유예가 지나도 runner가 살아 있으면 하드 종료한다 — 외부 취소 없이 기한 초과·정상 마무리에서 멈춘 runner도 같은 규칙
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Literal["cancelled", "deadline_exceeded", "finish", "supervisor_lost"]


class RunnerVideoFinishingParams(BaseModel):
    """
    runner.video_finishing 요청 (runner → 감독자): run.end를 쓴 뒤 영상 인코더 준비가 아직이라 실행 중 모은 프레임을 쓰려고 영상 마무리 단계를 청한다 (M3 사람 확인 R1 F1). 판정·run.end는 이미 정해졌고 바뀌지 않는다. wait_ms: 인코더를 더 기다리려는 실제 시간 (감독자는 30000 ms보다 길게 허락하지 않는다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    wait_ms: Annotated[int, Field(ge=1)]


class RunnerVideoFinishingResult(BaseModel):
    """
    runner.video_finishing 결과. granted: 허락. 감독자는 실행마다 한 번만 하드 종료 타이머를 지금 + wait_ms + shutdown_grace_ms로 다시 걸고, 외부 취소를 받았거나 이미 허락했거나 하드 종료했으면 거절한다. 단계 중 외부 취소가 오면 타이머를 지금 + 유예로 당긴다(run.cancel 기한). hard_stop_at_mono·hard_stop_in_ms: 지금 걸린 하드 종료 타이머의 기한 (RunCancelParams와 같은 뜻, 타이머를 쓰지 않는 감독자는 보내지 않는다). runner는 거절되면 모은 프레임을 버리고(starting 빈 구간 reason encoder_not_ready) 바로 마무리한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    granted: bool
    hard_stop_at_mono: float | None = None
    hard_stop_in_ms: Annotated[int | None, Field(ge=0)] = None


class SecretMessageWire(BaseModel):
    """
    비밀값이 든 메시지 (kookabug_sdk.codec, SDK SecretMessage): 가린 글(masked)과 원문(raw). 원문은 인증된 파이프로만 간다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_kb: Annotated[Literal["secret_message"], Field(alias="$kb")]
    masked: str
    raw: str


class SuccessResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: RequestId
    jsonrpc: JsonRpcVersion
    result: Annotated[Any, Field(description="메서드별 결과 (JSON 값)")]


class WireValue(RootModel[Any]):
    root: Annotated[
        Any,
        Field(
            description='노드 입력·출력·ctx 값 (kookabug_sdk.codec). JSON 값은 그대로, SDK 타입은 {"$kb": 태그, ...}(secret·rect·point·window·process·image·match·target), $kb 키를 가진 사용자 객체는 {"$kb": "dict", "value": ...}',
            title="WireValue",
        ),
    ]


class WorkerHelloParams(BaseModel):
    """
    worker.hello (runner → 워커): 프로토콜, import할 플러그인 모듈, 실행 ID, 원본 워크스페이스(표시용), ctx.path() 루트(실행 스냅샷)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    files_root: str
    modules: list[str]
    protocol: int
    run_id: str
    workspace_id: str


class WorkerPlugin(BaseModel):
    """
    워커가 읽은 플러그인 하나. schema는 노드 스키마 문서(node-schema.schema.json). M6: digest = schema_digest(schema) — 머리는 설치된 스키마 파일, 노드는 코드 선언
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    digest: Annotated[str | None, Field(pattern="^[0-9a-f]{64}$")] = None
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]
    schema_: Annotated[dict[str, Any], Field(alias="schema")]
    version: Annotated[str, Field(min_length=1)]


class CtxArtifactsSaveParams(BaseModel):
    """
    ctx.artifacts.save (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    image: WireValue
    invoke: InvokeId
    name: str


class CtxCaptureParams(BaseModel):
    """
    ctx.capture (워커 → runner). region은 rect 또는 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: DeadlineMs | None = None
    invoke: InvokeId
    region: WireValue


class CtxCaptureResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    image: WireValue


class CtxInputClickParams(BaseModel):
    """
    ctx.input.click (워커 → runner). at은 point·rect·match, count는 클릭 횟수(생략하면 1)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    at: WireValue
    button: str
    count: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    invoke: InvokeId


class CtxInputDragParams(BaseModel):
    """
    ctx.input.drag (워커 → runner). start·end는 point·rect·match
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    button: str
    duration_ms: Millis
    end: WireValue
    invoke: InvokeId
    start: WireValue


class CtxInputKeyParams(BaseModel):
    """
    ctx.input.key (워커 → runner). hold_ms는 누르고 있는 시간(생략하면 0)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hold_ms: Millis | None = None
    invoke: InvokeId
    key: str


class CtxInputScrollParams(BaseModel):
    """
    ctx.input.scroll (워커 → runner). at은 point·rect·match, amount는 휠 칸 수(양수 = 위)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    amount: Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]
    at: WireValue
    invoke: InvokeId


class CtxInputTypeTextParams(BaseModel):
    """
    ctx.input.type_text (워커 → runner). text는 문자열이나 비밀값
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    text: WireValue


class CtxLogParams(BaseModel):
    """
    ctx.log (워커 → runner). message는 str()로 만든 문자열, 비밀값·비밀값 메시지면 그 wire 값({"$kb": "secret"|"secret_message", ...}) — 가릴지는 runner가 기록 정책(record.redact_secrets)으로 정한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    level: Literal["debug", "info", "warn", "error"]
    message: WireValue


class CtxOcrReadParams(BaseModel):
    """
    ctx.ocr.read (워커 → runner). image는 참조 이미지나 파일·바이트 이미지, region은 rect 또는 null, sensitive면 글자가 비밀값으로 온다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: DeadlineMs | None = None
    image: WireValue
    invoke: InvokeId
    region: WireValue
    sensitive: bool


class CtxOcrReadResult(BaseModel):
    """
    result는 ocr_result 값
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    result: WireValue


class CtxProcessCloseParams(BaseModel):
    """
    ctx.process.close (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    force_after_ms: Millis
    invoke: InvokeId
    process: WireValue


class CtxProcessFindWindowParams(BaseModel):
    """
    ctx.process.find_window (워커 → runner). deadline_ms가 있으면 창이 뜰 때까지 기다린다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: DeadlineMs | None = None
    invoke: InvokeId
    process: WireValue
    title: str | None


class CtxProcessLaunchParams(BaseModel):
    """
    ctx.process.launch (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    args: list[str]
    cwd: str | None
    invoke: InvokeId
    path: str


class CtxProcessLaunchResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    process: WireValue


class CtxSettingParams(BaseModel):
    """
    ctx.setting (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    key: str


class CtxSettingResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    value: WireValue


class CtxVarsGetParams(BaseModel):
    """
    ctx.vars.get·has (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    name: str


class CtxVarsGetResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    found: bool
    value: WireValue


class CtxVarsSetParams(BaseModel):
    """
    ctx.vars.set (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    name: str
    value: WireValue


class CtxVisionDiffParams(BaseModel):
    """
    ctx.vision.diff (워커 → runner). a·b는 이미지, region은 rect 또는 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    a: WireValue
    b: WireValue
    invoke: InvokeId
    region: WireValue


class CtxVisionFindParams(BaseModel):
    """
    ctx.vision.find (워커 → runner). image는 이미지, target은 target 값, region은 rect 또는 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    deadline_ms: DeadlineMs | None = None
    image: WireValue
    invoke: InvokeId
    region: WireValue
    target: WireValue


class CtxVisionFindResult(BaseModel):
    """
    match는 match 값, 못 찾으면 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    match: WireValue


class CtxWindowParams(BaseModel):
    """
    창 하나를 받는 요청 (워커 → runner): ctx.windows.info·activate, ctx.set_window
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    window: WireValue


class CtxWindowResult(BaseModel):
    """
    ctx.windows.find·ctx.process.find_window의 결과. window는 window 값, 없으면 null
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    window: WireValue


class CtxWindowsFindParams(BaseModel):
    """
    ctx.windows.find (워커 → runner). title은 부분 일치 또는 /정규식/
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    owned: bool
    process_name: str | None
    title: str | None


class CtxWindowsInfoResult(BaseModel):
    """
    info는 window_info 값
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    info: WireValue


class CtxWindowsSetClientSizeParams(BaseModel):
    """
    ctx.windows.set_client_size (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    height: Annotated[int, Field(ge=1, le=9007199254740991)]
    invoke: InvokeId
    width: Annotated[int, Field(ge=1, le=9007199254740991)]
    window: WireValue


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: ErrorObject
    id: Annotated[
        RequestId | None, Field(description="요청을 읽지 못했으면(JSON 아님·id 없음) null")
    ]
    jsonrpc: JsonRpcVersion


class NodeInvokeParams(BaseModel):
    """
    node.invoke (runner → 워커): 노드 하나 실행. pure·effects는 runner가 아는 선언(워커 선언과 다르면 node_contract), deadline_remaining_ms는 테스트 전체 기한까지 남은 시간
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    config: WireValue
    deadline_remaining_ms: Annotated[int, Field(ge=0)]
    effects: list[Literal["capture", "input", "process"]]
    inputs: WireValue
    invoke: InvokeId
    node_id: str
    pure: bool
    step: str | None
    type: str
    window: WireValue


class NodeInvokeResult(BaseModel):
    """
    노드 결과. 순수 노드는 exit·kind가 null. 오류는 오류 응답(cancelled·node_error·context_violation·node_contract)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exit: str | None
    kind: Literal["ok", "fail"] | None
    message: Annotated[
        str | SecretMessageWire | None,
        Field(
            description="노드 메시지. 비밀값이 든 메시지(SDK SecretMessage)는 가린 글·원문을 둘 다 싣고, 무엇을 기록할지는 runner가 record.redact_secrets로 정한다"
        ),
    ]
    outputs: WireValue


class Notification(BaseModel):
    """
    응답이 없는 알림 (예: 취소)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    jsonrpc: JsonRpcVersion
    method: MethodName
    params: Params | None = None


class Request(BaseModel):
    """
    응답을 기다리는 요청
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: RequestId
    jsonrpc: JsonRpcVersion
    method: MethodName
    params: Params | None = None


class RunSpec(BaseModel):
    """
    실행 사양: 감독자가 runner의 stdin에 JSON 하나로 주고 닫는다 (제어 채널 키를 명령줄·실행 폴더에 남기지 않는다). 시간 값을 빼면 runner 기본값(취소 유예 2000, 워커 시작 30000, 마무리 유예 5000, 자기 종료 여유 10000 ms)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Annotated[
        Agent | None, Field(description="그 실행을 낸 에이전트 (M5 에이전트 제어 실행)")
    ] = None
    basis: Annotated[
        dict[str, Any] | None,
        Field(
            description="M8 3.6: run.json basis에 그대로 남길 실행 기준 기록 (형식은 run.schema.json basis)"
        ),
    ] = None
    bound_window: Annotated[
        BoundWindow | None,
        Field(
            description="에이전트 제어 실행의 대상 창 (M7 R1): daemon이 정한 바인딩. runner는 다시 찾지 않고 이 창에만 붙는다(PID·생성 시각·제목이 정확히 같아야). hwnd 0은 daemon이 창을 하나로 정하지 못함 — 붙지 않는다"
        ),
    ] = None
    breakpoints: Annotated[
        Any | None,
        Field(
            description="시작할 때의 브레이크포인트 (M3). 사람이 UI에서 시작한 실행만 daemon이 채운다. 없으면 빈 목록"
        ),
    ] = None
    capture_timeout_ms: Annotated[
        int | None,
        Field(
            description="관측 호출(캡처·찾기·OCR) 하나의 설정 기한. 넘으면 capture_timeout. 없으면 2000",
            ge=1,
        ),
    ] = None
    control: Annotated[
        Control,
        Field(description="제어 채널: 감독자가 연 파이프 이름과 상호 인증 키(32바이트 hex)"),
    ]
    deadline_ms: Annotated[int, Field(description="테스트 전체 기한 (runner 시작부터)", ge=1)]
    forbidden: Annotated[
        list[ForbiddenItem] | None,
        Field(
            description="M8 3.7·R6: Agent 주체 실행의 금지 동작 (daemon이 시작 때 kookabug.json automation.forbidden에서 고정). 있으면 runner가 입력마다 금지 판정을 한다. 사람 실행·검증 실행에는 없다"
        ),
    ] = None
    frame_budget_mib: Annotated[
        int | None,
        Field(
            description="프레임 저장소 바이트 예산 (MiB). 넘으면 출력 참조 프레임부터 버린다. 없으면 512",
            ge=1,
        ),
    ] = None
    frame_output_refs: Annotated[
        int | None, Field(description="스텝 출력으로 나간 캡처를 남기는 개수. 없으면 32", ge=0)
    ] = None
    graph: Annotated[str, Field(description="실행할 테스트 그래프 (워크스페이스 기준 경로)")]
    graph_value: Annotated[
        dict[str, Any] | None,
        Field(
            description="루트 그래프 값 (M5 에이전트 제어 실행 — daemon 내부 진입점만 채운다). 있으면 graph 자리의 워크스페이스 파일 대신 이 값을 스냅샷에 쓴다"
        ),
    ] = None
    job: Annotated[str | None, Field(description="M8: 이 실행을 낸 작업 ID")] = None
    job_name: Annotated[
        str,
        Field(
            description="감독자가 만든 실행 Job 이름. runner는 어떤 자식도 띄우기 전에 자기를 넣는다"
        ),
    ]
    overlay: Annotated[
        dict[str, Overlay] | None,
        Field(
            description="M8 3.6: 스냅샷 덧씌움 (워크스페이스 기준 경로 → 감독자가 시작 때 실행 폴더에 고정한 바이트). 스냅샷은 이 경로를 원본 대신 이 바이트로 복사한다"
        ),
    ] = None
    platform: RunSpecPlatform
    plugin_modules: Annotated[
        list[str],
        Field(
            description="워커가 import할 플러그인 모듈 (개발용 --plugin-module). 비면 워커를 띄우지 않는다"
        ),
    ]
    profile: str | None
    record_override: RecordOverride | None = None
    run_dir: Annotated[str, Field(description="감독자가 만든 실행 폴더 (절대 경로)")]
    run_id: Annotated[str, Field(pattern="^[a-z0-9]{8}$")]
    self_kill_margin_ms: Annotated[
        int | None,
        Field(
            description="감독자가 살아 있을 때 자기 종료 감시자가 마무리 유예 뒤 더 기다리는 시간 (내부 값, 사용자 설정 아님)",
            ge=0,
        ),
    ] = None
    settings: Annotated[dict[str, Any], Field(description="--set 설정값 (옵션 계층)")]
    shutdown_grace_ms: Annotated[
        int | None,
        Field(description="마무리 유예: 감독자 하드 종료·감독자 사망 뒤 자기 종료까지", ge=0),
    ] = None
    source: Annotated[
        Literal["agent_control"] | None,
        Field(description="실행 출처 (M5: agent_control = 에이전트 게임 조작). run.json에 남는다"),
    ] = None
    supervisor: ProcessIdent
    unattended: Annotated[
        bool | None,
        Field(
            description="M8: 사람 없는 Agent 연결이 시작한 실행. 치트 노드는 분류가 무인 허용인 채택 치트만 통과한다. 없으면 false"
        ),
    ] = None
    worker_cancel_grace_ms: Annotated[int | None, Field(ge=0)] = None
    worker_start_timeout_ms: Annotated[int | None, Field(ge=1)] = None
    workspace_root: str


class WorkerHelloResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    pid: Annotated[
        int | None,
        Field(
            description="M6: 워커의 실제 인터프리터 PID (기록용 — venv 런처를 거쳐 띄웠어도)",
            ge=0,
            le=4294967295,
        ),
    ] = None
    plugins: list[WorkerPlugin]
    protocol: int


class RpcMessage(RootModel[Request | Notification | SuccessResponse | ErrorResponse]):
    root: Annotated[
        Request | Notification | SuccessResponse | ErrorResponse,
        Field(
            description="감독자 ↔ runner, runner ↔ 워커 사이 JSON-RPC 2.0 메시지 하나 (named pipe 프레임 본문, UTF-8 JSON). 메서드별 params·result는 쓰는 작업에서 $defs에 더한다",
            title="RpcMessage",
        ),
    ]
