# 생성물 (packages/schema/working-claims.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Agent(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Job(RootModel[str]):
    root: Annotated[str, Field(pattern="^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class By(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Agent | None = None
    job: Job | None = None


class WorkingClaim(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    base_rev: Annotated[int, Field(ge=1)]
    by: By | None = None
    claim: Annotated[Any, Field(description="urn:kookabug:claims:0#/$defs/Claim")]
    history: Annotated[
        list[Any] | None,
        Field(
            description="이 덧씌움의 지난 작업 rev (보고 항목이 가리킨 rev를 찾을 때, B3). 지우지 않는다"
        ),
    ] = None
    ops: list[Literal["mark_conflicted", "revise", "set_status", "supersede"]]


class WorkingClaims(BaseModel):
    """
    작업 기준 주장 덧씌움 knowledge/working/claims/<기능>.json (계획 9장 R4). Agent가 기존 expected 주장에 한 revise·supersede·set_status·mark_conflicted는 팀 파일 대신 여기 쌓이고 보고함 수락 때 팀에 반영된다. base_rev = 바탕이 된 팀 주장 rev, claim.rev = 작업 revision
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    claims: list[WorkingClaim]
    feature: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    format: Literal["kookabug.working-claims/0"]
    revision: Annotated[int, Field(ge=0)]
