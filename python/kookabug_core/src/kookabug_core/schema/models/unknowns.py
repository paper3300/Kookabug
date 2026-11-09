# 생성물 (packages/schema/unknowns.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class UnknownAnswer(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    by: Literal["human"]
    text: Annotated[str, Field(max_length=4000, min_length=1)]


class Block(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Option(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Source(RootModel[str]):
    root: Annotated[str, Field(pattern="^sources:[A-Za-z0-9_.-]{1,64}$")]


class Unknown(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    answer: UnknownAnswer | None = None
    blocks: list[Block] | None = None
    how: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    human_only: bool
    id: Annotated[str, Field(pattern="^u-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    options: Annotated[list[Option] | None, Field(max_length=20)] = None
    question: Annotated[str, Field(max_length=4000, min_length=1)]
    rev: Annotated[int, Field(ge=1)]
    source: Source | None = None
    state: Literal["answered", "dropped", "open"]


class Unknowns(BaseModel):
    """
    미지수 knowledge/unknowns.json (M8 계획 3.2). 답은 사람 전용 unknowns.answer만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.unknowns/0"]
    history: list[Unknown] | None = None
    revision: Annotated[int, Field(ge=0)]
    unknowns: list[Unknown]
