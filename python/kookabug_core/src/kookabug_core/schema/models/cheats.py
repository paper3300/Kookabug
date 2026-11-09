# 생성물 (packages/schema/cheats.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class CheatAdoption(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    by: Literal["human"]
    category: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    digest: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class Profile(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Env(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    profiles: list[Profile] | None = None


class Origin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    basis: list[Any] | None = None
    job: Annotated[str | None, Field(pattern="^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")] = None
    kind: Literal["agent", "human"]


class Precondition(RootModel[str]):
    root: Annotated[str, Field(max_length=4000, min_length=1)]


class CheatArgInteger(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    max: int
    min: int
    type: Literal["integer"]


class Value(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Za-z0-9_.-]{1,64}$")]


class CheatArgEnum(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["enum"]
    values: Annotated[list[Value], Field(min_length=1)]


class CheatArgId(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    type: Literal["id"]


class CheatArg(RootModel[CheatArgInteger | CheatArgEnum | CheatArgId]):
    root: Annotated[CheatArgInteger | CheatArgEnum | CheatArgId, Field(title="CheatArg")]


class CheatImplConsole(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    graph: Annotated[str, Field(pattern="^[^\\\\:]+\\.graph\\.json$")]
    kind: Literal["console"]
    template: Annotated[str, Field(max_length=500, min_length=1)]


class CheatImplPlugin(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["plugin"]
    node: Annotated[str, Field(pattern="^[a-z][a-z0-9_.]{0,127}$")]


class CheatImpl(RootModel[CheatImplConsole | CheatImplPlugin]):
    root: Annotated[CheatImplConsole | CheatImplPlugin, Field(title="CheatImpl")]


class Cheat(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    adoption: CheatAdoption | None = None
    args: dict[Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,31}$")], CheatArg]
    effect: Annotated[str, Field(max_length=4000, min_length=1)]
    env: Env | None = None
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    impl: CheatImpl
    origin: Origin | None = None
    preconditions: list[Precondition] | None = None
    rev: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(max_length=200, min_length=1)]


class Cheats(BaseModel):
    """
    치트 정의 knowledge/cheats.json (M8 계획 3.2). adoption은 사람 전용
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    cheats: list[Cheat]
    format: Literal["kookabug.cheats/0"]
    history: list[Cheat] | None = None
    revision: Annotated[int, Field(ge=0)]
