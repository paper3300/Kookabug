# 생성물 (packages/schema/recorder-fragment.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel


class ExitName(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_][a-z0-9_]*$", title="ExitName")]


class FragmentSpecialValue2(BaseModel):
    """
    특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_literal: Annotated[
        Any, Field(alias="$literal", description="해석하지 않고 그대로 쓰는 값")
    ]


class FragmentSpecialValue3(BaseModel):
    """
    특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_secret: Annotated[
        str, Field(alias="$secret", pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$")
    ]


class FragmentSpecialValue4(BaseModel):
    """
    특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_setting: Annotated[
        str, Field(alias="$setting", pattern="^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$")
    ]


class FragmentSpecialValue5(BaseModel):
    """
    특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_target: Annotated[str, Field(alias="$target", pattern="^[^\\\\]+\\.target\\.json$")]


class FragmentWarning(BaseModel):
    """
    저장 결과에 보일 경고 (예: no_assertion — 검증이 없어 끝까지 가면 통과, attach_start — 재생 전에 게임을 같은 화면으로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    code: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]
    message: str


class LocalId(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="조각 안 로컬 노드 ID (r + 번호). 그래프 노드 ID(n_ + base32)와 겹치지 않는다",
            pattern="^r[1-9][0-9]{0,5}$",
            title="LocalId",
        ),
    ]


class LocalLink(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="조각 안 $link: <로컬 ID>.<출력 이름>",
            pattern="^r[1-9][0-9]{0,5}\\.[a-z_][a-z0-9_]*$",
            title="LocalLink",
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


class OpenEnd(BaseModel):
    """
    열린 끝점: 삽입이면 렌더러가 원래 다음 노드를 이 노드의 이 출구에 잇는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    exit: ExitName
    node: LocalId


class FragmentSpecialValue1(BaseModel):
    """
    특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_link: Annotated[LocalLink, Field(alias="$link")]


class FragmentSpecialValue(
    RootModel[
        FragmentSpecialValue1
        | FragmentSpecialValue2
        | FragmentSpecialValue3
        | FragmentSpecialValue4
        | FragmentSpecialValue5
    ]
):
    root: Annotated[
        FragmentSpecialValue1
        | FragmentSpecialValue2
        | FragmentSpecialValue3
        | FragmentSpecialValue4
        | FragmentSpecialValue5,
        Field(
            description="특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)",
            title="FragmentSpecialValue",
        ),
    ]


class RecorderFragment(BaseModel):
    """
    녹화 커밋 조각 (recorder.commit_prepare 결과, M4 계획 2.9). daemon이 로컬 ID로 만들고 렌더러가 그래프에 넣는다(새 테스트·삽입 공용). chain = 실행 차례(첫 항목이 들어가는 노드, 모든 노드가 한 번씩). 새 테스트(mode new_test)는 현재 창을 정하는 노드(first_window_node: core.app.launch 또는 core.window.attach)로 시작하고 open_end가 없다(검증이 없으면 core.test.pass로 끝남). 삽입(mode insert)은 맨 앞 창 노드·종료 노드 없이 open_end로 끝난다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    chain: Annotated[list[LocalId], Field(min_length=1)]
    first_window_node: LocalId | None = None
    mode: Literal["insert", "new_test"]
    nodes: Annotated[list[FragmentNode], Field(min_length=1)]
    open_end: OpenEnd | None = None
    warnings: list[FragmentWarning]


class FragmentNode(BaseModel):
    """
    노드 하나. in은 그래프 in 핀 값 규칙(특수 값 $link·$secret·$setting·$target·$literal) 그대로이고, $link의 노드 자리는 로컬 ID다 (예: {"$link": "r2.match"}). next는 출구 → 다음 노드 로컬 ID. 렌더러 insertFragment가 로컬 ID를 새 노드 ID로 바꾸면서 in 안 모든 $link(배열·객체 안쪽까지)와 next를 같이 바꾼다. 비밀값 구간의 글자는 {"$secret": "<키>"}로만 들어간다 — 원문은 조각 어디에도 없다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    config: Annotated[
        dict[str, Any] | None, Field(description="노드 설정 (그래프 Node.config 그대로)")
    ] = None
    in_: Annotated[dict[str, JsonValue | None], Field(alias="in", description="입력 핀 이름 → 값")]
    local_id: LocalId
    next: Annotated[
        dict[str, LocalId] | None,
        Field(description="exec 연결: 출구 이름 → 이 조각 안 다음 노드 로컬 ID"),
    ] = None
    title: str
    type: NodeType
    version: Annotated[int, Field(ge=1, le=9007199254740991)]


class FragmentObject(RootModel[dict[str, JsonValue | None]]):
    """
    특수 값 키가 없는 일반 객체 (값은 다시 Value). 특수 값 키와 다른 키를 섞으면 특수 값도 일반 객체도 아니다. 그 밖의 $로 시작하는 키는 그래프 Value 검사(kookabug_core.recorder.fragment)가 거부한다
    """

    root: dict[str, JsonValue | None]


RecorderFragment.model_rebuild()
