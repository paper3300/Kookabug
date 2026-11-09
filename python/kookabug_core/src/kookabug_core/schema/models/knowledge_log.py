# 생성물 (packages/schema/knowledge-log.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Client(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Id(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Model(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class KnowledgeActor(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    client: Client | None = None
    id: Id | None = None
    kind: Literal["agent", "human", "kookabug"]
    model: Model | None = None


class BaseRev(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class Basi(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ref: Annotated[str, Field(max_length=200, min_length=1)]
    type: Annotated[str, Field(max_length=200, min_length=1)]


class FieldModel(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Job(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class NewRev(RootModel[int]):
    root: Annotated[int, Field(ge=0)]


class RequestId(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class KnowledgeLogLine(BaseModel):
    """
    지식 감사 이력 knowledge/log.jsonl 한 줄 (M8 계획 3.2). 값 대신 바뀐 필드 이름만
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agent: Annotated[KnowledgeActor, Field(title="KnowledgeActor")]
    at: Annotated[str, Field(max_length=40, min_length=1)]
    base_rev: BaseRev | None = None
    basis: list[Basi] | None = None
    code: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    fields: list[FieldModel] | None = None
    file: Annotated[str, Field(max_length=200, min_length=1)]
    format: Literal["kookabug.knowledge-log/0"]
    id: Id | None = None
    job: Job | None = None
    new_rev: NewRev | None = None
    op: Annotated[str, Field(max_length=200, min_length=1)]
    request_id: RequestId | None = None
    result: Literal["applied", "conflict", "refused"]
    seq: Annotated[int, Field(ge=1)]
