# 생성물 (packages/schema/case.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class CaseHypothesis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    cause: Literal[
        "environment",
        "flow_change",
        "intended_change",
        "intermittent",
        "product_regression",
        "test_defect",
        "ui_change",
    ]
    note: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    state: Literal["confirmed", "open", "refuted", "supported"]
    support: list[Any] | None = None


class Adoption(RootModel[str]):
    root: Annotated[str, Field(pattern="^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class Report(RootModel[str]):
    root: Annotated[str, Field(pattern="^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class WorkingItem(RootModel[str]):
    root: Annotated[str, Field(pattern="^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]


class Links(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    adoption: Adoption | None = None
    claims: list[Any] | None = None
    reports: list[Report] | None = None
    working: list[WorkingItem] | None = None


class CaseNeed(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    how: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    human_only: bool | None = None
    observation: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    permission: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    splits: Annotated[str | None, Field(max_length=4000, min_length=1)] = None
    unknown: Annotated[str, Field(max_length=4000, min_length=1)]


class Basis(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["team", "working"]


class Evidence(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z][a-z0-9-]{0,95}$")]


class GraphSha(RootModel[str]):
    root: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]


class CaseOriginal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    basis: Basis | None = None
    claims: list[Any] | None = None
    evidence: Evidence | None = None
    graph_sha: GraphSha | None = None
    run: Annotated[str, Field(max_length=200, min_length=1)]


class Until(RootModel[str]):
    root: Annotated[str, Field(max_length=40, min_length=1)]


class Recheck(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    on: list[Literal["new_build", "new_evidence", "new_source"]] | None = None
    until: Until | None = None


class CaseResolution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    adoption: Annotated[str | None, Field(pattern="^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")] = None
    at: Annotated[str | None, Field(max_length=40, min_length=1)] = None
    by: Literal["adoption", "human"]
    note: Annotated[str | None, Field(max_length=4000, min_length=1)] = None


class Run(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    at: Annotated[str, Field(max_length=40, min_length=1)]
    evidence: Evidence | None = None
    run: Annotated[str, Field(max_length=200, min_length=1)]


class Code(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Node(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Test(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class CaseSymptom(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    code: Code | None = None
    kind: Literal[
        "launch_failed",
        "node_error",
        "stalled",
        "target_missing",
        "unexpected_screen",
        "value_mismatch",
    ]
    node: Node | None = None
    test: Test | None = None


class Case(BaseModel):
    """
    조사 사건 knowledge/cases/<사건 ID>.json (M8 계획 3.2). resolved·closed는 Kookabug만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    actions: list[Literal["baseline_change", "reobserve", "repair_candidate", "rerun"]] | None = (
        None
    )
    format: Literal["kookabug.case/0"]
    hypotheses: list[CaseHypothesis] | None = None
    id: Annotated[str, Field(pattern="^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")]
    links: Links | None = None
    needs: list[CaseNeed] | None = None
    original: Annotated[CaseOriginal, Field(title="CaseOriginal")]
    recheck: Recheck | None = None
    resolution: CaseResolution | None = None
    revision: Annotated[int, Field(ge=1)]
    runs: list[Run] | None = None
    signature: Annotated[str, Field(pattern="^sha256:[0-9a-f]{64}$")]
    state: Literal["closed", "needs_info", "open", "resolved", "watching"]
    symptom: Annotated[CaseSymptom, Field(title="CaseSymptom")]
    title: Annotated[str, Field(max_length=200, min_length=1)]
