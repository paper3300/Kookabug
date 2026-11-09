# 생성물 (packages/schema/adoption.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class By(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    kind: Literal["human", "kookabug"]


class Case(RootModel[str]):
    root: Annotated[str, Field(pattern="^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class Change(RootModel[str]):
    root: Annotated[str, Field(pattern="^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class AfterSha256(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class BeforeSha256(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class AdoptionFile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after_sha256: AfterSha256 | None
    before_sha256: BeforeSha256 | None
    path: Annotated[str, Field(max_length=200, min_length=1)]


class Negative(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    frame: Annotated[str, Field(max_length=200, min_length=1)]
    note: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    source: Annotated[str | None, Field(max_length=200, min_length=1)] = None


class PolicySha(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class Reverted(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    adoption: Annotated[str, Field(pattern="^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    at: Annotated[str, Field(max_length=40, min_length=1)]


class Run(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Adoption(BaseModel):
    """
    채택 기록 knowledge/adoptions/<채택 ID>.json (M8 계획 3.8): 자동 채택·묶음 수락·되돌리기
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    by: By | None = None
    case: Case | None = None
    change: Change | None = None
    changes: list[Change] | None = None
    files: list[AdoptionFile]
    format: Literal["kookabug.adoption/0"]
    id: Annotated[str, Field(pattern="^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    kind: Literal["accept", "auto", "revert"]
    negatives: list[Negative] | None = None
    policy_sha: PolicySha | None = None
    reverted: Reverted | None = None
    runs: list[Run] | None = None
