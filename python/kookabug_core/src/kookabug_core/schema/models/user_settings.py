# 생성물 (packages/schema/user-settings.schema.json → tools/gen_schema.py). 직접 고치지 않는다.

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StringConstraints


class PermissionVerdict(RootModel[Literal["allow", "ask", "deny"]]):
    root: Annotated[Literal["allow", "ask", "deny"], Field(title="PermissionVerdict")]


class SecretRef(BaseModel):
    """
    비밀값 저장소의 키 (값은 실행 때 찾는다)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    field_secret: Annotated[str, Field(alias="$secret", min_length=1)]


class Agent(BaseModel):
    """
    판단 노드·에이전트 패널이 띄우는 ACP 에이전트 하나. env의 비밀값은 {"$secret": 키}로만 쓴다 (실행 때 찾음)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    args: list[str] | None = None
    command: Annotated[str, Field(min_length=1)]
    env: (
        dict[
            Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")],
            str | SecretRef,
        ]
        | None
    ) = None
    id: Annotated[str, Field(pattern="^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]
    name: Annotated[str, Field(min_length=1)]


class PermissionRule(BaseModel):
    """
    권한 규칙 하나. rule은 "도구" 또는 "도구(인자 패턴)". 도구·인자 모두 glob(*, ?), 대소문자 구분
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    rule: Annotated[str, Field(pattern="^[a-z0-9_*?]+(\\(.*\\))?$")]
    verdict: PermissionVerdict


class Permissions(BaseModel):
    """
    에이전트 권한 (사용자 계층). 모든 워크스페이스에 적용되고, 프로젝트 계층 값이 먼저다
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    preset: (
        Literal["curator", "explorer", "full", "graph_author", "qa_runner", "read_only", "runner"]
        | None
    ) = None
    rules: list[PermissionRule] | None = None
    toolsets: (
        dict[
            Literal[
                "cases", "control", "core", "graph_edit", "knowledge", "observe", "run", "screens"
            ],
            PermissionVerdict,
        ]
        | None
    ) = None


class UserSettings(BaseModel):
    """
    사용자 설정 (%APPDATA%\\Kookabug\\settings.json, 워크스페이스 밖)
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    agents: list[Agent] | None = None
    default_agent: Annotated[
        str | None, Field(description="판단 노드의 agent가 null일 때 쓰는 에이전트 ID")
    ] = None
    format: Literal["kookabug.user-settings/0"]
    permissions: Permissions | None = None
