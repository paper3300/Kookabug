# 생성물 (packages/schema/lessons.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Build(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Profile(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Screen(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Applies(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    builds: list[Build] | None = None
    profiles: list[Profile] | None = None
    screens: list[Screen] | None = None


class Lesson(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    active: bool
    advice: Annotated[str, Field(max_length=4000, min_length=1)]
    applies: Applies | None = None
    basis: list[Any]
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_.]{0,127}$")]
    rev: Annotated[int, Field(ge=1)]


class Lessons(BaseModel):
    """
    경험칙 knowledge/lessons.json (M8 계획 3.2). 저장·근거·활성만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.lessons/0"]
    history: list[Lesson] | None = None
    lessons: list[Lesson]
    revision: Annotated[int, Field(ge=0)]
