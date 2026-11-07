# 생성물 (packages/schema/explore.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class Agent(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client: Annotated[str | None, Field(max_length=200)] = None
    id: Annotated[str, Field(max_length=200, min_length=1)]


type PromotedAdditionalProperty = Annotated[str, Field(max_length=128, pattern="^[^/\\\\]+$")]


class ExploreApproval(BaseModel):
    """
    "이 탐색 동안 허용" 감사 기록 하나 (값 없음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    arg: Annotated[
        str | None, Field(description="권한 인자 (control은 창 제목)", max_length=200)
    ] = None
    at: Annotated[str, Field(description="UTC ISO 8601")]
    scope: Literal["session"]
    tool: Annotated[str, Field(max_length=64, min_length=1)]


class Explore(BaseModel):
    """
    에이전트 탐색 세션 기록 (screens/_explored/<세션 ID>/explore.json, M7)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Agent
    approvals: list[ExploreApproval] | None = None
    ended_at: Annotated[str | None, Field(description="UTC ISO 8601")] = None
    format: Literal["kookabug.explore/0"]
    goal: Annotated[str | None, Field(max_length=1000)] = None
    id: Annotated[str, Field(pattern="^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    max_steps: Annotated[int, Field(ge=1, le=1000)]
    promoted: Annotated[
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")],
            PromotedAdditionalProperty,
        ]
        | None,
        Field(description="승격한 후보 키 → 확정 화면 ID"),
    ] = None
    started_at: Annotated[str, Field(description="UTC ISO 8601")]
    status: Literal["active", "ended", "interrupted"]
    steps: Annotated[int, Field(ge=0)]
    title: Annotated[str, Field(max_length=200, min_length=1)]
    window: Annotated[str | None, Field(max_length=200)] = None
