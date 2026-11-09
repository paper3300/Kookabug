# 생성물 (packages/schema/automation.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Profile(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class ScopeItem(RootModel[str]):
    root: Annotated[str, Field(pattern="^[^\\\\:]+/$")]


class AutoRepair(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    enabled: bool | None = None
    max_adoptions: Annotated[int | None, Field(ge=0)] = None
    profiles: list[Profile] | None = None
    scope: list[ScopeItem] | None = None


class JobBudget(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    minutes: Annotated[int | None, Field(ge=1)] = None
    runs: Annotated[int | None, Field(ge=1)] = None


class ForbiddenText(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["text"]
    value: Annotated[str, Field(max_length=200, min_length=1)]


class ForbiddenTarget(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["target"]
    path: Annotated[str, Field(pattern="^[^\\\\:]+\\.target\\.json$")]


class ForbiddenScreen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    kind: Literal["screen"]


class Forbidden(RootModel[ForbiddenText | ForbiddenTarget | ForbiddenScreen]):
    root: Annotated[ForbiddenText | ForbiddenTarget | ForbiddenScreen, Field(title="Forbidden")]


class Automation(BaseModel):
    """
    자동화 정책 kookabug.json#automation (M8 계획 3.4). 사람 전용 쓰기. 빠진 키는 기본값
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    auto_repair: Annotated[AutoRepair | None, Field(title="AutoRepair")] = None
    budget: Annotated[JobBudget | None, Field(title="JobBudget")] = None
    forbidden: list[Forbidden] | None = None
    format: Literal["kookabug.automation/0"]
