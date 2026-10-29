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
