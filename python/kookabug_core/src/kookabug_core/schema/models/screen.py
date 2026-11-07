# 생성물 (packages/schema/screen.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class NormPointItem(RootModel[float]):
    root: Annotated[float, Field(ge=0.0, le=1.0)]


class NormPoint(RootModel[list[NormPointItem]]):
    """
    정규화 점 [x, y] (클라이언트 영역 기준 0~1)
    """

    root: Annotated[
        list[NormPointItem],
        Field(
            description="정규화 점 [x, y] (클라이언트 영역 기준 0~1)",
            max_length=2,
            min_length=2,
            title="NormPoint",
        ),
    ]


class NormRectItem(RootModel[float]):
    root: Annotated[float, Field(ge=0.0, le=1.0)]


class NormRect(RootModel[list[NormRectItem]]):
    """
    정규화 사각형 [x, y, w, h] (클라이언트 영역 기준 0~1)
    """

    root: Annotated[
        list[NormRectItem],
        Field(
            description="정규화 사각형 [x, y, w, h] (클라이언트 영역 기준 0~1)",
            max_length=4,
            min_length=4,
            title="NormRect",
        ),
    ]


class Ocr(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    match: Literal["contains"] | None = None
    rect: NormRect
    text: Annotated[str, Field(max_length=100, min_length=1)]


class OcrCondition(BaseModel):
    """
    OCR 조건 (M7): 그 영역에서 읽은 글자에 text가 들어 있다 (공백·대소문자 무시)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    ocr: Ocr


class ScreenCondition(BaseModel):
    """
    찾기 대상 조건($target)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_target: Annotated[
        str,
        Field(
            alias="$target",
            description="워크스페이스 루트 기준 *.target.json 경로 ('/' 구분)",
            pattern="^[^\\\\]+\\.target\\.json$",
        ),
    ]


class ScreenCondition1(RootModel[ScreenCondition | OcrCondition]):
    root: Annotated[
        ScreenCondition | OcrCondition,
        Field(description="조건 하나: $target 또는 ocr", title="ScreenCondition1"),
    ]


class ScreenDetect(BaseModel):
    """
    all은 전부 보여야, none은 하나도 보이지 않아야 이 화면이다. 적어도 하나
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    all: Annotated[list[ScreenCondition] | None, Field(min_length=1)] = None
    none: Annotated[list[ScreenCondition] | None, Field(min_length=1)] = None


class ScreenDetect1(BaseModel):
    """
    ScreenDetect와 같고 조건에 ocr을 쓸 수 있다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    all: Annotated[list[ScreenCondition1] | None, Field(min_length=1)] = None
    none: Annotated[list[ScreenCondition1] | None, Field(min_length=1)] = None


class ScreenElement(BaseModel):
    """
    UI 요소 하나. 이름은 카드 안에서 겹치지 않는다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["button", "field", "list", "text"]
    name: Annotated[str, Field(max_length=100, min_length=1)]
    rect: NormRect


class ScreenOrigin(BaseModel):
    """
    출처. 없으면 사람이 직접 쓴 화면
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Annotated[str | None, Field(max_length=200)] = None
    at: Annotated[str | None, Field(description="UTC ISO 8601")] = None
    kind: Literal["explored"]
    session: Annotated[str, Field(pattern="^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class ScreenRef(RootModel[str]):
    root: Annotated[
        str,
        Field(
            description="화면 ID(파일 이름 줄기) 또는 후보 키",
            max_length=128,
            pattern="^[^/\\\\]+$",
            title="ScreenRef",
        ),
    ]


class ClientSizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class ScreenShot(BaseModel):
    """
    대표 스크린샷 (워크스페이스 루트 기준 PNG 경로, 찍을 때 클라이언트 크기·배율)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Annotated[list[ClientSizeItem], Field(max_length=2, min_length=2)]
    image: Annotated[str, Field(pattern="^[^\\\\]+\\.png$")]
    scale: Annotated[float | None, Field(ge=0.0)] = None


class Click(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    element: Annotated[str, Field(max_length=100, min_length=1)]


class ScreenVia1(BaseModel):
    """
    이동 입력: 요소 클릭·점 클릭·키
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    click: Click


class Click1(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    point: NormPoint


class ScreenVia2(BaseModel):
    """
    이동 입력: 요소 클릭·점 클릭·키
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    click: Click1


class ScreenVia3(BaseModel):
    """
    이동 입력: 요소 클릭·점 클릭·키
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    key: Annotated[str, Field(max_length=64, min_length=1)]


class ScreenVia(RootModel[ScreenVia1 | ScreenVia2 | ScreenVia3]):
    root: Annotated[
        ScreenVia1 | ScreenVia2 | ScreenVia3,
        Field(description="이동 입력: 요소 클릭·점 클릭·키", title="ScreenVia"),
    ]


class Screen0(BaseModel):
    """
    M1 최소 형식: 판정 조건은 $target만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    detect: ScreenDetect
    format: Literal["kookabug.screen/0"]
    title: Annotated[str | None, Field(description="사람이 읽는 화면 이름")] = None


class ScreenMove(BaseModel):
    """
    이동 하나: via 입력으로 to 화면에 간다. tried면 to가 있어야 한다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    note: Annotated[str | None, Field(max_length=256)] = None
    status: Literal["tried", "untried"]
    to: Annotated[
        ScreenRef | None, Field(description="화면 ID 또는 같은 세션의 후보 키. untried면 null 가능")
    ] = None
    via: ScreenVia


class Screen1(BaseModel):
    """
    화면 지도 형식 (M7): OCR 조건·설명·UI 요소·이동·대표 스크린샷·출처. screens/의 확정 화면은 detect가 있어야 하고, of는 screens/_explored/의 후보만 쓴다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    description: Annotated[str | None, Field(max_length=2000)] = None
    detect: ScreenDetect1 | None = None
    elements: Annotated[list[ScreenElement] | None, Field(max_length=200)] = None
    format: Literal["kookabug.screen/1"]
    kind: Literal["popup", "screen"] | None = None
    moves: Annotated[list[ScreenMove] | None, Field(max_length=200)] = None
    of: Annotated[ScreenRef | None, Field(description="후보 전용: 이 후보를 합칠 확정 화면 ID")] = (
        None
    )
    origin: ScreenOrigin | None = None
    shot: ScreenShot | None = None
    title: Annotated[str | None, Field(max_length=200)] = None


class Screen(RootModel[Screen0 | Screen1]):
    root: Annotated[
        Screen0 | Screen1,
        Field(
            description="화면 판정 파일 (*.screen.json). 화면 ID는 파일 이름 줄기. kookabug.screen/0(M1)·/1(M7 화면 지도)",
            title="Screen",
        ),
    ]
