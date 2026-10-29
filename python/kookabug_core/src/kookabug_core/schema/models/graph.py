# 생성물 (packages/schema/graph.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    RootModel,
    StringConstraints,
)

type PluginsAdditionalProperty = Annotated[str, Field(min_length=1)]


class ExitName(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$", title="ExitName")]


class InterfaceExit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    kind: Literal["fail", "ok"]
    screen: Annotated[
        str | None,
        Field(description="이 출구로 나갔을 때 도착하는 화면 (화면 지도용)", min_length=1),
    ] = None


class LayoutComment(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    rect: Annotated[list[float], Field(description="[x, y, w, h]", max_length=4, min_length=4)]
    text: str


class LinkRef(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="노드ID.출력",
            pattern="^[A-Za-z_][A-Za-z0-9_-]{0,63}\\.[a-z_][a-z0-9_]*$",
            title="LinkRef",
        ),
    ]


class Tag(RootModel[str]):
    root: Annotated[str, Field(min_length=1)]


class Meta(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    tags: list[Tag] | None = None
    title: str | None = None


class NodeId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="만들 때 정하고 바꾸지 않는다. $link가 '.'으로 노드와 출력을 나누므로 '.'을 쓸 수 없다",
            pattern="^[A-Za-z_][A-Za-z0-9_-]{0,63}$",
            title="NodeId",
        ),
    ]


class NodeType(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="<플러그인>.<분류>.<동작>",
            pattern="^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
            title="NodeType",
        ),
    ]


class ObjectValue(BaseModel):
    """
    $로 시작하는 키가 있으면 특수 값, 없으면 일반 객체
    """


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


class Position(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    x: float
    y: float


class RecordPolicy(BaseModel):
    """
    기록 정책. 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 켤 수 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    screenshots: Literal["off", "on"] | None = None
    video: Literal["failed_only", "off", "on"] | None = None


class RetryConfig(BaseModel):
    """
    노드 config.retry. 노드 스키마의 retry 선언 범위 안에서만 켠다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    max_attempts: Annotated[int, Field(description="첫 실행 포함", ge=1)]
    on: Annotated[
        list[ExitName] | None,
        Field(description="재시도할 fail 출구. 생략하면 노드 스키마의 retry.on 전부", min_length=1),
    ] = None


class SecretKey(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$", title="SecretKey")]


class SettingKey(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$", title="SettingKey")]


class TargetPath(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="워크스페이스 루트 기준 *.target.json 경로 ('/' 구분)",
            pattern="^[^\\\\]+\\.target\\.json$",
            title="TargetPath",
        ),
    ]


class InterfaceInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    default: Annotated[
        Any | None, Field(description="호출 노드가 값을 주지 않았을 때 쓰는 상수")
    ] = None
    description: str | None = None
    type: PinType


class InterfaceOutput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: str | None = None
    nullable: Annotated[bool | None, Field(description="exit 노드가 주지 않으면 null로 채운다")] = (
        None
    )
    type: PinType


class LayoutGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    nodes: list[NodeId]
    title: str | None = None
    x: float
    y: float


class NodeConfig(BaseModel):
    """
    연결할 수 없는 노드 설정. 키는 노드 스키마가 정한다 (retry만 공통)
    """

    model_config = ConfigDict(
        extra="allow",
    )
    retry: RetryConfig | None = None


class SpecialValue(BaseModel):
    """
    $로 시작하는 키 하나만 가진 객체. 닫힌 목록
    """

    field_link: Annotated[LinkRef | None, Field(alias="$link")] = None
    field_literal: Annotated[
        Any | None, Field(alias="$literal", description="해석하지 않고 그대로 쓰는 값")
    ] = None
    field_secret: Annotated[SecretKey | None, Field(alias="$secret")] = None
    field_setting: Annotated[SettingKey | None, Field(alias="$setting")] = None
    field_target: Annotated[TargetPath | None, Field(alias="$target")] = None


class Interface(BaseModel):
    """
    서브그래프의 공개 핀. inputs → 호출 노드 입력, exits → 출구, outputs → 출력
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exits: Annotated[
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], InterfaceExit],
        Field(min_length=1),
    ]
    inputs: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")],
            InterfaceInput,
        ]
        | None
    ) = None
    outputs: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")],
            InterfaceOutput,
        ]
        | None
    ) = None


class Layout(BaseModel):
    """
    편집기 배치. 실행에는 영향이 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    collapsed: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")],
            LayoutGroup,
        ]
        | None
    ) = None
    comments: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")],
            LayoutComment,
        ]
        | None
    ) = None
    nodes: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")],
            Position,
        ]
        | None
    ) = None


class Node(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    config: NodeConfig | None = None
    in_: Annotated[
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], JsonValue | None]
        | None,
        Field(alias="in", description="입력 핀 값. 상수 또는 특수 값"),
    ] = None
    next: Annotated[
        dict[Annotated[str, StringConstraints(pattern=r"^[a-z_][a-z0-9_]*$")], NodeId] | None,
        Field(description="exec 연결: 출구 이름 → 다음 노드 ID"),
    ] = None
    record: RecordPolicy | None = None
    title: str | None = None
    type: NodeType
    version: Annotated[int, Field(ge=1)]


class Graph(BaseModel):
    """
    테스트·서브그래프 그래프 파일 (*.graph.json). 테스트와 서브그래프는 같은 형식이고 kind만 다르다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.graph/0"]
    interface: Interface | None = None
    kind: Literal["subgraph", "test"]
    layout: Layout | None = None
    meta: Meta | None = None
    nodes: dict[
        Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")],
        Node,
    ]
    plugins: Annotated[
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")],
            PluginsAdditionalProperty,
        ],
        Field(description="그래프가 쓰는 플러그인 ID → 버전"),
    ]
    record: RecordPolicy | None = None
