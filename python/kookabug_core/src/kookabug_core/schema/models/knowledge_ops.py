# 생성물 (packages/schema/knowledge-ops.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class OpAdd(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_revision: Annotated[int, Field(ge=0)]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    item: dict[str, Any]
    op: Literal["add"]


class OpRevise(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_rev: Annotated[int, Field(ge=0)]
    changes: Annotated[dict[str, Any], Field(min_length=1)]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    op: Literal["revise"]


class OpSupersede(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_rev: Annotated[int, Field(ge=0)]
    by: Annotated[Any, Field(description="urn:kookabug:claims:0#/$defs/ClaimRef")]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    op: Literal["supersede"]


class OpMarkConflicted(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_rev: Annotated[int, Field(ge=0)]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    op: Literal["mark_conflicted"]
    with_: Annotated[list[Any], Field(alias="with", min_length=1)]


class OpAttachEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_rev: Annotated[int, Field(ge=0)]
    basis: Annotated[Any, Field(description="urn:kookabug:claims:0#/$defs/Basis")]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    op: Literal["attach_evidence"]


class OpSetStatus(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    base_rev: Annotated[int, Field(ge=0)]
    file: Annotated[
        str,
        Field(
            description="features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)",
            max_length=80,
            min_length=1,
        ),
    ]
    id: Annotated[str, Field(max_length=128, min_length=1)]
    op: Literal["set_status"]
    status: Annotated[str, Field(max_length=200, min_length=1)]


class KnowledgeOp(
    RootModel[OpAdd | OpRevise | OpSupersede | OpMarkConflicted | OpAttachEvidence | OpSetStatus]
):
    root: Annotated[
        OpAdd | OpRevise | OpSupersede | OpMarkConflicted | OpAttachEvidence | OpSetStatus,
        Field(title="KnowledgeOp"),
    ]


class KnowledgeOps(BaseModel):
    """
    제한 지식 변경 요청 kb_knowledge_apply (M8 계획 3.3). 한 요청 전부 적용 또는 전부 거부
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    format: Literal["kookabug.knowledge-ops/0"] | None = None
    ops: Annotated[list[KnowledgeOp], Field(max_length=200, min_length=1)]
    request_id: Annotated[str, Field(pattern="^[A-Za-z0-9_.:-]{1,128}$")]
