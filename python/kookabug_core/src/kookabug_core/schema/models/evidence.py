# 생성물 (packages/schema/evidence.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Basis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["team", "working"]


class By(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    kind: Literal["agent", "human", "kookabug"]


class ClientSizeItem(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class GameBuild(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Platform(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Profile(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Env(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client_size: Annotated[list[ClientSizeItem] | None, Field(max_length=2, min_length=2)] = None
    dpi: Annotated[int | None, Field(ge=1)] = None
    game_build: GameBuild | None = None
    platform: Platform | None = None
    profile: Profile | None = None


class Code(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Node(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Step(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Type(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class FailedStep(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Code | None = None
    node: Node | None = None
    step: Step | None = None
    type: Type | None = None


class EvidenceFile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    bytes: Annotated[int | None, Field(ge=0)] = None
    path: Annotated[str, Field(pattern="^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")]
    sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class GraphSha(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class OmittedItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Annotated[str, Field(max_length=200, min_length=1)]
    what: Annotated[str, Field(max_length=200, min_length=1)]


class Run(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Evidence(BaseModel):
    """
    증거 묶음 knowledge/evidence/<묶음 ID>/manifest.json (M8 계획 3.2). 가림 처리된 최소 증거, 지우거나 고치는 도구 없음
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    basis: Basis | None = None
    by: By
    env: Env | None = None
    failed_step: FailedStep | None = None
    files: list[EvidenceFile]
    format: Literal["kookabug.evidence/0"]
    graph_sha: GraphSha | None = None
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9-]{0,95}$")]
    note: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    omitted: list[OmittedItem] | None = None
    origin: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    pinned_at: Annotated[str, Field(max_length=40, min_length=1)]
    run: Run | None = None
    verdict: Literal["error", "fail", "pass", "skip"] | None = None
