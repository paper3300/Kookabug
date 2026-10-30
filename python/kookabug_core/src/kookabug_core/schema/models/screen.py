# 생성물 (packages/schema/screen.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ScreenCondition(BaseModel):
    """
    조건 하나. M1은 찾기 대상($target)만
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


class ScreenDetect(BaseModel):
    """
    all은 전부 보여야, none은 하나도 보이지 않아야 이 화면이다. 적어도 하나
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    all: Annotated[list[ScreenCondition] | None, Field(min_length=1)] = None
    none: Annotated[list[ScreenCondition] | None, Field(min_length=1)] = None


class Screen(BaseModel):
    """
    화면 판정 파일 (*.screen.json). 화면 ID는 파일 이름 줄기
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    detect: ScreenDetect
    format: Literal["kookabug.screen/0"]
    title: Annotated[str | None, Field(description="사람이 읽는 화면 이름")] = None
