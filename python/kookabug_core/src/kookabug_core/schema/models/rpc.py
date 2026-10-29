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
    run.cancel·run.pause·run.resume (감독자 → runner)의 결과. 노드가 실행 중이어도 받는 즉시 답한다
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


class EmptyResult(BaseModel):
    """
    결과 없음 (ctx.log·ctx.vars.set·ctx.input.*·worker.shutdown)
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class ErrorCode(
    RootModel[
        Literal[-32700, -32600, -32601, -32602, -32603, -32001, -32002, -32003, -32004, -32005]
    ]
):
    root: Annotated[
        Literal[-32700, -32600, -32601, -32602, -32603, -32001, -32002, -32003, -32004, -32005],
        Field(
            description="표준: -32700 parse_error, -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32001 cancelled, -32002 node_error, -32003 context_violation, -32004 node_contract, -32005 protocol_version",
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


class Control(BaseModel):
    """
    제어 채널: 감독자가 연 파이프 이름과 상호 인증 키(32바이트 hex)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    key: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    pipe: str


class Hooks(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after_down: dict[str, str] | None = None
    before_down: dict[str, str] | None = None
    before_up: dict[str, str] | None = None


class RunSpecPlatform(BaseModel):
    """
    플랫폼: none(캡처·입력 없음) 또는 fake(frames를 차례로 캡처, 입력은 input_log JSONL에 기록, hooks는 가짜 백엔드의 키별 훅)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    frames: list[str] | None = None
    hooks: Hooks | None = None
    input_log: str | None = None
    kind: Literal["fake", "none"]


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
    워커가 읽은 플러그인 하나. schema는 노드 스키마 문서(node-schema.schema.json)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
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
    ctx.capture (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    region: WireValue


class CtxCaptureResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    image: WireValue


class CtxInputClickParams(BaseModel):
    """
    ctx.input.click (워커 → runner). at은 point·rect·match
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    at: WireValue
    button: str
    invoke: InvokeId


class CtxInputKeyParams(BaseModel):
    """
    ctx.input.key (워커 → runner)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    key: str


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
    ctx.log (워커 → runner). message는 str()로 만든 것(비밀값은 가려짐)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    invoke: InvokeId
    level: Literal["debug", "info", "warn", "error"]
    message: str


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
    message: str | None
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
    control: Annotated[
        Control,
        Field(description="제어 채널: 감독자가 연 파이프 이름과 상호 인증 키(32바이트 hex)"),
    ]
    deadline_ms: Annotated[int, Field(description="테스트 전체 기한 (runner 시작부터)", ge=1)]
    graph: Annotated[str, Field(description="실행할 테스트 그래프 (워크스페이스 기준 경로)")]
    job_name: Annotated[
        str,
        Field(
            description="감독자가 만든 실행 Job 이름. runner는 어떤 자식도 띄우기 전에 자기를 넣는다"
        ),
    ]
    platform: RunSpecPlatform
    plugin_modules: Annotated[
        list[str],
        Field(
            description="워커가 import할 플러그인 모듈 (개발용 --plugin-module). 비면 워커를 띄우지 않는다"
        ),
    ]
    profile: str | None
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
    supervisor: ProcessIdent
    worker_cancel_grace_ms: Annotated[int | None, Field(ge=0)] = None
    worker_start_timeout_ms: Annotated[int | None, Field(ge=1)] = None
    workspace_root: str


class WorkerHelloResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
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
