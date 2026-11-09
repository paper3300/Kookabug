# 생성물 (packages/schema/working.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Case(RootModel[str]):
    root: Annotated[str, Field(pattern="^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class Job(RootModel[str]):
    root: Annotated[str, Field(pattern="^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class Created(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    at: Annotated[str, Field(max_length=40, min_length=1)]
    job: Job | None = None


class BaseSha256(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class WorkingFile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    after_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    base_sha256: BaseSha256 | None
    copy_: Annotated[str, Field(alias="copy", max_length=200, min_length=1)]
    path: Annotated[str, Field(pattern="^(tests|subgraphs|targets)/[^\\\\:]+$")]


class Group(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class WorkingChange(BaseModel):
    """
    작업 기준 변경 knowledge/working/<변경 ID>/change.json (M8 계획 3.2). 경로는 tests/·subgraphs/·targets/만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    case: Case | None = None
    created: Created
    files: list[WorkingFile]
    format: Literal["kookabug.working/0"]
    group: Group | None = None
    id: Annotated[str, Field(pattern="^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    kind: Literal["claim_expected", "graph", "locator_repair", "other", "screen_flow", "target"]
    state: Literal["accepted", "active", "adopted", "rejected", "reverted", "stale"]
