# 생성물 (packages/schema/report.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Agent(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Minute(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class Run(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class Budget(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    minutes: Annotated[list[Minute] | None, Field(max_length=2, min_length=2)] = None
    runs: Annotated[list[Run] | None, Field(max_length=2, min_length=2)] = None


class EndedAt(RootModel[str]):
    root: Annotated[str, Field(max_length=40, min_length=1)]


class Decision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    by: Literal["human"]
    decision: Literal["accept", "reject"]


class Check(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Setting(BaseModel):
    """
    UX2: 설정 바꾸기 제안 (Agent가 제안, 사람이 report.decide로 수락·거절). 팀 보고에는 ID·키·이유만 — 값·현재 값은 이 PC .kookabug/jobs/<작업>/proposals.json에만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^s-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    key: Literal[
        "automation.forbidden.add",
        "cheats.categories.add",
        "game.args",
        "game.cwd",
        "game.executable",
        "game.title",
        "sources.add",
    ]
    reason: Annotated[str, Field(max_length=2000, min_length=1)]


type SummaryAdditionalProperty = Annotated[int, Field(ge=0)]


class Unknown(RootModel[str]):
    root: Annotated[str, Field(pattern="^u-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class ReportItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    adoption: Annotated[str | None, Field(pattern="^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")] = None
    case: Annotated[str | None, Field(pattern="^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")] = None
    change: Annotated[str | None, Field(pattern="^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")] = None
    cheat: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    checks: list[Check] | None = None
    claims: list[Any] | None = None
    detail: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    evidence: Annotated[str | None, Field(pattern="^[a-z][a-z0-9-]{0,95}$")] = None
    kind: Literal[
        "auto_adopted",
        "budget",
        "cheat_candidate",
        "init_summary",
        "prep_failed",
        "regression_suspect",
        "setting_change",
        "stalled",
        "undetermined",
        "working_only",
    ]
    setting: Annotated[
        Setting | None,
        Field(
            description="UX2: 설정 바꾸기 제안 (Agent가 제안, 사람이 report.decide로 수락·거절). 팀 보고에는 ID·키·이유만 — 값·현재 값은 이 PC .kookabug/jobs/<작업>/proposals.json에만"
        ),
    ] = None
    summary: dict[str, SummaryAdditionalProperty] | None = None
    unknowns: list[Unknown] | None = None


class ReportGroup(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cause: Annotated[str, Field(max_length=200, min_length=1)]
    decision: Decision | None = None
    items: list[ReportItem]
    key: Annotated[str, Field(max_length=600, min_length=1)]
    title: Annotated[str, Field(max_length=200, min_length=1)]


class Notes(RootModel[str]):
    root: Annotated[str, Field(max_length=4096)]


class Rendered(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


type ClaimsAdditionalProperty = Annotated[int, Field(ge=1)]


class Revisions(BaseModel):
    """
    생성 시점에 고정한 revision (렌더가 이 값을 쓴다 — 결정 뒤 다시 렌더해도 그대로)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    claims: dict[str, ClaimsAdditionalProperty]


class Report(BaseModel):
    """
    작업 보고 knowledge/reports/<작업 ID>.json (M8 계획 3.11). 항목은 Kookabug가 작업의 구조화 기록에서 만들고 Agent 글은 notes 하나
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Agent | None = None
    budget: Budget | None = None
    ended_at: EndedAt | None = None
    format: Literal["kookabug.report/0"]
    groups: list[ReportGroup]
    job: Annotated[str, Field(pattern="^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    notes: Notes | None = None
    playbook: Annotated[str, Field(max_length=200, min_length=1)]
    rendered: Rendered | None = None
    revisions: Annotated[
        Revisions | None,
        Field(
            description="생성 시점에 고정한 revision (렌더가 이 값을 쓴다 — 결정 뒤 다시 렌더해도 그대로)"
        ),
    ] = None
    started_at: Annotated[str, Field(max_length=40, min_length=1)]
    state: Literal[
        "budget_exhausted", "cancelled", "done", "failed", "interrupted", "prep_failed", "running"
    ]
    trigger: Literal["ci", "manual", "schedule"]
    unknowns: list[Unknown] | None = None
