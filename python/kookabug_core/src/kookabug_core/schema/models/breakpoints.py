# 생성물 (packages/schema/breakpoints.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Breakpoint(BaseModel):
    """
    브레이크포인트 열쇠: 그래프 파일 + 노드 ID (노드 ID는 바뀌지 않는다). exec 노드에만 건다. 서브그래프 파일에 건 것은 어느 호출에서든, 반복 본문 노드에 건 것은 회차마다 적중한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    graph: Annotated[
        str,
        Field(
            description="노드가 든 그래프 파일 (워크스페이스 루트 기준 '/' 구분 상대 경로, 그대로 비교한다). 빈 조각·'.'·'..'·앞 '/'는 받지 않는다",
            min_length=1,
            pattern="^(?:(?:[^/\\\\.][^/\\\\]*|\\.[^/\\\\.][^/\\\\]*|\\.\\.[^/\\\\]+)/)*[^/\\\\]+\\.graph\\.json$",
        ),
    ]
    node: Annotated[
        str,
        Field(
            description="노드 ID (graph.schema.json NodeId)",
            pattern="^[A-Za-z_][A-Za-z0-9_-]{0,63}$",
        ),
    ]


class BreakpointList(RootModel[list[Breakpoint]]):
    """
    브레이크포인트 목록 (순서 무관, 같은 항목은 하나로 본다)
    """

    root: Annotated[
        list[Breakpoint],
        Field(
            description="브레이크포인트 목록 (순서 무관, 같은 항목은 하나로 본다)",
            max_length=1000,
            title="BreakpointList",
        ),
    ]


class Breakpoints(BaseModel):
    """
    브레이크포인트 파일 (.kookabug/breakpoints.json, 개인 파일). daemon이 원자적 교체로 쓰고, 사람이 UI에서 시작한 실행에만 넣는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    breakpoints: BreakpointList
    format: Literal["kookabug.breakpoints/0"]
