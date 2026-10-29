# 생성물 (packages/schema/rpc.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


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


class ErrorResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    error: ErrorObject
    id: Annotated[
        RequestId | None, Field(description="요청을 읽지 못했으면(JSON 아님·id 없음) null")
    ]
    jsonrpc: JsonRpcVersion


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


class RpcMessage(RootModel[Request | Notification | SuccessResponse | ErrorResponse]):
    root: Annotated[
        Request | Notification | SuccessResponse | ErrorResponse,
        Field(
            description="감독자 ↔ runner, runner ↔ 워커 사이 JSON-RPC 2.0 메시지 하나 (named pipe 프레임 본문, UTF-8 JSON). 메서드별 params·result는 쓰는 작업에서 $defs에 더한다",
            title="RpcMessage",
        ),
    ]
