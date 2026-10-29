# 생성물 (packages/schema/node-schema.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class ExitName(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$", title="ExitName")]


class FromInterface(BaseModel):
    """
    핀을 그래프 interface에서 만든다 (graph.entry·exit·call)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    from_interface: Literal["exits", "inputs", "outputs"]


class NodeType(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="<플러그인>.<분류>.<동작>",
            pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
            title="NodeType",
        ),
    ]


class PinName(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$", title="PinName")]


class PinType(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="핀 타입: bool|int|float|string|secret|target|match|rect|point|image|window|process|any, list[T], dict[str,T], <플러그인>.<Type>, 유니온 A|B",
            pattern="^(list\\[|dict\\[str,)*(bool|int|float|string|secret|target|match|rect|point|image|window|process|any|[a-z][a-z0-9_]*\\.[A-Z][A-Za-z0-9_]*)\\]*(\\|(list\\[|dict\\[str,)*(bool|int|float|string|secret|target|match|rect|point|image|window|process|any|[a-z][a-z0-9_]*\\.[A-Z][A-Za-z0-9_]*)\\]*)*$",
            title="PinType",
        ),
    ]


class PluginId(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$", title="PluginId")]


class PluginInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: PluginId
    title: str | None = None
    version: Annotated[str, Field(min_length=1)]


class RetryDecl(BaseModel):
    """
    노드 타입의 재시도 선언. 생략하면 never
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    mode: Literal["never", "observation"]
    on: Annotated[
        list[ExitName] | None, Field(description="재시도할 수 있는 fail 출구", min_length=1)
    ] = None


class ConfigDecl(BaseModel):
    """
    config 항목 하나. default가 없으면 필수
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    default: Any | None = None
    description: str | None = None
    enum: Annotated[list[Any] | None, Field(min_length=1)] = None
    maximum: float | None = None
    min_items: Annotated[int | None, Field(ge=0)] = None
    minimum: float | None = None
    type: PinType


class ExitOutputs(RootModel[list[PinName]]):
    """
    이 출구로 나갈 때 주는 출력 이름
    """

    root: Annotated[
        list[PinName], Field(description="이 출구로 나갈 때 주는 출력 이름", title="ExitOutputs")
    ]


class InputPin(BaseModel):
    """
    입력 핀. default가 없으면 필수
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    default: Any | None = None
    description: str | None = None
    enum: Annotated[list[Any] | None, Field(min_length=1)] = None
    maximum: float | None = None
    min_items: Annotated[int | None, Field(ge=0)] = None
    minimum: float | None = None
    nullable: bool | None = None
    type: PinType


class OutputPin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    nullable: bool | None = None
    type: PinType


class Exit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["fail", "ok"]
    name: ExitName
    outputs: ExitOutputs


class DynamicExits(BaseModel):
    """
    config 값(문자열 배열)으로 출구를 만든다. 배열 순서가 우선순위. extra는 고정 출구
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    extra: list[Exit] | None = None
    from_config: PinName
    kind: Literal["fail", "ok"]
    outputs: ExitOutputs


class NodeDecl(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    assertion: Annotated[bool | None, Field(description="검증 노드 (판정 5행)")] = None
    category: str | None = None
    config: (
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], ConfigDecl] | None
    ) = None
    description: str | None = None
    effects: Annotated[
        list[Literal["capture", "input", "process"]] | None,
        Field(
            description="게임에 영향을 주는 동작. input·process가 있으면 관측 재시도를 선언할 수 없다"
        ),
    ] = None
    engine: Annotated[
        str | None,
        Field(description="실행기가 직접 처리하는 노드 (core 전용)", pattern="^[a-z][a-z0-9_]*$"),
    ] = None
    exits: Annotated[
        list[Exit] | DynamicExits | FromInterface | None,
        Field(description="exec 노드의 출구. 종료 노드는 빈 배열"),
    ] = None
    inputs: (
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], InputPin]
        | FromInterface
        | None
    ) = None
    outputs: (
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], OutputPin]
        | FromInterface
        | None
    ) = None
    pure: Annotated[bool | None, Field(description="exec 핀이 없는 순수 노드")] = None
    retry: RetryDecl | None = None
    title: str
    type: NodeType
    version: Annotated[int, Field(ge=1)]


class NodeSchemaFile(BaseModel):
    """
    플러그인의 노드 스키마 (kookabug-sdk build 산출물, src/<패키지>/kookabug.schema.json). 팔레트와 실행 전 검증이 읽는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.nodes/0"]
    nodes: Annotated[list[NodeDecl], Field(description="type 순으로 정렬")]
    plugin: PluginInfo
