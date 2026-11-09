# 생성물 (packages/schema/claims.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


class Basis(BaseModel):
    """
    근거 하나. source = sources:<원본 ID>#<위치>, evidence = 증거 묶음 ID, run = 실행 ID, human = 사람 답(u-…)·사람 연산. 위키·주장 근거 형식은 없다(자기 인용 차단). source의 hash·verified는 서비스가 계산해 넣는다(URL 등 확인 못 한 원본은 verified: false — 그것만으로 expected를 supported로 못 올린다, 계획 9장 R5)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    hash: Annotated[str | None, Field(max_length=200)] = None
    note: Annotated[str | None, Field(max_length=1000)] = None
    ref: Annotated[str, Field(max_length=300, min_length=1)]
    seen_at: Annotated[str | None, Field(max_length=40, min_length=1)] = None
    type: Literal["evidence", "human", "run", "source"]
    verified: bool | None = None


class Precondition(RootModel[str]):
    root: Annotated[str, Field(max_length=4000, min_length=1)]


class ClaimVerifier(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    graph: Annotated[str, Field(max_length=200, min_length=1)]
    node: Annotated[str, Field(max_length=200, min_length=1)]


class ClaimRef(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_.]{0,127}$")]
    rev: Annotated[int, Field(ge=1)]


class From(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class To(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Builds(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    from_: Annotated[From | None, Field(alias="from")] = None
    to: To | None = None


class DataRev(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Locale(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class Profile(RootModel[str]):
    root: Annotated[str, Field(max_length=200, min_length=1)]


class ClaimScope(BaseModel):
    """
    적용 범위. null·빠짐 = 제한 없음
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    builds: Builds | None = None
    data_rev: DataRev | None = None
    locale: Locale | None = None
    profiles: list[Profile] | None = None


class Claim(BaseModel):
    """
    주장 하나 (KB문서 6장)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    basis: list[Basis]
    conflicts_with: list[ClaimRef] | None = None
    id: Annotated[str, Field(pattern="^[a-z][a-z0-9_.]{0,127}$")]
    kind: Literal["expected", "guess", "observed"]
    preconditions: list[Precondition] | None = None
    property: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    rev: Annotated[int, Field(ge=1)]
    scope: ClaimScope | None = None
    statement: Annotated[str, Field(max_length=4000, min_length=1)]
    status: Literal["conflicted", "hypothesis", "superseded", "supported", "unverifiable"]
    subject: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    superseded_by: ClaimRef | None = None
    supersedes: ClaimRef | None = None
    unit: Annotated[str | None, Field(max_length=200, min_length=1)] = None
    value: Annotated[Any | None, Field(description="명제의 값 (JSON 값 무엇이든)")] = None
    verified_by: list[ClaimVerifier] | None = None


class Claims(BaseModel):
    """
    기능별 주장 파일 knowledge/features/<기능>.json (M8 계획 3.2). history는 옛 rev 항목
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    claims: list[Claim]
    feature: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    format: Literal["kookabug.claims/0"]
    history: list[Claim] | None = None
    revision: Annotated[int, Field(ge=0)]
