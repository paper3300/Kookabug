# 생성물 (packages/schema/target.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Click(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    anchor: Annotated[
        Literal[
            "bottom",
            "bottom_left",
            "bottom_right",
            "center",
            "left",
            "right",
            "top",
            "top_left",
            "top_right",
        ]
        | None,
        Field(description="9분할 클릭 지점"),
    ] = None
    offset: Annotated[
        list[float] | None,
        Field(description="anchor에서 더하는 [x, y] (픽셀)", max_length=2, min_length=2),
    ] = None


class Match(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    color_tolerance: Annotated[
        float | None,
        Field(
            description="rgb가 true일 때 찾은 영역과 이미지의 채널별 평균 차이 상한 (0~255, 기본 40)",
            ge=0.0,
            le=255.0,
        ),
    ] = 40
    methods: Annotated[
        list[Literal["template", "template_multiscale"]] | None,
        Field(description="앞에서부터 시도한다. 각 방법은 threshold를 넘어야 성공", min_length=1),
    ] = None
    rgb: bool | None = None
    threshold: Annotated[
        float | None,
        Field(
            description="매칭 점수 하한. 기본값은 이 default 하나에서 나온다 (Python kookabug_platform.vision.DEFAULT_THRESHOLD, TS 생성 상수 DEFAULT_MATCH_THRESHOLD)",
            ge=0.0,
            le=1.0,
        ),
    ] = 0.85


class ClientSizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class Recorded(BaseModel):
    """
    녹화 당시 클라이언트 영역 크기와 DPI
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Annotated[list[ClientSizeItem] | None, Field(max_length=2, min_length=2)] = None
    dpi: Annotated[int | None, Field(ge=1)] = None


class RegionItem(RootModel[float]):
    root: Annotated[float, Field(ge=0.0, le=1.0)]


class Search(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    region: Annotated[
        list[RegionItem] | None,
        Field(
            description="클라이언트 영역 기준 정규화 좌표 [x, y, w, h]", max_length=4, min_length=4
        ),
    ] = None


class Target(BaseModel):
    """
    찾기 대상 파일 (*.target.json): 이미지, 임계값, 검색 범위, 클릭 지점
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    click: Click | None = None
    format: Literal["kookabug.target/0"]
    image: Annotated[
        str, Field(description="이 target 파일 기준 상대 경로 ('/' 구분)", pattern="^[^\\\\]+$")
    ]
    match: Match | None = None
    recorded: Recorded | None = None
    search: Search | None = None
    sensitive: Annotated[
        bool | None,
        Field(description="true면 이 대상으로 읽은 OCR 결과와 그 파생값이 secret이 된다"),
    ] = None
